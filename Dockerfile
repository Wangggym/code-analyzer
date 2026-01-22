# syntax=docker/dockerfile:1
FROM --platform=linux/amd64 ghcr.io/astral-sh/uv:latest AS uv
FROM --platform=linux/amd64 python:3.12-slim-bookworm

# Install system dependencies (including Docker CLI and unzip for sandbox execution)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    gnupg \
    unzip \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian bookworm stable" > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=uv /uv /uvx /bin/

WORKDIR /app

# Copy dependency files and README (required by hatchling)
COPY pyproject.toml uv.lock* README.md ./

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
