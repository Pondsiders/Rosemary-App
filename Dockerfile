# Rosemary — Kylee's AI companion
# Multi-stage: Node builds frontend, Python serves everything.

# ── Stage 1: Build frontend ──
FROM node:22-slim AS frontend-build

WORKDIR /build
COPY Rosemary-App/frontend/package.json Rosemary-App/frontend/package-lock.json* ./
RUN npm install
COPY Rosemary-App/frontend/ ./
RUN npm run build

# ── Stage 2: Python app ──
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
COPY Rosemary-App/backend-py/ /app/backend-py/
# Patch the SDK path — pyproject.toml points to ../../Rosemary-SDK (local dev layout)
# but inside Docker the SDK lives at /app/Rosemary-SDK
RUN cd /app/backend-py && \
    sed -i 's|path = "../../Rosemary-SDK", editable = true|path = "/app/Rosemary-SDK"|' pyproject.toml && \
    uv pip install --system .

# Copy built frontend from stage 1
COPY --from=frontend-build /build/dist/ /app/frontend/dist/

# Non-root user — the Claude Agent SDK refuses --dangerously-skip-permissions
# as root. UID 1000 matches jefferyharrell on the host so mounted files
# (Tailscale certs, Claude credentials) are readable without chmod.
RUN useradd --uid 1000 --create-home --shell /bin/bash rosemary \
    && mkdir -p /home/rosemary/.claude \
    && chown rosemary:rosemary /home/rosemary/.claude
USER rosemary

EXPOSE 8780

CMD ["python", "-m", "uvicorn", "rosemary_app.main:app", "--host", "0.0.0.0", "--port", "8780"]
