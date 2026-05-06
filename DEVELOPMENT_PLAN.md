# mcp-guardian: Development Plan

## Overview

mcp-guardian is a Python MCP proxy implementing the MCP spec's recommended
progressive discovery pattern at the infrastructure layer. It sits between
any MCP client and any upstream MCP server(s), providing tool scoping,
on-demand schema loading, auth injection, and audit logging — without
modifying any client or server.

**Spec reference:** https://modelcontextprotocol.io/docs/develop/clients/client-best-practices

**Tech stack:** Python 3.13+ / FastMCP / uv / YAML config
**License:** MIT
**Target:** ~800-1000 lines of core code, well-tested, open source quality

---

## Architecture

```
                         mcp-guardian proxy
┌───────────┐    ┌──────────────────────────────┐    ┌──────────────┐
│ MCP Client│    │                              │    │ GitHub MCP   │
│ (Claude,  │───▶│  Exposes 3 meta-tools:       │───▶│ (41 tools)   │
│  Cursor,  │    │  • search_tools              │    └──────────────┘
│  any)     │    │  • get_schema                │    ┌──────────────┐
└───────────┘    │  • execute_tool              │───▶│ PostgreSQL   │
   ~300 tokens   │                              │    │ MCP (232)   │
   upfront       │  Internal components:        │    └──────────────┘
                 │  ├── config.py (YAML loader)  │
                 │  ├── upstream.py (connections) │
                 │  ├── index.py (tool catalog)  │
                 │  ├── search/ (pluggable)      │
                 │  ├── auth.py (credential mgr) │
                 │  ├── audit.py (JSONL logger)  │
                 │  └── tokens.py (counter)      │
                 └──────────────────────────────┘
```

### Core Design Principles

1. **Proxy-layer, not client-side.** The MCP spec recommends progressive
   discovery as a client pattern. This proxy implements it as infrastructure
   so every client benefits with zero client changes.

2. **No LLM in the loop.** The proxy never calls an LLM. Search is
   deterministic (keyword matching). This keeps latency predictable and
   cost zero.

3. **Pluggable search.** Abstract interface for search strategy. Ships with
   keyword search. Can be swapped for fuzzy, embedding, or subagent-based
   without touching the rest of the codebase.

4. **Per-call upstream connections.** Don't hold persistent connections to
   upstream servers. Reconnect per execute_tool call. MCP servers (especially
   SSE-based ones) drop connections. Robustness over performance.

5. **Transport auto-detection.** Probe Streamable HTTP first, fall back to
   SSE. Cache the detected transport per server after first probe.

6. **Fail fast.** Validate config at startup. If a scope references a tool
   that doesn't exist upstream, error immediately with a clear message.

7. **Clean errors.** Return structured JSON error objects, never raw stack
   traces. The proxy is user-facing infrastructure.

---

## Project Structure

```
mcp-guardian/
├── pyproject.toml
├── README.md
├── LICENSE                      # MIT
├── DEVELOPMENT_PLAN.md          # this file
├── agents.md                    # future upgrade roadmap
├── examples/                        # example scope configs (pick one, copy to scope.yaml)
│   ├── scope.direct.yaml           # direct connections, PAT-based auth
│   └── scope.gateway.yaml          # via MCP Gateway (TrueFoundry), per-user OAuth
├── .env.example                     # env var template (committed)
├── Dockerfile                   # production container
├── docker-compose.yml           # dev: PostgreSQL MCP server + proxy
│
├── src/
│   └── mcp_guardian/
│       ├── __init__.py          # version string
│       ├── __main__.py          # python -m mcp_guardian
│       ├── cli.py               # CLI entry point (argparse)
│       ├── settings.py          # Pydantic Settings (env vars)
│       ├── config.py            # YAML config loader + validation
│       ├── upstream.py          # Upstream server connection manager
│       ├── index.py             # Tool index (catalog of allowed tools)
│       ├── search/
│       │   ├── __init__.py      # re-exports SearchStrategy
│       │   ├── base.py          # Abstract SearchStrategy interface
│       │   └── keyword.py       # Keyword search implementation (v1)
│       ├── proxy.py             # Core proxy server (3 meta-tools)
│       ├── auth.py              # Auth header injection
│       ├── audit.py             # JSONL audit logger
│       ├── tokens.py            # Token counter (tiktoken)
│       └── exceptions.py        # Custom exception classes
│
├── tests/
│   ├── conftest.py              # Shared fixtures
│   ├── test_config.py
│   ├── test_settings.py
│   ├── test_upstream.py
│   ├── test_index.py
│   ├── test_search.py
│   ├── test_proxy.py
│   ├── test_auth.py
│   ├── test_audit.py
│   └── test_integration.py      # End-to-end tests
│
├── benchmarks/
│   ├── bench_tokens.py          # Token cost comparison
│   ├── bench_latency.py         # Latency comparison
│   ├── bench_search_quality.py  # Search accuracy
│   ├── bench_scaling.py         # Scaling: 14, 30, 50, 100 tools
│   ├── bench_security.py        # Scope enforcement validation
│   ├── queries.json             # Test queries for search benchmark
│   ├── run_all.py               # Run all benchmarks
│   └── results/                 # Benchmark outputs (committed)
│
└── docs/
    ├── ARCHITECTURE.md          # Design decisions explained
    ├── QUICKSTART.md            # 5-minute setup guide
    └── COMPARISON.md            # vs Code Mode, vs direct, vs spec recommendation
```

---

## Coding Standards

This is an open-source project. Code quality matters.

### Style

- **Type hints everywhere.** Every function parameter, return type, and class attribute.
- **Docstrings:** Google style on all public functions and classes.
- **Naming:** snake_case for functions/variables, PascalCase for classes, UPPER_CASE for constants.
- **Imports:** Group into stdlib → third-party → local. One blank line between groups.
- **Max line length:** 100 characters (configured in ruff).
- **No magic strings.** Use constants or enums for repeated values.

### Error Handling

- **Never expose raw stack traces to users.** Catch exceptions at the proxy boundary
  and return structured error dicts: `{"error": "message", "code": "ERROR_CODE"}`.
- **Specific exceptions.** Define custom exception classes in a `exceptions.py` if needed.
  Don't catch bare `Exception` except at the outermost boundary.
- **Log at appropriate levels.** DEBUG for internal flow, INFO for startup/config,
  WARNING for recoverable issues, ERROR for failures.

### Testing

- **pytest** with pytest-asyncio for async tests.
- **Every public function has at least one test.**
- **Integration tests** run the proxy against real upstream servers.
- **No mocking of core logic.** Mock only external I/O (upstream server connections).
- **Test names describe behavior:** `test_search_returns_empty_for_blocked_tools`,
  not `test_search_1`.

### Linting

- **ruff** for linting and formatting. Config in pyproject.toml.
- **CI runs ruff check and ruff format --check** on every PR.

---

## pyproject.toml

```toml
[project]
name = "mcp-guardian"
version = "0.1.0"
description = "MCP proxy for tool scoping and progressive discovery"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.13"
authors = [
    {name = "Prathamesh Saraf"}
]
keywords = ["mcp", "proxy", "tools", "context", "progressive-discovery"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.13",
]
dependencies = [
    "fastmcp>=2.0.0",
    "pyyaml>=6.0",
    "tiktoken>=0.7.0",
    "pydantic-settings>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8.0",
    "coverage>=7.0",
]
fuzzy = [
    "rapidfuzz>=3.0",
]

[project.scripts]
mcp-guardian = "mcp_guardian.cli:main"

[tool.ruff]
line-length = 100
target-version = "py313"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM", "TCH"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

---

## Example Configs (Pick One → Copy to scope.yaml)

The proxy doesn't care what's upstream — a raw MCP server or a gateway.
Same code, same 3 meta-tools. Just swap the config.

```bash
# Option A: Direct connections (PAT-based, no gateway)
cp examples/scope.direct.yaml scope.yaml

# Option B: Via MCP Gateway (per-user OAuth, managed tokens)
cp examples/scope.gateway.yaml scope.yaml

# Then run
uv run mcp-guardian --scope support-agent
```

### examples/scope.direct.yaml

Direct connections to MCP servers. Auth via Personal Access Tokens.
No external dependencies beyond the MCP servers themselves.

```yaml
# examples/scope.direct.yaml — Direct connections, PAT-based auth
# Usage: cp examples/scope.direct.yaml scope.yaml

