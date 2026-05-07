"""Compatibility patches for third-party libraries.

Applied once at startup via ``apply_patches()``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _patch_oauth_token_status() -> None:
    """Accept any 2xx status from the OAuth token endpoint.

    The MCP SDK's ``_handle_token_response`` rejects anything that
    isn't exactly HTTP 200.  Some OAuth providers (e.g. TrueFoundry)
    return 201 Created — a perfectly valid success response.  This
    patch relaxes the check to accept the full 2xx range.
    """
    try:
        from mcp.client.auth.oauth2 import OAuthClientProvider
    except ImportError:
        return

    _original = OAuthClientProvider._handle_token_response

    async def _lenient_handle(self, response):  # type: ignore[override]
        if 200 <= response.status_code < 300:
            response.status_code = 200
        return await _original(self, response)

    OAuthClientProvider._handle_token_response = _lenient_handle  # type: ignore[assignment]
    logger.debug("Patched OAuthClientProvider._handle_token_response to accept 2xx")


def _suppress_oauth_token_logging() -> None:
    """Prevent the MCP SDK from dumping full JWTs to stderr on OAuth errors."""
    oauth_logger = logging.getLogger("mcp.client.auth.oauth2")
    oauth_logger.setLevel(logging.CRITICAL)


def apply_patches() -> None:
    """Apply all compatibility patches."""
    _patch_oauth_token_status()
    _suppress_oauth_token_logging()
