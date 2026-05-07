"""Pydantic Settings for environment-based configuration."""

from __future__ import annotations

import os

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

from mcp_guardian.exceptions import ConfigError

load_dotenv()


class GuardianSettings(BaseSettings):
    """Environment-based settings for mcp-guardian.

    Loaded from .env file and/or environment variables.
    All env vars are prefixed with GUARDIAN_ (except auth tokens
    which are referenced by name in scope.yaml — those are loaded
    into os.environ via load_dotenv() above).
    """

    model_config = SettingsConfigDict(
        env_prefix="GUARDIAN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 9000
    transport: str = "streamable-http"

    config_path: str = "scope.yaml"
    scope: str = ""

    audit_log_file: str = "audit.log"

    log_level: str = "INFO"

    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""
    llm_model_name: str = "gpt-4o-mini"


def get_settings(**overrides: object) -> GuardianSettings:
    """Load settings from env/.env file with optional overrides."""
    return GuardianSettings(**overrides)  # type: ignore[arg-type]


def get_env_var(name: str) -> str:
    """Read an env var by name. Used for auth tokens referenced in scope.yaml.

    Args:
        name: Environment variable name.

    Returns:
        The value of the environment variable.

    Raises:
        ConfigError: If the environment variable is not set or empty.
    """
    value = os.environ.get(name, "")
    if not value:
        raise ConfigError(
            f"Environment variable '{name}' not set. Set it: export {name}=your-value"
        )
    return value
