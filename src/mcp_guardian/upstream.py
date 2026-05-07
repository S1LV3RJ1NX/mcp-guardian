"""Upstream MCP server connection manager."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from mcp_guardian.exceptions import ConfigError, UpstreamError
from mcp_guardian.keystore import InMemoryKeyStore, KeyStore

if TYPE_CHECKING:
    from fastmcp import Client
    from mcp.types import Tool

    from mcp_guardian.config import ServerConfig

logger = logging.getLogger(__name__)


class UpstreamManager:
    """Manages connections to upstream MCP servers.

    Non-OAuth servers use a fresh connection per call to avoid stale
    sessions. OAuth servers keep a persistent client so the in-memory
    token survives across calls (one browser auth per session).

    API keys are resolved through a pluggable KeyStore (defaults to
    InMemoryKeyStore). Pass a custom KeyStore for Redis, database, etc.
    """

    def __init__(
        self,
        servers: dict[str, ServerConfig],
        key_store: KeyStore | None = None,
    ) -> None:
        self._servers = servers
        self._oauth_clients: dict[str, Client] = {}
        self.key_store: KeyStore = key_store or InMemoryKeyStore()

    async def _resolve_auth(
        self,
        name: str,
        server: ServerConfig,
        *,
        interactive: bool = True,
        client_headers: dict[str, str] | None = None,
    ) -> str | None:
        """Resolve the auth credential for a server.

        Priority chain for bearer_env:
          1. Client Authorization header (curl, Postman, MCP client)
          2. KeyStore (dashboard-entered or external store)
          3. Environment variable (value_env)
          4. None (server will be deferred)

        Args:
            name: Server name (used to look up cached keys).
            server: Server configuration.
            interactive: When False, OAuth servers return None so the
                call fails fast with 401 instead of blocking on a
                browser flow.
            client_headers: Headers from the incoming client request.
        """
        if server.auth.type == "bearer_env":
            if client_headers:
                for key in ("authorization", "Authorization"):
                    if key in client_headers:
                        return client_headers[key].removeprefix("Bearer ").strip()
            cached = await self.key_store.get(name)
            if cached:
                return cached
            if server.auth.value_env:
                try:
                    from mcp_guardian.settings import get_env_var

                    return get_env_var(server.auth.value_env)
                except ConfigError:
                    pass
            return None

        if server.auth.type == "oauth":
            return "oauth" if interactive else None

        return None

    def _get_server(self, name: str) -> ServerConfig:
        """Look up a server config by name, raising on unknown names."""
        if name not in self._servers:
            available = ", ".join(self._servers.keys()) or "(none)"
            raise UpstreamError(f"Unknown server '{name}'. Available servers: {available}")
        return self._servers[name]

    def _is_oauth(self, name: str) -> bool:
        """Check if a server uses OAuth auth."""
        return self._servers[name].auth.type == "oauth"

    async def _get_oauth_client(self, name: str) -> Client:
        """Return a cached, connected OAuth client (creating on first use)."""
        if name not in self._oauth_clients:
            from fastmcp import Client as FastMCPClient

            server = self._get_server(name)
            url = server.get_url()
            auth = self._build_oauth_provider(server)
            client = FastMCPClient(url, auth=auth)
            await client.__aenter__()
            self._oauth_clients[name] = client
            logger.info("Persistent OAuth client created for '%s'", name)
        return self._oauth_clients[name]

    def _build_oauth_provider(self, server: ServerConfig) -> str | object:
        """Build an OAuth auth provider, using static credentials when configured."""
        if not server.auth.client_id:
            return "oauth"

        from fastmcp.client.auth.oauth import OAuth

        client_secret: str | None = None
        if server.auth.client_secret_env:
            from mcp_guardian.settings import get_env_var

            try:
                client_secret = get_env_var(server.auth.client_secret_env)
            except Exception:
                logger.debug("client_secret_env '%s' not set", server.auth.client_secret_env)

        return OAuth(
            client_id=server.auth.client_id,
            client_secret=client_secret,
        )

    async def disconnect_oauth(self, name: str) -> bool:
        """Disconnect and discard the cached OAuth client for a server.

        Returns True if a client was disconnected, False if none was cached.
        """
        client = self._oauth_clients.pop(name, None)
        if client is None:
            return False
        try:
            await client.__aexit__(None, None, None)
        except Exception:
            logger.debug("Error during OAuth client disconnect for '%s'", name, exc_info=True)
        logger.info("OAuth client disconnected for '%s'", name)
        return True

    async def shutdown(self) -> None:
        """Close all cached OAuth clients. Safe to call multiple times."""
        names = list(self._oauth_clients.keys())
        for name in names:
            await self.disconnect_oauth(name)
        if names:
            logger.info("All upstream OAuth clients closed")

    async def list_tools(self, name: str, *, interactive: bool = True) -> list[Tool]:
        """Connect to a server, list its tools, and disconnect.

        Args:
            name: Server name as defined in upstream_servers config.
            interactive: If False, skip OAuth browser flow and fail fast.

        Returns:
            List of MCP Tool objects from the server.

        Raises:
            UpstreamError: If the server is unreachable or returns an error.
        """
        server = self._get_server(name)

        if self._is_oauth(name) and interactive:
            try:
                client = await self._get_oauth_client(name)
                return await client.list_tools()
            except Exception as exc:
                self._oauth_clients.pop(name, None)
                raise UpstreamError(f"Failed to list tools from '{name}': {exc}") from exc

        from fastmcp import Client

        url = server.get_url()
        auth = await self._resolve_auth(name, server, interactive=interactive)

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
        if self._is_oauth(name):
            try:
                client = await self._get_oauth_client(name)
                return await client.call_tool(tool_name, params)
            except Exception as exc:
                self._oauth_clients.pop(name, None)
                raise UpstreamError(f"Failed to call '{tool_name}' on '{name}': {exc}") from exc

        from fastmcp import Client

        server = self._get_server(name)
        url = server.get_url()
        auth = await self._resolve_auth(name, server, client_headers=client_headers)

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
