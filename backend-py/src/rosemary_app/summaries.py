"""Rosemary's daily capsules — periodic summaries written to Neon.

Three capsule types, each on its own schedule (America/Los_Angeles):
- today_so_far: Hourly from 7 AM to 9 PM (replaces previous row each time)
- yesterday: Once at 9:30 PM (permanent record)
- last_night: Once at 5:30 AM (permanent record)

Each capsule is standalone — no session continuity between jobs.
The capsule text is captured from the streamed response and written
to the `summaries` table in Neon via asyncpg.

Prompts live in the plugin directory (capsule-prompts.md) so Rosemary
can edit them herself. Parsed by splitting on ## headers.

Usage:
    python -m rosemary_app.summaries                     # Start scheduler
    python -m rosemary_app.summaries --test today_so_far # Test one capsule type
    python -m rosemary_app.summaries --test yesterday
    python -m rosemary_app.summaries --test last_night
"""

import asyncio
import logging
import os
import re
import signal
import sys
from pathlib import Path

import asyncpg
import logfire
import pendulum
from apscheduler.schedulers.blocking import BlockingScheduler

from rosemary_sdk import RosemaryClient
from rosemary_sdk.memories import close as close_memories

# ── Logging & Observability ──

# Suppress harmless OTel context detach warnings
logging.getLogger("opentelemetry.context").setLevel(logging.CRITICAL)

logfire.configure(
    service_name="rosemary-summaries",
    distributed_tracing=True,
    scrubbing=False,
)

logging.basicConfig(handlers=[logfire.LogfireLoggingHandler()], level=logging.INFO)
logger = logging.getLogger("rosemary.summaries")


# ── Prompts (loaded from plugin directory) ──

_PLUGIN_DIR = Path(os.environ.get("ROSEMARY_PLUGIN_DIR", "/home/rosemary/plugin"))
_CAPSULE_PROMPTS_FILE = _PLUGIN_DIR / "prompts" / "capsule-prompts.md"

# Fallbacks if the file is missing or a section is absent
_FALLBACK_TODAY_SO_FAR = "It's {time}. Write a brief summary of your day so far."
_FALLBACK_YESTERDAY = "It's {time}. Write a brief summary of yesterday."
_FALLBACK_LAST_NIGHT = "It's {time}. Write a brief summary of last night."


def _load_capsule_prompts() -> dict[str, str]:
    """Parse capsule-prompts.md into a dict mapping section name to content.

    Splits on ## headers, strips whitespace, returns lowercase keys.
    Reloaded on every capsule so edits take effect without restart.
    """
    prompts: dict[str, str] = {}

    try:
        text = _CAPSULE_PROMPTS_FILE.read_text()
    except FileNotFoundError:
        logger.warning(f"Capsule prompts file not found: {_CAPSULE_PROMPTS_FILE}")
        return prompts

    # Split on ## headers
    sections = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    # sections[0] is preamble (before first ##), then alternating: header, content
    for i in range(1, len(sections), 2):
        header = sections[i].strip().lower()
        content = sections[i + 1].strip() if i + 1 < len(sections) else ""
        if content:
            prompts[header] = content

    return prompts


def _get_prompt(capsule_type: str) -> str:
    """Get the prompt for a capsule type, with fallback."""
    prompts = _load_capsule_prompts()

    if capsule_type == "today_so_far":
        return prompts.get("today so far", _FALLBACK_TODAY_SO_FAR)
    elif capsule_type == "yesterday":
        return prompts.get("yesterday", _FALLBACK_YESTERDAY)
    elif capsule_type == "last_night":
        return prompts.get("last night", _FALLBACK_LAST_NIGHT)
    else:
        return _FALLBACK_TODAY_SO_FAR


