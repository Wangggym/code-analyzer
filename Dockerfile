# syntax=docker/dockerfile:1
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:latest AS uv
FROM --platform=linux/amd64 python:3.12-slim-bookworm

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=uv /uv /uvx /bin/

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock* ./

# Install dependencies
RUN uv sync --frozen --no-cache --python-platform linux || uv sync --no-cache --python-platform linux

# Copy source code
COPY src ./src

# Create temp directory for uploads
RUN mkdir -p /tmp/code-analyzer

EXPOSE 3006

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:3006/health || exit 1

CMD [".venv/bin/uvicorn", "src.main:app", "--port", "3006", "--host", "0.0.0.0", "--workers", "2"]
