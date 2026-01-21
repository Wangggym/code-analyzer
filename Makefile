.PHONY: install dev run test lint format clean docker-build docker-run

# Install dependencies
install:
	uv sync

# Install dev dependencies
dev:
	uv sync --group dev

# Run the application
run:
	uv run uvicorn src.main:app --reload --port 3006

# Run tests
test:
	uv run pytest -v

# Lint code
lint:
	uv run ruff check src/

# Format code
format:
	uv run ruff format src/

# Clean up
clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf tmp/*

# Docker commands
docker-build:
	docker build -t code-analyzer .

docker-run:
	docker run -p 3006:3006 --env-file .env -v /var/run/docker.sock:/var/run/docker.sock code-analyzer

docker-compose-up:
	docker-compose up -d

docker-compose-down:
	docker-compose down
