"""Sessions route — list sessions from Neon database.

GET /api/sessions lists recent sessions.
GET /api/sessions/{session_id} loads a session's message history from JSONL.
"""

import json
import os
from pathlib import Path
from typing import Any

import asyncpg
import logfire
from fastapi import APIRouter, HTTPException, Query

router = APIRouter()

DATABASE_URL = os.environ["DATABASE_URL"]

# Claude Code stores sessions as JSONL files.
# Configurable via env var; default based on the Rosemary project cwd.
SESSIONS_DIR = Path(
    os.getenv(
        "SESSIONS_DIR",
        os.path.expanduser("~/.claude/projects/-Pondside-Workshop-Projects-Rosemary"),
    )
)


def _filter_user_display_content(parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Filter SDK-injected blocks from user messages for display.

    The SDK wraps user prompts with recalled memories, archive hits,
    timestamps, and orientation blocks. For display, we only want
    the human's actual text and any image attachments.

    Strategy: find the PSO-8601 timestamp block ("[Sent ...]") —
    the human's actual text is always the block immediately after it.
    If no timestamp found, return all parts as-is (pre-SDK or simple message).
    """
    # Find the timestamp block
    timestamp_idx = None
    for i, part in enumerate(parts):
        if part.get("type") == "text":
            text = part.get("text", "")
            if text.startswith("[Sent ") and text.rstrip().endswith("]"):
                timestamp_idx = i
                break

    if timestamp_idx is not None:
        filtered = []

        # The human's text is the block right after the timestamp
        human_text_idx = timestamp_idx + 1
        if human_text_idx < len(parts) and parts[human_text_idx].get("type") == "text":
            filtered.append(parts[human_text_idx])

        # Collect all image blocks
        for part in parts:
            if part.get("type") == "image":
                filtered.append(part)

        return filtered if filtered else parts
    else:
        # No timestamp — simple message, return as-is
        return parts


def extract_display_messages(lines: list[str]) -> list[dict[str, Any]]:
    """Extract user and assistant messages from JSONL records.

    User messages are filtered to show only the human's actual text
    and images, stripping out SDK-injected memories and metadata.
    """
    messages: list[dict[str, Any]] = []
    tool_calls_by_id: dict[str, dict[str, Any]] = {}

    for line in lines:
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue

        record_type = record.get("type")

        if record_type == "user":
            content = record.get("message", {}).get("content", "")

            if isinstance(content, str):
                parts = [{"type": "text", "text": content}]
                messages.append({"role": "user", "content": parts})
            elif isinstance(content, list):
                parts: list[dict[str, Any]] = []
                has_tool_results = False

                for block in content:
                    if isinstance(block, str):
                        parts.append({"type": "text", "text": block})
                    elif isinstance(block, dict):
                        block_type = block.get("type")
                        if block_type == "text":
                            parts.append({"type": "text", "text": block.get("text", "")})
                        elif block_type == "image":
                            source = block.get("source", {})
                            if source.get("type") == "base64":
                                media_type = source.get("media_type", "image/png")
                                data = source.get("data", "")
                                data_url = f"data:{media_type};base64,{data}"
                                parts.append({"type": "image", "image": data_url})
                            else:
                                parts.append({"type": "image", "image": "[image]"})
                        elif block_type == "tool_result":
                            has_tool_results = True
                            tool_use_id = block.get("tool_use_id")
                            result_content = block.get("content", "")
                            if isinstance(result_content, str):
                                result_text = result_content
                            elif isinstance(result_content, list):
                                texts = []
                                for r in result_content:
                                    if isinstance(r, dict) and r.get("type") == "text":
                                        texts.append(r.get("text", ""))
                                    elif isinstance(r, str):
                                        texts.append(r)
                                result_text = "\n".join(texts)
                            else:
                                result_text = str(result_content)
                            if tool_use_id and tool_use_id in tool_calls_by_id:
                                tool_calls_by_id[tool_use_id]["result"] = result_text

                if parts:
                    # Filter out SDK-injected blocks for display
                    display_parts = _filter_user_display_content(parts)
                    if display_parts:
                        messages.append({"role": "user", "content": display_parts})
            else:
                parts = [{"type": "text", "text": str(content)}]
                messages.append({"role": "user", "content": parts})

        elif record_type == "assistant":
            content_blocks = record.get("message", {}).get("content", [])
            parts: list[dict[str, Any]] = []

            for block in content_blocks:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append({"type": "text", "text": block.get("text", "")})
                    elif block.get("type") == "tool_use":
                        tool_input = block.get("input", {})
                        tool_call = {
                            "type": "tool-call",
                            "toolCallId": block.get("id"),
                            "toolName": block.get("name"),
                            "args": tool_input,
                            "argsText": json.dumps(tool_input, indent=2),
                        }
                        parts.append(tool_call)
                        tool_id = block.get("id")
                        if tool_id:
                            tool_calls_by_id[tool_id] = tool_call

            if parts:
                messages.append({"role": "assistant", "content": parts})

    return messages


@router.get("/api/sessions")
async def list_sessions(limit: int = Query(default=20, ge=1, le=100)) -> list[dict[str, Any]]:
    """List recent sessions from the Neon database."""
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        try:
            rows = await conn.fetch(
                """
                SELECT session_id, title, created_at, updated_at
                FROM rosemary_sessions
                ORDER BY updated_at DESC
                LIMIT $1
                """,
                limit,
            )
        finally:
            await conn.close()

        return [
            {
                "session_id": row["session_id"],
                "title": row["title"] or row["session_id"][:8],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
            }
            for row in rows
        ]

    except Exception as e:
        logfire.exception(f"Failed to list sessions: {e}")
        raise


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> dict[str, Any]:
    """Load a session's message history from JSONL."""
    jsonl_path = SESSIONS_DIR / f"{session_id}.jsonl"

    if not jsonl_path.exists():
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    content = jsonl_path.read_text()
    lines = [line for line in content.split("\n") if line.strip()]

    messages = extract_display_messages(lines)

    # Get metadata from first/last records
    first = json.loads(lines[0]) if lines else {}
    last = json.loads(lines[-1]) if lines else {}

    return {
        "session_id": session_id,
        "messages": messages,
        "created_at": first.get("timestamp"),
        "updated_at": last.get("timestamp"),
    }
