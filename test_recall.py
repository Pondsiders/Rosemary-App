#!/usr/bin/env python3
"""Test the recall pipeline end-to-end.

Takes a simulated user prompt and prints all recall results — own memories
and Sage archive hits — with dates, scores, and source labels.

Usage:
    cd Rosemary-App
    op run --env-file=.env.op -- backend-py/.venv/bin/python test_recall.py "Tell me about that AI resistance paper"
    op run --env-file=.env.op -- backend-py/.venv/bin/python test_recall.py  # reads from stdin

Requires: DATABASE_URL, OLLAMA_URL, OLLAMA_MODEL in environment.
"""

import asyncio
import os
import sys
import textwrap

# Fail fast if env vars are missing
for var in ("DATABASE_URL", "OLLAMA_URL", "OLLAMA_MODEL"):
    if var not in os.environ:
        print(f"FATAL: {var} not set. Run with: op run --env-file=.env.op -- python {sys.argv[0]}")
        sys.exit(1)

# Must set ROSEMARY_PLUGIN_DIR for prompts to load
# The plugin directory is adjacent to this app directory
plugin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Rosemary-Plugin")
os.environ.setdefault("ROSEMARY_PLUGIN_DIR", os.path.abspath(plugin_dir))

from rosemary_sdk.memories.recall import recall
from rosemary_sdk.memories.db import close_pool


def format_result(result: dict, index: int) -> str:
    """Pretty-print a single recall result."""
    source = result.get("source", "memory")
    score = result.get("score", 0)
    content = result.get("content", "").strip()

    # Truncate long content for display
    if len(content) > 300:
        content = content[:297] + "..."

    if source == "archive":
        speaker = result.get("speaker", "unknown")
        speaker_name = "Kylee" if speaker == "kylee" else "Sage"
        created_at = result.get("created_at", "unknown")
        title = result.get("conversation_title", "")
        msg_id = result.get("id", "?")

        header = f"  [{index}] 📚 SAGE ARCHIVE (score {score:.3f})"
        meta = f"      msg #{msg_id} | {speaker_name} | {created_at}"
        if title:
            meta += f"\n      conversation: {title}"
    else:
        mem_id = result.get("id", "?")
        created_at = result.get("created_at", "unknown")

        header = f"  [{index}] 🧠 MEMORY #{mem_id} (score {score:.3f})"
        meta = f"      created: {created_at}"

    # Indent content
    wrapped = textwrap.fill(content, width=80, initial_indent="      ", subsequent_indent="      ")

    return f"{header}\n{meta}\n{wrapped}"


async def main():
    # Get prompt from argv or stdin
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        print("Enter prompt (Ctrl+D to finish):")
        prompt = sys.stdin.read().strip()

    if not prompt:
        print("No prompt provided.")
        sys.exit(1)

    print(f"\n{'=' * 70}")
    print(f"  RECALL TEST")
    print(f"  Prompt: {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    print(f"{'=' * 70}\n")

    try:
        # Run recall with a fake session ID (no seen-cache state)
        results = await recall(prompt, session_id="test-session")

        if not results:
            print("  No results above threshold.\n")
        else:
            memory_count = sum(1 for r in results if r.get("source") == "memory")
            archive_count = sum(1 for r in results if r.get("source") == "archive")
            print(f"  Found {len(results)} results: {memory_count} memories, {archive_count} archive hits\n")
            print(f"  {'─' * 66}\n")

            for i, result in enumerate(results, 1):
                print(format_result(result, i))
                print()

    finally:
        await close_pool()

    print(f"{'=' * 70}")


if __name__ == "__main__":
    asyncio.run(main())
