"""Custom exception classes for mcp-guardian."""


class GuardianError(Exception):
    """Base exception for mcp-guardian."""


class ConfigError(GuardianError):
    """Invalid configuration."""


class UpstreamError(GuardianError):
    """Upstream MCP server connection or call failure."""


class ScopeError(GuardianError):
    """Tool not allowed in current scope."""
