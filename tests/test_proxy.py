"""Tests for mcp_guardian.proxy — all mocked, no real servers needed."""

from __future__ import annotations

import json
import textwrap
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_guardian.proxy import Guardian


def _fake_tool(name: str, description: str = "A tool.") -> Any:
    """Create a mock MCP Tool object."""
    t = MagicMock()
    t.name = name
    t.description = description
    t.model_dump = MagicMock(
        return_value={
            "name": name,
            "description": description,
            "inputSchema": {"type": "object"},
        },
    )
    return t


FAKE_TOOLS = [
    _fake_tool("list_issues", "List issues in a repository"),
    _fake_tool("search_code", "Search code in a repository"),
    _fake_tool("pg_list_tables", "List all tables in the database"),
]

MINIMAL_CONFIG = textwrap.dedent("""\
    upstream_servers:
      srv:
        url: http://localhost:3000/mcp
    scopes:
      test:
        description: "test"
        servers:
          srv:
            allowed_tools: "*"
    """)


@pytest.fixture()
def guardian(tmp_path: pytest.TempPathFactory) -> Guardian:
    """Create a Guardian with mocked upstream, writing config to tmp dir."""
    config_file = tmp_path / "scope.yaml"  # type: ignore[union-attr]
    config_file.write_text(MINIMAL_CONFIG)
    audit_log = tmp_path / "audit.log"  # type: ignore[union-attr]

    g = Guardian(config_path=str(config_file), scope="test")
    g.config.audit.log_file = str(audit_log)
    g.audit._log_file = str(audit_log)
    return g


@pytest.fixture()
async def built_guardian(guardian: Guardian) -> Guardian:
    """Guardian with a built index (mocked upstream tools)."""
    mock_upstream = AsyncMock()
    mock_upstream.list_tools = AsyncMock(return_value=FAKE_TOOLS)
    mock_upstream.call_tool = AsyncMock(return_value={"result": "ok"})
    guardian.upstream = mock_upstream
    await guardian.index.build(guardian.config, guardian.upstream)
    return guardian


@pytest.mark.asyncio()
async def test_guardian_has_three_meta_tools(guardian: Guardian) -> None:
    """Guardian's FastMCP server exposes exactly 3 tools."""
    tools = await guardian.server.list_tools()
    assert len(tools) == 3
    names = {t.name for t in tools}
    assert names == {"search_tools", "get_schema", "execute_tool"}


@pytest.mark.asyncio()
async def test_search_tools_returns_results(built_guardian: Guardian) -> None:
    """search_tools returns matching tools."""
    tool = await built_guardian.server.get_tool("search_tools")
    results = await tool.fn(query="issues")
    assert isinstance(results, list)
    assert len(results) >= 1
    names = [r["name"] for r in results]
    assert "list_issues" in names


@pytest.mark.asyncio()
async def test_search_tools_no_match(built_guardian: Guardian) -> None:
    """search_tools with no matches returns helpful message."""
    tool = await built_guardian.server.get_tool("search_tools")
    results = await tool.fn(query="xyznonexistent")
    assert isinstance(results, list)
    assert len(results) == 1
    assert "message" in results[0]
    assert "No tools matching" in results[0]["message"]


@pytest.mark.asyncio()
async def test_get_schema_valid_tool(built_guardian: Guardian) -> None:
    """get_schema returns full schema for a valid tool."""
    tool = await built_guardian.server.get_tool("get_schema")
    schema = await tool.fn(tool_name="list_issues")
    assert isinstance(schema, dict)
    assert schema["name"] == "list_issues"


@pytest.mark.asyncio()
async def test_get_schema_blocked_tool(built_guardian: Guardian) -> None:
    """get_schema for a tool not in scope returns error."""
    tool = await built_guardian.server.get_tool("get_schema")
    result = await tool.fn(tool_name="delete_repo")
    assert "error" in result
    assert "hint" in result


@pytest.mark.asyncio()
async def test_execute_tool_forwards_to_upstream(built_guardian: Guardian) -> None:
    """execute_tool calls upstream and returns the result."""
    tool = await built_guardian.server.get_tool("execute_tool")
    result = await tool.fn(tool_name="list_issues", params={"repo": "acme/backend"})
    assert result == {"result": "ok"}
    built_guardian.upstream.call_tool.assert_awaited_once()


@pytest.mark.asyncio()
async def test_execute_tool_blocked(built_guardian: Guardian) -> None:
    """execute_tool on a tool not in scope returns TOOL_NOT_IN_SCOPE."""
    tool = await built_guardian.server.get_tool("execute_tool")
    result = await tool.fn(tool_name="delete_repo", params={})
    assert result["code"] == "TOOL_NOT_IN_SCOPE"


@pytest.mark.asyncio()
async def test_execute_tool_upstream_error(built_guardian: Guardian) -> None:
    """execute_tool returns UPSTREAM_ERROR when call fails."""
    built_guardian.upstream.call_tool = AsyncMock(
        side_effect=Exception("connection refused"),
    )
    tool = await built_guardian.server.get_tool("execute_tool")
    result = await tool.fn(tool_name="list_issues", params={})
    assert result["code"] == "UPSTREAM_ERROR"
    assert "connection refused" in result["error"]


@pytest.mark.asyncio()
async def test_execute_tool_auth_required(built_guardian: Guardian) -> None:
    """execute_tool returns AUTH_REQUIRED for OAuth errors."""
    built_guardian.upstream.call_tool = AsyncMock(
        side_effect=Exception("McpAuthRequiredError: authorization needed"),
    )
    tool = await built_guardian.server.get_tool("execute_tool")
    result = await tool.fn(tool_name="list_issues", params={})
    assert result["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio()
async def test_audit_log_written(built_guardian: Guardian) -> None:
    """Audit log has entries after execute_tool calls."""
    tool = await built_guardian.server.get_tool("execute_tool")
    await tool.fn(tool_name="list_issues", params={"repo": "test"})

    log_file = built_guardian.audit._log_file
    with open(log_file) as f:
        lines = [json.loads(line) for line in f if line.strip()]

    assert len(lines) == 2
    assert lines[0]["event"] == "call"
    assert lines[0]["tool"] == "list_issues"
    assert lines[1]["event"] == "result"
    assert lines[1]["status"] == "ok"


@pytest.mark.asyncio()
async def test_startup_prints_report(built_guardian: Guardian, capsys: Any) -> None:
    """startup prints the token savings report."""
    await built_guardian.startup()
    captured = capsys.readouterr()
    assert "mcp-guardian started" in captured.out
    assert "Scope:" in captured.out
    assert "Savings:" in captured.out
