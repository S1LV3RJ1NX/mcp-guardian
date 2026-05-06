"""Tests for mcp_guardian.index — all mocked, no real servers needed."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp_guardian.config import (
    AuditConfig,
    GuardianConfig,
    Scope,
    ScopeServer,
    ServerAuth,
    ServerConfig,
)
from mcp_guardian.index import ToolIndex, _make_brief


def _fake_tool(name: str, description: str = "A tool.", schema_extra: dict | None = None) -> Any:
    """Create a mock MCP Tool object."""
    t = MagicMock()
    t.name = name
    t.description = description
    dump = {"name": name, "description": description, "inputSchema": {"type": "object"}}
    if schema_extra:
        dump.update(schema_extra)
    t.model_dump = MagicMock(return_value=dump)
    return t


def _make_config(
    allowed_tools: list[str] | str = "*",
    blocked_tools: list[str] | None = None,
) -> GuardianConfig:
    """Build a minimal GuardianConfig for testing."""
    return GuardianConfig(
        upstream_servers={
            "srv": ServerConfig(url="http://localhost:3000/mcp", auth=ServerAuth(type="none")),
        },
        scopes={
            "test": Scope(
                description="test scope",
                servers={
                    "srv": ScopeServer(
                        allowed_tools=allowed_tools,
                        blocked_tools=blocked_tools or [],
                    ),
                },
            ),
        },
        audit=AuditConfig(),
        active_scope="test",
    )


def _mock_upstream(tools: list[Any]) -> AsyncMock:
    """Create a mocked UpstreamManager that returns the given tools."""
    upstream = AsyncMock()
    upstream.list_tools = AsyncMock(return_value=tools)
    return upstream


@pytest.mark.asyncio()
async def test_build_indexes_correct_tools() -> None:
    """Index builds the correct number of tools for an explicit allow list."""
    tools = [
        _fake_tool("tool_a", "First tool"),
        _fake_tool("tool_b", "Second tool"),
        _fake_tool("tool_c", "Third tool"),
    ]
    config = _make_config(allowed_tools=["tool_a", "tool_b"])
    upstream = _mock_upstream(tools)

    index = ToolIndex()
    await index.build(config, upstream)

    assert len(index.entries) == 2
    assert "tool_a" in index.entries
    assert "tool_b" in index.entries
    assert "tool_c" not in index.entries


@pytest.mark.asyncio()
async def test_wildcard_with_blocked_tools() -> None:
    """allowed_tools='*' with blocked_tools excludes the right tools."""
    tools = [
        _fake_tool("safe_tool"),
        _fake_tool("dangerous_tool"),
        _fake_tool("another_safe"),
    ]
    config = _make_config(allowed_tools="*", blocked_tools=["dangerous_tool"])
    upstream = _mock_upstream(tools)

    index = ToolIndex()
    await index.build(config, upstream)

    assert "safe_tool" in index.entries
    assert "another_safe" in index.entries
    assert "dangerous_tool" not in index.entries


@pytest.mark.asyncio()
async def test_tokens_saved_positive() -> None:
    """Excluded tools contribute to tokens_saved."""
    tools = [_fake_tool("allowed"), _fake_tool("excluded_a"), _fake_tool("excluded_b")]
    config = _make_config(allowed_tools=["allowed"])
    upstream = _mock_upstream(tools)

    index = ToolIndex()
    await index.build(config, upstream)

    assert index.tokens_saved > 0
    assert index._excluded_count == 2


@pytest.mark.asyncio()
async def test_search_returns_matching_tools() -> None:
    """search('first') finds tools with 'first' in name or description."""
    tools = [_fake_tool("first_tool", "First tool"), _fake_tool("second_tool", "Second tool")]
    config = _make_config(allowed_tools="*")
    upstream = _mock_upstream(tools)

    index = ToolIndex()
    await index.build(config, upstream)

    results = index.search("first")
    names = [r.name for r in results]
    assert "first_tool" in names
    assert "second_tool" not in names


@pytest.mark.asyncio()
async def test_get_schema_valid_tool() -> None:
    """get_schema returns the full schema dict for an indexed tool."""
    tools = [_fake_tool("my_tool")]
    config = _make_config(allowed_tools="*")
    upstream = _mock_upstream(tools)

    index = ToolIndex()
    await index.build(config, upstream)

    schema = index.get_schema("my_tool")
    assert schema is not None
    assert schema["name"] == "my_tool"


@pytest.mark.asyncio()
async def test_get_schema_missing_tool() -> None:
    """get_schema returns None for a tool not in the index."""
    tools = [_fake_tool("my_tool")]
    config = _make_config(allowed_tools="*")
    upstream = _mock_upstream(tools)

    index = ToolIndex()
    await index.build(config, upstream)

    assert index.get_schema("nonexistent") is None


@pytest.mark.asyncio()
async def test_get_server_for_tool() -> None:
    """get_server_for_tool returns the correct server name."""
    tools = [_fake_tool("my_tool")]
    config = _make_config(allowed_tools="*")
    upstream = _mock_upstream(tools)

    index = ToolIndex()
    await index.build(config, upstream)

    assert index.get_server_for_tool("my_tool") == "srv"
    assert index.get_server_for_tool("nonexistent") is None


def test_make_brief_truncates() -> None:
    """_make_brief truncates long descriptions to MAX_BRIEF_LENGTH."""
    long_desc = "A" * 200 + ". Second sentence."
    brief = _make_brief(long_desc)
    assert len(brief) <= 100
    assert brief.endswith("...")


def test_make_brief_first_sentence() -> None:
    """_make_brief extracts the first sentence."""
    desc = "This is the first sentence. This is the second."
    brief = _make_brief(desc)
    assert brief == "This is the first sentence"


@pytest.mark.asyncio()
async def test_stats_property() -> None:
    """stats returns correct index statistics."""
    tools = [_fake_tool("a"), _fake_tool("b"), _fake_tool("c")]
    config = _make_config(allowed_tools=["a", "b"])
    upstream = _mock_upstream(tools)

    index = ToolIndex()
    await index.build(config, upstream)

    stats = index.stats
    assert stats["tools_indexed"] == 2
    assert stats["tools_excluded"] == 1
    assert stats["tokens_saved"] > 0
    assert "srv" in stats["servers"]
