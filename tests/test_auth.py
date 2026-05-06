"""Tests for mcp_guardian.auth."""

from __future__ import annotations

import pytest

from mcp_guardian.auth import get_auth_headers
from mcp_guardian.config import ServerAuth
from mcp_guardian.exceptions import ConfigError


def test_none_returns_empty() -> None:
    """type: none returns an empty dict."""
    auth = ServerAuth(type="none")
    assert get_auth_headers(auth) == {}


def test_bearer_env_returns_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """type: bearer_env returns Authorization: Bearer <token>."""
    monkeypatch.setenv("TEST_GH_TOKEN", "ghp_abc123")
    auth = ServerAuth(type="bearer_env", value_env="TEST_GH_TOKEN")
    headers = get_auth_headers(auth)
    assert headers == {"Authorization": "Bearer ghp_abc123"}


def test_static_header_custom_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """type: static_header with custom header name works."""
    monkeypatch.setenv("MY_API_KEY", "key-xyz")
    auth = ServerAuth(type="static_header", header="X-Api-Key", value_env="MY_API_KEY")
    headers = get_auth_headers(auth)
    assert headers == {"X-Api-Key": "key-xyz"}


def test_token_passthrough_forwards_header() -> None:
    """type: token_passthrough forwards the client's Authorization header."""
    auth = ServerAuth(type="token_passthrough")
    client_headers = {"Authorization": "Bearer user-jwt-token"}
    headers = get_auth_headers(auth, client_headers=client_headers)
    assert headers == {"Authorization": "Bearer user-jwt-token"}


def test_token_passthrough_no_client_headers() -> None:
    """type: token_passthrough with no client headers returns empty dict."""
    auth = ServerAuth(type="token_passthrough")
    assert get_auth_headers(auth) == {}
    assert get_auth_headers(auth, client_headers={}) == {}


def test_missing_env_var_raises() -> None:
    """Missing env var raises ConfigError with a helpful message."""
    auth = ServerAuth(type="bearer_env", value_env="DEFINITELY_MISSING_VAR_XYZ_99")
    with pytest.raises(ConfigError, match="DEFINITELY_MISSING_VAR_XYZ_99"):
        get_auth_headers(auth)


def test_unknown_auth_type_raises() -> None:
    """Unknown auth type raises ConfigError."""
    auth = ServerAuth(type="magic_token")
    with pytest.raises(ConfigError, match="magic_token"):
        get_auth_headers(auth)
