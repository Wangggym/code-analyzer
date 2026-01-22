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

    start_method: str  # docker-compose, dockerfile, npm, python, unknown
    start_command: str
    stop_command: str
    health_check_url: str | None
    service_port: int
    env_vars: dict[str, str]
    estimated_startup_time: int  # seconds
    working_dir: str  # relative to project root


STARTUP_ANALYSIS_PROMPT = """You are a DevOps expert. Analyze the project configuration files and determine the best way to start this project for testing.

Given the project files, output a JSON with the startup configuration.

Important rules:
1. Prefer docker-compose if available (most isolated)
2. If only Dockerfile exists, use that
3. If neither, use the native runtime (npm for Node.js, python for Python)
4. Look at README for any special instructions
5. Identify the health check endpoint if available (often /health, /api/health, or GraphQL playground)
6. For GraphQL projects, the health check can be the GraphQL endpoint itself

Output ONLY valid JSON in this format:
{
  "start_method": "docker-compose" | "dockerfile" | "npm" | "python" | "unknown",
  "start_command": "the command to start the service",
  "stop_command": "the command to stop/cleanup",
  "health_check_url": "http://localhost:PORT/health or null if unknown",
  "service_port": 3000,
  "env_vars": {"KEY": "VALUE"},
  "estimated_startup_time": 30,
  "working_dir": "." 
}

Examples:
- docker-compose project: {"start_method": "docker-compose", "start_command": "docker-compose up -d", "stop_command": "docker-compose down -v", ...}
- npm project: {"start_method": "npm", "start_command": "npm install && npm run start", "stop_command": "pkill -f node", ...}
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
            start_command=data.get("start_command", ""),
            stop_command=data.get("stop_command", ""),
            health_check_url=data.get("health_check_url"),
            service_port=data.get("service_port", 3000),
            env_vars=data.get("env_vars", {}),
            estimated_startup_time=data.get("estimated_startup_time", 30),
            working_dir=data.get("working_dir", "."),
        )

    except Exception as e:
        logger.exception(f"Failed to analyze startup method: {e}")
        return _default_config()


def _default_config() -> StartupConfig:
    """Return default config when analysis fails"""
    return StartupConfig(
        start_method="unknown",
        start_command="",
        stop_command="",
        health_check_url=None,
        service_port=3000,
        env_vars={},
        estimated_startup_time=30,
        working_dir=".",
    )
