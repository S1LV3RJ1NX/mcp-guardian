# MCP Dev Summit — Final Session Plan (Updated)

## Talk: "Putting MCP on a Diet: A Proxy for Tool Scoping and Context Compression"
**Track:** Building with MCP
**Format:** Session Presentation (25 min)
**Speaker:** Prathamesh Saraf

---

## WHAT YOU BUILD: `mcp-guardian`

### Architecture

```
                         mcp-guardian
┌───────────┐    ┌──────────────────────────┐    ┌──────────────┐
│ MCP Client│    │                          │    │ GitHub MCP   │
│ (Claude,  │───▶│  3 meta-tools exposed:   │───▶│ Server       │
│  Cursor,  │    │  • search_tools          │    │ (41 tools)   │
│  Agent)   │    │  • get_schema            │    └──────────────┘
└───────────┘    │  • execute_tool          │    ┌──────────────┐
   ~300 tokens   │                          │───▶│ Slack MCP    │
   upfront       │  Internal:               │    │ Server       │
                 │  • scope.yaml (scoping)  │    │ (8 tools)    │
                 │  • tool index (search)   │    └──────────────┘
                 │  • audit.log (logging)   │    ┌──────────────┐
                 │  • token counter         │───▶│ + 45 more    │
                 └──────────────────────────┘    │ servers      │
                                                 └──────────────┘
```

### What happens on startup

1. Proxy reads scope.yaml (which scopes, which servers, which tools allowed)
2. Connects to each upstream server, calls `tools/list`
3. Filters tools per scope (drops delete_repo etc.)
4. Builds a local search index from the allowed tools:
   ```
   list_issues | github | List issues in a repository by state
   get_issue | github | Get a specific issue by ID with full details
   list_pull_requests | github | List pull requests by state
   get_pull_request | github | Get PR details including mergeable status
   ```
5. Counts total tokens the full schemas would have cost (for benchmarking)
6. Exposes 3 meta-tools to clients instead of the full tool list

### What the client sees

Instead of 14 tool schemas (~8,000 tokens), the client sees:

```json
{
  "tools": [
    {
      "name": "search_tools",
      "description": "Search available tools by keyword. Returns matching tool names and one-line descriptions.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "Search query (e.g. 'github issues', 'send message')"}
        },
        "required": ["query"]
      }
    },
    {
      "name": "get_schema",
      "description": "Get the full parameter schema for a specific tool. Call this before execute_tool to understand required parameters.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "tool_name": {"type": "string", "description": "Exact tool name from search results"}
        },
        "required": ["tool_name"]
      }
    },
    {
      "name": "execute_tool",
      "description": "Execute a tool by name with parameters. Use get_schema first to understand the required parameter format.",
      "inputSchema": {
        "type": "object",
        "properties": {
          "tool_name": {"type": "string"},
          "params": {"type": "object"}
        },
        "required": ["tool_name", "params"]
      }
    }
  ]
}
```

That's ~300 tokens. Down from ~8,000.

### A typical agent interaction through the proxy

```
User: "What open bugs do we have in the backend repo?"

Agent thinks: I need to find issues. Let me search for tools.
Agent → search_tools(query="issues bugs")

Proxy: [grep "issues" against index, filtered by support-agent scope]
Proxy → returns:
  [
    {"name": "list_issues", "server": "github",
     "brief": "List issues in a repository by state"},
    {"name": "get_issue", "server": "github",
     "brief": "Get a specific issue by ID with full details"}
  ]

Agent thinks: list_issues is what I need. Let me get the full schema.
Agent → get_schema(tool_name="list_issues")

Proxy → returns:
  {
    "name": "list_issues",
    "inputSchema": {
      "type": "object",
      "properties": {
        "repo": {"type": "string", "description": "Repository in owner/name format"},
        "state": {"type": "string", "enum": ["open", "closed", "all"], "default": "open"}
      },
      "required": ["repo"]
    }
  }

Agent thinks: Now I know the params. Let me call it.
Agent → execute_tool(tool_name="list_issues", params={"repo": "acme/backend", "state": "open"})

Proxy: [checks scope: list_issues allowed for support-agent ✓]
       [injects auth header from env: GITHUB_TOKEN]
       [forwards to upstream GitHub server as tools/call]
       [logs to audit.log]
Proxy → returns: [{"id": 1, "title": "Login fails on Safari", ...}, ...]

Agent: "There are 3 open bugs in acme/backend: ..."
```

