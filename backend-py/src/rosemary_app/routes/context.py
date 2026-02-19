"""Context route — basic time info."""

import socket

import pendulum
from fastapi import APIRouter

router = APIRouter()


@router.get("/api/context")
async def get_context() -> dict[str, str]:
    now = pendulum.now("America/Los_Angeles")
    return {
        "hostname": socket.gethostname(),
        "date": now.format("ddd MMM D YYYY"),
        "time": now.format("h:mm A"),
        "datetime": now.format("ddd MMM D YYYY, h:mm A"),
    }
