SHELL := /bin/bash
HIDE ?= @

.PHONY: gen dev test fix lint clean docker-build docker-push docker-up docker-down docker-log ship help

name := "code-analyzer"
port := 3006

# Initialize environment
gen:
	-$(HIDE)rm -rf .venv
	$(HIDE)uv venv .venv --python=3.12
	$(HIDE)source .venv/bin/activate && uv sync
	@echo "Run: source .venv/bin/activate"

# Format and fix code
fix:
	$(HIDE)source .venv/bin/activate && uv run ruff format src/
	$(HIDE)source .venv/bin/activate && uv run ruff check --fix src/

# Lint check
lint:
	$(HIDE)source .venv/bin/activate && uv run ruff check src/

# Development mode
dev:
	$(HIDE)source .venv/bin/activate && uv run uvicorn src.main:app --port $(port) --reload

# Run tests
test:
	$(HIDE)source .venv/bin/activate && uv run pytest -v

# Clean up
clean:
	$(HIDE)rm -rf __pycache__ .pytest_cache .ruff_cache
	$(HIDE)find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	$(HIDE)rm -rf tmp/*
	@echo "✅ Cleaned up."

# Docker build
docker-build:
	$(HIDE)docker build -f Dockerfile -t $(name) .
	@echo "✅ Docker image built: $(name)"

# Docker push
docker-push: version := $(shell date +%y%m%d%H%M%S)
docker-push: tag := wangggym/$(name):$(version)
docker-push:
	$(HIDE)docker build --platform linux/amd64 -f Dockerfile -t $(tag) .
	$(HIDE)docker tag $(tag) wangggym/$(name):latest
	$(HIDE)docker push $(tag)
	$(HIDE)docker push wangggym/$(name):latest
	@echo "✅ Pushed: $(tag)"

# Docker start
docker-up: image := $(name)
docker-up: docker-down
	$(HIDE)docker run -d --name $(name) --env-file .env -p 0.0.0.0:$(port):$(port) -v /var/run/docker.sock:/var/run/docker.sock $(image)
	@echo "✅ Container started: $(name)"

# Docker stop
docker-down:
	-$(HIDE)docker rm -f $(name) 2>/dev/null || true

# Docker logs
docker-log:
	$(HIDE)docker logs $(name) -f -n 1000

# One-click deploy
ship: SERVER ?= yiminlab
ship: docker-push
	@echo "📦 Deploying to server..."
	@ssh $(SERVER) 'cd /root/apps/yiminlab/external/code-analyzer && docker compose pull && docker compose up -d --force-recreate'
	@echo "✅ Deployed!"

# Help
help:
	@echo "Available commands:"
	@echo ""
	@echo "Setup:"
	@echo "  make gen            - Initialize Python environment"
	@echo ""
	@echo "Development:"
	@echo "  make dev            - Run dev server (port $(port))"
	@echo "  make test           - Run tests"
	@echo "  make fix            - Format and fix code"
	@echo "  make lint           - Lint check"
	@echo "  make clean          - Clean build artifacts"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build   - Build Docker image"
	@echo "  make docker-push    - Build and push to Docker Hub"
	@echo "  make docker-up      - Start container"
	@echo "  make docker-down    - Stop container"
	@echo "  make docker-log     - View logs"
	@echo ""
	@echo "Deployment:"
	@echo "  make ship           - One-click build, push and deploy 🚀"
