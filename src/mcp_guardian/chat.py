"""Chat agent that demonstrates progressive tool discovery via LLM."""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from mcp_guardian.proxy import Guardian

logger = logging.getLogger(__name__)

META_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_tools",
            "description": (
                "Search available MCP tools by keyword. Returns tool names and brief "
                "descriptions. Always call this first to discover available tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search keywords (e.g., 'github issues', 'list tables')",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_schema",
            "description": (
                "Get the full parameter schema for a specific tool. "
                "Call this after search_tools to understand the required parameters."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {
                        "type": "string",
                        "description": "Exact tool name from search_tools results.",
                    }
                },
                "required": ["tool_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_tool",
            "description": (
                "Execute a tool with parameters. Always call get_schema first "
                "to understand the required parameter format."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "tool_name": {"type": "string", "description": "Exact tool name."},
                    "params": {
                        "type": "object",
                        "description": "Tool parameters as a JSON object.",
                    },
                },
                "required": ["tool_name", "params"],
            },
        },
    },
]

MAX_TOOL_LOOPS = 6
MAX_TOOL_FAILURES = 2

SYSTEM_PROMPT = """\
You are a helpful assistant connected to MCP servers via mcp-guardian.
Active scope: {scope}

You have access to {tool_count} tools.

STRICT RULES — follow these exactly:
1. Call search_tools to find relevant tools.
2. Call get_schema for EVERY tool BEFORE calling execute_tool. \
Never guess parameters.
3. Call execute_tool with the exact parameters from the schema.
4. If a tool call fails, do NOT retry with the same parameters. \
Explain the error to the user.

Available tools overview:
{tool_list}

Be concise in your responses. Show the tool results clearly.\
"""


