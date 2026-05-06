"""Tests for mcp_guardian.settings."""

from __future__ import annotations

import os

import pytest

from mcp_guardian.exceptions import ConfigError
from mcp_guardian.settings import GuardianSettings, get_env_var, get_settings


def test_default_settings_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default settings have correct values when no env vars are set."""
    for key in ("GUARDIAN_HOST", "GUARDIAN_PORT", "GUARDIAN_SCOPE", "GUARDIAN_LOG_LEVEL"):
        monkeypatch.delenv(key, raising=False)
    settings = GuardianSettings(_env_file=None)  # type: ignore[call-arg]
    assert settings.host == "0.0.0.0"
    assert settings.port == 9000
    assert settings.transport == "streamable-http"
    assert settings.config_path == "scope.yaml"
    assert settings.scope == ""
    assert settings.log_level == "INFO"


def test_get_settings_with_overrides() -> None:
    """get_settings applies keyword overrides."""
    settings = get_settings(port=8080, scope="dev", log_level="DEBUG")
    assert settings.port == 8080
    assert settings.scope == "dev"
    assert settings.log_level == "DEBUG"


def test_get_env_var_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_env_var returns the value when the env var is set."""
    monkeypatch.setenv("TEST_TOKEN_ABC", "secret123")
    assert get_env_var("TEST_TOKEN_ABC") == "secret123"


def test_get_env_var_raises_on_missing() -> None:
    """get_env_var raises ConfigError when the env var is not set."""
    var_name = "DEFINITELY_NOT_SET_VAR_XYZ_12345"
    assert os.environ.get(var_name) is None
    with pytest.raises(ConfigError, match=var_name):
        get_env_var(var_name)