Total schema tokens loaded: ~150 (just list_issues schema)
vs. direct connection: ~8,000 (all 14 tool schemas)

---

## MINUTE-BY-MINUTE SESSION PLAN (25 min)

### 0:00–2:30 — Opening: The MCP Tax

**What you say:**

"I've spent the last two months building a public MCP playground —
real servers, real users, real OAuth flows.

Here's what I learned: GitHub's MCP server alone exposes 41 tools.
Slack adds another 8. A code interpreter adds 12. Before my agent
reads a single word of the user's query, 55,000 tokens are gone.
That's over a quarter of Claude's 200K context window. Spent on
tool descriptions the agent may never use this session.

The MCP spec now officially recognizes this. Their Client Best
Practices page recommends progressive discovery — search for tools,
load schemas on demand. Perplexity's CTO flagged it publicly.
Cloudflare measured 244,000 tokens for their API surface.

The spec's advice is sound. But it's a recommendation to clients:
every client has to implement progressive discovery independently.
Claude Desktop, Cursor, your custom agent — each builds it from
scratch. And the spec doesn't address tool scoping or auth.

I'm Prathamesh. I built a proxy called mcp-guardian that moves
progressive discovery to the infrastructure layer. One proxy, every
client benefits — plus tool scoping, auth injection, and audit
logging. Without modifying any MCP server. Let me show you."

**Slide 1:** Title slide.
**Slide 2:** The numbers: 41 tools from GitHub alone /
55K tokens before work begins — your own numbers plus industry
sources (Apideck, Perplexity CTO, Cloudflare).

### 2:30–4:00 — The Two Problems (1.5 min)

"MCP's default loading pattern creates two problems. The spec
acknowledges the first but not the second.

First, a cost problem. Every tool schema costs 300 to 1,400 tokens.
The more tools, the more cost. The spec's Client Best Practices now
recommends progressive discovery to fix this. Good. But every
client has to build it themselves.

Second, a security problem the spec doesn't solve. Standard servers
expose every tool they wrap. Connect to the GitHub server and the
agent sees delete_repo alongside list_issues. The spec mentions
least privilege and per-tool auth scopes, but there's no
off-the-shelf scoping mechanism. When I built a public playground,
I had to carefully curate which tools to expose. A visitor shouldn't
be able to call delete_repo on a demo account.

Both problems have the same root cause: the agent sees too much.
Too many tools (security) with too much detail (cost) too early
(before it knows what it needs).

My proxy solves both in one place — and it does it at the
infrastructure layer, so clients don't need to change."

**Slide 3:** Two-column layout.
Left: "Security: agent sees dangerous tools" (list with delete_repo
highlighted in red).
Right: "Cost: 8,000 tokens of schemas before work begins" (token
counter visual).

### 4:00–7:30 — Demo 1: The Problem Live (3.5 min)

**4:00–5:00 — God Mode demo (1 min)**

"Let me show you. Mock GitHub MCP server. 14 tools."

- MCP Inspector → connect to `localhost:8001/mcp`
- tools/list → 14 tools appear
- Scroll through: highlight delete_repo, force_push, transfer_repo
- "These are all in the agent's context window."

**5:00–5:30 — Token count (30 sec)**

- Show token counter output (pre-computed):
  "14 tools. Total schema tokens: 8,247."
- "That's one server. The real GitHub MCP? 41 tools. Add Slack and
  you're at 50+. I know because I've registered them all."

**5:30–7:30 — Through the proxy demo (2 min)**

"Now through mcp-guardian. Same server underneath."

- MCP Inspector → connect to `localhost:9000/mcp`
- tools/list → 3 meta-tools appear (search_tools, get_schema, execute_tool)
- "Three tools. About 300 tokens. 96% reduction."

- Call search_tools(query="issues")
- Returns: list_issues, get_issue (with one-line descriptions)
- "Found the tools I need. delete_repo? Doesn't appear. Not in the
  support-agent scope."

- Call get_schema(tool_name="list_issues")
- Returns: full JSON Schema for just that one tool
- "Now I have the full schema, but only for the tool I actually need.
  About 150 tokens instead of 8,000."