class ChatAgent:
    """Runs an agentic loop: user message -> LLM -> tool calls -> result."""

    def __init__(self, guardian: Guardian, base_url: str, api_key: str, model: str) -> None:
        self.guardian = guardian
        self.client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        self.model = model

    def _build_system_prompt(self) -> str:
        scope = self.guardian.config.active_scope
        briefs = []
        for entry in sorted(self.guardian.index.entries.values(), key=lambda e: e.name):
            briefs.append(f"- {entry.name} ({entry.server}): {entry.brief}")
        tool_list = "\n".join(briefs) if briefs else "(no tools indexed yet)"

        return SYSTEM_PROMPT.format(
            scope=scope,
            tool_count=len(self.guardian.index.entries),
            tool_list=tool_list,
        )

    async def _handle_tool_call(
        self, name: str, arguments: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        """Execute a single tool call and return (result_str, step_info)."""
        step: dict[str, Any] = {
            "action": name,
            "tool": None,
            "tokens": 0,
            "error": False,
        }
        start = time.monotonic()

        if name == "search_tools":
            query = arguments.get("query", "")
            results = self.guardian.index.search(query)
            output = [{"name": r.name, "server": r.server, "brief": r.brief} for r in results]
            step["tool"] = query
            step["tokens"] = sum(len(json.dumps(r)) // 4 for r in output)
            result_str = json.dumps(output, indent=2)

        elif name == "get_schema":
            tool_name = arguments.get("tool_name", "")
            schema = self.guardian.index.get_schema(tool_name)
            step["tool"] = tool_name
            if schema is None:
                result_str = json.dumps({"error": f"Tool '{tool_name}' not found"})
                step["tokens"] = 10
                step["error"] = True
            else:
                result_str = json.dumps(schema, indent=2)
                step["tokens"] = len(result_str) // 4

        elif name == "execute_tool":
            tool_name = arguments.get("tool_name", "")
            params = arguments.get("params") or arguments.get("parameters", {})
            entry = self.guardian.index.entries.get(tool_name)
            step["tool"] = tool_name

            if entry is None:
                result_str = json.dumps({"error": f"Tool '{tool_name}' not in scope"})
                step["tokens"] = 10
                step["error"] = True
            else:
                try:
                    result = await self.guardian.upstream.call_tool(entry.server, tool_name, params)
                    result_str = json.dumps(result, default=str)
                    if len(result_str) > 4000:
                        result_str = result_str[:4000] + "...(truncated)"
                    step["tokens"] = len(result_str) // 4
                    if '"isError": true' in result_str.lower():
                        step["error"] = True
                except Exception as exc:
                    result_str = json.dumps({"error": str(exc)})
                    step["tokens"] = 10
                    step["error"] = True
        else:
            result_str = json.dumps({"error": f"Unknown tool: {name}"})
            step["tokens"] = 5
            step["error"] = True

        step["duration_ms"] = int((time.monotonic() - start) * 1000)
        if step["error"]:
            logger.warning(
                "chat: %s(%s) FAILED: %s",
                name,
                step["tool"],
                result_str,
            )
        return result_str, step

    def _make_accounting(
        self,
        report: dict[str, Any],
        tool_tokens: int,
        llm_input: int,
        llm_output: int,
    ) -> dict[str, Any]:
        return {
            "direct_cost": report["direct_tokens"],
            "proxy_meta_tokens": report["proxy_tokens"],
            "tool_tokens": tool_tokens,
            "llm_input_tokens": llm_input,
            "llm_output_tokens": llm_output,
        }

    async def run_stream(
        self,
        message: str,
        history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[str]:
        """Run the agentic loop, yielding SSE events as steps complete.

        Events:
            data: {"type":"step", "step": {...}}
            data: {"type":"reply", "reply": "...", "token_accounting": {...}}
            data: {"type":"error", "error": "..."}
        """
        from mcp_guardian.tokens import savings_report

        report = savings_report(self.guardian.index)

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._build_system_prompt()},
        ]

        if history:
            for h in history:
                messages.append({"role": h["role"], "content": h["content"]})

        messages.append({"role": "user", "content": message})

        steps: list[dict[str, Any]] = []
        total_llm_input = 0
        total_llm_output = 0
        total_tool_tokens = 0
        failure_counts: dict[str, int] = {}

        for _ in range(MAX_TOOL_LOOPS):
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=META_TOOLS,
                tool_choice="auto",
            )

            choice = response.choices[0]

            if response.usage:
                total_llm_input += response.usage.prompt_tokens
                total_llm_output += response.usage.completion_tokens

            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                messages.append(choice.message.model_dump())
                hit_failure_limit = False

                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}

                    result_str, step = await self._handle_tool_call(tc.function.name, args)
                    total_tool_tokens += step["tokens"]
                    steps.append(step)

                    step_out = {k: v for k, v in step.items() if k != "error"}
                    yield f"data: {json.dumps({'type': 'step', 'step': step_out})}\n\n"

                    if step["error"]:
                        key = f"{step['action']}:{step['tool']}"
                        failure_counts[key] = failure_counts.get(key, 0) + 1
                        if failure_counts[key] >= MAX_TOOL_FAILURES:
                            result_str = json.dumps(
                                {
                                    "error": (
                                        f"Tool '{step['tool']}' failed "
                                        f"{MAX_TOOL_FAILURES} times. "
                                        "Summarize what you know so far."
                                    )
                                }
                            )
                            hit_failure_limit = True

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": result_str,
                        }
                    )

                if hit_failure_limit:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "A tool has failed repeatedly. Stop calling it "
                                "and respond with what you know."
                            ),
                        }
                    )
                continue

            reply = choice.message.content or ""
            acct = self._make_accounting(
                report, total_tool_tokens, total_llm_input, total_llm_output
            )
            clean_steps = [{k: v for k, v in s.items() if k != "error"} for s in steps]
            payload = {
                "type": "reply",
                "reply": reply,
                "steps": clean_steps,
                "token_accounting": acct,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            return

        acct = self._make_accounting(report, total_tool_tokens, total_llm_input, total_llm_output)
        clean_steps = [{k: v for k, v in s.items() if k != "error"} for s in steps]
        payload = {
            "type": "reply",
            "reply": "Reached maximum tool call depth. Try a simpler query.",
            "steps": clean_steps,
            "token_accounting": acct,
        }
        yield f"data: {json.dumps(payload)}\n\n"
