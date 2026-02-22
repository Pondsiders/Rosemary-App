"""Upload route — save non-image files to disk for Rosemary to read.

POST /api/upload accepts a multipart file upload. Images are rejected
(they go through the chat endpoint as inline base64). Everything else is
saved to the uploads directory and the path is returned so the frontend
can reference it in the conversation.
"""

import os
import re
import time

import logfire
from fastapi import APIRouter, UploadFile, File, HTTPException

router = APIRouter()

UPLOADS_DIR = os.environ.get("ROSEMARY_UPLOADS_DIR", "/home/rosemary/uploads")
MAX_FILE_SIZE = int(os.environ.get("ROSEMARY_MAX_UPLOAD_SIZE", str(1024 * 1024 * 1024)))  # 1 GB


def sanitize_filename(name: str) -> str:
    """Remove path separators and special characters from a filename.

    Keeps alphanumerics, hyphens, underscores, dots, and spaces.
    Collapses consecutive underscores.
    """
    # Strip any directory components
    name = os.path.basename(name)
    # Replace anything that isn't safe with an underscore
    name = re.sub(r"[^\w.\- ]", "_", name)
    # Collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    # Strip leading/trailing whitespace and underscores
    name = name.strip(" _")
    return name or "unnamed_file"


def ensure_uploads_dir() -> None:
    """Create the uploads directory if it does not exist."""
    os.makedirs(UPLOADS_DIR, exist_ok=True)


@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...)) -> dict[str, str | int]:
    """Accept a file upload and save it to disk.

    Returns the saved path, original filename, and file size so the
    frontend can reference it in conversation messages.

    Images are rejected — they should be sent inline through /api/chat.
    """
    content_type = file.content_type or ""

    if content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Image files should be sent inline via the chat endpoint, not uploaded here.",
        )

    # Read file contents (enforce size limit)
    contents = await file.read()
    if len(contents) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_FILE_SIZE // (1024 * 1024)} MB.",
        )

    original_name = file.filename or "unnamed_file"
    sanitized = sanitize_filename(original_name)
    timestamp = int(time.time())
    dest_name = f"{timestamp}_{sanitized}"
    dest_path = os.path.join(UPLOADS_DIR, dest_name)

    ensure_uploads_dir()

    with open(dest_path, "wb") as f:
        f.write(contents)

    logfire.info(
        "File uploaded",
        filename=original_name,
        path=dest_path,
        size=len(contents),
    )

    return {
        "path": dest_path,
        "filename": original_name,
        "size": len(contents),
    }
