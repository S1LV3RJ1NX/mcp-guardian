"""Auth header injection for upstream servers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_guardian.exceptions import ConfigError
from mcp_guardian.settings import get_env_var

if TYPE_CHECKING:
    from mcp_guardian.config import ServerAuth


def get_auth_headers(
    auth: ServerAuth,
    client_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build HTTP headers for upstream server authentication.

    For token_passthrough, forwards the client's own Authorization
    header to the upstream server. This is used when the upstream
    is an MCP Gateway that manages per-user OAuth tokens.

    Args:
        auth: Server auth configuration from scope.yaml.
        client_headers: Original headers from the MCP client request.
            Required when auth.type is "token_passthrough".

    Returns:
        Dict of header name -> header value.

    Raises:
        ConfigError: If required env var or client header is missing.
    """
    if auth.type == "none":
        return {}

    if auth.type == "static_header":
        value = get_env_var(auth.value_env)
        return {auth.header: value}

    if auth.type == "bearer_env":
        token = get_env_var(auth.value_env)
        return {"Authorization": f"Bearer {token}"}

    if auth.type == "token_passthrough":
        if client_headers:
            for key in ("authorization", "Authorization"):
                if key in client_headers:
                    return {"Authorization": client_headers[key]}
        return {}

    if auth.type == "oauth":
        return {}

    raise ConfigError(
        f"Unknown auth type: '{auth.type}'. "
        f"Supported: none, static_header, bearer_env, token_passthrough, oauth"
    )
