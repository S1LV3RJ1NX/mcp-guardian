# agents.md — Future Upgrade Roadmap

Future enhancements for mcp-guardian, organized by priority and complexity.
Each section describes the problem, the proposed solution, and the
architectural impact.

---

## Tier 1: Near-Term (Next Release)

### 1.1 Fuzzy Search

**Problem:** Keyword search misses semantic matches. "find bugs" doesn't
match `list_issues` because the words don't overlap.

**Solution:** Add `rapidfuzz` as an optional dependency. Implement
`FuzzySearch(SearchStrategy)` that uses token-set ratio matching.

**Architecture impact:** None — swap the search strategy in ToolIndex.
Already designed for this via the `SearchStrategy` abstract interface.

```python
# src/mcp_guardian/search/fuzzy.py
from rapidfuzz import fuzz, process
from mcp_guardian.search.base import SearchStrategy

class FuzzySearch(SearchStrategy):
    def __init__(self, threshold: int = 60):
        self.threshold = threshold

    def search(self, query: str, entries: dict[str, ToolEntry]) -> list[SearchResult]:
        searchable = {name: f"{e.name} {e.brief}" for name, e in entries.items()}
        matches = process.extract(query, searchable, scorer=fuzz.token_set_ratio, limit=10)
        return [
            SearchResult(name=name, server=entries[name].server, brief=entries[name].brief)
            for name, score, _ in matches if score >= self.threshold
        ]
```

**Config addition:**
```yaml
search:
  strategy: fuzzy     # keyword | fuzzy | embedding
  threshold: 60       # fuzzy match threshold (0-100)
```

**Effort:** 2-3 hours. Tests + optional dependency handling.

---

### 1.2 Transport Auto-Detection Caching

**Problem:** Current implementation probes transport on every connection.
Wasteful for servers with known transports.

**Solution:** Cache detected transport in-memory after first successful probe.
Add `transport` field to config for explicit override.

**Architecture impact:** Already designed for this in `UpstreamManager`.
Just add a dict cache and check before probing.

**Effort:** 30 min.

---

### 1.3 Rate Limiting

**Problem:** Public-facing proxies get abused. No per-scope or per-tool
call limits.

**Solution:** In-memory rate limiter. Configurable per scope.

```yaml
rate_limit:
  enabled: true
  requests_per_hour: 10    # per scope, global across all tools
```

**Architecture impact:** Add a `RateLimiter` class. Check in `execute_tool`
before forwarding. Return structured error with remaining quota and reset time.

```python
class RateLimiter:
    def check(self, scope: str) -> tuple[bool, int, float]:
        """Returns (allowed, remaining, reset_at_timestamp)."""
```

**Effort:** 1-2 hours. In-memory dict with timestamp tracking.
Production upgrade: swap to Redis.

---

### 1.4 Multiple Detail Levels

**Problem:** The MCP spec recommends offering multiple detail levels:
name-only, name-and-description, full-schema. Currently search_tools
only returns name + brief.

**Solution:** Add an optional `detail` parameter to search_tools:

```python
@self.server.tool()
async def search_tools(query: str, detail: str = "brief") -> list[dict]:
    """Search tools. detail: 'name' | 'brief' (default) | 'full'"""
```

- `name`: just tool names (minimum tokens)
- `brief`: name + one-line description (current default)
- `full`: name + description + parameter names and types (more tokens but
  may skip the get_schema step for simple tools)

**Spec reference:** The spec explicitly recommends this:
> "Let the model choose between name-only, name-and-description, or
> full-schema responses."

**Effort:** 1 hour.

---

## Tier 2: Medium-Term (v0.2)

### 2.1 Embedding-Based Search

**Problem:** Both keyword and fuzzy search struggle with semantic queries.
"help me with version control" should match GitHub tools.

**Solution:** Implement `EmbeddingSearch(SearchStrategy)` using a lightweight
embedding model. Compute embeddings for all tool descriptions at startup.
At query time, embed the query and do cosine similarity.