upstream_servers:
  github:
    url: https://api.githubcopilot.com/mcp/
    transport: auto
    auth:
      type: bearer_env
      value_env: GITHUB_TOKEN # GitHub PAT from env

  postgres:
    url_env: POSTGRES_MCP_URL # Full URL from env (has credentials)
    transport: auto
    auth:
      type: none

scopes:
  support-agent:
    description: "Read-only tools for support agents"
    servers:
      github:
        allowed_tools:
          - get_me
          - list_issues
          - issue_read
          - list_pull_requests
          - pull_request_read
          - search_issues
          - search_code
      postgres:
        allowed_tools:
          - pg_read_query
          - pg_list_tables
          - pg_describe_table
          - pg_count
          - pg_exists
          - pg_explain
          - pg_table_stats

  developer:
    description: "Full access minus destructive operations"
    servers:
      github:
        allowed_tools: "*"
        blocked_tools:
          - delete_file
          - fork_repository
          - push_files
      postgres:
        allowed_tools: "*"
        blocked_tools:
          - pg_drop_table
          - pg_drop_index
          - pg_truncate
          - pg_terminate_backend

audit:
  enabled: true
  log_file: audit.log
  include_params: true
```

**`.env.example`:**

```env
# GitHub — create a PAT at https://github.com/settings/tokens
GITHUB_TOKEN=ghp_your_token_here

# PostgreSQL MCP — full URL including credentials (kept in env, not in yaml)
POSTGRES_MCP_URL=https://your-postgres-mcp.example.com/mcp

# Proxy settings
GUARDIAN_PORT=9000
GUARDIAN_SCOPE=support-agent
GUARDIAN_CONFIG_PATH=scope.yaml
GUARDIAN_LOG_LEVEL=INFO
```

---

### examples/scope.gateway.yaml

Same proxy, same scopes — but through an MCP Gateway. The Gateway
handles per-user OAuth (each user connects their own GitHub), token
refresh, and routing. You just pass one gateway token.

This example uses TrueFoundry's MCP Gateway. Any MCP Gateway that
exposes servers via HTTP endpoints works the same way.

```yaml
# examples/scope.gateway.yaml — Via MCP Gateway
# Usage: cp examples/scope.gateway.yaml scope.yaml
#
# The Gateway handles OAuth for GitHub and routes to PostgreSQL.
# One token (TFY_GATEWAY_TOKEN) authenticates to the Gateway.
# Gateway injects per-user OAuth tokens for each downstream server.
#
# mcp-guardian --config scope.yaml --scope support-agent

upstream_servers:
  github:
    url: https://gateway.truefoundry.ai/tfy-eo/mcp/github-mcp/server
    transport: auto
    auth:
      type: bearer_env
      value_env:
        TFY_GATEWAY_TOKEN # Gateway validates this token,
        # looks up user's GitHub OAuth token,
        # injects it when calling GitHub MCP.

  postgres:
    url: https://gateway.truefoundry.ai/tfy-eo/mcp/postgres-mcp/server
    transport: auto
    auth:
      type: bearer_env
      value_env: TFY_GATEWAY_TOKEN # Same token — Gateway routes to PG MCP.

scopes:
  support-agent:
    description: "Read-only tools for support agents"
    servers:
      github:
        allowed_tools:
          - get_me
          - list_issues
          - issue_read
          - list_pull_requests
          - pull_request_read
          - search_issues
          - search_code
      postgres:
        allowed_tools:
          - pg_read_query
          - pg_list_tables
          - pg_describe_table
          - pg_count
          - pg_exists
          - pg_explain
          - pg_table_stats

  developer:
    description: "Full access minus destructive operations"
    servers:
      github:
        allowed_tools: "*"
        blocked_tools:
          - delete_file
          - fork_repository
          - push_files
      postgres:
        allowed_tools: "*"
        blocked_tools:
          - pg_drop_table
          - pg_drop_index
          - pg_truncate
          - pg_terminate_backend

audit:
  enabled: true
  log_file: audit.log
  include_params: true
```

**`.env` when using gateway config:**

```env
TFY_GATEWAY_TOKEN=eyJhbGciOiJSUzI1NiIs...
GUARDIAN_PORT=9000
GUARDIAN_SCOPE=support-agent
GUARDIAN_CONFIG_PATH=examples/scope.gateway.yaml
```

**Same proxy, different configs. Swap the file, not the code.**

|                     | `scope.direct.yaml`                   | `scope.gateway.yaml`                             |
| ------------------- | ------------------------------------- | ------------------------------------------------ |
| **GitHub URL**      | `api.githubcopilot.com/mcp/` (direct) | `gateway.truefoundry.ai/.../github-mcp/server`   |
| **GitHub auth**     | PAT from `GITHUB_TOKEN` env           | Gateway token — Gateway injects per-user OAuth   |
| **PostgreSQL URL**  | From `POSTGRES_MCP_URL` env (direct)  | `gateway.truefoundry.ai/.../postgres-mcp/server` |
| **PostgreSQL auth** | None (URL has credentials)            | Gateway token                                    |
| **Per-user OAuth?** | No — everyone uses same PAT           | Yes — each user connects their own GitHub        |
| **Setup effort**    | 2 min (create PAT, set env var)       | 15 min (configure Gateway + OAuth app)           |

---

## Staged Build Plan

Each stage is self-contained. Complete and test each stage before moving to
the next. Every stage ends with a verification step.

---

### Stage 0: Project Skeleton (30 min)

**Goal:** Empty project that builds, lints, and runs an empty test suite.

**Tasks:**

1. Initialize project:
   ```bash
   mkdir mcp-guardian && cd mcp-guardian
   uv init
   ```
2. Create `pyproject.toml` (from above).
3. Create the full directory structure (all empty `__init__.py` files).
4. Create `LICENSE` (MIT).
5. Create `examples/scope.direct.yaml` and `examples/scope.gateway.yaml` (from above).
6. Create `.gitignore`:
   ```
   __pycache__/
   *.pyc
   .venv/
   dist/
   *.egg-info/
   .ruff_cache/
   audit.log
   scope.yaml
   .env
   .coverage
   htmlcov/
   ```
7. Create `.env.example` (from the Settings section in Stage 2).
8. Create a minimal `tests/conftest.py`:
   ```python
   """Shared test fixtures."""
   ```
9. Create a minimal passing test:

```python
# tests/test_smoke.py
def test_import():
    import mcp_guardian
    assert mcp_guardian is not None
```

**Verify:**

```bash
uv sync --dev
uv run ruff check src/ tests/
uv run pytest tests/ -v
# All must pass
```

---

### Stage 1: Upstream Server Setup (30 min)

**Goal:** Both upstream MCP servers accessible and verified. No mock servers.

- **GitHub:** Real MCP via TrueFoundry Gateway (OAuth, real data, 41 tools)
- **PostgreSQL:** Real PostgreSQL MCP server connected to a real database (232 tools)

**Tasks:**

1. **GitHub — via TrueFoundry Gateway (already deployed)**

   Already working in your MCP Registry. The proxy connects to the
   Gateway URL with `token_passthrough` auth.

   ```yaml
   # In scope.yaml
   github:
     url: https://<your-gateway-url>/mcp/github-mcp/server
     transport: auto
     auth:
       type: token_passthrough
   ```

   **Verify it's still working:**
   - TrueFoundry Playground → select `github-mcp` → "List my repos" → ✅

2. **PostgreSQL — `writenotenow/postgres-mcp` (232 tools, real database)**

   This server has 232 tools across 22 tool groups. It also has its own
   built-in Code Mode — interesting for the talk's comparison section.

   Run via Docker with HTTP transport:

   ```bash
   docker run --rm -p 3000:3000 \
     -e POSTGRES_URL=postgresql://postgres:REDACTED@postgres-eo.eastus.cloudapp.azure.com:5432/mcp-dev-summit \
     writenotenow/postgres-mcp:latest \
     --transport http --port 3000
   ```

   **IMPORTANT:** Don't use `--tool-filter` — expose ALL 232 tools.
   The whole point of the proxy is to show 232 tools being scoped down.

   ```yaml
   # In scope.yaml
   postgres:
     url: http://localhost:3000/mcp
     transport: auto
     auth:
       type: none
   ```

3. **`.env` configuration:**

   ```env
   # Proxy settings
   GUARDIAN_PORT=9000
   GUARDIAN_SCOPE=support-agent
   GUARDIAN_CONFIG_PATH=scope.yaml

   # PostgreSQL MCP connection
   POSTGRES_URL=postgresql://postgres:REDACTED@postgres-eo.eastus.cloudapp.azure.com:5432/mcp-dev-summit
   ```

**Verify:**

```bash
# Terminal 1: Start PostgreSQL MCP server
docker run --rm -p 3000:3000 \
  -e POSTGRES_URL=postgresql://postgres:REDACTED@postgres-eo.eastus.cloudapp.azure.com:5432/mcp-dev-summit \
  writenotenow/postgres-mcp:latest \
  --transport http --port 3000

