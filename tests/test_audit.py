"""Tests for mcp_guardian.audit."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mcp_guardian.audit import AuditLogger
from mcp_guardian.config import AuditConfig

if TYPE_CHECKING:
    from pathlib import Path


def _make_logger(
    tmp_path: Path,
    *,
    enabled: bool = True,
    include_params: bool = True,
) -> AuditLogger:
    log_file = str(tmp_path / "audit.log")
    config = AuditConfig(
        enabled=enabled,
        log_file=log_file,
        include_params=include_params,
    )
    return AuditLogger(config)


def _read_lines(tmp_path: Path) -> list[dict]:
    log_file = tmp_path / "audit.log"
    if not log_file.exists():
        return []
    return [json.loads(line) for line in log_file.read_text().splitlines() if line.strip()]


def test_log_call_has_correct_fields(tmp_path: Path) -> None:
    """Call event is logged with all expected fields."""
    logger = _make_logger(tmp_path)
    logger.log_call(
        scope="support-agent",
        tool="list_issues",
        server="github",
        params={"repo": "acme"},
    )

    lines = _read_lines(tmp_path)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["event"] == "call"
    assert entry["scope"] == "support-agent"
    assert entry["tool"] == "list_issues"
    assert entry["server"] == "github"
    assert entry["params"] == {"repo": "acme"}
    assert "ts" in entry


def test_log_result_includes_duration(tmp_path: Path) -> None:
    """Result event includes duration_ms and tokens_saved."""
    logger = _make_logger(tmp_path)
    logger.log_result(tool="list_issues", status="ok", duration_ms=45, tokens_saved=7935)

    lines = _read_lines(tmp_path)
    assert len(lines) == 1
    entry = lines[0]
    assert entry["event"] == "result"
    assert entry["tool"] == "list_issues"
    assert entry["status"] == "ok"
    assert entry["duration_ms"] == 45
    assert entry["tokens_saved"] == 7935


def test_params_omitted_when_disabled(tmp_path: Path) -> None:
    """Params field is omitted when include_params is False."""
    logger = _make_logger(tmp_path, include_params=False)
    logger.log_call(scope="dev", tool="pg_query", server="pg", params={"sql": "SELECT 1"})

    lines = _read_lines(tmp_path)
    assert len(lines) == 1
    assert "params" not in lines[0]


def test_disabled_logger_writes_nothing(tmp_path: Path) -> None:
    """Disabled logger produces no log file."""
    logger = _make_logger(tmp_path, enabled=False)
    logger.log_call(scope="x", tool="y", server="z", params={})
    logger.log_result(tool="y", status="ok", duration_ms=10)

    assert _read_lines(tmp_path) == []


def test_log_file_is_valid_jsonl(tmp_path: Path) -> None:
    """Every line in the log file is valid JSON."""
    logger = _make_logger(tmp_path)
    logger.log_call(scope="s", tool="t1", server="srv", params=None)
    logger.log_result(tool="t1", status="ok", duration_ms=5)
    logger.log_call(scope="s", tool="t2", server="srv", params={"k": "v"})
    logger.log_result(tool="t2", status="error", duration_ms=12, error="timeout")

    lines = _read_lines(tmp_path)
    assert len(lines) == 4
    for line in lines:
        assert isinstance(line, dict)
        assert "ts" in line
        assert "event" in line
