# Contributing

Thanks for your interest in mcp-guardian. Here's how to contribute.

## Setup

```bash
git clone https://github.com/prathamesh-saraf/mcp-guardian.git
cd mcp-guardian
uv sync --dev
uv run pre-commit install
```

## Development Workflow

1. **Fork** the repository
2. **Create a branch** from `main`: `git checkout -b feature/my-change`
3. **Make your changes** with tests
4. **Run checks** before committing:

```bash
uv run ruff check src/ tests/
uv run ruff format src/ tests/
uv run pytest tests/ -v
```

5. **Commit** — pre-commit hooks will run ruff and tests automatically
6. **Push** and open a **Pull Request**

## Code Style

- **Type hints** on all function signatures
- **Google-style docstrings** on all public functions
- **ruff** for linting and formatting (config in `pyproject.toml`)
- Line length: 100 characters
- Target: Python 3.12+ syntax (ruff target)

## Testing

- Unit tests go in `tests/test_<module>.py`
- Integration tests (requiring live servers) use `@pytest.mark.integration`
- All async tests use `pytest-asyncio` with `asyncio_mode = "auto"`
- Mock external dependencies — tests must pass without network access

```bash
# Unit tests only
uv run pytest tests/ -v -m "not integration"

# All tests (requires upstream servers)
uv run pytest tests/ -v
```

## Adding a New Search Strategy

1. Create `src/mcp_guardian/search/my_strategy.py`
2. Subclass `SearchStrategy` from `search/base.py`
3. Implement the `search(query, entries)` method
4. Add tests in `tests/test_search.py`

## Docker Development

```bash
# Build and run the full stack
docker compose up --build

# Run just the proxy (if upstream is already running)
docker build -t mcp-guardian .
docker run -p 9000:9000 \
  -v ./scope.yaml:/app/scope.yaml \
  -e GUARDIAN_SCOPE=support-agent \
  mcp-guardian
```

## Project Structure

```
src/mcp_guardian/       # Main package
  cli.py                # CLI entry point
  config.py             # YAML config parsing
  proxy.py              # Core proxy (3 meta-tools)
  index.py              # Tool index + search
  upstream.py           # Upstream connection manager
  search/               # Search strategies (pluggable)
tests/                  # Unit + integration tests
benchmarks/             # 5 experiments with results
examples/               # Example scope.yaml configs
scripts/                # Verification + seed scripts
docs/                   # Architecture, quickstart, comparison
```
