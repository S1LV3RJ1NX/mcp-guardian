"""Tests for mcp_guardian.config."""

from __future__ import annotations

import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from mcp_guardian.config import load_config
from mcp_guardian.exceptions import ConfigError


@pytest.fixture()
def config_dir(tmp_path: Path) -> Path:
    """Return a temp directory for writing test config files."""
    return tmp_path


def _write_config(config_dir: Path, content: str, name: str = "scope.yaml") -> str:
    """Write a YAML config to a temp file and return the path string."""
    p = config_dir / name
    p.write_text(textwrap.dedent(content))
    return str(p)


MINIMAL_VALID = """\
    upstream_servers:
      myserver:
        url: http://localhost:3000/mcp
        auth:
          type: none

    scopes:
      test-scope:
        description: "Test scope"
        servers:
          myserver:
            allowed_tools:
              - tool_a
              - tool_b
    """


def test_valid_config_loads(config_dir: Path) -> None:
    """A well-formed config file loads without errors."""
    path = _write_config(config_dir, MINIMAL_VALID)
    config = load_config(path, "test-scope")
    assert config.active_scope == "test-scope"
    assert "myserver" in config.upstream_servers
    assert config.upstream_servers["myserver"].url == "http://localhost:3000/mcp"
    assert config.scopes["test-scope"].servers["myserver"].allowed_tools == ["tool_a", "tool_b"]


def test_loads_real_example_config() -> None:
    """examples/scope.direct.yaml loads successfully."""
    config = load_config("examples/scope.direct.yaml", "support-agent")
    assert set(config.upstream_servers.keys()) == {"github-oauth", "postgres", "trends"}
    assert config.active_scope == "support-agent"
    assert "github-oauth" in config.scopes["support-agent"].servers
    assert "postgres" in config.scopes["support-agent"].servers
    assert "trends" in config.scopes["support-agent"].servers


def test_missing_scope_raises(config_dir: Path) -> None:
    """Requesting a scope not in the config raises ConfigError."""
    path = _write_config(config_dir, MINIMAL_VALID)
    with pytest.raises(ConfigError, match="no-such-scope"):
        load_config(path, "no-such-scope")


def test_unknown_server_in_scope_raises(config_dir: Path) -> None:
    """A scope referencing a server not in upstream_servers raises ConfigError."""
    content = """\
        upstream_servers:
          real_server:
            url: http://localhost:3000/mcp

        scopes:
          broken:
            description: "refs nonexistent server"
            servers:
              ghost_server:
                allowed_tools:
                  - tool_a
        """
    path = _write_config(config_dir, content)
    with pytest.raises(ConfigError, match="ghost_server"):
        load_config(path, "broken")


def test_invalid_auth_type_raises(config_dir: Path) -> None:
    """An unsupported auth type raises ConfigError."""
    content = """\
        upstream_servers:
          srv:
            url: http://localhost:3000/mcp
            auth:
              type: magic_token

        scopes:
          s:
            description: x
            servers:
              srv:
                allowed_tools: "*"
        """
    path = _write_config(config_dir, content)
    with pytest.raises(ConfigError, match="magic_token"):
        load_config(path, "s")


def test_allowed_tools_wildcard(config_dir: Path) -> None:
    """allowed_tools: '*' is parsed as the string '*'."""
    content = """\
        upstream_servers:
          srv:
            url: http://localhost:3000/mcp

        scopes:
          s:
            description: x
            servers:
              srv:
                allowed_tools: "*"
        """
    path = _write_config(config_dir, content)
    config = load_config(path, "s")
    assert config.scopes["s"].servers["srv"].allowed_tools == "*"


def test_blocked_tools_parsed(config_dir: Path) -> None:
    """blocked_tools is parsed as a list."""
    content = """\
        upstream_servers:
          srv:
            url: http://localhost:3000/mcp

        scopes:
          s:
            description: x
            servers:
              srv:
                allowed_tools: "*"
                blocked_tools:
                  - dangerous_tool
                  - another_bad_tool
        """
    path = _write_config(config_dir, content)
    config = load_config(path, "s")
    assert config.scopes["s"].servers["srv"].blocked_tools == [
        "dangerous_tool",
        "another_bad_tool",
    ]


def test_missing_auth_defaults_to_none(config_dir: Path) -> None:
    """A server with no auth block defaults to type: none."""
    content = """\
        upstream_servers:
          srv:
            url: http://localhost:3000/mcp

        scopes:
          s:
            description: x
            servers:
              srv:
                allowed_tools: "*"
        """
    path = _write_config(config_dir, content)
    config = load_config(path, "s")
    assert config.upstream_servers["srv"].auth.type == "none"


def test_empty_yaml_raises(config_dir: Path) -> None:
    """An empty YAML file raises ConfigError."""
    path = _write_config(config_dir, "")
    with pytest.raises(ConfigError, match="empty"):
        load_config(path, "anything")


def test_url_env_resolves(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """url_env resolves the URL from an environment variable."""
    monkeypatch.setenv("TEST_PG_URL", "http://from-env:3000/mcp")
    content = """\
        upstream_servers:
          pg:
            url_env: TEST_PG_URL

        scopes:
          s:
            description: x
            servers:
              pg:
                allowed_tools: "*"
        """
    path = _write_config(config_dir, content)
    config = load_config(path, "s")
    assert config.upstream_servers["pg"].get_url() == "http://from-env:3000/mcp"


def test_server_without_url_or_url_env_raises(config_dir: Path) -> None:
    """A server with neither url nor url_env raises ConfigError."""
    content = """\
        upstream_servers:
          broken:
            transport: auto

        scopes:
          s:
            description: x
            servers:
              broken:
                allowed_tools: "*"
        """
    path = _write_config(config_dir, content)
    with pytest.raises(ConfigError, match="url"):
        load_config(path, "s")


def test_token_passthrough_auth_accepted(config_dir: Path) -> None:
    """token_passthrough is a valid auth type."""
    content = """\
        upstream_servers:
          gw:
            url: http://gateway:8080/mcp
            auth:
              type: token_passthrough

        scopes:
          s:
            description: x
            servers:
              gw:
                allowed_tools: "*"
        """
    path = _write_config(config_dir, content)
    config = load_config(path, "s")
    assert config.upstream_servers["gw"].auth.type == "token_passthrough"