# Connect MCP Inspector to http://localhost:3000/mcp → should see 232 tools
# Call pg_list_tables → should return real tables from mcp-dev-summit database

# GitHub MCP (via Gateway)
# Already verified in TrueFoundry Playground
```

**Tests:**

```python
# tests/test_upstream_servers.py
# Mark with @pytest.mark.integration — these need real servers running

# test_postgres_mcp_accessible:
#   - Connect to PostgreSQL MCP at localhost:3000
#   - Verify 232 tools visible
#   - Call pg_list_tables → returns real data

# test_github_mcp_via_gateway:
#   - Connect to Gateway URL with a valid JWT
#   - Verify 41 tools visible
#   - Call get_me → returns real GitHub user data
#   - (Or: returns AUTH_REQUIRED if JWT user hasn't authorized GitHub)
```

---

### Stage 2: Config Loader + Settings (1-2 hours)

**Goal:** Parse scope.yaml, load environment variables via Pydantic Settings,
and validate everything with clear error messages.

**Tasks:**

1. **`src/mcp_guardian/settings.py`** — Pydantic Settings for env vars:

   ```python
   from pydantic_settings import BaseSettings, SettingsConfigDict

   class GuardianSettings(BaseSettings):
       """Environment-based settings for mcp-guardian.

       Loaded from .env file and/or environment variables.
       All env vars are prefixed with GUARDIAN_ (except auth tokens
       which are referenced by name in scope.yaml).
       """

       model_config = SettingsConfigDict(
           env_prefix="GUARDIAN_",
           env_file=".env",
           env_file_encoding="utf-8",
           extra="ignore",
       )

       # Proxy server config
       host: str = "0.0.0.0"
       port: int = 9000
       transport: str = "streamable-http"

       # Config file path
       config_path: str = "scope.yaml"
       scope: str = ""  # required, set via CLI or env

       # Audit
       audit_log_file: str = "audit.log"

       # Logging
       log_level: str = "INFO"

   def get_settings(**overrides) -> GuardianSettings:
       """Load settings from env/.env file with optional overrides."""
       return GuardianSettings(**overrides)
   ```

   **`.env.example`:**

   ```env
   # mcp-guardian settings (GUARDIAN_ prefix)
   GUARDIAN_HOST=0.0.0.0
   GUARDIAN_PORT=9000
   GUARDIAN_CONFIG_PATH=scope.yaml
   GUARDIAN_SCOPE=support-agent
   GUARDIAN_LOG_LEVEL=INFO

   # Auth tokens — referenced by name in scope.yaml (no prefix)
   GITHUB_TOKEN=ghp_your_token_here

   # Server URLs from env — for URLs containing credentials
   POSTGRES_MCP_URL=https://your-postgres-mcp.example.com/mcp
   ```

   **Key design:** The `GUARDIAN_` prefix is for proxy config. Auth tokens
   (GITHUB_TOKEN, etc.) are NOT prefixed because they're referenced
   by name in scope.yaml's `value_env` field. This keeps the YAML portable —
   it just says "read from GITHUB_TOKEN", not "read from GUARDIAN_GITHUB_TOKEN".

2. **Auth token resolution via Settings:**

   For auth tokens referenced in scope.yaml, we still read from env by name
   (not via Pydantic Settings) because the token names are dynamic — they're
   defined per-server in scope.yaml. Pydantic Settings handles the proxy's own
   config; `os.environ` or a helper handles dynamic auth tokens.

   Create a helper in settings.py:

   ```python
   import os

   def get_env_var(name: str) -> str:
       """Read an env var by name. Used for auth tokens referenced in scope.yaml.

       Raises ConfigError if not set.
       """
       value = os.environ.get(name, "")
       if not value:
           from mcp_guardian.exceptions import ConfigError
           raise ConfigError(
               f"Environment variable '{name}' not set. "
               f"Set it: export {name}=your-value"
           )
       return value
   ```

3. **`src/mcp_guardian/config.py`** — YAML config loader (unchanged from original plan):

   Define dataclasses:

   ```python
   @dataclass
   class ServerAuth:
       type: str              # "none" | "static_header" | "bearer_env" | "token_passthrough"
       header: str = "Authorization"
       value_env: str = ""

   @dataclass
   class ServerConfig:
       url: str = ""                    # direct URL
       url_env: str = ""                # OR env var name containing URL (for URLs with credentials)
       transport: str = "auto"          # "auto" | "streamable-http" | "sse"
       auth: ServerAuth = field(default_factory=lambda: ServerAuth(type="none"))

       def get_url(self) -> str:
           """Resolve the server URL.

           If url_env is set, reads the URL from that environment variable.
           This is used when the URL contains credentials (e.g., database passwords)
           that shouldn't be in the YAML config file.
           """
           if self.url_env:
               from mcp_guardian.settings import get_env_var
               return get_env_var(self.url_env)
           if self.url:
               return self.url
           raise ConfigError("Server must have either 'url' or 'url_env'")

   @dataclass
   class ScopeServer:
       allowed_tools: list[str] | str  # list or "*"
       blocked_tools: list[str] = field(default_factory=list)

   @dataclass
   class Scope:
       description: str
       servers: dict[str, ScopeServer]

   @dataclass
   class AuditConfig:
       enabled: bool = True
       log_file: str = "audit.log"
       include_params: bool = True

   @dataclass
   class GuardianConfig:
       upstream_servers: dict[str, ServerConfig]
       scopes: dict[str, Scope]
       audit: AuditConfig
       active_scope: str  # set at runtime, not in YAML
   ```

   Implement `load_config(path: str, scope: str) -> GuardianConfig`:
   - Parse YAML
   - Validate: active_scope exists in scopes
   - Validate: all servers referenced in scope exist in upstream_servers
   - Validate: each server has either `url` or `url_env` (not both empty)
   - Validate: auth type is one of: none, static_header, bearer_env, token_passthrough
   - Return typed GuardianConfig

   On any validation error, raise `ConfigError` with a human-readable message
   that says exactly what's wrong and where to fix it.

4. **`src/mcp_guardian/exceptions.py`**

   ```python
   class GuardianError(Exception):
       """Base exception for mcp-guardian."""

   class ConfigError(GuardianError):
       """Invalid configuration."""

   class UpstreamError(GuardianError):
       """Upstream MCP server connection or call failure."""

   class ScopeError(GuardianError):
       """Tool not allowed in current scope."""
   ```

**Verify:**

```bash
uv run python -c "
from mcp_guardian.config import load_config
config = load_config('examples/scope.direct.yaml', 'support-agent')
print(f'Servers: {list(config.upstream_servers.keys())}')
print(f'Scope: {config.active_scope}')
print(f'Allowed tools in github: {config.scopes[config.active_scope].servers[\"github\"].allowed_tools}')
"
```

**Tests (`tests/test_config.py`):**

- Valid config loads correctly
- Missing scope name raises ConfigError with message
- Unknown server in scope raises ConfigError
- Invalid auth type raises ConfigError
- `allowed_tools: "*"` parsed correctly
- `blocked_tools` parsed correctly
- Missing `auth` defaults to `type: none`
- Empty YAML file raises ConfigError
- `url_env` resolves URL from environment variable
- Server with neither `url` nor `url_env` raises ConfigError
- `token_passthrough` auth type accepted as valid

---

### Stage 3: Upstream Connection Manager (1-2 hours)

**Goal:** Connect to upstream MCP servers with transport auto-detection.

**Tasks:**

1. **`src/mcp_guardian/upstream.py`**

   ```python
   class UpstreamManager:
       """Manages connections to upstream MCP servers."""

       def __init__(self, servers: dict[str, ServerConfig]):
           self._servers = servers
           self._transport_cache: dict[str, str] = {}  # server_name → detected transport

       async def probe_server(self, name: str) -> str:
           """Detect transport type for a server. Returns 'streamable-http' or 'sse'.
           Caches the result for subsequent calls."""

       async def list_tools(self, name: str) -> list[Tool]:
           """Connect to server, call tools/list, return tools. Reconnects each time."""

       async def call_tool(self, name: str, tool_name: str, params: dict) -> Any:
           """Connect to server, call a specific tool, return result."""

       async def probe_all(self) -> dict[str, list[Tool]]:
           """Probe all servers and return their tools. Used at startup."""
   ```

   Transport detection logic:
   - If config says `transport: streamable-http` or `transport: sse` → use that
   - If config says `transport: auto`:
     1. Try StreamableHttpTransport → connect → list_tools → success → cache "streamable-http"
     2. If fails → try SSETransport → connect → list_tools → success → cache "sse"
     3. If both fail → raise UpstreamError with helpful message

   Auth headers: Use `auth.py` (Stage 5) to build headers. For now, pass empty
   headers and wire auth in later.

**Verify:**

```bash
# Ensure upstream servers are running
uv run python -c "
import asyncio
from mcp_guardian.config import load_config
from mcp_guardian.upstream import UpstreamManager

