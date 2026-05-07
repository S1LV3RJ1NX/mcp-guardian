# mcp-guardian: Complete Walkthrough

A detailed guide to what mcp-guardian does, why it exists, how the code is structured, and how to extend it. Use this to prep for your MCP Dev Summit session.

## 1. The Problem in One Sentence

When an AI agent connects directly to MCP servers, every tool's full JSON schema gets loaded into the LLM's context window upfront — **before the user even types a question**.

**Concrete numbers from the benchmarks in this repo:**
- PostgreSQL MCP alone: 248 tools = ~108,000 tokens
- + GitHub MCP: +41 tools = 160,143 tokens total
- Claude's context is 200K tokens. **You've burned 80% of it on tool descriptions before the agent does any work.**

This is "the MCP tax".

## 2. What mcp-guardian Does

It's a **proxy** — a middleman between the AI client and the upstream MCP servers. To the client it looks like a normal MCP server. To upstream servers it looks like a normal MCP client.

```
                         mcp-guardian
┌───────────┐    ┌──────────────────────────┐    ┌──────────────┐
│ MCP Client│    │                          │    │ PostgreSQL   │
│ (Claude,  │───▶│  3 meta-tools exposed:   │───▶│ MCP          │
│  Cursor,  │    │  • search_tools          │    │ (248 tools)  │
│  Agent)   │    │  • get_schema            │    └──────────────┘
└───────────┘    │  • execute_tool          │    ┌──────────────┐
   456 tokens    │                          │───▶│ GitHub MCP   │
   upfront       │  Internal:               │    │ (41 tools)   │
                 │  • scope.yaml (scoping)  │    └──────────────┘
                 │  • tool index (search)   │
                 │  • audit.log (logging)   │
                 │  • token counter         │
                 └──────────────────────────┘
```

Instead of forwarding all 289 tool schemas, the proxy exposes **3 meta-tools**:

| Meta-tool | What it does |
|-----------|--------------|
| `search_tools(query)` | Keyword search over allowed tools, returns names + 1-line briefs |
| `get_schema(tool_name)` | Returns the full JSON schema for one specific tool |
| `execute_tool(tool_name, params)` | Forwards the actual call to the upstream server |

