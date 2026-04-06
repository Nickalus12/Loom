"""Local Ollama agent with tool-calling, caching, git safety, and Graphiti memory."""

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypedDict

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

try:
    from loom.telemetry import get_telemetry as _get_telemetry
except Exception:
    _get_telemetry = None

try:
    from loom.tracer import ExecutionTracer, EventType
    _TRACER_AVAILABLE = True
except Exception:
    _TRACER_AVAILABLE = False

_DEFAULT_SYSTEM_PROMPT = (
    "You are a local code assistant with access to tools for reading, writing, "
    "editing, and searching code files, and running PowerShell commands. You work "
    "inside the project directory. Use tools to accomplish the task. Be precise "
    "and concise. When reviewing code, cite specific line numbers. When modifying "
    "files, prefer edit_file over write_file for targeted changes. Read files "
    "before editing them."
)

_DEFAULT_MAX_RESULT_CHARS = 8000


class AgentResult(TypedDict):
    success: bool
    response: str
    tool_calls_made: int
    turns_used: int
    files_changed: list[str]
    git_branch: str | None
    git_diff: str | None
    validation_results: list[dict]
    tool_log: list[dict]
    token_log: list[dict]
    memory_stored: bool
    truncated: bool


class LocalAgent:
    """Multi-turn agent loop for local Ollama models with tool calling."""

    _AGENT_TOOLS: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a file with line numbers. Use to review code.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path relative to project root",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file_lines",
                "description": "Read specific line range from a file. Use for large files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path relative to project root",
                        },
                        "start_line": {
                            "type": "integer",
                            "description": "First line number to read (1-based)",
                        },
                        "end_line": {
                            "type": "integer",
                            "description": "Last line number to read (1-based, inclusive)",
                        },
                    },
                    "required": ["path", "start_line", "end_line"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit_file",
                "description": (
                    "Replace a specific text snippet in a file. Read the file first "
                    "to find the exact text to replace. Prefer this over write_file "
                    "for targeted changes."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path relative to project root",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "Exact text to find and replace",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text",
                        },
                    },
                    "required": ["path", "old_text", "new_text"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write content to a file. Use to create or fully rewrite files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "File path relative to project root",
                        },
                        "content": {
                            "type": "string",
                            "description": "Full file content to write",
                        },
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "search_code",
                "description": "Search code files for a regex pattern. Returns matching lines.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Regex pattern to search for",
                        },
                        "path": {
                            "type": "string",
                            "description": "Directory to search in (default: '.')",
                        },
                        "include": {
                            "type": "string",
                            "description": "File glob filter (default: '*.*')",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "find_files",
                "description": "Find files by name pattern.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "File name pattern (e.g., '*.py')",
                        },
                        "path": {
                            "type": "string",
                            "description": "Directory to search in (default: '.')",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_powershell",
                "description": (
                    "Execute a PowerShell command. Use for git, tests, builds, "
                    "or any shell operation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "PowerShell command to execute",
                        },
                    },
                    "required": ["command"],
                },
            },
        },
    ]

    _CACHEABLE_TOOLS: frozenset[str] = frozenset({"read_file", "read_file_lines"})
    _FILE_MUTATING_TOOLS: frozenset[str] = frozenset({"write_file", "edit_file"})

    def __init__(
        self,
        inference_engine: Any,
        ps_manager: Any,
        memory_engine: Any = None,
        tool_model: str = "",
        analysis_model: str = "",
        max_turns: int = 15,
        max_result_chars: int = _DEFAULT_MAX_RESULT_CHARS,
        hybrid: bool = False,
    ) -> None:
        # Create a DEDICATED Ollama client to avoid connection pool conflicts
        # with the background worker in LocalInferenceEngine
        ollama_base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self._client: AsyncOpenAI = AsyncOpenAI(
            base_url=ollama_base + "/v1",
            api_key="ollama",
        )
        self._ps_manager = ps_manager
        self._memory = memory_engine
        self._hybrid = hybrid
        self._tool_model = (
            tool_model
            or os.getenv("LOOM_AGENT_TOOL_MODEL", "")
            or "qwen3:4b"
        )
        # In hybrid mode, analysis goes through cloud (LiteLLM proxy)
        if hybrid:
            self._analysis_model = (
                analysis_model
                or os.getenv("LOOM_HEAVY_MODEL", "")
                or "heavy/default"
            )
            litellm_key = os.getenv("LITELLM_MASTER_KEY", "sk-loom-internal-master")
            litellm_base = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1")
            logger.info("[Hybrid] Creating cloud client: base=%s key=%s...", litellm_base, litellm_key[:12] if litellm_key else "NONE")
            self._cloud_client: AsyncOpenAI | None = AsyncOpenAI(
                base_url=litellm_base, api_key=litellm_key,
            )
            logger.info("[Hybrid] Tool model: %s (local) | Analysis model: %s (cloud via %s)",
                         self._tool_model, self._analysis_model, litellm_base)
        else:
            self._analysis_model = (
                analysis_model
                or os.getenv("LOOM_AGENT_ANALYSIS_MODEL", "")
                or "deepseek-coder-v2:16b"
            )
            self._cloud_client = None
        self._max_turns = max_turns
        self._max_result_chars = max_result_chars

        self._cache: dict[str, str] = {}
        self._path_cache_keys: dict[str, set[str]] = {}
        self._tool_log: list[dict] = []
        self._validation_results: list[dict] = []
        self._files_changed: set[str] = set()
        self._git_branch_created: bool = False
        self._git_branch_name: str | None = None
        self._telemetry = _get_telemetry() if _get_telemetry is not None else None
        self.tracer: Any = ExecutionTracer() if _TRACER_AVAILABLE else None

    def _trace(self, event_type: str, name: str, **data: Any) -> int | None:
        if self.tracer is not None and _TRACER_AVAILABLE:
            return self.tracer.emit(EventType(event_type), name, **data)
        return None

    def _trace_begin(self, event_type: str, name: str, **data: Any) -> int | None:
        if self.tracer is not None and _TRACER_AVAILABLE:
            return self.tracer.begin(EventType(event_type), name, **data)
        return None

    def _trace_end(self, idx: int | None = None) -> None:
        if self.tracer is not None and idx is not None:
            self.tracer.end(idx)

    def _telem_inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        if self._telemetry is not None:
            try:
                self._telemetry.inc(name, value, **labels)
            except Exception:
                logger.debug("Telemetry inc failed for %s", name, exc_info=True)

    def _telem_observe(self, name: str, value: float, **labels: str) -> None:
        if self._telemetry is not None:
            try:
                self._telemetry.observe(name, value, **labels)
            except Exception:
                logger.debug("Telemetry observe failed for %s", name, exc_info=True)

    async def run(self, task: str, system_prompt: str | None = None) -> AgentResult:
        run_start = time.monotonic()
        if self.tracer is not None:
            self.tracer.reset()
        agent_span = self._trace_begin("agent_start", task[:80], model=self._tool_model, max_turns=self._max_turns)
        logger.info("=" * 60)
        logger.info("[Agent] Starting task: %s", task[:100])
        logger.info("[Agent] Tool model: %s | Analysis model: %s | Max turns: %d",
                     self._tool_model, self._analysis_model, self._max_turns)
        logger.info("=" * 60)
        self._telem_inc("agent_tasks_total")

        self._cache.clear()
        self._path_cache_keys.clear()
        self._tool_log.clear()
        self._validation_results.clear()
        self._files_changed.clear()
        self._git_branch_created = False
        self._git_branch_name = None

        memory_context = await self._retrieve_memory_context(task)

        system = system_prompt or _DEFAULT_SYSTEM_PROMPT
        if memory_context:
            system += memory_context
        if "qwen3" in self._tool_model.lower():
            system += (
                "\n\nEnable your thinking. Reason step by step about what tools "
                "to use and in what order before making tool calls."
            )

        messages: list[dict[str, Any]] = [{"role": "system", "content": system}]

        if "qwen3" not in self._tool_model.lower():
            plan_text = await self._planning_turn(task)
            if plan_text:
                messages.append({"role": "assistant", "content": f"Plan: {plan_text}"})

        messages.append({"role": "user", "content": task})

        total_tool_calls = 0
        turns_used = 0
        final_response = ""
        truncated = False
        token_log: list[dict] = []  # Per-turn token tracking

        for turn in range(self._max_turns):
            turns_used = turn + 1
            turn_start = time.monotonic()
            turn_span = self._trace_begin("turn_start", f"Turn {turn + 1}", turn=turn + 1)
            logger.info("[Turn %d/%d] Calling %s...", turn + 1, self._max_turns, self._tool_model)

            try:
                response = await self._llm_call(
                    self._tool_model, messages, tools=self._AGENT_TOOLS
                )
            except Exception as exc:
                logger.error("[Turn %d] LLM FAILED after %.1fs: %s: %s", turn + 1, time.monotonic() - turn_start, type(exc).__name__, exc, exc_info=True)
                self._telem_inc("agent_tasks_failed")
                self._telem_inc("model_call_errors", provider="ollama")
                final_response = f"LLM call failed on turn {turn} ({type(exc).__name__}): {exc}"
                elapsed = time.monotonic() - run_start
                self._telem_observe("agent_duration_seconds", elapsed)
                return AgentResult(
                    success=False,
                    response=final_response,
                    tool_calls_made=total_tool_calls,
                    turns_used=turns_used,
                    files_changed=list(self._files_changed),
                    git_branch=self._git_branch_name,
                    git_diff=None,
                    validation_results=list(self._validation_results),
                    tool_log=list(self._tool_log),
                    token_log=list(token_log),
                    memory_stored=False,
                    truncated=False,
                )

            choice = response.choices[0]
            assistant_msg: dict[str, Any] = {
                "role": "assistant",
                "content": choice.message.content or "",
            }

            turn_elapsed = time.monotonic() - turn_start
            # Token delta tracking
            input_chars = sum(len(m.get("content", "")) for m in messages)
            output_chars = len(choice.message.content or "")
            token_entry = {
                "turn": turn + 1,
                "input_tokens_est": input_chars // 4,
                "output_tokens_est": output_chars // 4,
                "llm_duration_ms": int(turn_elapsed * 1000),
                "has_tool_calls": bool(choice.message.tool_calls),
            }
            token_log.append(token_entry)

            if not choice.message.tool_calls:
                messages.append(assistant_msg)
                final_response = choice.message.content or ""
                logger.info("[Turn %d] Final response (%.1fs, ~%d input tokens, ~%d output tokens)",
                             turn + 1, turn_elapsed, token_entry["input_tokens_est"], token_entry["output_tokens_est"])
                self._trace_end(turn_span)
                break

            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in choice.message.tool_calls
            ]
            messages.append(assistant_msg)

            n_calls = len(choice.message.tool_calls)
            logger.info("[Turn %d] LLM responded in %.1fs with %d tool call(s)", turn + 1, time.monotonic() - turn_start, n_calls)

            for tc_idx, tc in enumerate(choice.message.tool_calls):
                total_tool_calls += 1
                tool_name = tc.function.name
                self._telem_inc("agent_tool_calls_total", tool=tool_name)
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}

                was_cached = False
                was_retried = False

                tool_start = time.monotonic()
                args_preview = {k: (v[:40] + "..." if isinstance(v, str) and len(v) > 40 else v) for k, v in args.items()}
                tool_span = self._trace_begin("tool_call", tool_name, args=args_preview)
                logger.info("[Turn %d] Tool %d/%d: %s(%s)", turn + 1, tc_idx + 1, n_calls, tool_name, json.dumps(args_preview, default=str)[:100])

                cache_key = self._cache_key(tool_name, args)
                if tool_name in self._CACHEABLE_TOOLS and cache_key in self._cache:
                    result = self._cache[cache_key]
                    was_cached = True
                    self._telem_inc("agent_tool_calls_cached")
                else:
                    if tool_name in self._FILE_MUTATING_TOOLS:
                        await self._ensure_git_branch()

                    result, was_retried = await self._execute_with_retry(
                        tool_name, args
                    )
                    if was_retried:
                        self._telem_inc("agent_tool_calls_retried")

                    if tool_name in self._CACHEABLE_TOOLS:
                        self._cache[cache_key] = result
                        path = args.get("path", "")
                        if path:
                            self._path_cache_keys.setdefault(path, set()).add(
                                cache_key
                            )

                    if tool_name in self._FILE_MUTATING_TOOLS:
                        path = args.get("path", "")
                        if path:
                            self._files_changed.add(path)
                            self._invalidate_path(path)

                        if path.endswith(".py"):
                            await self._validate_python_file(path)

                truncated_result = result[:self._max_result_chars]
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": truncated_result,
                })

                tool_elapsed_ms = int((time.monotonic() - tool_start) * 1000)
                self._trace_end(tool_span)
                if was_cached:
                    self._trace("cache_hit", tool_name)
                log_entry = {
                    "turn": turn,
                    "tool": tool_name,
                    "args": {
                        k: (v[:50] if isinstance(v, str) else v)
                        for k, v in args.items()
                    },
                    "result_preview": result[:200],
                    "cached": was_cached,
                    "retried": was_retried,
                    "duration_ms": tool_elapsed_ms,
                }
                self._tool_log.append(log_entry)
                status = "CACHED" if was_cached else f"{tool_elapsed_ms}ms"
                logger.info(
                    "[Turn %d] Tool %s -> %s%s",
                    turn + 1,
                    tool_name,
                    status,
                    " (retried)" if was_retried else "",
                )

            turn_total = time.monotonic() - turn_start
            self._trace_end(turn_span)
            logger.info(
                "[Turn %d] Complete: %d tool calls, %.1fs total",
                turn + 1,
                len(choice.message.tool_calls),
                turn_total,
            )
        else:
            final_response = messages[-1].get("content", "Max turns reached")
            truncated = True

        if self._tool_model != self._analysis_model and not truncated:
            synthesis = await self._analysis_turn(messages)
            if synthesis:
                final_response = synthesis

        git_diff = None
        if self._git_branch_created:
            git_diff = await self._git_diff()

        memory_stored = await self._store_memory(
            task, final_response, list(self._files_changed), total_tool_calls
        )

        elapsed = time.monotonic() - run_start
        self._telem_inc("agent_tasks_completed")
        self._telem_inc("agent_turns_total", value=float(turns_used))
        self._telem_observe("agent_duration_seconds", elapsed)
        self._trace_end(agent_span)
        logger.info(
            "Agent run complete: %d turns, %d tool calls, %.1fs elapsed",
            turns_used,
            total_tool_calls,
            elapsed,
        )
        # Save trace for post-mortem analysis
        if self.tracer is not None:
            try:
                trace_dir = Path("docs/loom/traces")
                trace_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                self.tracer.save(trace_dir / f"trace-{ts}.json")
            except Exception:
                logger.debug("Failed to save trace", exc_info=True)

        return AgentResult(
            success=True,
            response=final_response,
            tool_calls_made=total_tool_calls,
            turns_used=turns_used,
            files_changed=list(self._files_changed),
            git_branch=self._git_branch_name,
            git_diff=git_diff,
            validation_results=list(self._validation_results),
            tool_log=list(self._tool_log),
            token_log=list(token_log),
            memory_stored=memory_stored,
            truncated=truncated,
        )

    def _select_client(self, model: str) -> AsyncOpenAI:
        """Select the right client: cloud for analysis in hybrid mode, local otherwise."""
        if self._hybrid and self._cloud_client is not None and model == self._analysis_model:
            return self._cloud_client
        return self._client

    async def _llm_call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Any:
        client = self._select_client(model)
        provider = "cloud" if client is self._cloud_client else "ollama"

        self._telem_inc("agent_model_calls", model=model)
        self._telem_inc("model_calls_total", provider=provider)

        input_est = sum(len(m.get("content", "")) // 4 for m in messages)
        self._telem_inc("model_tokens_input", value=float(input_est))

        kwargs: dict[str, Any] = {"model": model, "messages": messages}
        if tools:
            kwargs["tools"] = tools

        msg_count = len(messages)
        input_chars = sum(len(m.get("content", "")) for m in messages)
        logger.info("[LLM] Calling %s via %s (%d msgs, ~%d chars)...", model, provider, msg_count, input_chars)

        call_start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                client.chat.completions.create(**kwargs),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            logger.error("[LLM] TIMEOUT after 120s waiting for %s (%s)", model, provider)
            self._telem_inc("model_call_errors", provider=provider)
            raise
        except Exception:
            logger.error("[LLM] ERROR after %.1fs from %s (%s)", time.monotonic() - call_start, model, provider, exc_info=True)
            self._telem_inc("model_call_errors", provider=provider)
            raise

        call_elapsed = time.monotonic() - call_start
        has_tools = bool(result.choices[0].message.tool_calls)
        logger.info("[LLM] %s (%s) responded in %.1fs (tool_calls=%s)", model, provider, call_elapsed, has_tools)
        self._telem_observe("model_call_duration_seconds", call_elapsed, provider=provider)

        content = result.choices[0].message.content
        if isinstance(content, str):
            self._telem_inc("model_tokens_output", value=float(len(content) // 4))

        return result

    async def _planning_turn(self, task: str) -> str:
        client = self._select_client(self._analysis_model)
        provider = "cloud" if client is self._cloud_client else "local"
        logger.info("[Planning] Calling %s (%s) for plan...", self._analysis_model, provider)
        plan_start = time.monotonic()
        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self._analysis_model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a planning assistant. Given a task, outline "
                                "a step-by-step plan for how to accomplish it using "
                                "file reading, editing, searching, and shell commands. "
                                "Be concise."
                            ),
                        },
                        {"role": "user", "content": task},
                    ],
                ),
                timeout=60.0,
            )
            plan_text = response.choices[0].message.content or ""
            logger.info("[Planning] Done in %.1fs (%d chars)", time.monotonic() - plan_start, len(plan_text))
            return plan_text
        except Exception as exc:
            logger.warning("[Planning] Failed after %.1fs: %s", time.monotonic() - plan_start, exc)
            return ""

    async def _analysis_turn(self, messages: list[dict[str, Any]]) -> str:
        try:
            messages_copy = list(messages)
            messages_copy.append({
                "role": "user",
                "content": "Synthesize your findings into a final response.",
            })
            client = self._select_client(self._analysis_model)
            provider = "cloud" if client is self._cloud_client else "local"
            logger.info("[Analysis] Calling %s (%s) for synthesis...", self._analysis_model, provider)
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    model=self._analysis_model,
                    messages=messages_copy,
                ),
                timeout=120.0,
            )
            return response.choices[0].message.content or ""
        except Exception as exc:
            logger.warning("Analysis turn failed: %s", exc, exc_info=True)
            return ""

    async def _ensure_git_branch(self) -> None:
        if self._git_branch_created:
            return
        branch = f"loom/agent-{int(time.time())}"
        result = await self._ps_manager.execute(
            f"git checkout -b '{branch}'", timeout=15
        )
        if result.get("success"):
            self._git_branch_created = True
            self._git_branch_name = branch
            self._telem_inc("git_branches_created")
            logger.info("Created git branch: %s", branch)
        else:
            logger.warning(
                "Failed to create git branch: %s", result.get("errors", "")
            )

    async def _git_diff(self) -> str | None:
        try:
            result = await self._ps_manager.execute(
                "git diff main...HEAD --stat", timeout=15
            )
            return result.get("output", "")
        except Exception as exc:
            logger.warning("Git diff failed: %s", exc, exc_info=True)
            return None

    async def _execute_with_retry(
        self, tool_name: str, args: dict[str, Any]
    ) -> tuple[str, bool]:
        result = await self._execute_agent_tool(tool_name, args)
        lower = result.lower()
        is_error = lower.startswith(("tool execution error", "error"))
        is_not_found = "not found" in lower
        if is_error and not is_not_found:
            logger.warning(
                "Tool %s failed, retrying: %s", tool_name, result[:100]
            )
            result = await self._execute_agent_tool(tool_name, args)
            return result, True
        return result, False

    async def _execute_agent_tool(
        self, tool_name: str, args: dict[str, Any]
    ) -> str:
        try:
            if tool_name == "read_file":
                path_escaped = args["path"].replace("'", "''")
                r = await self._ps_manager.execute(
                    f"Read-LoomFile '{path_escaped}'", timeout=15
                )
                return r.get("output", r.get("error", "No output"))

            elif tool_name == "read_file_lines":
                path_escaped = args["path"].replace("'", "''")
                r = await self._ps_manager.execute(
                    f"Read-LoomFile '{path_escaped}'", timeout=15
                )
                content = r.get("output", r.get("error", "No output"))
                if r.get("success"):
                    lines = content.splitlines()
                    start = max(0, int(args.get("start_line", 1)) - 1)
                    end = int(args.get("end_line", len(lines)))
                    return "\n".join(lines[start:end])
                return content

            elif tool_name == "edit_file":
                path = args["path"]
                old_text = args["old_text"]
                new_text = args["new_text"]

                cache_key = self._cache_key("read_file", {"path": path})
                if cache_key in self._cache:
                    file_content = self._cache[cache_key]
                else:
                    path_escaped = path.replace("'", "''")
                    r = await self._ps_manager.execute(
                        f"Read-LoomFile '{path_escaped}'", timeout=15
                    )
                    if not r.get("success"):
                        return f"Error reading file: {r.get('error', r.get('errors', 'Unknown error'))}"
                    file_content = r.get("output", "")

                raw_lines = file_content.splitlines()
                stripped_lines: list[str] = []
                for line in raw_lines:
                    parts = line.split("\t", 1)
                    if len(parts) == 2 and parts[0].strip().isdigit():
                        stripped_lines.append(parts[1])
                    else:
                        stripped_lines.append(line)
                raw_content = "\n".join(stripped_lines)

                if old_text not in raw_content:
                    return json.dumps({
                        "success": False,
                        "error": "old_text not found in file",
                        "path": path,
                    })

                updated_content = raw_content.replace(old_text, new_text, 1)
                content_escaped = updated_content.replace("'", "''")
                path_escaped = path.replace("'", "''")
                r = await self._ps_manager.execute(
                    f"Write-LoomFile '{path_escaped}' '{content_escaped}'",
                    timeout=15,
                )
                if not r.get("success"):
                    return f"Error writing file: {r.get('error', r.get('errors', 'Unknown error'))}"

                self._invalidate_path(path)
                return json.dumps({
                    "success": True,
                    "replacements": 1,
                    "path": path,
                })

            elif tool_name == "write_file":
                content_escaped = args["content"].replace("'", "''")
                path_escaped = args["path"].replace("'", "''")
                r = await self._ps_manager.execute(
                    f"Write-LoomFile '{path_escaped}' '{content_escaped}'",
                    timeout=15,
                )
                return r.get("output", r.get("error", "No output"))

            elif tool_name == "search_code":
                path = args.get("path", ".").replace("'", "''")
                include = args.get("include", "*.*").replace("'", "''")
                query_escaped = args["query"].replace("'", "''")
                r = await self._ps_manager.execute(
                    f"Search-LoomCode '{query_escaped}' -Path '{path}' -Include '{include}'",
                    timeout=30,
                )
                return r.get("output", r.get("error", "No output"))

            elif tool_name == "find_files":
                path = args.get("path", ".").replace("'", "''")
                pattern_escaped = args["pattern"].replace("'", "''")
                r = await self._ps_manager.execute(
                    f"Find-LoomFiles '{pattern_escaped}' -Path '{path}'",
                    timeout=15,
                )
                return r.get("output", r.get("error", "No output"))

            elif tool_name == "run_powershell":
                r = await self._ps_manager.execute(args["command"], timeout=60)
                return r.get("output", r.get("error", "No output"))

            else:
                return f"Unknown tool: {tool_name}"

        except Exception as exc:
            return f"Tool execution error: {exc}"

    def _cache_key(self, tool_name: str, args: dict[str, Any]) -> str:
        raw = json.dumps(args, sort_keys=True)
        return f"{tool_name}:{hashlib.md5(raw.encode()).hexdigest()}"

    def _invalidate_path(self, path: str) -> None:
        keys_to_remove = self._path_cache_keys.pop(path, set())
        for key in keys_to_remove:
            self._cache.pop(key, None)

    async def _validate_python_file(self, path: str) -> dict:
        escaped = path.replace("'", "''")
        result = await self._ps_manager.execute(
            f"python -c \"import ast; ast.parse(open('{escaped}').read()); print('OK')\"",
            timeout=15,
        )
        validation = {
            "path": path,
            "valid": result.get("success", False),
            "output": result.get("output", ""),
        }
        self._validation_results.append(validation)
        if not validation["valid"]:
            logger.warning(
                "Syntax validation FAILED for %s: %s",
                path,
                result.get("errors", ""),
            )
        return validation

    async def _retrieve_memory_context(self, task: str) -> str:
        if self._memory is None:
            return ""
        try:
            self._telem_inc("memory_searches")
            results = await self._memory.memory.search(task, num_results=3)
            if not results:
                return ""
            context_parts: list[str] = []
            for ep in results:
                fact = getattr(ep, "fact", "") or getattr(ep, "content", "")
                if fact:
                    context_parts.append(fact)
            if context_parts:
                return "\n\n## Previous Context\n" + "\n---\n".join(context_parts)
        except Exception:
            logger.debug("Session memory retrieval failed", exc_info=True)
        return ""

    async def _store_memory(
        self,
        task: str,
        response: str,
        files_changed: list[str],
        tool_calls_made: int,
    ) -> bool:
        if self._memory is None:
            return False
        try:
            from graphiti_core.nodes import EpisodeType

            episode_body = json.dumps({
                "task": task,
                "files_changed": files_changed,
                "tool_calls_made": tool_calls_made,
                "summary": response[:500],
            })
            await self._memory.memory.add_episode(
                name=f"Agent Task: {task[:50]}",
                episode_body=episode_body,
                source=EpisodeType.json,
                source_description="Loom local agent task result",
                reference_time=datetime.now(timezone.utc),
                group_id="loom-agent",
            )
            self._telem_inc("memory_episodes_stored")
            return True
        except Exception:
            logger.debug("Session memory storage failed", exc_info=True)
            return False