async def test():
    config = load_config('examples/scope.direct.yaml', 'support-agent')
    manager = UpstreamManager(config.upstream_servers)
    all_tools = await manager.probe_all()
    for name, tools in all_tools.items():
        print(f'{name}: {len(tools)} tools')
        for t in tools[:3]:
            print(f'  - {t.name}')

asyncio.run(test())
"
# Should print: github: 41 tools, postgres: 232 tools
```

**Tests (`tests/test_upstream.py`):**

- Connects to upstream server and lists tools
- Returns correct number of tools
- Handles server-not-running with UpstreamError
- Transport auto-detection works
- Respects transport override from config

---

### Stage 4: Tool Index + Search (1-2 hours)

**Goal:** Build a searchable index of scope-filtered tools.

**Tasks:**

1. **`src/mcp_guardian/search/base.py`** — Abstract interface:

   ```python
   from abc import ABC, abstractmethod

   class SearchStrategy(ABC):
       @abstractmethod
       def search(self, query: str, entries: dict[str, ToolEntry]) -> list[SearchResult]:
           """Search tool entries. Return matches sorted by relevance."""
           ...
   ```

2. **`src/mcp_guardian/search/keyword.py`** — Keyword implementation:
   - Split query into keywords
   - Match if ANY keyword appears in tool name or description (case-insensitive)
   - Score by: exact name match > name contains > description contains
   - Return sorted by score

3. **`src/mcp_guardian/index.py`** — Tool index:

   ```python
   @dataclass
   class ToolEntry:
       name: str
       server: str
       description: str
       brief: str             # first sentence, max 100 chars
       full_schema: dict      # complete tool definition (stored, not exposed)
       token_cost: int        # tiktoken count of full schema JSON

   @dataclass
   class SearchResult:
       name: str
       server: str
       brief: str

   class ToolIndex:
       def __init__(self, search_strategy: SearchStrategy | None = None):
           self.entries: dict[str, ToolEntry] = {}
           self.tokens_saved: int = 0  # tokens not loaded due to scoping
           self._search = search_strategy or KeywordSearch()

       async def build(self, config: GuardianConfig, upstream: UpstreamManager) -> None:
           """Probe upstream servers, filter by scope, build index."""

       def search(self, query: str) -> list[SearchResult]:
           """Search indexed tools."""

       def get_schema(self, tool_name: str) -> dict | None:
           """Get full schema for a specific tool."""

       def get_server_for_tool(self, tool_name: str) -> str | None:
           """Which upstream server owns this tool?"""

       @property
       def stats(self) -> dict:
           """Return index statistics: tools indexed, tokens saved, etc."""
   ```

   Build logic:
   - For each server in the active scope:
     - Get tools from upstream via `upstream.list_tools(server_name)`
     - Filter: if `allowed_tools == "*"`, include all except `blocked_tools`
     - Filter: if `allowed_tools` is a list, include only those
     - For included tools: create ToolEntry, add to index
     - For excluded tools: count their token cost → add to `tokens_saved`

**Verify:**

```bash
# Ensure upstream servers are running
uv run python -c "
import asyncio
from mcp_guardian.config import load_config
from mcp_guardian.upstream import UpstreamManager
from mcp_guardian.index import ToolIndex

async def test():
    config = load_config('examples/scope.direct.yaml', 'support-agent')
    upstream = UpstreamManager(config.upstream_servers)
    index = ToolIndex()
    await index.build(config, upstream)
    print(f'Indexed: {len(index.entries)} tools')
    print(f'Tokens saved by scoping: {index.tokens_saved}')
    print()
    results = index.search('issues')
    for r in results:
        print(f'  {r.name} ({r.server}): {r.brief}')
    print()
    schema = index.get_schema('list_issues')
    print(f'Schema keys: {list(schema.keys()) if schema else \"NOT FOUND\"}'  )

asyncio.run(test())
"
# Should show: ~14 indexed tools (support-agent scope: 7 github + 7 postgres)
# search("issues") → list_issues, get_issue
# search("delete") → empty (blocked by scope)
# get_schema("list_issues") → full schema dict
```

**Smoke check (inline experiment — validates core value prop):**

```bash
uv run python -c "
import asyncio
from mcp_guardian.config import load_config
from mcp_guardian.upstream import UpstreamManager
from mcp_guardian.index import ToolIndex
from mcp_guardian.tokens import count_schema_tokens

async def smoke():
    config = load_config('examples/scope.direct.yaml', 'support-agent')
    upstream = UpstreamManager(config.upstream_servers)
    index = ToolIndex()
    await index.build(config, upstream)

    # Quick token sanity check
    total_in_scope = sum(e.token_cost for e in index.entries.values())
    print(f'Tools in scope: {len(index.entries)}')
    print(f'Tokens if loaded directly: {total_in_scope + index.tokens_saved}')
    print(f'Tokens saved by scoping alone: {index.tokens_saved}')
    assert index.tokens_saved > 0, 'Scoping should save tokens'
    assert len(index.entries) < 22, 'Support-agent scope should filter tools'
    print('✅ Smoke check passed')