**Options:**
- **sentence-transformers** (local, ~100MB model, no API cost)
- **OpenAI embeddings API** (remote, needs API key, better quality)
- **Cohere embed** (remote, free tier available)

**Architecture impact:** New optional dependency. New search strategy class.
No changes to core proxy.

```yaml
search:
  strategy: embedding
  model: all-MiniLM-L6-v2    # sentence-transformers model
```

**Effort:** 3-4 hours. Model loading + embedding computation + similarity.

---

### 2.2 Code Execution Meta-Tool (Proxy-Side Code Mode)

**Problem:** The proxy adds 2 extra round trips per tool call (search +
get_schema before execute). For tasks requiring multiple tool calls,
this adds up.

**Solution:** Add a 4th meta-tool: `execute_code`. The model writes a
Python script that calls multiple tools. The script runs in a sandbox
(Monty, Deno, or subprocess). Only the final result returns to the model.

```python
@self.server.tool()
async def execute_code(code: str) -> str:
    """Execute Python code that can call tools.

    Available functions match the tools from search_tools.
    Example:
        issues = await list_issues(repo="acme/backend")
        for issue in issues:
            details = await get_issue(repo="acme/backend", issue_number=issue["number"])
            print(details["title"])

    Only console output (print statements) is returned to you.
    """
```

**Architecture impact:** Significant. Requires:
- Sandbox runtime (subprocess with restrictions, or Monty)
- Function stub generation from tool schemas
- Intercepting function calls → routing to execute_tool
- Output capture
- Security: timeouts, memory limits, no network access

**Spec reference:** This is exactly the "Programmatic Tool Calling / Code Mode"
pattern from the MCP spec, but implemented at the proxy layer for servers
that don't support it natively.

**Effort:** 1-2 weeks. This is the biggest single feature.

---

### 2.3 Per-User Identity Mapping

**Problem:** Current auth is per-server (one credential for all users).
In production, Alice's GitHub token should be different from Bob's.

**Solution:** Accept a user identity header from the client. Map user
identities to per-server credentials stored in a credentials store.

```yaml
auth:
  type: per_user
  user_header: X-Guardian-User-Id  # header the client sends
  credential_store: file            # file | env | vault
  credential_path: ./credentials/   # directory of per-user YAML files
```

```yaml
# credentials/alice.yaml
github:
  type: bearer
  token: ghp_alice_token
slack:
  type: bearer
  token: xoxb-alice-token
```

**Architecture impact:** Moderate. New auth resolution path. New credential
store abstraction. Need to handle missing credentials gracefully (return
error asking user to register credentials).

**Effort:** 1 week.

---

### 2.4 Dynamic Server Registry

**Problem:** Scopes are loaded from YAML at startup. Adding a new server
requires a restart.

**Solution:** Watch scope.yaml for changes and hot-reload. Or add an
admin API endpoint for runtime registration.

**Options:**
- **File watcher** (watchdog library) — simplest, watch scope.yaml
- **Admin API** — POST /admin/servers to add/remove servers at runtime
- **Directory-based** — watch a directory, each .yaml file is a server config

**The MCP spec recommends this pattern:**
> "Maintain a registry of available servers and their high-level descriptions.
> Connect to a server only when the model determines it needs that server's
> capabilities."

**Architecture impact:** Need to make ToolIndex and UpstreamManager
support incremental updates (add/remove servers and tools without full
rebuild).

**Effort:** 1 week.

---

## Tier 3: Long-Term (v1.0)

### 3.1 Session-Aware Context Compaction

**Problem:** Progressive discovery solves the startup tax (tokens consumed
before work begins). But agents in production run long sessions. Tool
results from turn 3 accumulate in context even after they're no longer
relevant. This is the "dynamic tax."

**Solution:** A compaction layer that tracks which tool results are in the
model's context and suggests evictions at turn boundaries.

**How it could work:**
- Track which results were returned in which turn
- After N turns, tag stale results (results the model has already
  processed and summarized)
- Provide a `compact_context` meta-tool that returns a summary of
  stale results, allowing the model to drop the full versions
