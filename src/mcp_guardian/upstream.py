"""Upstream MCP server connection manager."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from mcp_guardian.exceptions import UpstreamError

if TYPE_CHECKING:
    from mcp.types import Tool

    from mcp_guardian.config import ServerConfig

logger = logging.getLogger(__name__)


class UpstreamManager:
    """Manages per-call connections to upstream MCP servers.

    Each list_tools / call_tool invocation opens a fresh connection
    and closes it afterward. This avoids holding persistent sessions
    that can drop (especially with SSE-based servers).
    """

    def __init__(self, servers: dict[str, ServerConfig]) -> None:
        self._servers = servers

    def _resolve_auth(self, server: ServerConfig) -> str | None:
        """Resolve the auth token for a server, if applicable."""
        if server.auth.type == "bearer_env" and server.auth.value_env:
            from mcp_guardian.settings import get_env_var

            return get_env_var(server.auth.value_env)
        return None

    def _get_server(self, name: str) -> ServerConfig:
        """Look up a server config by name, raising on unknown names."""
        if name not in self._servers:
            available = ", ".join(self._servers.keys()) or "(none)"
            raise UpstreamError(f"Unknown server '{name}'. Available servers: {available}")
        return self._servers[name]

    async def list_tools(self, name: str) -> list[Tool]:
        """Connect to a server, list its tools, and disconnect.

        Args:
            name: Server name as defined in upstream_servers config.

        Returns:
            List of MCP Tool objects from the server.

        Raises:
            UpstreamError: If the server is unreachable or returns an error.
        """
        from fastmcp import Client

        server = self._get_server(name)
        url = server.get_url()
        auth = self._resolve_auth(server)

        try:
            async with Client(url, auth=auth) as client:
                return await client.list_tools()
        except Exception as exc:
            raise UpstreamError(f"Failed to list tools from '{name}' at {url}: {exc}") from exc

    async def call_tool(
        self,
        name: str,
        tool_name: str,
        params: dict[str, Any],
        *,
        client_headers: dict[str, str] | None = None,
    ) -> Any:
        """Connect to a server, call a tool, and return the result.

        Args:
            name: Server name as defined in upstream_servers config.
            tool_name: Name of the tool to invoke.
            params: Arguments to pass to the tool.
            client_headers: Original client request headers (for token_passthrough).

        Returns:
            The tool call result from the upstream server.

        Raises:
            UpstreamError: If the call fails.
        """
        from fastmcp import Client

        server = self._get_server(name)
        url = server.get_url()
        auth = self._resolve_auth(server)

        try:
            async with Client(url, auth=auth) as client:
                return await client.call_tool(tool_name, params)
        except Exception as exc:
            raise UpstreamError(
                f"Failed to call '{tool_name}' on '{name}' at {url}: {exc}"
            ) from exc

    async def probe_all(self) -> dict[str, list[Tool]]:
        """List tools from all configured servers concurrently.

        Returns:
            Dict of server_name -> list of tools.

        Raises:
            UpstreamError: If any server fails to respond.
        """

        async def _probe(name: str) -> tuple[str, list[Tool]]:
            tools = await self.list_tools(name)
            logger.info("Server '%s': %d tools", name, len(tools))
            return name, tools

        tasks = [_probe(name) for name in self._servers]
        results = await asyncio.gather(*tasks)
        return dict(results)