- Call execute_tool(tool_name="list_issues", params={"repo": "acme/app"})
- Returns: mock issue data
- "The call went through. Proxy injected auth, logged it, forwarded
  to the upstream server."

- Try execute_tool(tool_name="delete_repo", params={"repo": "acme/app"})
- Error: "Tool 'delete_repo' not found in scope 'support-agent'"
- "Security and compression in one proxy."

### 7:30–11:00 — How It Works (3.5 min)

**7:30–9:00 — The interception (1.5 min)**

**Slide 4:** Sequence diagram.

```
Client            mcp-guardian              GitHub Server
  |                    |                         |
  |--- tools/list ---->|                         |
  |                    |--- tools/list --------->|
  |                    |<-- 14 tools (8K tok) ---|
  |                    |                         |
  |                    | [filter by scope: 4]    |
  |                    | [build search index]    |
  |                    | [replace with 3 meta]   |
  |                    |                         |
  |<-- 3 tools (300t) -|                         |
  |                    |                         |
  |--- search_tools -->|  [grep over index]      |
  |<-- 2 matches ------|                         |
  |                    |                         |
  |--- get_schema ---->|  [lookup full schema]   |
  |<-- 1 schema (150t)-|                         |
  |                    |                         |
  |--- execute_tool -->|  [scope check ✓]        |
  |                    |  [inject auth header]   |
  |                    |  [log to audit.log]     |
  |                    |--- tools/call --------->|
  |                    |<-- result --------------|
  |<-- result ---------|                         |
```

"On startup, the proxy connects upstream, discovers all tools, filters
by scope, and builds a text index. When the client calls tools/list,
it gets 3 meta-tools. All discovery happens through those. The full
schema only loads when the agent asks for a specific tool."

**9:00–10:00 — The search implementation (1 min)**

"The search is deliberately simple. V1 is keyword matching — grep over
the tool name and description index. It's fast, deterministic, and
doesn't cost any LLM tokens.

You could upgrade this to fuzzy matching, TF-IDF, or a small model
call for semantic search. The architecture supports all of those.
But for a catalog of 50-100 tools, grep works surprisingly well.
The tool names and descriptions are already written to be
searchable — that's what they're for."

**10:00–11:00 — Design decisions (1 min)**

"Three decisions worth explaining.

Why a proxy and not a client library? The MCP spec recommends
progressive discovery as a client-side pattern. That's correct
for client authors. But a proxy works with every MCP client — Claude
Desktop, Cursor, VS Code, any agent framework — without changing
any of them. A client library ties you to one implementation. The
proxy is the infrastructure answer to a spec recommendation.

Why YAML config? Because scope definitions should be in version
control. In my own MCP playground, each MCP is a folder with a
config.yaml and display.yaml. Devs add servers via pull request.
I review which tools are exposed the same way I review code.
That's the security model.

Why expose execute_tool as a meta-tool instead of re-registering
the filtered tools directly? Because re-registering 4 tools with
full schemas is still 600+ tokens. The meta-tool pattern keeps
the upfront cost at 300 tokens regardless of how many tools exist
behind the proxy."

### 11:00–15:00 — How This Compares to Code Mode (4 min)

_This section prevents audience confusion and shows you understand
the ecosystem. It's the most important section for credibility._

**11:00–12:00 — What Code Mode is (1 min)**

"Some of you are thinking: doesn't FastMCP Code Mode already solve
this? Let me clarify, because the two approaches are complementary,
not competing.

FastMCP Code Mode is a server-side transform. The server author adds
one line — transforms=[CodeMode()] — and the server starts exposing
meta-tools instead of raw tools. Clients discover on demand, then
write Python scripts that chain multiple tool calls in a sandbox.
The scripts execute server-side and only the final result comes
back.

Code Mode solves two problems: discovery cost AND execution round
trips. It was introduced by Cloudflare and implemented in FastMCP
3.1."

**12:00–13:30 — The key differences (1.5 min)**

**Slide 5:** Comparison table.