- Or: automatically truncate old results when re-injecting context

**Architecture impact:** Major. This goes beyond tool management into
context management. May need to track conversation state, which the
proxy currently doesn't do (stateless per-call).

**Status:** Genuinely unsolved across the ecosystem. Nobody has shipped
tooling for this. The first good implementation would be significant.

**Effort:** 2-4 weeks of research + implementation.

---

### 3.2 Subagent-Based Search

**Problem:** Keyword and embedding search can miss complex queries.
"Help me set up CI for my repo" should match create_issue + list_pull_requests
but might not with simple search.

**Solution:** Use a small, fast LLM (Claude Haiku, Gemini Flash) as the
search backend. The proxy sends the query + tool catalog to the LLM and
asks it to select the best tools.

**The MCP spec explicitly lists this as an option:**
> "Subagent-based: A secondary model selects tools for the task.
> This usually works very well but can be more costly."

**Architecture impact:** New search strategy. Requires LLM API key
configuration. Adds latency (LLM call) and cost (per-search tokens).

```yaml
search:
  strategy: subagent
  model: claude-3-haiku
  api_key_env: ANTHROPIC_API_KEY
```

**Effort:** 3-4 hours once the search interface exists.

---

### 3.3 Multi-Proxy Deployment (HA)

**Problem:** Single-process proxy. No horizontal scaling. If it goes down,
all clients lose access.

**Solution:** Stateless proxy design + shared state store (Redis).
Deploy multiple instances behind a load balancer.

**What needs to be shared:**
- Tool index (rebuild per-instance, or share via Redis)
- Audit log (write to centralized logging, not local file)
- Rate limit counters (Redis)
- Transport detection cache (Redis or rebuild per-instance)

**Architecture impact:** Replace in-memory stores with Redis-backed
implementations. Add health check endpoint.

**Effort:** 1-2 weeks.

---

### 3.4 Observability Integration

**Problem:** Audit log is a local JSONL file. No metrics, no tracing,
no dashboards.

**Solution:** Add OpenTelemetry integration for:
- **Metrics:** tool call count, latency histograms, error rates, token savings
- **Traces:** span per tool call showing proxy → upstream → response
- **Logs:** structured logging to stdout (compatible with log aggregators)

```yaml
observability:
  metrics: true
  tracing: true
  otlp_endpoint: http://localhost:4317
```

**Effort:** 1 week.

---

### 3.5 Plugin System

**Problem:** Users want custom behavior (custom search, custom auth,
custom audit) without forking the proxy.

**Solution:** Plugin interface using Python entry points.

```toml
# In the plugin's pyproject.toml
[project.entry-points."mcp_guardian.search"]
my_custom_search = "my_package:MyCustomSearch"
```

The proxy discovers plugins at startup and makes them available in config:
```yaml
search:
  strategy: my_custom_search    # loaded from entry point
```

**Architecture impact:** Refactor search, auth, and audit into
proper plugin interfaces with entry point discovery.

**Effort:** 1 week.

---

## Priority Matrix

| Feature | Value | Effort | Priority |
|---------|-------|--------|----------|
| Fuzzy search | Medium | Low | **P1** |
| Transport caching | Low | Tiny | **P1** |
| Rate limiting | High (public use) | Low | **P1** |
| Multiple detail levels | Medium (spec alignment) | Low | **P1** |
| Embedding search | Medium | Medium | P2 |
| Code execution meta-tool | Very High | High | **P2** |
| Per-user identity | High (production) | Medium | P2 |
| Dynamic registry | Medium | Medium | P2 |
| Session compaction | Very High (novel) | Very High | P3 |
| Subagent search | Medium | Low | P3 |
| Multi-proxy HA | High (production) | High | P3 |
| Observability | Medium | Medium | P3 |
| Plugin system | Low | Medium | P3 |

---

## Contributing

If you want to work on any of these, open an issue first to discuss the
approach. The architecture is designed to be modular — most features can
be added without touching the core proxy logic.

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
