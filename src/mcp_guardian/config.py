"""YAML config loader and validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from mcp_guardian.exceptions import ConfigError

VALID_AUTH_TYPES = frozenset({"none", "static_header", "bearer_env", "token_passthrough", "oauth"})
VALID_TRANSPORTS = frozenset({"auto", "streamable-http", "sse"})


@dataclass
class ServerAuth:
    """Authentication configuration for an upstream server."""

    type: str
    header: str = "Authorization"
    value_env: str = ""


@dataclass
class ServerConfig:
    """Connection configuration for an upstream MCP server."""

    url: str = ""
    url_env: str = ""
    transport: str = "auto"
    auth: ServerAuth = field(default_factory=lambda: ServerAuth(type="none"))

    def get_url(self) -> str:
        """Resolve the server URL.

        If url_env is set, reads the URL from that environment variable.
        This is used when the URL contains credentials that shouldn't
        be in the YAML config file.

        Raises:
            ConfigError: If neither url nor url_env is set, or the env var is missing.
        """
        if self.url_env:
            from mcp_guardian.settings import get_env_var

            return get_env_var(self.url_env)
        if self.url:
            return self.url
        raise ConfigError("Server must have either 'url' or 'url_env'")


@dataclass
class ScopeServer:
    """Tool access rules for a server within a scope."""

    allowed_tools: list[str] | str
    blocked_tools: list[str] = field(default_factory=list)


@dataclass
class Scope:
    """A named scope defining tool access across servers."""

    description: str
    servers: dict[str, ScopeServer]


@dataclass
class AuditConfig:
    """Audit logging configuration."""

    enabled: bool = True
    log_file: str = "audit.log"
    include_params: bool = True


@dataclass
class GuardianConfig:
    """Top-level configuration for mcp-guardian."""

    upstream_servers: dict[str, ServerConfig]
    scopes: dict[str, Scope]
    audit: AuditConfig
    active_scope: str


def _parse_auth(raw: dict | None) -> ServerAuth:
    """Parse an auth block from YAML, defaulting to type: none."""
    if raw is None:
        return ServerAuth(type="none")
    auth_type = raw.get("type", "none")
    if auth_type not in VALID_AUTH_TYPES:
        raise ConfigError(
            f"Invalid auth type: '{auth_type}'. Supported: {', '.join(sorted(VALID_AUTH_TYPES))}"
        )
    return ServerAuth(
        type=auth_type,
        header=raw.get("header", "Authorization"),
        value_env=raw.get("value_env", ""),
    )


def _parse_server(name: str, raw: dict) -> ServerConfig:
    """Parse a single upstream server config block."""
    url = raw.get("url", "")
    url_env = raw.get("url_env", "")
    if not url and not url_env:
        raise ConfigError(
            f"Server '{name}' must have either 'url' or 'url_env'. "
            f"Add one of these fields to the server config."
        )
    transport = raw.get("transport", "auto")
    if transport not in VALID_TRANSPORTS:
        raise ConfigError(
            f"Server '{name}' has invalid transport: '{transport}'. "
            f"Supported: {', '.join(sorted(VALID_TRANSPORTS))}"
        )
    return ServerConfig(
        url=url,
        url_env=url_env,
        transport=transport,
        auth=_parse_auth(raw.get("auth")),
    )


def _parse_scope_server(server_name: str, raw: dict) -> ScopeServer:
    """Parse a scope's server access rules."""
    allowed = raw.get("allowed_tools", [])
    blocked = raw.get("blocked_tools", [])
    if isinstance(blocked, str):
        blocked = [blocked]
    return ScopeServer(allowed_tools=allowed, blocked_tools=blocked)


def _parse_audit(raw: dict | None) -> AuditConfig:
    """Parse audit config block, defaulting to enabled."""
    if raw is None:
        return AuditConfig()
    return AuditConfig(
        enabled=raw.get("enabled", True),
        log_file=raw.get("log_file", "audit.log"),
        include_params=raw.get("include_params", True),
    )


def load_config(path: str, scope: str) -> GuardianConfig:
    """Load and validate a scope.yaml configuration file.

    Args:
        path: Path to the YAML config file.
        scope: Name of the active scope to use.

    Returns:
        A fully validated GuardianConfig.

    Raises:
        ConfigError: On any validation error with a human-readable message.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(f"Config file not found: {path}")

    raw_text = config_path.read_text()
    raw = yaml.safe_load(raw_text)

    if not raw or not isinstance(raw, dict):
        raise ConfigError(f"Config file is empty or invalid: {path}")

    # Parse upstream servers
    raw_servers = raw.get("upstream_servers")
    if not raw_servers or not isinstance(raw_servers, dict):
        raise ConfigError(
            "Config must have an 'upstream_servers' section with at least one server."
        )
    servers = {name: _parse_server(name, srv) for name, srv in raw_servers.items()}

    # Parse scopes
    raw_scopes = raw.get("scopes")
    if not raw_scopes or not isinstance(raw_scopes, dict):
        raise ConfigError("Config must have a 'scopes' section with at least one scope.")

    scopes: dict[str, Scope] = {}
    for scope_name, scope_data in raw_scopes.items():
        scope_servers: dict[str, ScopeServer] = {}
        for srv_name, srv_data in scope_data.get("servers", {}).items():
            if srv_name not in servers:
                raise ConfigError(
                    f"Scope '{scope_name}' references server '{srv_name}' "
                    f"which is not defined in upstream_servers. "
                    f"Available servers: {', '.join(servers.keys())}"
                )
            scope_servers[srv_name] = _parse_scope_server(srv_name, srv_data)
        scopes[scope_name] = Scope(
            description=scope_data.get("description", ""),
            servers=scope_servers,
        )

    # Validate active scope exists
    if scope not in scopes:
        raise ConfigError(
            f"Scope '{scope}' not found in config. Available scopes: {', '.join(scopes.keys())}"
        )

    audit = _parse_audit(raw.get("audit"))

    return GuardianConfig(
        upstream_servers=servers,
        scopes=scopes,
        audit=audit,
        active_scope=scope,
    )