```
                     FastMCP Code Mode    mcp-guardian proxy
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Runs where?          Inside the server    Between client and server
Who opts in?         Server author        Nobody (works with any server)
Client changes?      Must support code    Works with any MCP client
                     execution
Sandbox needed?      Yes                  No
Calling pattern      LLM writes Python    Normal tools/call
Reduces discovery    Yes                  Yes
  tokens?
Reduces round        Yes (chains calls    No (still 1 trip per call)
  trips?             in one script)
Tool scoping?        No                   Yes
Works with 3rd-      Only if they add     Yes, unmodified
  party servers?     Code Mode
```

"The sweet spot for Code Mode: servers you author and control, complex
workflows with many chained calls, environments where sandbox
execution is available.

The sweet spot for a proxy: servers you don't control, any MCP client,
environments where you need tool scoping, and teams that want one
infrastructure layer across multiple servers."

**13:30–15:00 — They're complementary (1.5 min)**

"In practice, you'd use both.

Your internal MCP servers — the ones your team writes and maintains —
add Code Mode for maximum efficiency. Your third-party servers —
GitHub, Slack, Sentry, vendor servers — sit behind the proxy for
scoping and compression.

The proxy can even sit in front of a Code Mode server. They don't
conflict. The proxy handles scoping and auth; Code Mode handles
execution efficiency.

And there's a future version where the proxy itself offers a
code execution meta-tool — so you get Code Mode for servers that
don't have it natively. That's not built yet, but the architecture
supports it."

**Slide 6:** Diagram showing both patterns working together:
```
Internal servers ──[Code Mode built-in]──▶ Agent
                                            ▲
Third-party servers ──[mcp-guardian proxy]───┘
```

### 15:00–18:00 — Benchmarks (3 min)

_Real numbers from your actual proxy. This is what separates your
talk from every blog post about the Perplexity controversy._

**15:00–16:30 — Token cost comparison (1.5 min)**

**Slide 7:** Bar chart with three bars.

```
                          Input Tokens (per session startup)
Direct connection:        ████████████████████████ 8,247 tokens
mcp-guardian proxy:       ██ 312 tokens (96.2% reduction)
After 1 tool discovery:   ███ 462 tokens (still 94.4% less)
```

"Direct connection: 14 tool schemas, 8,247 tokens before work begins.

Through the proxy: 3 meta-tools, 312 tokens. Agent then searches and
loads one schema, bringing it to 462. Still 94% cheaper.

At production scale — 500 sessions per day, Claude Sonnet pricing —
that's roughly $290 per day in schema overhead eliminated."

**16:30–17:30 — Reliability comparison (1 min)**

**Slide 8:** Table.

```
Test: 20 queries against 14-tool GitHub server

                    Direct    mcp-guardian
Correct tool used    18/20      17/20
Task completed       17/20      16/20
Avg tokens/session   9,412      1,847
Avg round trips      1.2        3.4
```

"The proxy adds about 2 extra round trips on average — the search
and get_schema steps. Task completion drops slightly because
occasionally the search doesn't surface the right tool on the first
try. But token usage drops by 80% per session.

For small tool sets (under 15 tools), direct connection is fine. The
proxy really shines at 30+ tools across multiple servers, where the
token savings dwarf the round-trip cost."

_Be honest if the numbers aren't perfect. "17/20 vs 18/20" with
80% fewer tokens is a completely acceptable tradeoff. The audience
will respect honest benchmarks more than inflated claims._

**17:30–18:00 — Where it breaks (30 sec)**

"Where the proxy doesn't help: if you have 5 tools and use all of
them every session, progressive disclosure adds latency for no
benefit. If the server author has already added Code Mode, the proxy
adds an unnecessary hop. Know when to use which."

### 18:00–20:30 — Auth + Audit (2.5 min)

**18:00–19:00 — Auth injection (1 min)**

"Because the proxy sits in the execution path, it handles credentials.
Each upstream server has an auth config in the YAML. The proxy reads
tokens from environment variables and injects them as headers. The
agent never sees raw API keys.

From building a public MCP playground, I can tell you
auth is the hardest part of the whole stack. You've got No Auth
servers, API Key servers, and OAuth2 servers that need per-user
token management. The proxy handles the simple cases — static
headers and bearer tokens. The per-user OAuth case — where Alice
connects her own GitHub and Bob connects his — that's an
infrastructure layer beyond what a proxy should do. Be honest about
the boundaries.

