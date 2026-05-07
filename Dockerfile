FROM python:3.13-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11.9 /uv /uvx /bin/

WORKDIR /app

# Install dependencies (cached layer)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-editable

# Copy source
COPY src/ ./src/
COPY docs/ ./docs/
COPY examples/scope.direct.yaml ./scope.yaml

# Default env vars (override at runtime)
ENV GUARDIAN_HOST=0.0.0.0
ENV GUARDIAN_PORT=9000
ENV GUARDIAN_CONFIG_PATH=scope.yaml

EXPOSE 9000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/mcp')" || exit 1

ENTRYPOINT ["uv", "run", "mcp-guardian", "--scope", "developer"]
