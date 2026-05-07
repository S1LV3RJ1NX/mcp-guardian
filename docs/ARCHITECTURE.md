# Architecture

Design decisions behind mcp-guardian and how they map to the MCP specification.

## Why a Proxy, Not a Client Library

A proxy sits transparently between any MCP client and any upstream server. The client doesn't need code changes — it connects to the proxy exactly like it would connect to any MCP server. This means mcp-guardian works with Claude Desktop, Cursor, custom clients, and any future MCP client without modification.

A client library would require every client to integrate it, and wouldn't work with closed-source clients.

## Connection Strategy

The `UpstreamManager` uses two strategies depending on auth type:

**Non-OAuth servers** (`none`, `bearer_env`, `static_header`, `token_passthrough`) open a fresh `fastmcp.Client` connection per `call_tool` invocation. Reasons:
- **Simplicity** — no connection lifecycle management, reconnection logic, or stale connection bugs
- **Statelessness** — each call is independent, which makes the proxy horizontally scalable
- **Auth freshness** — tokens are resolved at call time, so rotated credentials work immediately

**OAuth servers** use **persistent cached clients** (`_oauth_clients` dict). The OAuth flow requires a browser-based authorization and token exchange; creating a fresh client each time would repeat the flow. The cached client preserves the token for the session. `disconnect_oauth()` and `shutdown()` clean up these clients.

The overhead of reconnecting (for non-OAuth) is negligible compared to the upstream call latency (typically 50-5000ms).

## Why YAML Config + Pydantic Settings

Two configuration layers serve different purposes:

**scope.yaml** handles tool scoping — which servers exist, which tools are allowed per scope, and how auth works per server. This is declarative, version-controllable, and easy to review in PRs.

**Environment variables** (via Pydantic Settings with `GUARDIAN_` prefix) handle runtime config — host, port, transport, log level. These change per deployment without touching the config file.

Auth tokens are referenced by name in scope.yaml but read from the environment, the dashboard's KeyStore, or client headers — keeping secrets out of config files.

## Why Keyword Search as Default

The `KeywordSearch` strategy splits queries into words and matches against tool names and descriptions. It's simple, fast, requires no external dependencies, and works offline.

Scoring: exact name match (3 points) > name contains (2) > description contains (1).

Limitations: synonym gaps ("bugs" won't match "issues"). The `SearchStrategy` abstract base class allows plugging in fuzzy search (rapidfuzz) or semantic search (embeddings) without changing the rest of the system.

## Why Meta-Tools Instead of Re-Registering Filtered Tools

Alternative approach: the proxy could re-register each allowed tool under its own name, forwarding calls to upstream. This preserves the standard MCP tool discovery flow.

Why we chose meta-tools instead:

1. **Token savings** — re-registering 14 tools still puts 14 schemas in context. Meta-tools put 3 schemas in context regardless of scope size.
2. **Progressive discovery** — the LLM discovers tools on-demand via search, which matches how humans use documentation.
3. **Consistency** — the client always sees exactly 3 tools, making prompting and behavior predictable.
4. **MCP spec alignment** — this is the pattern recommended in the [Client Best Practices](https://modelcontextprotocol.io/docs/develop/clients/client-best-practices) section.

## Data Flow

```
Client                    Proxy                         Upstream
  │                         │                              │
  │── list_tools ──────────>│                              │
  │<── [search, schema,     │                              │
  │     execute] ───────────│                              │
  │                         │                              │
  │── search_tools("q") ──>│                              │
  │<── [{name, brief}] ────│  (index lookup, no upstream)  │
  │                         │                              │
  │── get_schema("tool") ─>│                              │
  │<── {inputSchema} ──────│  (index lookup, no upstream)  │
  │                         │                              │
  │── execute_tool ────────>│── call_tool ────────────────>│
  │                         │<── result ──────────────────│
  │<── result ──────────────│  (+ audit log)               │
```

Only `execute_tool` hits the upstream server. Search and schema lookups are served from the in-memory index built at startup.

## Web Dashboard

The proxy serves a web dashboard at `http://<host>:<port>/` with API endpoints under `/api/*`. The dashboard provides:

- **Server cards** — status of each upstream server (connected, pending OAuth, needs API key)
- **Tool browser** — expand any connected server to see its indexed tools
- **OAuth connect** — click to trigger browser-based OAuth for deferred servers
- **API key input** — paste API keys for `bearer_env` servers, persisted in browser localStorage
- **Search** — search across all indexed tools
- **Stats** — tools in scope, token savings, server count
- **Chat Demo** — conversational interface that uses an LLM (any OpenAI-compatible endpoint) to demonstrate the progressive discovery pattern. Streams each tool call step via SSE and shows real-time token accounting (with vs without proxy)

The dashboard is a single HTML file (`dashboard.html`) served via custom Starlette routes in `routes.py`. The Chat Demo tab uses a `POST /api/chat` SSE endpoint backed by `ChatAgent` in `chat.py`.

## Module Structure

```
src/mcp_guardian/
  cli.py          # argparse entry point, graceful shutdown
  settings.py     # Pydantic Settings + load_dotenv
  config.py       # YAML parsing, dataclasses, validation
  exceptions.py   # GuardianError hierarchy
  upstream.py     # UpstreamManager (connections, OAuth client cache)
  index.py        # ToolIndex (scope filtering, search, deferred indexing)
  search/
    base.py       # SearchStrategy ABC
    keyword.py    # KeywordSearch implementation
  auth.py         # get_auth_headers per server
  audit.py        # JSONL audit logger
  tokens.py       # tiktoken counting + meta-tool schemas
  proxy.py        # Guardian class (FastMCP server + 3 meta-tools)
  routes.py       # Dashboard HTTP API + static page serving
  chat.py         # ChatAgent — LLM-driven agentic loop for Chat Demo (SSE streaming)
  keystore.py     # KeyStore ABC + InMemoryKeyStore for API keys
  patches.py      # OAuth compatibility patches (2xx, form-encoded)
  dashboard.html  # Embedded web dashboard (single-file HTML/CSS/JS)
```