asyncio.run(smoke())
"
```

**Tests (`tests/test_index.py` and `tests/test_search.py`):**

- Index builds correct number of tools for support-agent scope
- Index excludes delete_repo, force_push etc.
- `allowed_tools: "*"` with `blocked_tools` works correctly
- `tokens_saved` is > 0 (excluded tools contribute)
- search("issues") returns list_issues and get_issue
- search("delete") returns empty for support-agent scope
- search("query") returns postgres tools
- search with no matches returns empty list
- get_schema for valid tool returns dict with inputSchema
- get_schema for invalid tool returns None
- get_schema for excluded tool returns None
- Brief truncation works (max 100 chars)

---

### Stage 5: Auth Injection (30 min)

**Goal:** Build auth headers for upstream server requests.

**Tasks:**

1. **`src/mcp_guardian/auth.py`**

   ```python
   from mcp_guardian.config import ServerAuth
   from mcp_guardian.settings import get_env_var
   from mcp_guardian.exceptions import ConfigError

   def get_auth_headers(
       auth: ServerAuth,
       client_headers: dict[str, str] | None = None,
   ) -> dict[str, str]:
       """Build HTTP headers for upstream server authentication.

       For token_passthrough, forwards the client's own Authorization
       header to the upstream server. This is used when the upstream
       is an MCP Gateway that manages per-user OAuth tokens.

       Args:
           auth: Server auth configuration from scope.yaml.
           client_headers: Original headers from the MCP client request.
               Required when auth.type is "token_passthrough".

       Returns:
           Dict of header name → header value.

       Raises:
           ConfigError: If required env var or client header is missing.
       """
       if auth.type == "none":
           return {}
       elif auth.type == "static_header":
           value = get_env_var(auth.value_env)
           return {auth.header: value}
       elif auth.type == "bearer_env":
           token = get_env_var(auth.value_env)
           return {"Authorization": f"Bearer {token}"}
       elif auth.type == "token_passthrough":
           # Forward the client's own auth header to the upstream server.
           # Used when upstream is an MCP Gateway handling per-user OAuth.
           if client_headers:
               for key in ("authorization", "Authorization"):
                   if key in client_headers:
                       return {"Authorization": client_headers[key]}
           return {}
       else:
           raise ConfigError(
               f"Unknown auth type: '{auth.type}'. "
               f"Supported: none, static_header, bearer_env, token_passthrough"
           )
   ```

2. Wire auth headers into `UpstreamManager` — pass headers when creating
   transports. For `token_passthrough`, the `call_tool` method must accept
   `client_headers` and pass them through.

**Tests (`tests/test_auth.py`):**

- `type: none` returns empty dict
- `type: bearer_env` returns correct header (set env var in test)
- `type: static_header` with custom header name works
- `type: token_passthrough` forwards client Authorization header
- `type: token_passthrough` with no client headers returns empty dict
- Missing env var raises ConfigError with helpful message
- Unknown auth type raises ConfigError

---

### Stage 6: Audit Logger (30 min)

**Goal:** JSONL logging of all tool calls.

**Tasks:**

1. **`src/mcp_guardian/audit.py`**

   ```python
   class AuditLogger:
       def __init__(self, config: AuditConfig):
           ...

       def log_call(self, scope: str, tool: str, server: str, params: dict | None) -> None:
           """Log a tool call event."""

       def log_result(self, tool: str, status: str, duration_ms: int, error: str | None = None, tokens_saved: int = 0) -> None:
           """Log a tool result event."""
   ```

   Format:

   ```json
   {"ts":"2026-06-09T14:23:01Z","event":"call","scope":"support-agent","tool":"list_issues","server":"github","params":{"repo":"acme/backend"}}
   {"ts":"2026-06-09T14:23:01Z","event":"result","tool":"list_issues","status":"ok","duration_ms":45,"tokens_saved":7935}
   ```

   If `include_params` is false, omit the `params` field.
   If `enabled` is false, all methods are no-ops.

**Tests (`tests/test_audit.py`):**

- Call event logged with correct fields (use tmp_path for log file)
- Result event includes duration_ms
- Params omitted when include_params=false
- Disabled logger writes nothing
- Log file is valid JSONL (each line parses as JSON)

---

### Stage 7: Token Counter (30 min)

**Goal:** Count tokens in schemas and report savings.

**Tasks:**

1. **`src/mcp_guardian/tokens.py`**

   ```python
   import tiktoken
   import json

   _encoder = tiktoken.get_encoding("cl100k_base")

   def count_tokens(text: str) -> int:
       """Count tokens in a string using cl100k_base encoding."""

   def count_schema_tokens(schema: dict) -> int:
       """Count tokens in a tool schema dict (JSON-serialized)."""

   def build_meta_tools_token_count() -> int:
       """Return the approximate token cost of the 3 meta-tool schemas."""

   def savings_report(index) -> dict:
       """Generate a token savings report from a built ToolIndex.
       Returns: {
           direct_tokens: int,    # tokens if all tools loaded directly
           proxy_tokens: int,     # tokens for 3 meta-tools
           savings_pct: float,    # percentage saved
           tools_in_scope: int,
           tools_excluded: int,
       }
       """
   ```

**Tests (`tests/test_tokens.py`):**

- count_tokens("hello world") returns a positive integer
- count_schema_tokens returns > 0 for a schema dict
- savings_report returns correct structure
- savings_pct is > 90% for typical configs

---

### Stage 8: Core Proxy Server (2-3 hours)

**Goal:** The proxy server exposing 3 meta-tools. This is the heart of the project.

**Tasks:**

1. **`src/mcp_guardian/proxy.py`**

   ```python
   class Guardian:
       """MCP proxy server implementing progressive discovery.

       Sits between MCP clients and upstream servers. Exposes three
       meta-tools (search_tools, get_schema, execute_tool) instead of
       forwarding full tool schemas. Implements the MCP spec's recommended
       progressive discovery pattern at the infrastructure layer.

       See: https://modelcontextprotocol.io/docs/develop/clients/client-best-practices
       """

       def __init__(self, config_path: str, scope: str):
           self.config = load_config(config_path, scope)
           self.upstream = UpstreamManager(self.config.upstream_servers)
           self.index = ToolIndex()
           self.audit = AuditLogger(self.config.audit)
           self.server = FastMCP(
               f"mcp-guardian ({scope})",
               instructions=(
                   "This is an MCP proxy. Use search_tools to find available tools, "
                   "get_schema to inspect a tool's parameters, then execute_tool to call it."
               ),
           )
           self._register_meta_tools()

       def _register_meta_tools(self):
           """Register the 3 meta-tools on the FastMCP server."""

           @self.server.tool()
           async def search_tools(query: str) -> list[dict]:
               """Search available tools by keyword.

               Returns tool names and brief descriptions. Use this to discover
               what tools are available before calling get_schema.

               Args:
                   query: Search keywords (e.g., 'github issues', 'query database', 'list tables')
               """
               results = self.index.search(query)
               if not results:
                   return [{"message": f"No tools matching '{query}'. Try different keywords."}]
               return [{"name": r.name, "server": r.server, "brief": r.brief} for r in results]

           @self.server.tool()
           async def get_schema(tool_name: str) -> dict:
               """Get the full parameter schema for a specific tool.

               Call this before execute_tool to understand the required parameters
               and their types.

               Args:
                   tool_name: Exact tool name from search_tools results.
               """
               schema = self.index.get_schema(tool_name)
               if schema is None:
                   return {
                       "error": f"Tool '{tool_name}' not found in scope '{self.config.active_scope}'.",
                       "hint": "Use search_tools to find available tools.",
                   }
               return schema

           @self.server.tool()
           async def execute_tool(tool_name: str, params: dict) -> dict | list | str:
               """Execute a tool with the given parameters.

               Always call get_schema first to understand the required parameter format.
               If the upstream server requires OAuth authorization, this will return
               an auth_url — open it in a browser to authorize, then retry.

               Args:
                   tool_name: Exact tool name.
                   params: Tool parameters as a JSON object.
               """
               import time

               entry = self.index.entries.get(tool_name)
               if entry is None:
                   return {
                       "error": f"Tool '{tool_name}' not found in scope '{self.config.active_scope}'.",
                       "code": "TOOL_NOT_IN_SCOPE",
                   }

               # Audit: log the call
               self.audit.log_call(
                   scope=self.config.active_scope,
                   tool=tool_name,
                   server=entry.server,
                   params=params,
               )

               # Execute upstream (pass client headers for token_passthrough auth)
               start = time.time()
               try:
                   result = await self.upstream.call_tool(
                       entry.server,
                       tool_name,
                       params,
                       client_headers=self._get_client_headers(),
                   )
                   duration_ms = int((time.time() - start) * 1000)
                   self.audit.log_result(
                       tool=tool_name,
                       status="ok",
                       duration_ms=duration_ms,
                       tokens_saved=self.index.tokens_saved,
                   )
                   return result
               except Exception as e:
                   duration_ms = int((time.time() - start) * 1000)
                   error_str = str(e)

                   # Handle OAuth auth required error from MCP Gateway
                   # The Gateway returns this when the user hasn't authorized
                   # the OAuth app (e.g., GitHub) yet.
                   if "McpAuthRequiredError" in error_str or "authorization_url" in error_str:
                       self.audit.log_result(
                           tool=tool_name,
                           status="auth_required",
                           duration_ms=duration_ms,
                       )
                       # Try to extract auth URL from the error
                       auth_url = self._extract_auth_url(e)
                       return {
                           "error": "OAuth authorization required for this tool.",
                           "code": "AUTH_REQUIRED",
                           "auth_url": auth_url,
                           "message": (
                               f"The upstream server requires OAuth authorization. "
                               f"Open the auth_url in a browser to authorize, then retry."
                           ),
                       }

                   self.audit.log_result(
                       tool=tool_name,
                       status="error",
                       duration_ms=duration_ms,
                       error=error_str,
                   )
                   return {"error": error_str, "code": "UPSTREAM_ERROR"}

       def _get_client_headers(self) -> dict[str, str]:
           """Extract the current client's request headers.

           In FastMCP, the client's original headers are available via
           the request context. This is needed for token_passthrough auth.

           NOTE: The exact mechanism depends on FastMCP's API for accessing
           incoming request headers. This may need adjustment based on
           FastMCP's version. If headers aren't accessible, fall back to
           empty dict (token_passthrough won't work without it).
           """
           # TODO: Extract from FastMCP request context
           # This is framework-dependent — investigate FastMCP's API
           return {}

       @staticmethod
       def _extract_auth_url(error: Exception) -> str | None:
           """Try to extract an OAuth authorization URL from an upstream error."""
           import json
           error_str = str(error)
           # Try to parse JSON from the error message
           try:
               # Some errors contain JSON with authorization_urls
               for part in error_str.split("{"):
                   try:
                       data = json.loads("{" + part.split("}")[0] + "}")
                       if "authorization_urls" in data:
                           urls = data["authorization_urls"]
                           return next(iter(urls.values()), None)
                       if "auth_url" in data:
                           return data["auth_url"]
                   except (json.JSONDecodeError, StopIteration):
                       continue
           except Exception:
               pass
           return None

       async def startup(self) -> None:
           """Connect to upstream servers and build the tool index. Call before serving."""
           await self.index.build(self.config, self.upstream)

           report = savings_report(self.index)
           print(f"mcp-guardian started")
           print(f"  Scope:          {self.config.active_scope}")
           print(f"  Servers:        {len(self.config.upstream_servers)}")
           print(f"  Tools in scope: {report['tools_in_scope']}")
           print(f"  Direct cost:    {report['direct_tokens']:,} tokens")
           print(f"  Proxy cost:     {report['proxy_tokens']:,} tokens")
           print(f"  Savings:        {report['savings_pct']:.1f}%")

       def run(self, **kwargs) -> None:
           """Run the proxy server."""
           import asyncio
           asyncio.run(self.startup())
           self.server.run(**kwargs)
   ```

2. **`src/mcp_guardian/cli.py`**

   ```python
   import argparse
   from mcp_guardian.settings import get_settings

   def main():
       parser = argparse.ArgumentParser(
           description="mcp-guardian: MCP proxy for tool scoping and progressive discovery",
       )
       parser.add_argument("--config", help="Path to config file (default: from GUARDIAN_CONFIG_PATH or scope.yaml)")
       parser.add_argument("--scope", help="Active scope name (default: from GUARDIAN_SCOPE)")
       parser.add_argument("--port", type=int, help="Port to listen on (default: from GUARDIAN_PORT or 9000)")
       parser.add_argument("--host", help="Host to bind to (default: from GUARDIAN_HOST or 0.0.0.0)")
       parser.add_argument("--transport", choices=["streamable-http", "sse", "stdio"],
                           help="Transport for the proxy server itself")
       args = parser.parse_args()

       # CLI args override env vars override defaults
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
   ```

   **Priority order:** CLI args → env vars → .env file → defaults.
   This is Pydantic Settings' natural behavior. CLI args are passed as
   overrides to `get_settings()`.

3. **`src/mcp_guardian/__main__.py`**
   ```python
   from mcp_guardian.cli import main
   main()
   ```

**Verify (full end-to-end):**

```bash
# Prerequisites:
# 1. PostgreSQL MCP server running on port 3000 (connected to real DB)
# 2. GitHub MCP available via TrueFoundry Gateway