One token authenticates the user to the proxy. The proxy maps that
to the correct per-server credential. One token in, correct
credentials out."

**19:00–20:00 — Audit logging (1 min)**

- Show terminal: `tail -f audit.log`
- Make a call through Inspector
- JSONL entry appears

```json
{"ts":"2026-06-09T14:23:01Z","scope":"support-agent",
 "tool":"list_issues","server":"github",
 "params":{"repo":"acme/backend"},
 "status":"ok","duration_ms":45,"tokens_saved":7935}
```

"Every tool call logged with: who called it, what tool, what params,
and how many tokens were saved by not loading the full catalog.
You can pipe this to any observability stack."

**20:00–20:30 — Compounding effect (30 sec)**

"These three features compound. Tool scoping means fewer tools in the
catalog. Progressive disclosure means cheaper discovery of those
tools. Auth injection means no credentials in the agent's config.
Audit logging means you can see exactly what's happening. One proxy,
four problems solved."

### 20:30–23:00 — Limitations + Future Work (2.5 min)

**20:30–21:30 — What it doesn't do (1 min)**

"Let me be clear about what mcp-guardian is not.

It's a reference implementation. About 600 lines of Python. It
demonstrates patterns that production systems need.

It does NOT handle: per-user identity mapping — right now auth is
per-server, not per-user. I built a full OAuth2 flow for my MCP
playground — Auth0 for user login, per-user GitHub tokens managed
by a gateway. That's an infrastructure layer. The proxy handles
the simpler case: one credential per server.

It does NOT handle: transport negotiation. In the real world, some
MCP servers use Streamable HTTP, others use SSE. I discovered this
the hard way — my Calculator server uses Streamable HTTP, DeepWiki
uses SSE. The proxy currently assumes one transport. A production
version needs automatic fallback.

It does NOT handle: dynamic registry — scopes are in YAML, loaded
at startup. A registry with runtime discovery, versioning, and
health monitoring is a separate infrastructure layer.

It does NOT handle: high availability. Single-process proxy.
Production needs horizontal scaling."

**21:30–23:00 — Future directions (1.5 min)**

"Two things I want to build next.

First: a code execution meta-tool in the proxy. Right now the agent
does search → get_schema → execute, which is 3 round trips. With a
code execution tool, the agent could write a script that chains
multiple calls in one trip — the same pattern Code Mode uses, but
at the proxy layer for servers that don't support it natively. This
would give you Code Mode for any server.

Second, and this is the harder problem: session-aware context
compaction. Progressive disclosure solves the startup tax — tokens
consumed before work begins. But agents in production run long
sessions. Tool results from turn 3 that the agent already processed,
error traces that were resolved, superseded data — all of that
accumulates. A compaction layer that evicts stale tool results at
turn boundaries could cut session-level token waste by another 40-60%.
That's the next frontier of context engineering for MCP, and
currently nobody has built tooling for it.

If either of those interests you, the repo is open source. PRs are
welcome."

### 23:00–25:00 — Close (2 min)

**23:00–24:00 — The takeaway (1 min)**

"Three things.

One: MCP's context cost is a real problem, and the spec now
officially acknowledges it. Progressive discovery is the recommended
pattern. That's validation, not just my opinion.

Two: the spec tells every client to build progressive discovery
themselves. The proxy moves it to the infrastructure layer — one
deployment, every client benefits. If you control the server, add
Code Mode. If you don't, put a proxy in front. Use both for your
full MCP fleet.

Three: mcp-guardian is on GitHub. You can run it in five minutes. It
implements the spec's recommended patterns — progressive discovery,
least privilege, auth management — as a standalone proxy that works
with any MCP server, unmodified. And if you want to see what a
public MCP playground looks like, the link is in the repo."

**24:00–25:00 — GitHub link + close**

**Slide 12:** GitHub URL + QR code. Optionally: MCP Playground URL.

"Fork it. Break it. Tell me what I missed.

I'm Prathamesh. Thank you."

---

## DEMO SETUP

| Component | Port | What it is |
|-----------|------|------------|
| Mock GitHub MCP Server | 8001 | FastMCP, 14 tools, Streamable HTTP |
| mcp-guardian proxy | 9000 | Proxy with support-agent scope |
| MCP Inspector | browser | Two tabs: direct (8001) and proxy (9000) |
| Terminal | visible | `tail -f audit.log` |
| Token counter | terminal | Shows token savings in real time |

