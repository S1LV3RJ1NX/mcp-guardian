"""Dashboard HTTP routes registered via FastMCP custom_route."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from starlette.responses import HTMLResponse, JSONResponse, StreamingResponse

if TYPE_CHECKING:
    from starlette.requests import Request

    from mcp_guardian.proxy import Guardian

logger = logging.getLogger(__name__)


def _icon_hint(name: str) -> str:
    """Guess an icon category from the server name."""
    lower = name.lower()
    if "github" in lower:
        return "github"
    if any(kw in lower for kw in ("postgres", "db", "sql", "database", "mysql")):
        return "database"
    if any(kw in lower for kw in ("twitter", "trend", "x-")):
        return "twitter"
    return "server"


def register_dashboard_routes(guardian: Guardian) -> None:
    """Register dashboard API + HTML routes on the FastMCP server."""

    server = guardian.server
    _html_cache: dict[str, str] = {}

    @server.custom_route("/", methods=["GET"])
    async def dashboard_page(request: Request) -> HTMLResponse:
        if "html" not in _html_cache:
            html_path = Path(__file__).parent / "dashboard.html"
            _html_cache["html"] = html_path.read_text()
        return HTMLResponse(_html_cache["html"])

    @server.custom_route("/api/stats", methods=["GET"])
    async def api_stats(request: Request) -> JSONResponse:
        from mcp_guardian.tokens import savings_report

        report = savings_report(guardian.index)
        return JSONResponse(
            {
                "scope": guardian.config.active_scope,
                "servers": list(guardian.config.upstream_servers.keys()),
                "deferred_servers": list(guardian.index._deferred_servers),
                **report,
            }
        )

    _connecting: set[str] = set()

    @server.custom_route("/api/servers", methods=["GET"])
    async def api_servers(request: Request) -> JSONResponse:
        scope = guardian.config.scopes[guardian.config.active_scope]
        result = []
        for name in scope.servers:
            srv_config = guardian.config.upstream_servers.get(name)
            auth_type = srv_config.auth.type if srv_config else "none"
            is_deferred = name in guardian.index._deferred_servers
            tool_count = sum(1 for e in guardian.index.entries.values() if e.server == name)
            needs_key = auth_type == "bearer_env" and is_deferred and name not in _connecting
            result.append(
                {
                    "name": name,
                    "auth_type": auth_type,
                    "status": (
                        "connecting"
                        if name in _connecting
                        else "pending"
                        if is_deferred
                        else "connected"
                    ),
                    "tool_count": tool_count,
                    "icon": _icon_hint(name),
                    "needs_key": needs_key,
                }
            )
        return JSONResponse(result)

    @server.custom_route("/api/servers/{name}/connect", methods=["POST"])
    async def api_connect_server(request: Request) -> JSONResponse:
        name = request.path_params["name"]
        if name not in guardian.index._deferred_servers:
            return JSONResponse({"status": "already_connected"})
        if name in _connecting:
            return JSONResponse({"status": "connecting"})
        _connecting.add(name)

        async def _do_connect() -> None:
            try:
                await guardian.index.index_single_deferred(name, guardian.config, guardian.upstream)
            finally:
                _connecting.discard(name)

        asyncio.create_task(_do_connect())
        return JSONResponse({"status": "connecting"})

    @server.custom_route("/api/servers/{name}/disconnect", methods=["POST"])
    async def api_disconnect_server(request: Request) -> JSONResponse:
        name = request.path_params["name"]
        srv_config = guardian.config.upstream_servers.get(name)
        if not srv_config:
            return JSONResponse({"error": "Unknown server"}, status_code=404)

        if srv_config.auth.type == "oauth":
            await guardian.upstream.disconnect_oauth(name)
        elif srv_config.auth.type == "bearer_env":
            await guardian.upstream.key_store.delete(name)
        else:
            return JSONResponse({"error": "Server does not use managed auth"}, status_code=400)

        to_remove = [k for k, e in guardian.index.entries.items() if e.server == name]
        for k in to_remove:
            del guardian.index.entries[k]
        if name not in guardian.index._deferred_servers:
            guardian.index._deferred_servers.append(name)
        return JSONResponse({"status": "disconnected"})

    @server.custom_route("/api/servers/{name}/key", methods=["POST"])
    async def api_set_key(request: Request) -> JSONResponse:
        name = request.path_params["name"]
        srv_config = guardian.config.upstream_servers.get(name)
        if not srv_config or srv_config.auth.type != "bearer_env":
            return JSONResponse({"error": "Server does not use bearer_env auth"}, status_code=400)
        body = await request.json()
        key = body.get("key", "").strip()
        if not key:
            return JSONResponse({"error": "Missing 'key' in body"}, status_code=400)

        await guardian.upstream.key_store.set(name, key)

        if name in guardian.index._deferred_servers:
            if name not in _connecting:
                _connecting.add(name)

                async def _do_key_index() -> None:
                    try:
                        await guardian.index.index_single_deferred(
                            name, guardian.config, guardian.upstream
                        )
                    finally:
                        _connecting.discard(name)

                asyncio.create_task(_do_key_index())
            return JSONResponse({"status": "connecting"})
        return JSONResponse({"status": "key_updated"})

    @server.custom_route("/api/servers/{name}/key", methods=["DELETE"])
    async def api_delete_key(request: Request) -> JSONResponse:
        name = request.path_params["name"]
        srv_config = guardian.config.upstream_servers.get(name)
        if not srv_config or srv_config.auth.type != "bearer_env":
            return JSONResponse({"error": "Server does not use bearer_env auth"}, status_code=400)
        await guardian.upstream.key_store.delete(name)
        to_remove = [k for k, e in guardian.index.entries.items() if e.server == name]
        for k in to_remove:
            del guardian.index.entries[k]
        if name not in guardian.index._deferred_servers:
            guardian.index._deferred_servers.append(name)
        return JSONResponse({"status": "key_removed"})

    @server.custom_route("/api/tools", methods=["GET"])
    async def api_tools(request: Request) -> JSONResponse:
        server_filter = request.query_params.get("server", "")
        entries = sorted(guardian.index.entries.values(), key=lambda e: e.name)
        if server_filter:
            entries = [e for e in entries if e.server == server_filter]
        tools = [
            {
                "name": e.name,
                "server": e.server,
                "description": e.description,
                "brief": e.brief,
                "token_cost": e.token_cost,
            }
            for e in entries
        ]
        return JSONResponse(tools)

    @server.custom_route("/api/search", methods=["GET"])
    async def api_search(request: Request) -> JSONResponse:
        query = request.query_params.get("q", "")
        if not query:
            return JSONResponse([])
        results = guardian.index.search(query)
        return JSONResponse(
            [{"name": r.name, "server": r.server, "brief": r.brief} for r in results]
        )

    @server.custom_route("/api/schema/{tool_name}", methods=["GET"])
    async def api_schema(request: Request) -> JSONResponse:
        tool_name = request.path_params["tool_name"]
        schema = guardian.index.get_schema(tool_name)
        if schema is None:
            return JSONResponse({"error": f"Tool '{tool_name}' not found"}, status_code=404)
        return JSONResponse(schema)

    _chat_agent: dict[str, object] = {}

    @server.custom_route("/api/chat", methods=["POST"])
    async def api_chat(request: Request) -> StreamingResponse | JSONResponse:
        from mcp_guardian.chat import ChatAgent
        from mcp_guardian.settings import get_settings

        body = await request.json()
        message = body.get("message", "").strip()
        history = body.get("history", [])
        if not message:
            return JSONResponse({"error": "Missing 'message' in body"}, status_code=400)

        settings = get_settings()
        if not settings.llm_api_key:
            return JSONResponse(
                {"error": "GUARDIAN_LLM_API_KEY not configured. Set it in .env"},
                status_code=500,
            )

        if "agent" not in _chat_agent:
            _chat_agent["agent"] = ChatAgent(
                guardian=guardian,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                model=settings.llm_model_name,
            )

        agent: ChatAgent = _chat_agent["agent"]  # type: ignore[assignment]

        async def _event_stream():  # type: ignore[no-untyped-def]
            try:
                async for event in agent.run_stream(message, history):
                    yield event
            except Exception as exc:
                logger.exception("Chat agent error")
                yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @server.custom_route("/api/audit", methods=["GET"])
    async def api_audit(request: Request) -> JSONResponse:
        limit = int(request.query_params.get("limit", "50"))
        log_path = Path(guardian.config.audit.log_file)
        if not log_path.exists():
            return JSONResponse([])
        lines = log_path.read_text().strip().splitlines()
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return JSONResponse(list(reversed(entries)))