The agent uses these in sequence: **search → schema → execute**. Each step loads only what's needed at that moment. This is the **progressive discovery** pattern from the [MCP spec's Client Best Practices](https://modelcontextprotocol.io/docs/develop/clients/client-best-practices), implemented as infrastructure instead of as client code.

## 3. Why a Proxy (Not a Library or Code Mode)?

Three competing approaches exist. mcp-guardian's unique angle:

| Approach | Where it lives | Who has to opt in |
|----------|---------------|-------------------|
| **Spec recommendation** | Inside each client | Every client author |
| **FastMCP Code Mode** | Inside the server | Every server author |
| **mcp-guardian (this)** | Between them | Nobody — works with unmodified clients AND servers |

The spec's recommendation is good but means Claude Desktop, Cursor, and your custom agent each have to build progressive discovery from scratch. Code Mode requires the GitHub team / Slack team / vendors to add `transforms=[CodeMode()]` to their servers — they probably never will. mcp-guardian solves this at the infrastructure layer where one deployment helps everyone.

## 4. Code Walkthrough — How It's Built

The system lives in `src/mcp_guardian/` (~2400 lines including the HTML dashboard). Here's what each file does and how they fit together.

### Entry point: `cli.py` → `proxy.py`

`uv run mcp-guardian --scope support-agent` calls [src/mcp_guardian/cli.py](../src/mcp_guardian/cli.py) which:
1. Calls `apply_patches()` from `patches.py` to fix OAuth compatibility issues at startup
2. Parses CLI args and loads settings
3. Instantiates `Guardian` from [src/mcp_guardian/proxy.py](../src/mcp_guardian/proxy.py)
4. Calls `guardian.run()` inside a `try/finally` that cleanly shuts down OAuth clients on `Ctrl+C`

### `proxy.py` — the Guardian class

This is the heart of the system. Its `__init__` wires everything together:

```python
def __init__(self, config_path: str, scope: str) -> None:
    self.config = load_config(config_path, scope)
    self.upstream = UpstreamManager(self.config.upstream_servers)
    self.index = ToolIndex()
    self.audit = AuditLogger(self.config.audit)
    self.server = FastMCP(...)
    self._register_meta_tools()
    self._register_dashboard()  # web UI + API routes
```

`_register_dashboard()` adds the web dashboard at `/` and API endpoints under `/api/*` (server cards, tool browser, OAuth connect, API key management).

The `_register_meta_tools` method registers the 3 tools with FastMCP. Here's `execute_tool` — the most important one:

```python
entry = self.index.entries.get(tool_name)
if entry is None:
    return {
        "error": f"Tool '{tool_name}' not found in scope '{...}'",
        "code": "TOOL_NOT_IN_SCOPE",
    }

self.audit.log_call(scope=..., tool=tool_name, server=entry.server, params=params)

result = await self.upstream.call_tool(entry.server, tool_name, params)
self.audit.log_result(tool=tool_name, status="ok", duration_ms=..., tokens_saved=...)
return result
```

This is the security choke point: **first** check the index (`entry is None` → blocked), **then** audit log, **then** forward upstream. If the tool isn't in the active scope, it returns `TOOL_NOT_IN_SCOPE` and never touches upstream.

### `config.py` — YAML parsing

Defines dataclasses for the config structure. Key types:
- `ServerConfig` — one upstream server (URL, transport, auth)
- `Scope` — a named permission set (`support-agent`, `developer`)
- `ScopeServer` — within a scope, what tools are allowed/blocked per server
- `GuardianConfig` — the top-level loaded config with `active_scope` set

`load_config(path, scope)` parses the YAML, validates that referenced servers exist, that auth types are valid, that the active scope exists. All errors raise `ConfigError` with human-readable messages.

### `upstream.py` — connection manager

`UpstreamManager` handles two connection strategies:

**Non-OAuth servers** — fresh `fastmcp.Client` per call:

```python
async with Client(url, auth=auth) as client:
    return await client.list_tools()
```

**OAuth servers** — persistent cached clients (`_oauth_clients`) that preserve the OAuth token for the session. `_build_oauth_provider()` decides whether to use bare `auth="oauth"` (dynamic registration) or `OAuth(client_id=..., client_secret=...)` (pre-registered client).

`_resolve_auth()` implements the `bearer_env` priority chain: client header > KeyStore (dashboard) > env var > None.

`shutdown()` cleanly closes all cached OAuth clients (called on `Ctrl+C` via `cli.py`).

### `index.py` — the tool catalog

`ToolIndex.build()` runs once at startup. For each server in the active scope, it lists upstream tools and either adds them to the index or counts their token cost as "saved":

```python
for tool in tools:
    schema = tool.model_dump()
    tokens = count_schema_tokens(schema)

    if _is_tool_allowed(tool.name, allowed, blocked):
        self.entries[tool.name] = ToolEntry(...)
    else:
        self.tokens_saved += tokens
        self._excluded_count += 1
```

This is **the scope filter**. Two modes:
- `allowed_tools: ["foo", "bar"]` → only those tools (explicit allowlist)
- `allowed_tools: "*"` + `blocked_tools: ["delete_repo"]` → everything except blocked

### `search/keyword.py` — search strategy

Pluggable search via abstract `SearchStrategy`. Default `KeywordSearch` does word-by-word scoring:
- exact name match: 3 points
- name contains keyword: 2 points
- description contains keyword: 1 point

You could swap in fuzzy (`rapidfuzz`) or semantic (embeddings) without changing anything else.

### `auth.py` — credential injection

Returns headers per server based on auth type: `none`, `bearer_env`, `static_header`, `token_passthrough`, or `oauth`. For `oauth`, returns empty headers since `fastmcp` handles token injection internally. For `bearer_env`, the full resolution happens in `upstream.py`'s `_resolve_auth()` (client header > KeyStore > env var). Tokens never appear in scope.yaml — only env var **names** do.

### `patches.py` — OAuth compatibility

Applied once at startup. Fixes two issues in the MCP SDK:
1. Accepts any 2xx status from token endpoints (not just 200)
2. Handles form-encoded token responses from providers like GitHub (`access_token=...&token_type=bearer` instead of JSON)

### `routes.py` + `dashboard.html` — web dashboard

`routes.py` registers Starlette routes on the FastMCP server for the dashboard page (`/`) and JSON APIs (`/api/stats`, `/api/servers`, `/api/tools`, `/api/search`, etc.). Includes endpoints for OAuth connect/disconnect, API key management, and the Chat Demo SSE endpoint (`POST /api/chat`).

`dashboard.html` is a single-file HTML/CSS/JS dashboard with two tabs: the main **Dashboard** (server cards, tool browser, search, stats) and the **Chat Demo** (conversational tool use with live token accounting).

### `chat.py` — Chat Demo agent

`ChatAgent` implements an LLM-driven agentic loop that demonstrates progressive discovery in action. It uses the same three meta-tools the proxy exposes (`search_tools`, `get_schema`, `execute_tool`) but driven by an LLM via OpenAI function calling.

Key components:

- **`META_TOOLS`** — the function-calling schema given to the LLM, mirroring the proxy's 3 meta-tools
- **`SYSTEM_PROMPT`** — instructs the LLM to follow the search → schema → execute pattern and never guess parameters
- **`run_stream()`** — an `AsyncIterator` that yields SSE events as each tool step completes:
  - `type: "step"` — one tool action with name, tokens, and duration
  - `type: "reply"` — the final LLM response with full token accounting
  - `type: "error"` — if something goes wrong
- **`MAX_TOOL_LOOPS = 6`** — caps the total agentic loop iterations per conversation turn
- **`MAX_TOOL_FAILURES = 2`** — if the same tool fails twice, the agent stops retrying and asks the LLM to summarize with available information

The `/api/chat` endpoint in `routes.py` wraps `run_stream()` in a `StreamingResponse` (SSE), so the dashboard can show each step live as it happens. The frontend accumulates token counts across the conversation and displays a side-by-side comparison of costs with and without the proxy.

### `keystore.py` — API key store

Abstract `KeyStore` base class and `InMemoryKeyStore` implementation. Keys entered via the dashboard are stored here. For production, swap in a `RedisKeyStore` or database-backed store.

### `audit.py` — JSONL logging

Append-only log of every `execute_tool` call: timestamp, scope, tool, server, params, duration, tokens saved. Pipe to any observability stack.

### `tokens.py` — token counter

Wraps `tiktoken` (cl100k_base) with lazy loading and a `len(text) // 4` fallback if tiktoken can't download encoding data. `savings_report()` produces the startup output you see.

### `settings.py` — env vars

Pydantic Settings with `GUARDIAN_` prefix for runtime config (host, port, scope). `load_dotenv()` is called at import time so any `.env` var (`GITHUB_TOKEN`, `POSTGRES_MCP_URL`, etc.) is available throughout the codebase.

Also includes LLM settings for the Chat Demo:
- `GUARDIAN_LLM_BASE_URL` — any OpenAI-compatible endpoint (default: `https://api.openai.com/v1`)
- `GUARDIAN_LLM_API_KEY` — API key for the LLM provider
- `GUARDIAN_LLM_MODEL_NAME` — model to use (default: `gpt-4o-mini`)

These are optional — the Chat Demo tab is only active when `GUARDIAN_LLM_API_KEY` is set.

## 5. End-to-End Flow

```
                      Startup
Proxy ──list_tools──▶ Upstream (PostgreSQL MCP)
Proxy ◀── 248 tools ──
Proxy ──filter by support-agent scope──▶ Index (7 tools)


                      Runtime
Client ──list_tools──▶ Proxy
Client ◀── 3 meta-tools (456 tokens) ──

Client ──search_tools("tables")──▶ Proxy ──[index lookup]──▶
Client ◀── pg_list_tables, pg_describe_table... ──

Client ──get_schema("pg_list_tables")──▶ Proxy ──[index lookup]──▶
Client ◀── full inputSchema ──

Client ──execute_tool("pg_list_tables", {})──▶ Proxy
                                                ├── scope check
                                                ├── audit.log_call
                                                ├── forward to Upstream
                                                ├── audit.log_result
Client ◀── result ──
```

Only `execute_tool` hits the upstream server. Search and schema lookups are served from the in-memory index built at startup.

## 6. Scopes — What "support-agent" vs "developer" Means

Scopes are **named permission sets** in `scope.yaml`. The project ships two examples in [examples/scope.direct.yaml](../examples/scope.direct.yaml):

**`support-agent`** — explicit allowlist (read-only):
- GitHub: `get_me`, `list_issues`, `issue_read`, `list_pull_requests`, `pull_request_read`, `search_issues`, `search_code` (7 tools)
- Postgres: `pg_read_query`, `pg_list_tables`, `pg_describe_table`, `pg_count`, `pg_exists`, `pg_explain`, `pg_table_stats` (7 tools)
- **Total: 14 tools out of 289**. Everything else is invisible.

**`developer`** — wildcard with blocklist (broad access minus dangerous):
- GitHub: `"*"` minus `delete_file`, `fork_repository`, `push_files`
- Postgres: `"*"` minus `pg_drop_table`, `pg_drop_index`, `pg_truncate`, `pg_terminate_backend`
- **Total: 282 tools out of 289**

You pick which scope is active per proxy instance via `--scope` flag. In production you'd typically run different proxy instances per role (one for support agents on port 9000, one for developers on 9001), or one proxy per user with the right scope.

The active scope is set during `Guardian.__init__` and the index built once at startup. **Switching scopes requires restarting the proxy** — this is intentional, simpler, and means there's no runtime mistake possible.

## 7. The Web Dashboard

The proxy serves a web dashboard at `http://localhost:9000/` alongside the MCP endpoint at `/mcp`. You interact with mcp-guardian through:

1. **Web dashboard** (`http://localhost:9000/`) — server management, tool browsing, search, and stats
2. **MCP clients** (Claude Desktop, Cursor, custom agents) — connect to `http://localhost:9000/mcp` and see 3 tools
3. **MCP Inspector** ([github.com/modelcontextprotocol/inspector](https://github.com/modelcontextprotocol/inspector)) — a browser-based debug UI for any MCP server

**Dashboard features:**

- **Stats cards** — tools in scope, direct vs proxy token cost, savings percentage
- **Server cards** — each upstream server shows as a card with its status:
  - *Connected* — tools are indexed and browsable (auto-expanded)
  - *Pending OAuth* — click "Connect" to trigger browser-based authorization
  - *Needs API Key* — paste an API key (saved in browser localStorage)
  - *Connecting...* — OAuth flow in progress
- **Tool browser** — connected servers auto-expand to show their tools with token costs
- **Tool search** — search across all indexed tools by keyword
- **OAuth connect/disconnect** — manage OAuth sessions per server
- **API key management** — save and remove API keys from the dashboard
- **Chat Demo tab** — conversational interface powered by an LLM that demonstrates the progressive discovery pattern live, with real-time SSE streaming of each tool step and a token accounting sidebar showing cumulative costs with and without the proxy

**Startup output** (printed to terminal):
```
mcp-guardian started
  Scope:          support-agent
  Servers:        3
  Tools in scope: 7
  Direct cost:    108,549 tokens
  Proxy cost:     155 tokens
  Savings:        99.9%
  Deferred:       github, trends (will index on first call)
  Dashboard:      http://0.0.0.0:9000/
```

## 8. How Devs Extend It to More MCP Servers

The workflow is dead simple:

### Add a new upstream server (no code changes)

Edit `scope.yaml`:

```yaml
upstream_servers:
  # Existing servers...

  slack:                              # New server
    url: https://slack-mcp.example.com/mcp
    transport: auto
    auth:
      type: bearer_env
      value_env: SLACK_TOKEN

  sentry:
    url: https://sentry-mcp.example.com/mcp
    auth:
      type: static_header
      header: X-Sentry-Auth
      value_env: SENTRY_API_KEY
```

Then reference the new server in any scope:

```yaml
scopes:
  support-agent:
    servers:
      slack:
        allowed_tools:
          - list_channels
          - send_message
      sentry:
        allowed_tools: "*"
        blocked_tools:
          - delete_project
```

Set the env var, restart the proxy. **Done.** No Python required.

### Auth types supported (no code changes for these)

| Type | Use when |
|------|----------|
| `none` | Public server, no auth |
| `bearer_env` | Server expects `Authorization: Bearer <token>` (from env, dashboard, or client header) |
| `static_header` | Server expects a custom header (`X-API-Key`, etc.) |
| `token_passthrough` | Forward whatever Authorization header the client sends (per-user OAuth via gateway) |
| `oauth` | Server supports MCP OAuth discovery. Optional `client_id` / `client_secret_env` for pre-registered apps |

### Add a new search strategy (Python, but easy)

If keyword search isn't enough, subclass `SearchStrategy`:

```python
# src/mcp_guardian/search/fuzzy.py
from rapidfuzz import fuzz
from mcp_guardian.search.base import SearchStrategy

class FuzzySearch(SearchStrategy):
    def search(self, query, entries):
        # ... fuzz.ratio scoring
        return sorted_results
```

Pass it to `ToolIndex(search_strategy=FuzzySearch())`. Nothing else changes.

### Add a new auth type

Edit `auth.py`'s `get_auth_headers()` and add the type to `VALID_AUTH_TYPES` in `config.py`. ~10 lines of code.

## 9. Five Numbers to Memorize for the Talk

These come from actual benchmark runs in [benchmarks/summary.md](../benchmarks/summary.md):

| Claim | Number | Source |
|-------|--------|--------|
| Token reduction at startup | **99.7%** | Exp 1 |
| Direct vs proxy tokens | **160,143 → 456** | Exp 1 |
| Latency overhead | **-8ms** (within noise) | Exp 2 |
| Search hit rate | **93%** | Exp 3 |
| Break-even tool count | **39 tools** | Exp 4 |
| Scope security | **27/27 checks passed** | Exp 5 |
| Annual cost saved (Claude Opus 4.6, 1k sessions/day) | **$291/yr** | Exp 1 |

## 10. Q&A You Can Now Answer Confidently

**Q: How does the proxy know which tools belong to which server?**
A: At startup, `ToolIndex.build()` calls `upstream.list_tools(server_name)` for each server in the scope and stores `entry.server` alongside each tool. When `execute_tool` is called, the index lookup tells the proxy which upstream to forward to.

**Q: What if two servers have a tool with the same name?**
A: Currently the second one overwrites the first in the dict. A future version would namespace them (`github.list_issues`).

**Q: What stops a malicious agent from guessing a blocked tool name and calling execute_tool?**
A: Experiment 5 proves this. `execute_tool` checks `self.index.entries.get(tool_name)` first — blocked tools aren't in `entries`, so it returns `TOOL_NOT_IN_SCOPE` before touching upstream. Defense in depth across all three meta-tools (search, schema, execute).

**Q: Why per-call connections instead of a connection pool?**
A: Simplicity. Auth tokens are resolved at call time (rotation works immediately). Some MCP transports don't support multiplexing. The overhead is negligible vs upstream call latency (50-5000ms).

**Q: Can the proxy proxy a proxy?**
A: Yes — to mcp-guardian, an upstream MCP server is just a URL. You could chain them.

**Q: What about per-user OAuth?**
A: Use `token_passthrough` auth — the proxy forwards whatever `Authorization` header the client sends to upstream. The actual OAuth flow happens in a gateway in front of the proxy.

**Q: When would I need an MCP gateway like TrueFoundry?**
A: Three situations:

1. **The MCP server doesn't support OAuth discovery.** The MCP spec expects servers to expose `/.well-known/oauth-authorization-server` metadata (RFC 8414). Many servers — Slack, Notion, Jira, internal tools — give you a pre-registered client ID + secret instead. A gateway sits in front, serves the discovery metadata, and handles the token exchange so `type: oauth` just works in your `scope.yaml`.

2. **You need user isolation.** With `bearer_env`, every user shares the same PAT. With a gateway, each user gets their own OAuth session — the gateway maps the MCP OAuth flow to the upstream provider's OAuth, so users authenticate with their own GitHub/Slack/etc. identity. Audit logs then show *who* did what.

3. **You want centralized credential management.** Instead of distributing API keys to every proxy instance, the gateway holds the client secrets. Your `scope.yaml` stays clean (`type: oauth`, no secrets), and rotating credentials happens in one place.

If the MCP server already supports OAuth discovery and you don't need per-user isolation, you don't need a gateway — `type: oauth` connects directly.

**Q: What OAuth modes does mcp-guardian support?**
A: It depends on what the upstream MCP server supports. Here's the decision matrix:

| Server supports | scope.yaml config | What happens |
|---|---|---|
| Dynamic client registration (RFC 7591) + `/.well-known` | `type: oauth` | Fully automatic — `fastmcp` discovers endpoints and registers a client on the fly |
| `/.well-known` but NO dynamic registration | `type: oauth` + `client_id` (+ optional `client_secret_env`) | Skips registration, uses your pre-registered credentials. Auth/token URLs still discovered automatically |
| Neither `/.well-known` nor dynamic registration (raw OAuth2 like GitHub, Slack, Notion) | Use a gateway (e.g. TrueFoundry) | Gateway serves `/.well-known` metadata and handles the OAuth flow. Your config stays `type: oauth` |
| No OAuth at all, just API keys / PATs | `type: bearer_env` | Token from env var, dashboard, or client header — no OAuth involved |

Example — pre-registered client (no gateway needed):
```yaml
my-server:
  url: https://mcp.example.com/mcp
  auth:
    type: oauth
    client_id: "abc123"
    client_secret_env: MY_SERVER_SECRET  # optional, for confidential clients
```

`fastmcp` will discover `authorization_url` and `token_url` from `/.well-known/oauth-authorization-server` at the server URL, then run the browser-based OAuth flow using your `client_id`. No need to specify auth/token URLs manually.

**Q: What is FastMCP Code Mode and how does it compare to mcp-guardian?**
A: FastMCP Code Mode is a feature in the FastMCP Python framework where the **server author** writes code to control tool visibility. Instead of exposing all tools at once, the server defines tool groups or lazy-loading logic.

Example — a server using Code Mode to group tools:
```python
from fastmcp import FastMCP

mcp = FastMCP("my-server")

# Tools are tagged with categories
@mcp.tool(tags=["read"])
def list_tables():
    """List all tables in the database."""
    ...

@mcp.tool(tags=["write"])
def drop_table(name: str):
    """Drop a table. Dangerous!"""
    ...

@mcp.tool(tags=["discovery"])
def search_tools(query: str):
    """Search available tools by keyword."""
    # Server author manually implements search logic
    matching = [t for t in mcp.tools if query.lower() in t.name.lower()]
    return [{"name": t.name, "description": t.description} for t in matching]
```

The key differences:

| Aspect | FastMCP Code Mode | mcp-guardian proxy |
|---|---|---|
| **Who changes code?** | Server author must rewrite the server | Nobody — works with unmodified servers |
| **Works with 3rd-party servers?** | No — you can't modify PostgreSQL MCP or GitHub MCP | Yes — any MCP-compliant server |
| **Tool scoping** | Server defines groups in Python | YAML config, no code |
| **Search** | Server author implements search logic | Built-in pluggable search (keyword, semantic) |
| **Auth handling** | Server author implements | Declarative in scope.yaml (5 auth types) |
| **Audit logging** | Server author implements | Built-in JSONL audit log |
| **Multi-server** | One server at a time | Aggregate tools from N servers under one proxy |

**When Code Mode makes sense:** You're building your own MCP server from scratch and want built-in progressive discovery. You control the code and can add tags/groups.

**When mcp-guardian makes sense:** You're consuming existing MCP servers (PostgreSQL, GitHub, Slack, etc.) and want progressive discovery, scoping, and auth without modifying any of them. Or you're aggregating multiple servers into a single proxy.

In practice, the two can even work together — a server could use Code Mode internally, and you still put mcp-guardian in front for cross-server scoping, auth, and audit.

**Q: How does the Chat Demo work?**
A: The Chat Demo tab uses an LLM (configurable via `GUARDIAN_LLM_*` env vars) with OpenAI function calling. The LLM is given the same 3 meta-tools (`search_tools`, `get_schema`, `execute_tool`) and a system prompt that enforces the search → schema → execute pattern. Each turn runs an agentic loop (up to 6 iterations) where the LLM picks tools, `ChatAgent` executes them against the proxy's index and upstream servers, and results stream back to the browser via SSE. The sidebar tracks cumulative token costs — tool schema tokens, LLM input/output tokens, and the difference between using the proxy vs exposing all tools directly. If a tool fails twice, the agent stops retrying and asks the LLM to summarize with whatever data it has.

## Related Docs

- [QUICKSTART.md](QUICKSTART.md) — 5-minute setup guide
- [ARCHITECTURE.md](ARCHITECTURE.md) — design decisions and rationale
- [COMPARISON.md](COMPARISON.md) — vs direct, vs Code Mode, vs spec recommendation
- [benchmarks/summary.md](../benchmarks/summary.md) — all 5 experiment results
