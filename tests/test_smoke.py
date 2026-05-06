"""Smoke test: verify the package is importable."""


def test_import() -> None:
    """Package imports and exposes a version string."""
    import mcp_guardian

    assert mcp_guardian is not None
    assert mcp_guardian.__version__ == "0.1.0"
