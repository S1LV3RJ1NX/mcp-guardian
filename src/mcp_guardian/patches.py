"""Compatibility patches for third-party libraries.

Applied once at startup via ``apply_patches()``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _patch_oauth_token_response() -> None:
    """Fix two issues in the MCP SDK's token response handling:

    1. Accept any 2xx status (not just 200). Some providers like
       TrueFoundry return 201 Created.
    2. Handle form-encoded responses (``application/x-www-form-urlencoded``)
       from providers like GitHub that return ``access_token=...&token_type=bearer``
       instead of JSON.
    """
    try:
        from mcp.client.auth.oauth2 import OAuthClientProvider
    except ImportError:
        return

    async def _patched_handle(self, response):  # type: ignore[override]
        from urllib.parse import parse_qs

        from mcp.shared.auth import OAuthToken

        if not (200 <= response.status_code < 300):
            from mcp.client.auth.exceptions import OAuthTokenError

            raise OAuthTokenError(f"Token request failed: {response.status_code}")

        content = await response.aread()
        body = content.decode() if isinstance(content, bytes) else content

        if body and not body.lstrip().startswith("{"):
            parsed = parse_qs(body)
            token_data = {k: v[0] for k, v in parsed.items()}
            token = OAuthToken.model_validate(token_data)
        else:
            token = OAuthToken.model_validate_json(content)

        self.context.current_tokens = token
        self.context.update_token_expiry(token)
        await self.context.storage.set_tokens(token)

    OAuthClientProvider._handle_token_response = _patched_handle  # type: ignore[assignment]
    logger.debug("Patched _handle_token_response for 2xx + form-encoded support")


def _suppress_oauth_token_logging() -> None:
    """Prevent the MCP SDK from dumping full JWTs to stderr on OAuth errors."""
    oauth_logger = logging.getLogger("mcp.client.auth.oauth2")
    oauth_logger.setLevel(logging.CRITICAL)


def apply_patches() -> None:
    """Apply all compatibility patches."""
    _patch_oauth_token_response()
    _suppress_oauth_token_logging()