def _get_period(capsule_type: str, now: pendulum.DateTime) -> tuple[pendulum.DateTime, pendulum.DateTime]:
    """Compute (period_start, period_end) for a capsule type.

    All times are in America/Los_Angeles.
    """
    tz = "America/Los_Angeles"

    if capsule_type == "today_so_far":
        # period_start = today 7:00 AM, period_end = now
        period_start = now.start_of("day").add(hours=7)
        period_end = now

    elif capsule_type == "yesterday":
        # period_start = yesterday 7:00 AM, period_end = yesterday 9:30 PM
        yesterday = now.subtract(days=1)
        period_start = yesterday.start_of("day").add(hours=7)
        period_end = yesterday.start_of("day").add(hours=21, minutes=30)

    elif capsule_type == "last_night":
        # period_start = last night 10:00 PM, period_end = today 5:00 AM
        # "last night" means the previous evening: yesterday at 10 PM -> today at 5 AM
        yesterday = now.subtract(days=1)
        period_start = yesterday.start_of("day").add(hours=22)
        period_end = now.start_of("day").add(hours=5)

    else:
        raise ValueError(f"Unknown capsule type: {capsule_type}")

    return period_start, period_end


# ── Database ──

async def _fetch_memories_for_period(
    period_start: pendulum.DateTime,
    period_end: pendulum.DateTime,
) -> list[dict]:
    """Fetch Rosemary's memories from a time period.

    Returns list of dicts with 'content' and 'created_at' keys,
    ordered chronologically (oldest first).

    Converts period bounds to UTC for safe Postgres comparison —
    the metadata created_at is stored as UTC ISO strings.
    """
    # Convert to UTC standard datetimes for safe asyncpg transmission
    start_utc = period_start.in_tz("UTC")
    end_utc = period_end.in_tz("UTC")

    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT content, metadata->>'created_at' as created_at
                FROM memories
                WHERE NOT forgotten
                  AND (metadata->>'created_at')::timestamptz >= $1
                  AND (metadata->>'created_at')::timestamptz < $2
                ORDER BY (metadata->>'created_at')::timestamptz ASC
                """,
                start_utc,
                end_utc,
            )
            logger.info(f"Fetched {len(rows)} memories for period {period_start} to {period_end}")
            return [{"content": row["content"], "created_at": row["created_at"]} for row in rows]
    finally:
        await pool.close()


def _format_memories_for_prompt(memories: list[dict]) -> str:
    """Format memories into a text block for the capsule prompt.

    Each memory is prefixed with its timestamp, separated by blank lines.
    """
    if not memories:
        return "(No memories found for this period.)"

    parts = []
    for mem in memories:
        # Parse and format the timestamp for readability
        try:
            ts = pendulum.parse(mem["created_at"]).in_tz("America/Los_Angeles")
            time_label = ts.format("h:mm A")
        except Exception:
            time_label = "?"
        parts.append(f"[{time_label}] {mem['content']}")

    return "\n\n".join(parts)


async def _write_capsule(
    capsule_type: str,
    period_start: pendulum.DateTime,
    period_end: pendulum.DateTime,
    summary: str,
) -> None:
    """Write a capsule summary to the Neon summaries table.

    For today_so_far: DELETE existing row for today, then INSERT.
    For yesterday/last_night: just INSERT.
    """
    pool = await asyncpg.create_pool(os.environ["DATABASE_URL"], min_size=1, max_size=2)
    try:
        async with pool.acquire() as conn:
            if capsule_type == "today_so_far":
                # There's only ever one "today so far" — replace it each hour
                await conn.execute(
                    "DELETE FROM summaries WHERE capsule_type = 'today_so_far' AND period_start::date = $1::date",
                    period_start,
                )

            await conn.execute(
                """
                INSERT INTO summaries (period_start, period_end, summary, capsule_type, created_at)
                VALUES ($1, $2, $3, $4, NOW())
                """,
                period_start,
                period_end,
                summary,
                capsule_type,
            )
            logger.info(f"Capsule written: {capsule_type} ({len(summary)} chars)")
    finally:
        await pool.close()


# ── Core ──

async def _write_capsule_for(capsule_type: str, verbose: bool = False) -> None:
    """Execute one capsule-writing job.

    Creates a RosemaryClient, sends the capsule prompt, captures the full
    response text, and writes it to Neon.

    Args:
        capsule_type: "today_so_far", "yesterday", or "last_night"
        verbose: If True, print Rosemary's response to stdout (test mode).
    """
    now = pendulum.now("America/Los_Angeles")
    time_str = now.format("h:mm A")

    # Load prompt from plugin file (re-read each capsule so edits take effect)
    prompt_template = _get_prompt(capsule_type).format(time=time_str)
    period_start, period_end = _get_period(capsule_type, now)

    with logfire.span(
        "summaries.capsule.{capsule_type}",
        capsule_type=capsule_type,
        time=time_str,
    ):
        logger.info(f"Writing capsule: {capsule_type} at {time_str}")

        # Fetch memories for the period so Rosemary has material to summarize
        memories = await _fetch_memories_for_period(period_start, period_end)
        memory_block = _format_memories_for_prompt(memories)

        # Build full prompt: memories first, then the capsule instruction
        prompt = f"{memory_block}\n\n---\n\n{prompt_template}"

        try:
            client = RosemaryClient(
                cwd=os.environ.get("ROSEMARY_CWD", "/Pondside/Workshop/Projects/Rosemary"),
                client_name=f"summaries:{capsule_type}",
                permission_mode="bypassPermissions",
                archive=False,  # Don't archive capsule-writing sessions
            )
            await client.connect()

            try:
                await client.query(prompt)

                # Stream the response, capturing the full text
                response_parts: list[str] = []
                async for event in client.stream():
                    if hasattr(event, "type") and event.type == "text" and hasattr(event, "text"):
                        response_parts.append(event.text)
                        if verbose:
                            print(event.text, end="", flush=True)

                if verbose:
                    print()  # Final newline

                response_text = "".join(response_parts)

                if response_text.strip():
                    await _write_capsule(capsule_type, period_start, period_end, response_text)
                else:
                    logger.warning(f"Empty response for capsule: {capsule_type}")

            finally:
                await client.disconnect()

        except Exception as e:
            logger.error(f"Capsule failed ({capsule_type}): {e}", exc_info=True)
            if verbose:
                raise  # In test mode, let it crash loud

        finally:
            # Close database pool after each capsule — fresh connections next time
            try:
                await close_memories()
            except Exception:
                pass


def _run_capsule(capsule_type: str, verbose: bool = False) -> None:
    """Synchronous wrapper for the scheduler.

    Each invocation creates a fresh event loop via asyncio.run().
    The SDK's module-level database pool is created and destroyed
    within this loop — no state leaks between capsules.
    """
    asyncio.run(_write_capsule_for(capsule_type, verbose=verbose))


# ── Scheduler ──

scheduler = BlockingScheduler(
    timezone="America/Los_Angeles",
    job_defaults={
        "coalesce": True,        # Multiple missed runs = run once
        "max_instances": 1,      # No overlapping runs
        "misfire_grace_time": 3600,  # 1 hour grace for missed triggers
    },
)

# today_so_far: Hourly from 7 AM to 9 PM
scheduler.add_job(
    _run_capsule, "cron",
    hour="7,8,9,10,11,12,13,14,15,16,17,18,19,20,21", minute=0,
    kwargs={"capsule_type": "today_so_far"},
    id="today_so_far",
)

# yesterday: Once at 9:30 PM
scheduler.add_job(
    _run_capsule, "cron",
    hour=21, minute=30,
    kwargs={"capsule_type": "yesterday"},
    id="yesterday",
)

# last_night: Once at 5:30 AM
scheduler.add_job(
    _run_capsule, "cron",
    hour=5, minute=30,
    kwargs={"capsule_type": "last_night"},
    id="last_night",
)


# ── Entry Point ──

def main():
    # --test <capsule_type>: fire one capsule immediately and exit
    if "--test" in sys.argv:
        test_idx = sys.argv.index("--test")
        if test_idx + 1 < len(sys.argv):
            capsule_type = sys.argv[test_idx + 1]
        else:
            capsule_type = "today_so_far"

        if capsule_type not in ("today_so_far", "yesterday", "last_night"):
            print(f"Unknown capsule type: {capsule_type}")
            print("Valid types: today_so_far, yesterday, last_night")
            sys.exit(1)

        logger.info(f"Test mode: firing {capsule_type} capsule...")
        _run_capsule(capsule_type, verbose=True)
        logger.info("Test capsule complete.")
        return

    logger.info("Rosemary summaries starting...")
    logger.info("Schedule: today_so_far hourly 7AM-9PM, yesterday at 9:30PM, last_night at 5:30AM")
    logger.info("Timezone: America/Los_Angeles")

    # Graceful shutdown on SIGTERM (Docker sends this)
    def handle_signal(signum, frame):
        logger.info("Received signal, shutting down...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Rosemary summaries shutting down.")


if __name__ == "__main__":
    main()