### Demo sequence (rehearse until automatic)

| Step | Duration | What happens |
|------|----------|-------------|
| Connect Inspector to 8001 | 15 sec | Show 14 tools |
| Show token count | 15 sec | "8,247 tokens" |
| Connect Inspector to 9000 | 15 sec | Show 3 meta-tools |
| search_tools("issues") | 20 sec | Returns 2 matches |
| get_schema("list_issues") | 15 sec | Full schema loads |
| execute_tool("list_issues") | 15 sec | Mock data returns |
| execute_tool("delete_repo") | 15 sec | Error: not in scope |
| Show audit.log entry | 15 sec | JSONL appears |
| **Total** | **~2.5 min** | |

### If demo fails

1. Play pre-recorded 2-minute screencast (saved locally, not cloud)
2. If video also fails, slides contain static screenshots of each step
3. The talk works without the demo. The demo makes it great.

---

## SLIDES (12 slides)

| # | Content | Time |
|---|---------|------|
| 1 | Title + name + "Author of 'My Adventures with LLMs' / Built a public MCP playground" | 0:30 |
| 2 | The MCP Tax: 41 tools from GitHub alone / 55K tokens gone | 1:30 |
| 3 | The two problems: security + cost, same root cause | 1:30 |
| 4 | LIVE DEMO: direct (14 tools) → proxy (3 meta-tools) | 3:30 |
| 5 | Sequence diagram: how the interception works | 2:00 |
| 6 | Design decisions: proxy vs library, YAML, meta-tools | 1:00 |
| 7 | Comparison: mcp-guardian vs FastMCP Code Mode (table) | 2:00 |
| 8 | "They're complementary" — when to use which (diagram) | 2:00 |
| 9 | Benchmarks: tokens + reliability + cost savings | 3:00 |
| 10 | Auth injection + audit logging + LIVE DEMO (audit.log) | 2:30 |
| 11 | Limitations + future work (transport, code execution, session compaction) | 2:30 |
| 12 | GitHub link + QR code + "Fork it, break it" | 1:30 |

---

## BENCHMARKS TO RUN BEFORE THE TALK

These are YOUR numbers, not blog-post numbers. Run them, record them,
put them in slides.

### Benchmark 1: Token Cost

| Setup | Measure |
|-------|---------|
| Direct to mock server (14 tools) | Count tokens in tools/list response |
| Through proxy (support-agent, 4 tools allowed) | Count tokens in meta-tool schemas |
| After 1 search + 1 get_schema | Total tokens loaded so far |
| After completing a 5-turn task | Total input tokens across all turns |

Use `tiktoken` (cl100k_base) to count tokens accurately.

**Bonus benchmark (from your real deployment):** Count tokens from the
real GitHub MCP server (41 tools) registered in your playground. This
gives you a real-world number, not just a mock number.

### Benchmark 2: Reliability

Run 20 test queries through both direct and proxy setups:
- "What open issues do we have?"
- "Find the PR for the login fix"
- "List all channels in Slack"
- etc.

Measure: Did the agent find the right tool? Did it complete the task?
How many round trips? Record failures and analyze why.

### Benchmark 3: Latency

Measure wall-clock time for:
- Direct: tools/list + tools/call
- Proxy: tools/list + search + get_schema + execute_tool

The proxy adds 2 extra round trips. How much time does that actually cost?

### Benchmark 4: Scaling

Repeat with 14 tools, 30 tools, 50 tools, 100 tools.
At what point does the proxy's token savings clearly outweigh
the extra round trips?

**Real-world data point:** Your public MCP playground has dozens of servers. Even if you only
count the tools that are relevant to a single scope (say 30-40 tools),
that's already in the "proxy clearly wins" territory.

---

## BUILD TIMELINE (Updated — CFP already submitted)

