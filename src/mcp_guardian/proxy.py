"""Core proxy server exposing meta-tools."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastmcp import FastMCP

from mcp_guardian.audit import AuditLogger
from mcp_guardian.config import load_config
from mcp_guardian.index import ToolIndex
from mcp_guardian.tokens import savings_report
from mcp_guardian.upstream import UpstreamManager

logger = logging.getLogger(__name__)


class Guardian:
    """MCP proxy server implementing progressive discovery.

    Sits between MCP clients and upstream servers. Exposes three
    meta-tools (search_tools, get_schema, execute_tool) instead of
    forwarding full tool schemas. Implements the MCP spec's recommended
    progressive discovery pattern at the infrastructure layer.

    See: https://modelcontextprotocol.io/docs/develop/clients/client-best-practices
    """

    def __init__(self, config_path: str, scope: str) -> None:
        self.config = load_config(config_path, scope)
        self.upstream = UpstreamManager(self.config.upstream_servers)
        self.index = ToolIndex()
        self.audit = AuditLogger(self.config.audit)
        self._indexing_in_progress = False
        self.server = FastMCP(
            f"mcp-guardian ({scope})",
            instructions=(
                "This is an MCP proxy. Use search_tools to find available tools, "
                "get_schema to inspect a tool's parameters, then execute_tool to call it."
            ),
        )
        self._register_meta_tools()
        self._register_dashboard()

    def _register_meta_tools(self) -> None:
        """Register the 3 meta-tools on the FastMCP server."""

        @self.server.tool()
        async def search_tools(query: str) -> list[dict[str, Any]]:
            """Search available tools by keyword.

            Returns tool names and brief descriptions. Use this to discover
            what tools are available before calling get_schema.

            Args:
                query: Search keywords (e.g., 'github issues', 'query database', 'list tables')
            """
            self._try_index_deferred()
            results = self.index.search(query)
            output: list[dict[str, Any]] = [
                {"name": r.name, "server": r.server, "brief": r.brief} for r in results
            ]
            if self.index._deferred_servers:
                output.append(
                    {
                        "notice": (
                            f"Servers pending OAuth: {', '.join(self.index._deferred_servers)}. "
                            "Complete the OAuth flow in the browser, then search again."
                        ),
                    }
                )
            if not results and not self.index._deferred_servers:
                return [{"message": f"No tools matching '{query}'. Try different keywords."}]
            return output

        @self.server.tool()
        async def get_schema(tool_name: str) -> dict[str, Any]:
            """Get the full parameter schema for a specific tool.

            Call this before execute_tool to understand the required parameters
            and their types.

            Args:
                tool_name: Exact tool name from search_tools results.
            """
            self._try_index_deferred()
            schema = self.index.get_schema(tool_name)
            if schema is None:
                return {
                    "error": (
                        f"Tool '{tool_name}' not found in scope '{self.config.active_scope}'."
                    ),
                    "hint": "Use search_tools to find available tools.",
                }
            return schema

        @self.server.tool()
        async def execute_tool(
            tool_name: str,
            params: dict[str, Any],
        ) -> dict[str, Any] | list[Any] | str:
            """Execute a tool with the given parameters.

            Always call get_schema first to understand the required parameter
            format. If the upstream server requires OAuth authorization, this
            will return an auth_url -- open it in a browser to authorize,
            then retry.

            Args:
                tool_name: Exact tool name.
                params: Tool parameters as a JSON object.
            """
            entry = self.index.entries.get(tool_name)
            if entry is None:
                return {
                    "error": (
                        f"Tool '{tool_name}' not found in scope '{self.config.active_scope}'."
                    ),
                    "code": "TOOL_NOT_IN_SCOPE",
                }

            self.audit.log_call(
                scope=self.config.active_scope,
                tool=tool_name,
                server=entry.server,
                params=params,
            )

            start = time.monotonic()
            try:
                result = await self.upstream.call_tool(
                    entry.server,
                    tool_name,
                    params,
                    client_headers=self._get_client_headers(),
                )
                duration_ms = int((time.monotonic() - start) * 1000)
                self.audit.log_result(
                    tool=tool_name,
                    status="ok",
                    duration_ms=duration_ms,
                    tokens_saved=self.index.tokens_saved,
                )
                return result
            except Exception as exc:
                duration_ms = int((time.monotonic() - start) * 1000)
                error_str = str(exc)

                if "McpAuthRequiredError" in error_str or "authorization_url" in error_str:
                    self.audit.log_result(
                        tool=tool_name,
                        status="auth_required",
                        duration_ms=duration_ms,
                    )
                    auth_url = self._extract_auth_url(exc)
                    return {
                        "error": "OAuth authorization required for this tool.",
                        "code": "AUTH_REQUIRED",
                        "auth_url": auth_url,
                        "message": (
                            "The upstream server requires OAuth authorization. "
                            "Open the auth_url in a browser to authorize, then retry."
                        ),
                    }

                self.audit.log_result(
                    tool=tool_name,
                    status="error",
                    duration_ms=duration_ms,
                    error=error_str,
                )
                return {"error": error_str, "code": "UPSTREAM_ERROR"}

    def _register_dashboard(self) -> None:
        """Mount the web dashboard on the same HTTP server."""
        from mcp_guardian.routes import register_dashboard_routes

        register_dashboard_routes(self)

    def _try_index_deferred(self) -> None:
        """Kick off deferred indexing in the background (non-blocking).

        OAuth servers require browser interaction, so we can't block
        the current request. A background task handles the flow and
        subsequent calls will see the newly indexed tools.
        """
        if self.index._deferred_servers and not self._indexing_in_progress:
            self._indexing_in_progress = True
            asyncio.create_task(self._do_index_deferred())

    async def _do_index_deferred(self) -> None:
        """Background coroutine that runs the deferred indexing."""
        try:
            indexed = await self.index.index_deferred(self.config, self.upstream)
            if indexed:
                logger.info("Indexed deferred servers: %s", ", ".join(indexed))
                report = savings_report(self.index)
                print(  # noqa: T201
                    f"  OAuth servers indexed: {', '.join(indexed)} "
                    f"({report['tools_in_scope']} tools now in scope)"
                )
        except Exception:
            logger.exception("Deferred indexing failed")
        finally:
            self._indexing_in_progress = False

    def _get_client_headers(self) -> dict[str, str]:
        """Extract the current client's request headers.

        Needed for token_passthrough auth. Falls back to empty dict
        when headers are not accessible from the request context.
        """
        return {}

    @staticmethod
    def _extract_auth_url(error: Exception) -> str | None:
        """Try to extract an OAuth authorization URL from an upstream error."""
        error_str = str(error)
        try:
            for part in error_str.split("{"):
                try:
                    data = json.loads("{" + part.split("}")[0] + "}")
                    if "authorization_urls" in data:
                        urls = data["authorization_urls"]
                        return next(iter(urls.values()), None)
                    if "auth_url" in data:
                        return data["auth_url"]
                except (json.JSONDecodeError, StopIteration):
                    continue
        except Exception:
            pass
        return None

    async def startup(self) -> None:
        """Connect to upstream servers and build the tool index."""
        await self.index.build(self.config, self.upstream)

        report = savings_report(self.index)
        logger.info("mcp-guardian started")
        logger.info("  Scope:          %s", self.config.active_scope)
        logger.info("  Servers:        %d", len(self.config.upstream_servers))
        logger.info("  Tools in scope: %d", report["tools_in_scope"])
        logger.info("  Direct cost:    %s tokens", f"{report['direct_tokens']:,}")
        logger.info("  Proxy cost:     %s tokens", f"{report['proxy_tokens']:,}")
        logger.info("  Savings:        %.1f%%", report["savings_pct"])

        deferred = self.index._deferred_servers

        print("mcp-guardian started")  # noqa: T201
        print(f"  Scope:          {self.config.active_scope}")  # noqa: T201
        print(f"  Servers:        {len(self.config.upstream_servers)}")  # noqa: T201
        print(f"  Tools in scope: {report['tools_in_scope']}")  # noqa: T201
        print(f"  Direct cost:    {report['direct_tokens']:,} tokens")  # noqa: T201
        print(f"  Proxy cost:     {report['proxy_tokens']:,} tokens")  # noqa: T201
        print(f"  Savings:        {report['savings_pct']:.1f}%")  # noqa: T201
        if deferred:
            print(f"  Deferred:       {', '.join(deferred)} (will index on first call)")  # noqa: T201

    def run(self, **kwargs: Any) -> None:
        """Run the proxy server."""
        import asyncio

        asyncio.run(self.startup())
        host = kwargs.get("host", "0.0.0.0")
        port = kwargs.get("port", 9000)
        print(f"  Dashboard:      http://{host}:{port}/")  # noqa: T201
        self.server.run(**kwargs)
