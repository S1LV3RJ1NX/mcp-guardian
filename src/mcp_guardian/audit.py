"""JSONL audit logger for tool calls."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcp_guardian.config import AuditConfig


class AuditLogger:
    """Append-only JSONL audit log for tool calls and results.

    Each log_call / log_result writes one JSON line to the configured
    log file. When audit is disabled, all methods are no-ops.
    """

    def __init__(self, config: AuditConfig) -> None:
        self._enabled = config.enabled
        self._log_file = config.log_file
        self._include_params = config.include_params

    def log_call(
        self,
        scope: str,
        tool: str,
        server: str,
        params: dict[str, Any] | None,
    ) -> None:
        """Log a tool call event.

        Args:
            scope: Active scope name.
            tool: Tool being called.
            server: Upstream server handling the call.
            params: Tool parameters (omitted if include_params is False).
        """
        if not self._enabled:
            return

        entry: dict[str, Any] = {
            "ts": _utc_now(),
            "event": "call",
            "scope": scope,
            "tool": tool,
            "server": server,
        }
        if self._include_params and params is not None:
            entry["params"] = params

        self._write(entry)

    def log_result(
        self,
        tool: str,
        status: str,
        duration_ms: int,
        error: str | None = None,
        tokens_saved: int = 0,
    ) -> None:
        """Log a tool result event.

        Args:
            tool: Tool that was called.
            status: Result status ("ok", "error", "auth_required").
            duration_ms: Wall-clock time of the upstream call.
            error: Error message if status is "error".
            tokens_saved: Cumulative tokens saved by scoping.
        """
        if not self._enabled:
            return

        entry: dict[str, Any] = {
            "ts": _utc_now(),
            "event": "result",
            "tool": tool,
            "status": status,
            "duration_ms": duration_ms,
        }
        if error is not None:
            entry["error"] = error
        if tokens_saved:
            entry["tokens_saved"] = tokens_saved

        self._write(entry)

    def _write(self, entry: dict[str, Any]) -> None:
        """Append a single JSON line to the log file."""
        with open(self._log_file, "a") as f:
            f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def _utc_now() -> str:
    """Return the current UTC time as an ISO 8601 string."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
