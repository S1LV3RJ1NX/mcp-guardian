# mcp-guardian

MCP proxy for tool scoping and progressive discovery.

## Quick Start

```bash
# Install dependencies
uv sync --dev

# Install pre-commit hooks (ruff lint/format + unit tests on every commit)
uv run pre-commit install

# Copy and fill in your env vars
cp .env.example .env

# Verify upstream servers are accessible
uv run python scripts/verify_upstream.py

# Run tests
uv run pytest tests/ -v
```

## Upstream Servers

mcp-guardian proxies any MCP server. Out of the box it ships with configs
for two real servers: PostgreSQL MCP (248 tools) and GitHub MCP (41 tools).

### PostgreSQL MCP

Uses [writenotenow/postgres-mcp](https://hub.docker.com/r/writenotenow/postgres-mcp)
connected to a real PostgreSQL database.

Run locally via Docker:

```bash
docker run --rm -p 3000:3000 \
  -e POSTGRES_URL="postgresql://user:pass@host:5432/dbname" \
  writenotenow/postgres-mcp:latest \
  --transport http --port 3000
```

Then set `POSTGRES_MCP_URL=http://localhost:3000/mcp` in your `.env`.

The database needs to be deployed separately (Docker, any managed service, etc.).

**Seed the database** with sample data (idempotent, safe to re-run):

```bash
uv run python scripts/seed_db.py
```

Creates `customers`, `support_tickets`, and `invoices` tables with sample rows.
Reads `POSTGRES_URL` from `.env`.

### GitHub MCP

Uses the official GitHub MCP endpoint at `https://api.githubcopilot.com/mcp/`
with a personal access token (PAT).

1. Create a PAT at https://github.com/settings/tokens
2. Set `GITHUB_TOKEN=ghp_...` in your `.env`

That's it -- the verify script and integration tests use this directly.

> **Per-user OAuth:** If you need each user to authenticate with their own
> GitHub account (instead of sharing one PAT), you can put an MCP Gateway
> in front that handles OAuth token exchange per user. See
> `examples/scope.gateway.yaml` for a config example using
> [TrueFoundry's MCP Gateway](https://www.truefoundry.com/).

## Verification

```bash
# Verify both servers (skips GitHub if GITHUB_TOKEN not set)
uv run python scripts/verify_upstream.py

# Skip GitHub verification
uv run python scripts/verify_upstream.py --skip-github

# Integration tests (skip gracefully if servers unreachable)
uv run pytest tests/ -v -m integration
```

Expected output when both servers are configured:

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
