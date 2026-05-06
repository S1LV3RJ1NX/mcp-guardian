"""Tests for mcp_guardian.tokens."""

from __future__ import annotations

from unittest.mock import MagicMock

from mcp_guardian.tokens import (
    build_meta_tools_token_count,
    count_schema_tokens,
    count_tokens,
    savings_report,
)


def test_count_tokens_returns_positive_int() -> None:
    """count_tokens returns a positive integer for non-empty text."""
    result = count_tokens("hello world")
    assert isinstance(result, int)
    assert result > 0


def test_count_schema_tokens_returns_positive() -> None:
    """count_schema_tokens returns > 0 for a schema dict."""
    schema = {
        "name": "test_tool",
        "description": "A test tool",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
        },
    }
    result = count_schema_tokens(schema)
    assert result > 0


def test_build_meta_tools_token_count() -> None:
    """Meta-tools token count is a reasonable positive number."""
    result = build_meta_tools_token_count()
    assert result > 0
    assert result < 1000


def test_savings_report_structure() -> None:
    """savings_report returns the expected keys and types."""
    mock_entry = MagicMock()
    mock_entry.token_cost = 500

    mock_index = MagicMock()
    mock_index.entries = {"tool_a": mock_entry, "tool_b": mock_entry}
    mock_index.tokens_saved = 5000
    mock_index._excluded_count = 10

    report = savings_report(mock_index)

    assert "direct_tokens" in report
    assert "proxy_tokens" in report
    assert "savings_pct" in report
    assert "tools_in_scope" in report
    assert "tools_excluded" in report

    assert report["direct_tokens"] == 6000
    assert report["tools_in_scope"] == 2
    assert report["tools_excluded"] == 10
    assert report["savings_pct"] > 0
