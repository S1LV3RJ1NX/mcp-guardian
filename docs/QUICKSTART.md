# Quick Start

Get mcp-guardian running in 5 minutes.

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager
- At least one upstream MCP server (PostgreSQL MCP or GitHub MCP)

## 1. Install

```bash
git clone https://github.com/prathamesh-saraf/mcp-guardian.git
cd mcp-guardian
uv sync --dev
```

## 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` with your values:

```bash
# Required: at least one upstream server
POSTGRES_MCP_URL=http://localhost:3000/mcp
GITHUB_TOKEN=ghp_your_token_here

# Proxy settings (defaults are fine for local dev)
GUARDIAN_SCOPE=support-agent
```

## 3. Configure Scope

```bash
cp examples/scope.direct.yaml scope.yaml
```

The example config defines two scopes:
- `support-agent` — read-only tools (7 postgres + 7 github)
- `developer` — full access minus destructive operations

Edit `scope.yaml` to customize tool access per scope.

## 4. Start Upstream Servers

**PostgreSQL MCP** (via Docker):

```bash
docker run --rm -p 3000:3000 \
  -e POSTGRES_URL="postgresql://user:pass@host:5432/dbname" \
  writenotenow/postgres-mcp:latest \
  --transport http --port 3000
```

**GitHub MCP** — no server to start, just set `GITHUB_TOKEN` in `.env`.

## 5. Verify Upstream

```bash
uv run python scripts/verify_upstream.py
```

Expected output:

```
=== Upstream Server Verification ===
--- PostgreSQL MCP (http://localhost:3000/mcp) ---
  Tools found: 248
  OK: 248 tools (>= 200)
  OK: pg_list_tables returned real data
--- GitHub MCP (https://api.githubcopilot.com/mcp/) ---
  Tools found: 41
  OK: 41 tools (>= 30)
All checks passed.
```

## 6. Start the Proxy

```bash
uv run mcp-guardian --scope support-agent
```

The proxy starts on `http://localhost:9000/mcp`.

## 7. Connect a Client

Point any MCP client at `http://localhost:9000/mcp`. It will see three tools:

- `search_tools` — discover available tools
- `get_schema` — get parameters for a tool
- `execute_tool` — run a tool

## 8. Run Tests

```bash
# Unit tests
uv run pytest tests/ -v

# Integration tests (requires upstream servers running)
uv run pytest tests/ -v -m integration
```

## Docker Alternative

If you prefer Docker:

```bash
docker compose up --build
```

This starts both PostgreSQL MCP and the guardian proxy. Connect your client to `http://localhost:9000/mcp`.
