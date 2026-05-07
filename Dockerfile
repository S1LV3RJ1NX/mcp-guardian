FROM python:3.13-slim AS base

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.11.9 /uv /uvx /bin/

WORKDIR /app

# Copy project files needed for build
COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/

# Install dependencies
RUN uv sync --frozen --no-dev --no-editable

# Copy remaining assets
COPY docs/ ./docs/
COPY examples/scope.direct.yaml ./scope.yaml

# Default env vars (override at runtime)
ENV GUARDIAN_HOST=0.0.0.0
ENV GUARDIAN_PORT=9000
ENV GUARDIAN_CONFIG_PATH=scope.yaml

EXPOSE 9000

ENTRYPOINT ["uv", "run", "mcp-guardian", "--scope", "developer"]
