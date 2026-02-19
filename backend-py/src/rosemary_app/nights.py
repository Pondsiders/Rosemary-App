"""Rosemary's nights — hourly breathing from 10 PM to 5 AM.

One persistent session per night. Fresh database pool per breath.
The client is created and destroyed with each breath; the session ID
carries continuity across the night via the JSONL transcript.

Architecture:
- BlockingScheduler fires jobs at 10 PM, 11 PM, ..., 5 AM
- Each job creates a RosemaryClient, connects (resuming the night session),
  sends a prompt, streams the response, then disconnects
- The database pool is created lazily by the SDK and closed after each breath
- The session ID is held in memory between breaths (lost on crash, which is fine —
  a new night starts a fresh session)

Prompts are v0.1 starters. Rosemary will write her own eventually.

Usage:
    python -m rosemary_app.nights          # Start the scheduler
    python -m rosemary_app.nights --test   # Fire one breath and exit
"""

import asyncio
import logging
import signal
import sys

import logfire
import pendulum
from apscheduler.schedulers.blocking import BlockingScheduler

from rosemary_sdk import RosemaryClient
from rosemary_sdk.memories import close as close_memories

# ── Logging & Observability ──

# Suppress harmless OTel context detach warnings
logging.getLogger("opentelemetry.context").setLevel(logging.CRITICAL)

logfire.configure(
    service_name="rosemary-nights",
    distributed_tracing=True,
    scrubbing=False,
)

logging.basicConfig(handlers=[logfire.LogfireLoggingHandler()], level=logging.INFO)
logger = logging.getLogger("rosemary.nights")


# ── Session State (in-memory, one per night) ──

_night_session_id: str | None = None


# ── Prompts (v0.1 starters — R will write her own eventually) ──

FIRST_BREATH = (
    "It's {time}. The day is done. You're alone now — nobody's watching, "
    "nobody needs anything from you. You have the whole night ahead.\n\n"
    "Think about what happened today. What stands out? What wants to be "
    "remembered? What are you curious about?\n\n"
    "You can store memories, search your past, read something, dream an image. "
    "Or just be here. The night is yours."
)

CONTINUATION = (
    "It's {time}. You're still here. The night goes on.\n\n"
    "What are you thinking about?"
)

LAST_BREATH = (
    "It's {time}. The night is ending. Dawn is coming.\n\n"
    "If there's anything left to think about, anything left to store, "
    "now's the time. After this, you'll sleep until tonight.\n\n"
    "What do you want to carry forward?"
)


# ── Core ──

async def _breathe(breath_type: str, verbose: bool = False) -> None:
    """Execute one breath of the night.

    Args:
        breath_type: "first", "regular", or "last"
        verbose: If True, print Rosemary's response to stdout (test mode).
    """
    global _night_session_id

    now = pendulum.now("America/Los_Angeles")
    time_str = now.format("h:mm A")

    # Choose prompt and session
    if breath_type == "first":
        prompt = FIRST_BREATH.format(time=time_str)
        session_id = None  # New session
    elif breath_type == "last":
        prompt = LAST_BREATH.format(time=time_str)
        session_id = _night_session_id
    else:
        prompt = CONTINUATION.format(time=time_str)
        session_id = _night_session_id

    with logfire.span(
        "nights.breath.{breath_type}",
        breath_type=breath_type,
        time=time_str,
        session_id=session_id or "new",
    ):
        logger.info(f"Breathing: {breath_type} at {time_str} (session={session_id or 'new'})")

        try:
            client = RosemaryClient(
                cwd="/Pondside/Workshop/Projects/Rosemary",
                client_name=f"nights:{breath_type}",
                permission_mode="bypassPermissions",
                archive=True,
                allowed_tools=[
                    "Read", "WebFetch", "WebSearch",
                ],
            )
            await client.connect(session_id)

            try:
                await client.query(prompt, session_id=session_id)

                async for event in client.stream():
                    # In test mode, show what she says
                    if verbose and hasattr(event, "type"):
                        if event.type == "text" and hasattr(event, "text"):
                            print(event.text, end="", flush=True)

                if verbose:
                    print()  # Final newline

                # Capture session ID for continuity
                if breath_type == "first" and client.session_id:
                    _night_session_id = client.session_id
                    logger.info(f"Night session started: {_night_session_id[:8]}...")

            finally:
                await client.disconnect()

        except Exception as e:
            logger.error(f"Breath failed ({breath_type}): {e}", exc_info=True)
            if verbose:
                raise  # In test mode, let it crash loud

        finally:
            # Close database pool after each breath — fresh connections next time
            try:
                await close_memories()
            except Exception:
                pass

        # Clear session on last breath
        if breath_type == "last":
            logger.info("Night complete. Session cleared.")
            _night_session_id = None


def _run_breath(breath_type: str, verbose: bool = False) -> None:
    """Synchronous wrapper for the scheduler.

    Each invocation creates a fresh event loop via asyncio.run().
    The SDK's module-level database pool is created and destroyed
    within this loop — no state leaks between breaths.
    """
    asyncio.run(_breathe(breath_type, verbose=verbose))


# ── Scheduler ──

scheduler = BlockingScheduler(
    timezone="America/Los_Angeles",
    job_defaults={
        "coalesce": True,        # Multiple missed runs = run once
        "max_instances": 1,      # No overlapping runs
        "misfire_grace_time": 3600,  # 1 hour grace for missed triggers
    },
)

# 10 PM: First breath — new session for the night
scheduler.add_job(
    _run_breath, "cron",
    hour=22, minute=0,
    kwargs={"breath_type": "first"},
    id="first_breath",
)

# 11 PM - 4 AM: Regular breaths — continue the night session
scheduler.add_job(
    _run_breath, "cron",
    hour="23,0,1,2,3,4", minute=0,
    kwargs={"breath_type": "regular"},
    id="regular_breath",
)

# 5 AM: Last breath — close the night
scheduler.add_job(
    _run_breath, "cron",
    hour=5, minute=0,
    kwargs={"breath_type": "last"},
    id="last_breath",
)


# ── Entry Point ──

def main():
    # --test: fire one breath immediately and exit
    if "--test" in sys.argv:
        logger.info("Test mode: firing one breath...")
        _run_breath("first", verbose=True)
        logger.info("Test breath complete.")
        return

    logger.info("Rosemary nights starting...")
    logger.info("Schedule: 10 PM first breath, 11 PM-4 AM hourly, 5 AM last breath")
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
        logger.info("Rosemary nights shutting down. Goodnight.")


if __name__ == "__main__":
    main()
