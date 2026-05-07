"""CLI entry point for mcp-guardian."""

from __future__ import annotations

import argparse

from mcp_guardian.settings import get_settings


def main() -> None:
    """Parse CLI arguments and start the proxy server."""
    from mcp_guardian.patches import apply_patches

    apply_patches()
    parser = argparse.ArgumentParser(
        description="mcp-guardian: MCP proxy for tool scoping and progressive discovery",
    )
    parser.add_argument(
        "--config",
        help="Path to config file (default: from GUARDIAN_CONFIG_PATH or scope.yaml)",
    )
    parser.add_argument(
        "--scope",
        help="Active scope name (default: from GUARDIAN_SCOPE)",
    )
    parser.add_argument(
        "--port",
        type=int,
        help="Port to listen on (default: from GUARDIAN_PORT or 9000)",
    )
    parser.add_argument(
        "--host",
        help="Host to bind to (default: from GUARDIAN_HOST or 0.0.0.0)",
    )
    parser.add_argument(
        "--transport",
        choices=["streamable-http", "sse", "stdio"],
        help="Transport for the proxy server itself",
    )
    args = parser.parse_args()

    overrides = {k: v for k, v in vars(args).items() if v is not None}
    if "config" in overrides:
        overrides["config_path"] = overrides.pop("config")
    settings = get_settings(**overrides)

    if not settings.scope:
        parser.error("--scope is required (or set GUARDIAN_SCOPE)")

    from mcp_guardian.proxy import Guardian

    guardian = Guardian(config_path=settings.config_path, scope=settings.scope)
    guardian.run(
        transport=settings.transport,
        host=settings.host,
        port=settings.port,
    )