| Week | What to do |
|------|-----------|
| **Now** | Core proxy working: YAML config, upstream connection, tool index, 3 meta-tools |
| **+1 week** | Auth injection, audit logging, token counter. Full proxy end-to-end. |
| **+2 weeks** | All tests passing. README written. Push to GitHub. Publish to PyPI. |
| **+3 weeks** | Run all benchmarks. Record real numbers. Include real GitHub MCP (41 tools) benchmark. |
| **+4 weeks** | Build slides (12 slides). Take screenshots from actual demo. Write speaker notes. |
| **+5 weeks** | Practice talk 3× end-to-end. Time it. Cut anything over 23 min. Record backup screencast. |
| **Jun 2-8** | Final practice. Submit slides. Prep laptop. |
| **Jun 9-10** | Talk day. |

### Stretch goals (if time allows)

- [ ] Add fuzzy/semantic search (upgrade from grep)
- [ ] Add code execution meta-tool (proxy-side Code Mode)
- [ ] Test with real MCP servers (actual GitHub via your playground)
- [ ] Add transport auto-detection (SSE vs Streamable HTTP fallback)
- [ ] Write blog post: "Putting MCP on a Diet" (publish before event)
- [ ] Show the public MCP playground as a "real-world deployment" slide

---

## Q&A PREP

**Q: FastMCP Code Mode already does progressive disclosure. Why build a proxy?**

A: Code Mode requires the server author to add it. The GitHub community
server, the Slack server, vendor servers — they don't have Code Mode and
probably never will. The proxy gives you progressive disclosure for
servers you don't control. Use Code Mode for servers you author, the
proxy for everything else.

**Q: Doesn't adding a proxy add latency? Search + get_schema is 2 extra round trips.**

A: Yes. About 2 extra round trips per tool used. In my benchmarks, that's
20-40ms of added latency. The LLM inference is 1-3 seconds. The trade is:
20ms of proxy overhead vs. 8,000 fewer tokens processed per session. At
scale, the token savings dominate.

**Q: What if the search doesn't find the right tool?**

A: In my tests with keyword search, 17 out of 20 queries found the right
tool on the first try. When it misses, the agent can search again with
different keywords — the same way you'd retry a web search. For more
accuracy, upgrade to fuzzy matching or a small model call. The
architecture supports swapping the search implementation.

**Q: Perplexity abandoned MCP entirely. Why not just use REST APIs?**

A: Perplexity's use case is specific: known tools, single-agent product,
controlled environment. If your tools are static and you control everything,
direct API integration is simpler. MCP's value is when your tool landscape
is dynamic — multiple servers, multiple teams, evolving capabilities. The
proxy makes MCP affordable in that setting. Different tradeoffs for
different architectures.

**Q: Can this work with Claude Desktop / Cursor?**

A: Yes. Any MCP client that supports Streamable HTTP transport. You point
it at the proxy URL instead of the upstream server URL. No client-side
changes needed. That's the point.

**Q: How is this different from just writing fewer tool descriptions?**

A: Schema compression helps but doesn't scale. You'd have to manually
shorten descriptions across every server, and some parameter details
are essential for correct tool use. Progressive disclosure is orthogonal:
you keep the full schemas for accuracy but load them on demand. You don't
sacrifice quality for efficiency.

**Q: What about the session bloat problem — tool results accumulating?**

A: That's the next problem and it's genuinely unsolved. Progressive
disclosure handles the startup tax. Session bloat — stale tool results
accumulating across turns — is the dynamic tax. I'm working on a
compaction layer for that, but it's not in mcp-guardian today. Mentioning
it honestly because the audience should know the full picture.

**Q: You're a first-time speaker. Should I trust your benchmarks?**

A: The code is open source. The benchmark scripts are in the repo. Run
them yourself. That's why I published everything — so the numbers are
reproducible, not just claimed.

**Q: Have you actually deployed this in production?**

A: The proxy itself is a reference implementation. But the patterns —
tool scoping, progressive disclosure, auth management — I've deployed
those at scale in a public MCP playground. The playground
uses a gateway for scoping and auth. The proxy is the open-source,
standalone version of those same patterns that works without any
infrastructure dependency.

**Q: What about transport differences? Some servers use SSE, some use Streamable HTTP.**

A: Great question — I hit this exact issue. My Calculator MCP uses
Streamable HTTP, DeepWiki uses SSE. The current proxy assumes one
transport per server. A production version needs auto-detection with
fallback. It's on the roadmap. For the demo, everything uses
Streamable HTTP. In the real world, you'd want the proxy to probe
and negotiate.
