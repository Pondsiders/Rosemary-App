# Rosemary — Kylee's AI companion
# Claude CLI is a native binary bundled inside claude-agent-sdk — no Node needed.

FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

WORKDIR /app

# Install Rosemary SDK first (changes less often)
COPY Rosemary-SDK/ /app/Rosemary-SDK/
RUN uv pip install --system /app/Rosemary-SDK/

# Install app dependencies
COPY backend-py/ /app/backend-py/
RUN cd /app/backend-py && uv pip install --system .

# Build frontend and copy static files
# (In production, frontend is pre-built and served by FastAPI)
COPY frontend/dist/ /app/frontend/dist/

# Non-root user — the Claude Agent SDK refuses --dangerously-skip-permissions
# as root. Create a user with a home dir for ~/.claude/ session storage.
RUN useradd --create-home --shell /bin/bash rosemary \
    && mkdir -p /home/rosemary/.claude \
    && chown rosemary:rosemary /home/rosemary/.claude
USER rosemary

EXPOSE 8779

CMD ["python", "-m", "uvicorn", "rosemary_app.main:app", "--host", "0.0.0.0", "--port", "8779"]
