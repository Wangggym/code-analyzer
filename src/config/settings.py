"""Application settings and configuration"""

import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


def get_env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def get_env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).lower() in ("true", "1", "yes")


def get_env_int(key: str, default: str = "0") -> int:
    return int(os.getenv(key, default))


class Settings(BaseModel):
    """Application settings"""

    # Application
    debug: bool = get_env_bool("DEBUG", "false")
    app_name: str = "code-analyzer"
    api_port: int = get_env_int("API_PORT", "3006")
    log_level: str = get_env("LOG_LEVEL", "INFO")

    # CORS
    cors_origins: list[str] = ["*"]

    # Anthropic (Primary - Claude 4.5)
    anthropic_api_key: str = get_env("ANTHROPIC_API_KEY", "")
    anthropic_base_url: str = get_env(
        "ANTHROPIC_BASE_URL", "https://anthropic-proxy.brain.loocaa.com:1443"
    )
    anthropic_model_id: str = get_env(
        "ANTHROPIC_MODEL_ID", "claude-sonnet-4-20250514"
    )

    # OpenAI (Secondary - GPT-4o mini)
    openai_api_key: str = get_env("OPENAI_API_KEY", "")
    openai_base_url: str = get_env(
        "OPENAI_BASE_URL", "https://openai-proxy.brain.loocaa.com:1443/v1"
    )
    openai_model_id: str = get_env("OPENAI_MODEL_ID", "gpt-4o-mini")

    # Sandbox Configuration
    sandbox_timeout: int = get_env_int("SANDBOX_TIMEOUT", "300")
    sandbox_memory_limit: str = get_env("SANDBOX_MEMORY_LIMIT", "512m")
    sandbox_cpu_limit: float = float(get_env("SANDBOX_CPU_LIMIT", "1.0"))

    # Upload Configuration
    upload_dir: str = get_env("UPLOAD_DIR", "/tmp/code-analyzer")
    max_upload_size: int = get_env_int("MAX_UPLOAD_SIZE", "104857600")  # 100MB

    def print_config(self) -> None:
        """Print configuration (masking sensitive values)"""
        import logging

        logger = logging.getLogger(__name__)
        config_dict = self.model_dump()

        # Mask sensitive keys
        sensitive_keys = ["anthropic_api_key", "openai_api_key"]
        for key in sensitive_keys:
            if key in config_dict and config_dict[key]:
                config_dict[key] = config_dict[key][:8] + "***"

        logger.info(f"Configuration: {config_dict}")


settings = Settings()
