"""Tests for mcp_guardian.upstream – all mocked, no real servers needed."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mcp_guardian.config import ServerAuth, ServerConfig
from mcp_guardian.exceptions import UpstreamError
from mcp_guardian.upstream import UpstreamManager


def _make_server(
    url: str = "http://localhost:3000/mcp",
    auth_type: str = "none",
    value_env: str = "",
) -> ServerConfig:
    return ServerConfig(
        url=url,
        auth=ServerAuth(type=auth_type, value_env=value_env),
    )


def _fake_tool(name: str) -> Any:
    """Create a minimal mock Tool-like object."""
    t = MagicMock()
    t.name = name
    return t


@pytest.fixture()
def manager() -> UpstreamManager:
    """Manager with two servers configured."""
    servers = {
        "pg": _make_server("http://localhost:3000/mcp"),
        "github": _make_server("https://api.github.com/mcp"),
    }
    return UpstreamManager(servers)


@pytest.mark.asyncio()
async def test_list_tools_returns_tools(manager: UpstreamManager) -> None:
    """list_tools returns tools from a mocked client."""
    fake_tools = [_fake_tool("tool_a"), _fake_tool("tool_b")]

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.list_tools = AsyncMock(return_value=fake_tools)

    with patch("fastmcp.Client", return_value=mock_client):
        tools = await manager.list_tools("pg")

    assert len(tools) == 2
    assert tools[0].name == "tool_a"
    assert tools[1].name == "tool_b"


@pytest.mark.asyncio()
async def test_call_tool_forwards_and_returns(manager: UpstreamManager) -> None:
    """call_tool forwards to mocked client and returns the result."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.call_tool = AsyncMock(return_value={"rows": [1, 2, 3]})

    with patch("fastmcp.Client", return_value=mock_client):
        result = await manager.call_tool("pg", "pg_query", {"sql": "SELECT 1"})

    assert result == {"rows": [1, 2, 3]}
    mock_client.call_tool.assert_awaited_once_with("pg_query", {"sql": "SELECT 1"})


@pytest.mark.asyncio()
async def test_probe_all_returns_all_servers(manager: UpstreamManager) -> None:
    """probe_all returns tools from all configured servers."""
    pg_tools = [_fake_tool("pg_query")]
    gh_tools = [_fake_tool("list_issues"), _fake_tool("create_pr")]

    call_count = 0

    async def _list_tools_side_effect(name: str) -> list[Any]:
        nonlocal call_count
        call_count += 1
        return pg_tools if name == "pg" else gh_tools

    with patch.object(manager, "list_tools", side_effect=_list_tools_side_effect):
        result = await manager.probe_all()

    assert set(result.keys()) == {"pg", "github"}
    assert len(result["pg"]) == 1
    assert len(result["github"]) == 2
    assert call_count == 2


@pytest.mark.asyncio()
async def test_connection_failure_raises_upstream_error(
    manager: UpstreamManager,
) -> None:
    """Connection failure raises UpstreamError."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(side_effect=ConnectionRefusedError("connection refused"))
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("fastmcp.Client", return_value=mock_client),
        pytest.raises(UpstreamError, match="Failed to list tools"),
    ):
        await manager.list_tools("pg")


@pytest.mark.asyncio()
async def test_unknown_server_raises_upstream_error() -> None:
    """Requesting an unknown server raises UpstreamError."""
    manager = UpstreamManager({"pg": _make_server()})
    with pytest.raises(UpstreamError, match="Unknown server 'nonexistent'"):
        await manager.list_tools("nonexistent")