# Terminal 1: Start proxy
uv run mcp-guardian --config scope.yaml --scope support-agent --port 9000

# Should print:
# mcp-guardian started
#   Scope:          support-agent
#   Servers:        2
#   Tools in scope: 14
#   Direct cost:    ~125,000 tokens
#   Proxy cost:     ~300 tokens
#   Savings:        99.8%

# Terminal 3: Test with MCP Inspector or python
uv run python -c "
import asyncio
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

async def test():
    transport = StreamableHttpTransport(url='http://localhost:9000/mcp')
    async with Client(transport) as client:
        # Should see 3 meta-tools
        tools = await client.list_tools()
        print(f'Tools: {[t.name for t in tools]}')

        # Search
        results = await client.call_tool('search_tools', {'query': 'issues'})
        print(f'Search results: {results}')

        # Get schema
        schema = await client.call_tool('get_schema', {'tool_name': 'list_issues'})
        print(f'Schema: {list(schema.keys()) if isinstance(schema, dict) else schema}')

        # Execute
        result = await client.call_tool('execute_tool', {
            'tool_name': 'list_issues',
            'params': {'repo': 'acme/backend'}
        })
        print(f'Result: {result}')

        # Try blocked tool
        blocked = await client.call_tool('execute_tool', {
            'tool_name': 'delete_repo',
            'params': {'repo': 'acme/backend'}
        })
        print(f'Blocked: {blocked}')

asyncio.run(test())
"
```

**Tests (`tests/test_proxy.py` and `tests/test_integration.py`):**

- Proxy exposes exactly 3 tools
- search_tools returns filtered results
- search_tools with no matches returns helpful message
- get_schema returns full schema for valid tool
- get_schema for blocked tool returns error
- execute_tool forwards to upstream and returns result
- execute_tool on blocked tool returns TOOL_NOT_IN_SCOPE error
- execute_tool with bad params returns UPSTREAM_ERROR
- execute_tool returns AUTH_REQUIRED with auth_url when upstream needs OAuth
- token_passthrough auth forwards client's Authorization header to upstream
- Audit log has entries after calls (check file exists and has JSONL)
- Token savings printed at startup

---

### Stage 9: Experiments (2-3 hours)

**Goal:** Formal benchmarks that produce numbers for the README, slides,
and talk. These are reproducible measurements, not ad-hoc checks.

**Strategy:** Experiments run at the end because they need the full proxy
working. Each experiment is a standalone script in `benchmarks/` that
outputs both human-readable results and machine-readable CSV/JSON to
`benchmarks/results/`. Results are committed to git so they're
reproducible and version-tracked.

---

#### Experiment 1: Token Cost Comparison

**File:** `benchmarks/bench_tokens.py`

**Purpose:** Measure tokens consumed at session startup across three modes.

**Setup:**

- GitHub MCP (41 tools) + PostgreSQL MCP (232 tools) = 273 tools
- Proxy with support-agent scope (~7 allowed tools)

**Modes to measure:**

| Mode                            | What's in the model's context                  |
| ------------------------------- | ---------------------------------------------- |
| Direct (all servers)            | All 273 tool schemas loaded upfront            |
| Proxy startup                   | 3 meta-tool schemas only                       |
| Proxy after 1 search            | 3 meta-tools + 1 search result                 |
| Proxy after search + get_schema | 3 meta-tools + 1 search result + 1 full schema |

**Implementation:**

```python
import asyncio
import json
import csv
import tiktoken
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

enc = tiktoken.get_encoding("cl100k_base")

async def measure_direct():
    """Connect directly to upstream servers, count total schema tokens."""
    total = 0
    # PostgreSQL MCP (local) + optionally GitHub MCP (via Gateway with auth)
    urls = ["http://localhost:3000/mcp"]
    for url in urls:
        transport = StreamableHttpTransport(url=url)
        async with Client(transport) as client:
            tools = await client.list_tools()
            for tool in tools:
                schema_json = json.dumps(tool.model_dump())
                tokens = len(enc.encode(schema_json))
                total += tokens
    return total

async def measure_proxy_startup():
    """Connect to proxy, count meta-tool schema tokens."""
    transport = StreamableHttpTransport(url="http://localhost:9000/mcp")
    async with Client(transport) as client:
        tools = await client.list_tools()
        total = 0
        for tool in tools:
            schema_json = json.dumps(tool.model_dump())
            total += len(enc.encode(schema_json))
        return total

async def measure_proxy_after_search():
    """Proxy startup + one search_tools call."""
    transport = StreamableHttpTransport(url="http://localhost:9000/mcp")
    async with Client(transport) as client:
        tools = await client.list_tools()
        startup = sum(len(enc.encode(json.dumps(t.model_dump()))) for t in tools)

        result = await client.call_tool("search_tools", {"query": "issues"})
        search_tokens = len(enc.encode(json.dumps(result)))

        return startup + search_tokens

async def measure_proxy_after_schema():
    """Proxy startup + search + get_schema for one tool."""
    transport = StreamableHttpTransport(url="http://localhost:9000/mcp")
    async with Client(transport) as client:
        tools = await client.list_tools()
        startup = sum(len(enc.encode(json.dumps(t.model_dump()))) for t in tools)

        search_result = await client.call_tool("search_tools", {"query": "issues"})
        search_tokens = len(enc.encode(json.dumps(search_result)))

        schema_result = await client.call_tool("get_schema", {"tool_name": "list_issues"})
        schema_tokens = len(enc.encode(json.dumps(schema_result)))

        return startup + search_tokens + schema_tokens

