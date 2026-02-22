"""Rosemary backend - FastAPI application.

One process. One client. One companion.

Lazy initialization: no client at startup.
First chat request creates the client.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import logfire

from rosemary_app.client import client
from rosemary_app.routes.chat import router as chat_router
from rosemary_app.routes.sessions import router as sessions_router
from rosemary_app.routes.context import router as context_router
from rosemary_app.routes.upload import router as upload_router, ensure_uploads_dir

# Suppress harmless "Failed to detach context" warnings from OTel
# These occur when spans cross async generator boundaries - expected behavior
logging.getLogger("opentelemetry.context").setLevel(logging.CRITICAL)

# Initialize Logfire
# Scrubbing disabled - too aggressive (redacts "session", "auth", etc.)
# Our logs are authenticated with 30-day retention; acceptable risk for debugging visibility
logfire.configure(
    service_name="rosemary",
    distributed_tracing=True,
    scrubbing=False,
)

# Route Python logging through Logfire
logging.basicConfig(handlers=[logfire.LogfireLoggingHandler()], level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """App lifespan - just cleanup on shutdown.

    Client is created lazily on first request, not at startup.
    """
    print("[Rosemary] Starting up... (client will connect on first request)")

    # Ensure the uploads directory exists at startup
    ensure_uploads_dir()

    yield

    print("[Rosemary] Shutting down...")
    await client.shutdown()
    print("[Rosemary] Goodbye.")


app = FastAPI(
    title="Rosemary",
    description="Rosemary — Kylee's AI companion",
    version="0.1.0",
    lifespan=lifespan,
)

# Instrument FastAPI with Logfire for automatic request tracing
logfire.instrument_fastapi(app)

# CORS - allow frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routes
app.include_router(chat_router)
app.include_router(sessions_router)
app.include_router(context_router)
app.include_router(upload_router)


@app.get("/health")
async def health() -> dict[str, str | None]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "client_connected": str(client.connected),
        "current_session": client.current_session_id[:8] + "..." if client.current_session_id else None,
    }


# ── Static file serving (production: built frontend from Docker stage 1) ──

FRONTEND_DIR = Path("/app/frontend/dist")

if FRONTEND_DIR.is_dir():
    # Serve Vite's hashed asset bundles
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="static-assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str) -> FileResponse:
        """Serve built frontend — SPA catch-all.

        Try the exact file first (favicon.ico, etc.), fall back to
        index.html for client-side routing.
        """
        file_path = FRONTEND_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(FRONTEND_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8779"))
    uvicorn.run(app, host="0.0.0.0", port=port)
