"""Startup method analyzer using LLM"""

import json
import logging
import os
from dataclasses import dataclass

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from src.config import settings

logger = logging.getLogger(__name__)


@dataclass
class StartupConfig:
    """Configuration for starting the project"""

    start_method: str  # npm, python, go, dockerfile, docker-compose, unknown
    runtime: str  # Docker image: node:20, python:3.12, golang:1.21, etc.
    install_command: str  # npm install, pip install -r requirements.txt
    start_command: str  # npm start, python main.py
    health_check_url: str | None
    service_port: int
    estimated_startup_time: int  # seconds
    reason: str  # Why this method was chosen


STARTUP_ANALYSIS_PROMPT = """You are a DevOps expert. Analyze the project configuration files and determine the SIMPLEST and MOST RELIABLE way to start this project for testing.

IMPORTANT - Priority order (choose the FIRST one that works):
1. **Native commands** (npm/python/go) - MOST RELIABLE
   - Look at README.md for start instructions (e.g., "npm install && npm start")
   - Check package.json scripts
   - Check if code has sensible defaults (no mandatory env vars)
   
2. **Dockerfile** - If native won't work (complex dependencies)

3. **docker-compose** - LAST RESORT, often complex
   - Only if project REQUIRES multiple services (database, redis, etc.)
   - docker-compose configs often have complex env_file requirements that fail

AVOID docker-compose if:
- Project uses SQLite/in-memory DB by default
- README shows simple npm/python start commands
- docker-compose.yml has env_file dependencies

Output ONLY valid JSON:
{
  "start_method": "npm" | "python" | "go" | "dockerfile" | "docker-compose" | "unknown",
  "runtime": "node:20" | "python:3.12" | "golang:1.21" | "custom",
  "install_command": "npm install",
  "start_command": "npm run start",
  "health_check_url": "http://localhost:3000/graphql",
  "service_port": 3000,
  "estimated_startup_time": 90,
  "reason": "README shows npm start, uses SQLite by default"
}

Examples:
- Node.js with SQLite: {"start_method": "npm", "runtime": "node:20", "install_command": "npm install", "start_command": "npm run start", "health_check_url": "http://localhost:3000/graphql", "service_port": 3000, "estimated_startup_time": 90, "reason": "package.json has start script, uses SQLite default"}
- Python FastAPI: {"start_method": "python", "runtime": "python:3.12", "install_command": "pip install -r requirements.txt", "start_command": "uvicorn main:app --host 0.0.0.0 --port 8000", "health_check_url": "http://localhost:8000/health", "service_port": 8000, "estimated_startup_time": 30, "reason": "README shows uvicorn command"}
"""


async def analyze_startup_method(project_dir: str) -> StartupConfig:
    """
    Use LLM to analyze how to start the project.

    Args:
        project_dir: Path to the project directory

    Returns:
        StartupConfig with startup instructions
    """
    # Collect relevant config files
    config_files = {}

    files_to_check = [
        "package.json",
        "docker-compose.yml",
        "docker-compose.yaml",
        "Dockerfile",
        "README.md",
        "pyproject.toml",
        "requirements.txt",
        ".env.example",
        "Makefile",
    ]

    for filename in files_to_check:
        filepath = os.path.join(project_dir, filename)
        if os.path.exists(filepath):
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    # Truncate large files
                    if len(content) > 5000:
                        content = content[:5000] + "\n... (truncated)"
                    config_files[filename] = content
            except Exception as e:
                logger.warning(f"Failed to read {filename}: {e}")

    if not config_files:
        logger.warning("No config files found")
        return _default_config()

    # Build prompt
    files_content = "\n\n".join(
        f"## {name}\n```\n{content}\n```" for name, content in config_files.items()
    )

    user_prompt = f"""Analyze this project and determine how to start it:

{files_content}

Output the startup configuration as JSON.
"""

    # Call LLM
    provider = AnthropicProvider(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
    )
    model = AnthropicModel(
        model_name=settings.anthropic_model_id,
        provider=provider,
    )

    agent = Agent(model=model, system_prompt=STARTUP_ANALYSIS_PROMPT)

    try:
        result = await agent.run(user_prompt)
        response = result.output

        # Parse JSON from response
        json_str = response
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            json_str = response[start:end].strip()
        elif "```" in response:
            start = response.find("```") + 3
            end = response.find("```", start)
            json_str = response[start:end].strip()

        data = json.loads(json_str)

        return StartupConfig(
            start_method=data.get("start_method", "unknown"),
            runtime=data.get("runtime", "node:20"),
            install_command=data.get("install_command", ""),
            start_command=data.get("start_command", ""),
            health_check_url=data.get("health_check_url"),
            service_port=data.get("service_port", 3000),
            estimated_startup_time=data.get("estimated_startup_time", 90),
            reason=data.get("reason", ""),
        )

    except Exception as e:
        logger.exception(f"Failed to analyze startup method: {e}")
        return _default_config()


def _default_config() -> StartupConfig:
    """Return default config when analysis fails"""
    return StartupConfig(
        start_method="unknown",
        runtime="node:20",
        install_command="",
        start_command="",
        health_check_url=None,
        service_port=3000,
        estimated_startup_time=90,
        reason="Analysis failed, using defaults",
    )