async def main():
    results = {
        "direct": await measure_direct(),
        "proxy_startup": await measure_proxy_startup(),
        "proxy_after_search": await measure_proxy_after_search(),
        "proxy_after_schema": await measure_proxy_after_schema(),
    }

    print("\n=== Token Cost Comparison ===\n")
    print(f"{'Mode':<30} {'Tokens':>10} {'vs Direct':>12}")
    print("-" * 55)
    for mode, tokens in results.items():
        savings = f"{(1 - tokens / results['direct']) * 100:.1f}% saved" if mode != "direct" else "—"
        print(f"{mode:<30} {tokens:>10,} {savings:>12}")

    # Write CSV
    with open("benchmarks/results/token_costs.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["mode", "tokens", "savings_pct"])
        for mode, tokens in results.items():
            pct = round((1 - tokens / results["direct"]) * 100, 1) if mode != "direct" else 0
            writer.writerow([mode, tokens, pct])

    print("\nResults saved to benchmarks/results/token_costs.csv")

asyncio.run(main())
```

**Expected output:**

```
Mode                            Tokens    vs Direct
-------------------------------------------------------
direct                         125,000+          —
proxy_startup                      312    99.8% saved
proxy_after_search                 398    99.7% saved
proxy_after_schema                 548    99.6% saved
```

**Pass criteria:** Proxy startup savings > 95%. (With 273 tools, expect > 99%.)

---

#### Experiment 2: Latency Comparison

**File:** `benchmarks/bench_latency.py`

**Purpose:** Measure wall-clock time overhead of the proxy.

**Setup:** Same upstream servers + proxy.

**Modes:**
| Mode | Steps | Expected round trips |
|------|-------|---------------------|
| Direct | connect → tools/list → tools/call | 1 call (after schema load) |
| Proxy | connect → tools/list → search → get_schema → execute | 3 calls through proxy |

**Implementation:**

- Run each mode 20 times
- Measure per-run: total wall-clock time from first call to result
- Report: mean, median, p95, min, max for each mode
- Write results to `benchmarks/results/latency.csv`

**Expected output:**

```
=== Latency Comparison (20 runs) ===

Mode         Mean      Median    P95       Min       Max
--------------------------------------------------------------
direct       48ms      45ms      62ms      38ms      75ms
proxy        112ms     108ms     135ms     95ms      150ms
overhead     64ms      63ms      73ms      57ms      75ms
```

**Pass criteria:** Proxy overhead < 200ms (negligible vs LLM inference at 1-3s).

---

#### Experiment 3: Search Quality

**File:** `benchmarks/bench_search_quality.py`

**Purpose:** Does keyword search find the right tools?

**Method:** Define 20 natural language queries with expected correct tools.
Run each through `search_tools`. Check if the correct tool appears in results.

**Test queries (store in `benchmarks/queries.json`):**

```json
[
  { "query": "open bugs", "expected": ["list_issues"] },
  {
    "query": "find pull request",
    "expected": ["list_pull_requests", "get_pull_request"]
  },
  { "query": "issue details", "expected": ["get_issue"] },
  { "query": "merge PR", "expected": ["merge_pull_request"] },
  { "query": "list tables", "expected": ["pg_list_tables"] },
  { "query": "list tables", "expected": ["pg_list_tables"] },
  { "query": "table structure", "expected": ["pg_describe_table"] },
  { "query": "run query", "expected": ["pg_read_query"] },
  { "query": "insert data", "expected": ["pg_write_query", "pg_upsert"] },
  {
    "query": "database performance",
    "expected": ["pg_diagnose_database_performance"]
  },
  { "query": "issues in repo", "expected": ["list_issues"] },
  { "query": "PR status", "expected": ["get_pull_request"] },
  { "query": "create bug report", "expected": ["create_issue"] },
  { "query": "new PR", "expected": ["create_pull_request"] },
  { "query": "release", "expected": ["create_release"] },
  { "query": "team member", "expected": ["add_collaborator"] },
  { "query": "vacuum tables", "expected": ["pg_vacuum", "pg_vacuum_analyze"] },
  { "query": "full text search", "expected": ["pg_text_search"] },
  { "query": "repository issues", "expected": ["list_issues"] },
  {
    "query": "pull requests ready to merge",
    "expected": ["list_pull_requests"]
  }
]
```

**Metrics:**

- **Hit rate:** % of queries where at least one expected tool appears in results
- **Precision@1:** % of queries where the first result is an expected tool
- **Precision@3:** % of queries where an expected tool is in top 3
- **Miss analysis:** For each miss, log the query and what was returned instead

**Run against both scopes:**

- `support-agent` (restricted — some expected tools are blocked)
- `developer` (broader)

For `support-agent`, if the expected tool is blocked by scope (e.g., `create_issue`),
count that as a correct "not found" — the proxy is supposed to hide it.

**Output:** Table + CSV to `benchmarks/results/search_quality.csv`

```
=== Search Quality (developer scope, 20 queries) ===

Hit Rate:     17/20 (85%)
Precision@1:  14/20 (70%)
Precision@3:  17/20 (85%)

Misses:
  "open bugs" → returned: [] (expected: list_issues) — keyword "bugs" not in tool name
  "team member" → returned: [] (expected: add_collaborator) — no keyword overlap
  "PR status" → returned: [list_pull_requests] (expected: get_pull_request) — partial match
```

**Pass criteria:** Hit rate > 75%. Document misses honestly — these inform
the fuzzy search upgrade in agents.md.

---

#### Experiment 4: Scaling

**File:** `benchmarks/bench_scaling.py`

**Purpose:** At what tool count does the proxy's savings clearly dominate?

**Method:** Generate additional MCP servers with N tools (14, 30, 50, 100).
Measure direct token cost vs proxy token cost at each level.

**Implementation:**

- Create a `generate_test_server(num_tools, port)` function that spins up
  a FastMCP server with N randomly-named tools (realistic schemas)
- Measure token costs at each scale point
- Compute: savings %, overhead as % of savings

**Output:** Table + CSV to `benchmarks/results/scaling.csv`

```
=== Scaling: Token Savings vs Tool Count ===

Tools    Direct Tokens    Proxy Tokens    Savings %    Break-even?
----------------------------------------------------------------------
41       24,000           312             98.7%        Proxy wins
100      58,400           312             99.5%        Proxy wins
200      116,800          312             99.7%        Proxy wins clearly
273     125,000+         312             99.8%        Proxy wins dramatically
```

**Also measure:** At what tool count does the search start degrading?
Run the 20-query benchmark at each scale point.

**Pass criteria:** Savings > 95% at all scale points.

---

#### Experiment 5: Scope Security Validation

**File:** `benchmarks/bench_security.py`

**Purpose:** Verify that scoping actually works — blocked tools are
truly invisible.

**Method:**

- Connect to proxy with `support-agent` scope
- Attempt to access every dangerous tool through all three meta-tools:
  1. `search_tools("delete")` → should NOT return delete_repo
  2. `get_schema("delete_repo")` → should return error
  3. `execute_tool("delete_repo", ...)` → should return TOOL_NOT_IN_SCOPE
- Also try bypassing: `execute_tool("delete_repo", ...)` without
  searching first (direct tool name guess)

**Output:** Pass/fail for each blocked tool × each meta-tool

```
=== Scope Security Validation (support-agent) ===

GitHub blocked tools:
Blocked Tool              search_tools    get_schema    execute_tool
----------------------------------------------------------------------
delete_file               ✅ hidden       ✅ error      ✅ blocked
fork_repository           ✅ hidden       ✅ error      ✅ blocked
push_files                ✅ hidden       ✅ error      ✅ blocked
create_repository         ✅ hidden       ✅ error      ✅ blocked

PostgreSQL blocked tools (not in support-agent scope):
Blocked Tool              search_tools    get_schema    execute_tool
----------------------------------------------------------------------
pg_drop_table             ✅ hidden       ✅ error      ✅ blocked
pg_truncate               ✅ hidden       ✅ error      ✅ blocked
pg_write_query            ✅ hidden       ✅ error      ✅ blocked
pg_vacuum                 ✅ hidden       ✅ error      ✅ blocked
pg_terminate_backend      ✅ hidden       ✅ error      ✅ blocked

Result: All blocked tools are invisible across both servers.
```

**Pass criteria:** 100%. Any failure here is a security bug.

---

#### Running All Experiments

Add a convenience script:

**`benchmarks/run_all.py`:**

```python
"""Run all benchmarks and generate results."""
import subprocess
import sys

BENCHMARKS = [
    ("Token Cost", "benchmarks/bench_tokens.py"),
    ("Latency", "benchmarks/bench_latency.py"),
    ("Search Quality", "benchmarks/bench_search_quality.py"),
    ("Scaling", "benchmarks/bench_scaling.py"),
    ("Security", "benchmarks/bench_security.py"),
]

def main():
    print("=" * 60)
    print("mcp-guardian — Full Benchmark Suite")
    print("=" * 60)

    failed = []
    for name, script in BENCHMARKS:
        print(f"\n{'=' * 60}")
        print(f"Running: {name}")
        print("=" * 60)
        result = subprocess.run([sys.executable, script], cwd=".")
        if result.returncode != 0:
            failed.append(name)

    print(f"\n{'=' * 60}")
    if failed:
        print(f"FAILED: {', '.join(failed)}")
        sys.exit(1)
    else:
        print("ALL BENCHMARKS PASSED")
        print(f"Results saved to benchmarks/results/")

if __name__ == "__main__":
    main()
```

**Verify:**

```bash
# Ensure upstream servers + proxy are running
uv run python benchmarks/run_all.py
# All 5 experiments should pass
# Results committed to benchmarks/results/
```

**Commit results:**

```bash
git add benchmarks/results/
git commit -m "bench: add benchmark results"
```

---

### Stage 10: Documentation + Docker + Open Source Polish (1-2 hours)

**Goal:** Production-quality README, docs, Docker setup, and CI.

**Tasks:**

1. **README.md** — Complete with:
   - One-paragraph description
   - Architecture diagram (ASCII)
   - Quick Start (5-minute setup)
   - Configuration reference (scope.yaml format + env vars)
   - Benchmark results table
   - Comparison with spec recommendation, Code Mode
   - Docker usage
   - Known gotchas (transport, URL paths)
   - Contributing guidelines

2. **Dockerfile** — Production container:

   ```dockerfile
   FROM python:3.13-slim AS base

   # Install uv
   COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

   WORKDIR /app

   # Install dependencies (cached layer)
   COPY pyproject.toml uv.lock ./
   RUN uv sync --frozen --no-dev --no-editable

   # Copy source
   COPY src/ ./src/
   COPY examples/scope.direct.yaml ./scope.yaml

   # Default env vars (override at runtime)
   ENV GUARDIAN_HOST=0.0.0.0
   ENV GUARDIAN_PORT=9000
   ENV GUARDIAN_CONFIG_PATH=scope.yaml
   ENV GUARDIAN_SCOPE=support-agent

   EXPOSE 9000

   # Health check
   HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
       CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:9000/mcp')" || exit 1

   ENTRYPOINT ["uv", "run", "mcp-guardian"]
   ```

   **Usage:**

   ```bash
   # Build
   docker build -t mcp-guardian .

   # Run with direct config (PAT-based)
   docker run -p 9000:9000 \
     -v ./examples/scope.direct.yaml:/app/scope.yaml \
     -e GUARDIAN_SCOPE=support-agent \
     -e GITHUB_TOKEN=ghp_your_token \
     -e POSTGRES_MCP_URL=https://your-pg-mcp.example.com/mcp \
     mcp-guardian

   # OR run with gateway config
   docker run -p 9000:9000 \
     -v ./examples/scope.gateway.yaml:/app/scope.yaml \
     -e GUARDIAN_SCOPE=support-agent \
     -e TFY_GATEWAY_TOKEN=your_gateway_token \
     mcp-guardian
   ```

3. **docker-compose.yml** — Dev environment:

   ```yaml
   version: "3.8"

   services:
     postgres-mcp:
       image: writenotenow/postgres-mcp:latest
       ports:
         - "3000:3000"
       environment:
         POSTGRES_URL: postgresql://postgres:REDACTED@postgres-eo.eastus.cloudapp.azure.com:5432/mcp-dev-summit
       command: ["--transport", "http", "--port", "3000"]

     guardian:
       build:
         context: .
         dockerfile: Dockerfile
       ports:
         - "9000:9000"
       environment:
         GUARDIAN_SCOPE: support-agent
         GUARDIAN_CONFIG_PATH: scope.yaml
       volumes:
         - ./examples/scope.direct.yaml:/app/scope.yaml # swap with scope.gateway.yaml
       depends_on:
         - postgres-mcp
   ```

   **Usage:**

   ```bash
   # Direct config (PAT-based)
   docker compose up --build

   # OR gateway config (per-user OAuth via TrueFoundry)
   # Edit docker-compose.yml: change volume to ./examples/scope.gateway.yaml
   docker compose up --build
   ```

   **Note:** In docker-compose, update scope.yaml postgres URL to
   `http://postgres-mcp:3000/mcp` (service name, not localhost).

4. **docs/ARCHITECTURE.md** — Design decisions:
   - Why proxy, not client library
   - Why per-call connections
   - Why YAML config + Pydantic Settings (config file for tool scoping,
     env vars for secrets and runtime config)
   - Why keyword search as default
   - Why meta-tools instead of re-registering filtered tools
   - Alignment with MCP spec's Client Best Practices

5. **docs/QUICKSTART.md** — Step-by-step:
   - Install, configure, run, test with Inspector
   - Docker quick start alternative

6. **docs/COMPARISON.md** — Fair comparison:
   - vs direct connection (when direct is fine vs when proxy wins)
   - vs FastMCP Code Mode (complementary, not competing)
   - vs MCP spec recommendation (proxy is the infrastructure implementation)

7. **`.github/workflows/ci.yml`**:

   ```yaml
   name: CI
   on: [push, pull_request]
   jobs:
     lint:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: astral-sh/setup-uv@v4
         - run: uv sync --dev
         - run: uv run ruff check src/ tests/
         - run: uv run ruff format --check src/ tests/

     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: astral-sh/setup-uv@v4
         - run: uv sync --dev
         - run: uv run pytest tests/ -v --tb=short

     docker:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - run: docker build -t mcp-guardian .
         - run: docker run --rm mcp-guardian --help
   ```

8. **CONTRIBUTING.md** — How to contribute:
   - Fork, branch, PR workflow
   - Run tests before submitting
   - Code style (type hints, docstrings, ruff)
   - Docker development workflow

**Verify:**

```bash
# Full CI check locally
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
uv run pytest tests/ -v
# All must pass
```

---

## Review Checklist (Before Each Stage Merge)

Run this after completing each stage:

```
[ ] All new code has type hints
[ ] All public functions have docstrings
[ ] All new code passes: uv run ruff check src/ tests/
[ ] All new code passes: uv run ruff format --check src/ tests/
[ ] All tests pass: uv run pytest tests/ -v
[ ] No hardcoded values (use config or constants)
[ ] Error messages are human-readable
[ ] No raw stack traces exposed to users
[ ] New functionality has corresponding tests
[ ] README/docs updated if needed
```

---

## Stage Summary

| Stage | What                   | Time   | Key Deliverable                                                  |
| ----- | ---------------------- | ------ | ---------------------------------------------------------------- |
| 0     | Project skeleton       | 30 min | Empty project that builds and tests                              |
| 1     | Upstream server setup  | 30 min | Real GitHub (via Gateway) + real PostgreSQL MCP verified         |
| 2     | Config loader          | 1-2 hr | scope.yaml parsing with validation                               |
| 3     | Upstream manager       | 1-2 hr | Connect to servers with transport detection                      |
| 4     | Tool index + search    | 1-2 hr | Scope-filtered searchable tool catalog + inline smoke check      |
| 5     | Auth injection         | 30 min | Header building per server                                       |
| 6     | Audit logger           | 30 min | JSONL tool call logging                                          |
| 7     | Token counter          | 30 min | Savings measurement                                              |
| 8     | Core proxy             | 2-3 hr | **3 meta-tools, full end-to-end working**                        |
| 9     | Experiments            | 2-3 hr | 5 benchmarks: tokens, latency, search quality, scaling, security |
| 10    | Docs + Docker + polish | 1-2 hr | README, Dockerfile, docker-compose, architecture docs, CI        |

**Total estimated: ~14-18 hours of focused work.**
