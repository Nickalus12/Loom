import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

try:
    from loom.telemetry import get_telemetry as _get_telemetry
except ImportError:
    _get_telemetry = None  # type: ignore[assignment]


@dataclass
class Phase:
    id: int
    name: str
    agent: str
    objective: str
    parallel: bool = False
    blocked_by: list[int] = field(default_factory=list)
    status: str = "pending"
    result: str = ""
    task_report: dict = field(default_factory=dict)
    downstream_context: dict = field(default_factory=dict)
    files_created: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    retry_count: int = 0


@dataclass
class SwarmPlan:
    task: str
    phases: list[Phase]


class LoomOrchestrator:
    def __init__(self, memory_engine, agent_registry, proxy_base: str = "http://localhost:4000/v1"):
        self.proxy_base = proxy_base
        self.memory = memory_engine
        self.agents = agent_registry
        self.max_retries = 2
        self._client = AsyncOpenAI(
            base_url=proxy_base,
            api_key=os.getenv("LITELLM_MASTER_KEY", ""),
        )

    def _tel_inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        if _get_telemetry is None:
            return
        try:
            _get_telemetry().inc(name, value, **labels)
        except Exception:
            pass

    def _tel_observe(self, name: str, value: float, **labels: str) -> None:
        if _get_telemetry is None:
            return
        try:
            _get_telemetry().observe(name, value, **labels)
        except Exception:
            pass

    def _tel_wf_begin(self, name: str) -> None:
        if _get_telemetry is None:
            return
        try:
            _get_telemetry().waterfall.begin(name)
        except Exception:
            pass

    def _tel_wf_end(self) -> None:
        if _get_telemetry is None:
            return
        try:
            _get_telemetry().waterfall.end()
        except Exception:
            pass

    async def dispatch_agent(self, agent_name: str, task: str, context: str = "") -> str:
        """
        Dispatches an agent through the LiteLLM proxy using its registry definition.
        The agent's methodology is loaded as the system prompt, and its tier,
        temperature, and timeout are sourced from the registry frontmatter.

        Model resolution order:
        1. Agent frontmatter `model` field (explicit override)
        2. `{tier}/default` routing via LiteLLM proxy (with fallback chain)
        """
        config = self.agents.get(agent_name)
        model_string = config.model if config.model else f"{config.tier}/default"

        user_content = task
        if context:
            user_content = f"## Context from Previous Phases\n\n{context}\n\n## Current Task\n\n{task}"

        logger.info(
            "Dispatching %s (tier=%s, model=%s, temp=%.1f)",
            agent_name, config.tier, model_string, config.temperature,
        )

        messages = [
            {"role": "system", "content": config.methodology},
            {"role": "user", "content": user_content},
        ]
        input_tokens_est = sum(len(m.get("content", "")) // 4 for m in messages)

        # Single attempt — phase-level retries in _execute_phase handle transient failures.
        # Dual-layer retry previously caused up to (max_retries+1)^2 API calls per failure.
        call_start = time.monotonic()
        self._tel_inc("orch_agent_calls_total", agent=agent_name, tier=config.tier)
        try:
            response = await self._client.chat.completions.create(
                model=model_string,
                messages=messages,
                temperature=config.temperature,
                timeout=config.timeout_mins * 60,
            )
            result = response.choices[0].message.content
            if not result:
                raise RuntimeError(f"Agent '{agent_name}' returned empty response")

            call_elapsed = time.monotonic() - call_start
            self._tel_observe("orch_agent_call_duration_seconds", call_elapsed, agent=agent_name)

            usage = getattr(response, "usage", None)
            if usage:
                self._tel_inc("orch_tokens_input", value=float(getattr(usage, "prompt_tokens", input_tokens_est)), agent=agent_name)
                self._tel_inc("orch_tokens_output", value=float(getattr(usage, "completion_tokens", len(result) // 4)), agent=agent_name)
            else:
                self._tel_inc("orch_tokens_input", value=float(input_tokens_est), agent=agent_name)
                self._tel_inc("orch_tokens_output", value=float(len(result) // 4), agent=agent_name)

            return result
        except Exception as e:
            self._tel_inc("orch_agent_call_errors", agent=agent_name)
            raise RuntimeError(
                f"Agent '{agent_name}' dispatch failed on {config.tier} tier "
                f"(model={model_string}): {e}"
            ) from e

    def _parse_handoff(self, response: str) -> dict:
        """
        Parses Task Report and Downstream Context from an agent's response.
        Returns a dict with keys: raw, task_report, downstream_context.
        Extracts status, files_created, and files_modified from the Task Report section.
        Handles both single-line and multi-line (bulleted) file lists.
        """
        result = {"raw": response, "task_report": {}, "downstream_context": {}}

        tr_match = re.search(
            r'##?\s*Task Report\s*\n(.*?)(?=##?\s*Downstream Context|$)',
            response,
            re.DOTALL,
        )
        if tr_match:
            tr_text = tr_match.group(1)
            result["task_report"]["text"] = tr_text.strip()

            status_match = re.search(r'\*\*Status\*\*:\s*(\w+)', tr_text)
            if status_match:
                result["task_report"]["status"] = status_match.group(1)

            result["task_report"]["files_created"] = self._extract_file_list(tr_text, "Files Created")
            result["task_report"]["files_modified"] = self._extract_file_list(tr_text, "Files Modified")

        dc_match = re.search(
            r'##?\s*Downstream Context\s*\n(.*?)$',
            response,
            re.DOTALL,
        )
        if dc_match:
            result["downstream_context"]["text"] = dc_match.group(1).strip()

        return result

    @staticmethod
    def _extract_file_list(text: str, header: str) -> list[str]:
        r"""Extract backtick-quoted file paths from a section starting with bold header.

        Handles both single-line (``**Files Created**: `a.py`, `b.py```)
        and multi-line bulleted lists.
        """
        # Find the section: from **header**: to the next **bold**: header or end
        section_match = re.search(
            rf'\*\*{re.escape(header)}\*\*:\s*(.*?)(?=\n-?\s*\*\*[A-Z]|\Z)',
            text,
            re.DOTALL,
        )
        if not section_match:
            return []
        section = section_match.group(1)
        return re.findall(r'`([^`]+)`', section)

    def _build_context_chain(self, plan: SwarmPlan, phase: Phase) -> str:
        """
        Builds accumulated context from completed dependency phases.
        Each dependency's Downstream Context section is included with its
        phase number, name, and agent attribution.
        """
        context_parts: list[str] = []
        for dep_id in phase.blocked_by:
            dep_phase = next((p for p in plan.phases if p.id == dep_id), None)
            if dep_phase and dep_phase.status == "completed" and dep_phase.downstream_context:
                dc_text = dep_phase.downstream_context.get("text", "")
                if dc_text:
                    context_parts.append(
                        f"### Phase {dep_phase.id}: {dep_phase.name} ({dep_phase.agent})\n{dc_text}"
                    )

        if not context_parts:
            return ""
        return "\n\n".join(context_parts)

    def _get_ready_phases(self, plan: SwarmPlan) -> list[Phase]:
        """
        Returns phases whose status is pending and whose dependencies
        have all completed.
        """
        completed_ids = {p.id for p in plan.phases if p.status == "completed"}
        ready: list[Phase] = []
        for phase in plan.phases:
            if phase.status != "pending":
                continue
            if all(dep_id in completed_ids for dep_id in phase.blocked_by):
                ready.append(phase)
        return ready

    # Agents whose text responses should be parsed for file writes
    _WRITING_AGENTS = {"coder", "refactor", "devops_engineer", "data_engineer", "technical_writer"}

    def _extract_and_write_files(self, response: str) -> list[str]:
        """Parse a coder agent response for code blocks and write them to disk.

        Handles these markdown patterns:
          1. ### `path/to/file.py` or **`path/to/file.py`** before a code block
          2. # filepath: path  or  # path  as first line inside a code block
          3. <file path="...">...</file> XML blocks
          4. Write-LoomFile 'path' 'content' PowerShell commands in code blocks
        """
        import os
        written: list[str] = []

        # Pattern 1: header line immediately before a fenced code block
        # Matches:  ### `path`   **`path`**   **path**   ### path
        header_block = re.compile(
            r'(?:^|\n)'
            r'(?:#{1,4}\s*|(?:\*\*)+)'          # ### or **
            r'[`\'"]?([^\n`\'"]+?\.[\w]+)[`\'"]?' # filename with extension
            r'(?:\*\*)?[:\s]*\n'                  # optional colon/spaces
            r'```[\w]*\n(.*?)```',                # code block
            re.DOTALL | re.MULTILINE,
        )
        for m in header_block.finditer(response):
            path_raw, content = m.group(1).strip(), m.group(2)
            written += self._write_file_safe(path_raw, content)

        # Pattern 2: # filepath: path  or  # file: path  as first line inside block
        inline_path = re.compile(
            r'```[\w]*\n'
            r'(?:#\s*(?:filepath|file|path|filename)[:\s]+([^\n]+)\n)'
            r'(.*?)```',
            re.DOTALL,
        )
        already = {w.replace("\\", "/") for w in written}
        for m in inline_path.finditer(response):
            path_raw, content = m.group(1).strip(), m.group(2)
            if path_raw.replace("\\", "/") not in already:
                written += self._write_file_safe(path_raw, content)

        # Pattern 3: Write-LoomFile 'path' 'content' (PS command in response)
        ps_write = re.compile(
            r"Write-LoomFile\s+'([^']+)'\s+'((?:[^']|'')*)'",
            re.DOTALL,
        )
        for m in ps_write.finditer(response):
            path_raw = m.group(1).strip()
            content = m.group(2).replace("''", "'")
            if path_raw.replace("\\", "/") not in {w.replace("\\", "/") for w in written}:
                written += self._write_file_safe(path_raw, content)

        if written:
            logger.info("Cloud coder wrote %d file(s): %s", len(written), written)
        return written

    def _write_file_safe(self, path_raw: str, content: str) -> list[str]:
        """Resolve a path relative to LOOM_ALLOWED_ROOT and write it safely."""
        import os
        from pathlib import Path

        # Skip paths that look like examples or comments
        if any(x in path_raw.lower() for x in ("example", "placeholder", "...", "<", ">")):
            return []
        # Skip very short paths (likely not real files)
        if len(path_raw) < 4 or "." not in path_raw:
            return []

        allowed_root = os.getenv("LOOM_ALLOWED_ROOT", os.getcwd())
        try:
            p = Path(path_raw)
            if not p.is_absolute():
                p = Path(allowed_root) / p
            p = p.resolve()
            # Safety: must be within allowed root
            if not str(p).startswith(str(Path(allowed_root).resolve())):
                logger.warning("Skipping write outside allowed root: %s", p)
                return []
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            logger.info("Cloud coder wrote: %s (%d bytes)", p, len(content))
            return [str(p)]
        except Exception as exc:
            logger.warning("Failed to write %s: %s", path_raw, exc)
            return []

    async def _execute_phase(self, plan: SwarmPlan, phase: Phase) -> None:
        """
        Executes a single phase: dispatches the agent, parses the handoff
        response, and updates phase state. Retries up to max_retries on failure.
        """
        span_name = f"phase_{phase.id}:{phase.name}[{phase.agent}]"
        self._tel_wf_begin(span_name)
        phase_start = time.monotonic()
        phase.status = "in_progress"
        context = self._build_context_chain(plan, phase)

        prompt = f"## Objective\n\n{phase.objective}\n\n## Task\n\n{plan.task}"

        try:
            response = await self.dispatch_agent(phase.agent, prompt, context)
            handoff = self._parse_handoff(response)

            phase.result = response
            phase.task_report = handoff["task_report"]
            phase.downstream_context = handoff["downstream_context"]
            phase.files_created = handoff["task_report"].get("files_created", [])
            phase.files_modified = handoff["task_report"].get("files_modified", [])

            # For writing agents in cloud mode: extract code blocks and write to disk
            if phase.agent in self._WRITING_AGENTS:
                actually_written = self._extract_and_write_files(response)
                if actually_written:
                    # Merge with any paths the agent declared in its Task Report
                    declared = set(phase.files_created + phase.files_modified)
                    for path in actually_written:
                        if path not in declared:
                            phase.files_created.append(path)

            phase.status = "completed"

            phase_elapsed = time.monotonic() - phase_start
            self._tel_observe("orch_phase_duration_seconds", phase_elapsed, agent=phase.agent, phase=phase.name)
            self._tel_inc("orch_phases_completed", agent=phase.agent)
            self._tel_inc("orch_files_created", value=float(len(phase.files_created)))
            self._tel_inc("orch_files_modified", value=float(len(phase.files_modified)))
            logger.info("Phase %d (%s) completed by %s in %.1fs", phase.id, phase.name, phase.agent, phase_elapsed)

        except Exception as e:
            phase.retry_count += 1
            self._tel_inc("orch_phase_retries" if phase.retry_count <= self.max_retries else "orch_phases_failed", agent=phase.agent)
            if phase.retry_count <= self.max_retries:
                logger.warning(
                    "Phase %d failed (attempt %d/%d): %s",
                    phase.id, phase.retry_count, self.max_retries, e,
                )
                phase.status = "pending"
            else:
                phase.status = "failed"
                logger.error("Phase %d failed permanently: %s", phase.id, e)
                self._tel_wf_end()
                raise
        finally:
            if phase.status in ("completed", "pending"):
                self._tel_wf_end()

    def validate_plan(self, plan: SwarmPlan) -> list[str]:
        """
        Validates a plan before execution. Returns a list of error messages.
        Empty list means the plan is valid.
        """
        errors: list[str] = []
        phase_ids = [p.id for p in plan.phases]

        # Duplicate IDs
        seen_ids: set[int] = set()
        for pid in phase_ids:
            if pid in seen_ids:
                errors.append(f"Duplicate phase ID: {pid}")
            seen_ids.add(pid)

        # Missing agents
        for phase in plan.phases:
            if phase.agent not in self.agents:
                errors.append(f"Phase {phase.id}: agent '{phase.agent}' not found in registry")

        # Missing dependencies
        id_set = set(phase_ids)
        for phase in plan.phases:
            for dep_id in phase.blocked_by:
                if dep_id not in id_set:
                    errors.append(f"Phase {phase.id}: blocked_by references non-existent phase {dep_id}")

        # Cycle detection via topological sort
        in_degree = {p.id: len(p.blocked_by) for p in plan.phases}
        adj: dict[int, list[int]] = {p.id: [] for p in plan.phases}
        for phase in plan.phases:
            for dep_id in phase.blocked_by:
                if dep_id in adj:
                    adj[dep_id].append(phase.id)

        queue = [pid for pid, deg in in_degree.items() if deg == 0]
        visited = 0
        while queue:
            current = queue.pop(0)
            visited += 1
            for neighbor in adj.get(current, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if visited < len(plan.phases):
            errors.append("Dependency cycle detected — plan cannot be executed")

        return errors

    async def execute_plan(self, plan: SwarmPlan) -> SwarmPlan:
        """
        Executes a full phase plan with dependency resolution and parallel batching.
        Phases are executed in dependency order. Phases at the same depth with
        parallel=True run concurrently via asyncio.gather.
        """
        validation_errors = self.validate_plan(plan)
        if validation_errors:
            raise ValueError(f"Invalid plan: {'; '.join(validation_errors)}")

        logger.info("Executing plan: %s (%d phases)", plan.task, len(plan.phases))
        self._tel_inc("orch_plans_started")
        plan_start = time.monotonic()

        await self.memory.build_indices_and_constraints()

        while True:
            ready = self._get_ready_phases(plan)
            if not ready:
                # Deadlock detection: phases stuck in_progress with no ready work
                in_progress = [p for p in plan.phases if p.status == "in_progress"]
                pending = [p for p in plan.phases if p.status == "pending"]
                if in_progress or pending:
                    stuck = [f"{p.id}:{p.name}({p.status})" for p in in_progress + pending]
                    raise RuntimeError(f"Plan deadlocked — phases not completing: {stuck}")
                break

            parallel_batch = [p for p in ready if p.parallel]
            sequential = [p for p in ready if not p.parallel]

            if parallel_batch:
                logger.info("Dispatching parallel batch: %s", [p.name for p in parallel_batch])
                self._tel_inc("orch_parallel_batches")
                tasks = [self._execute_phase(plan, p) for p in parallel_batch]
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for r in results:
                    if isinstance(r, BaseException):
                        raise RuntimeError(f"Parallel phase raised: {r}") from r
                for p in parallel_batch:
                    if p.status == "failed":
                        raise RuntimeError(f"Phase {p.id} ({p.name}) failed permanently")

            for phase in sequential:
                await self._execute_phase(plan, phase)
                if phase.status == "failed":
                    raise RuntimeError(f"Phase {phase.id} ({phase.name}) failed permanently")

        failed = [p for p in plan.phases if p.status != "completed"]
        if failed:
            names = [f"{p.id}:{p.name}" for p in failed]
            raise RuntimeError(f"Plan incomplete — failed phases: {names}")

        plan_elapsed = time.monotonic() - plan_start
        self._tel_observe("orch_plan_duration_seconds", plan_elapsed)
        self._tel_inc("orch_plans_completed")
        logger.info("Plan execution complete: all %d phases succeeded in %.1fs", len(plan.phases), plan_elapsed)
        return plan

    # Keyword groups with associated weights.  Each group maps a plan type
    # to a dict of ``{keyword: weight}``.  When ``craft_plan`` is called the
    # task text is scanned against every keyword in every group and a total
    # score is accumulated per plan type.  The highest-scoring group wins.
    # "build" acts as the default when no other group scores above zero.
    KEYWORD_GROUPS: dict[str, dict[str, float]] = {
        "review": {
            "review": 3.0,
            "audit": 3.0,
            "inspect": 2.0,
            "evaluate": 1.5,
            "assess": 1.5,
            "check": 1.0,
        },
        "debug": {
            "fix": 3.0,
            "bug": 3.0,
            "debug": 3.0,
            "error": 2.0,
            "crash": 2.5,
            "broken": 2.0,
            "issue": 1.5,
            "fault": 1.5,
            "patch": 2.0,
        },
        "refactor": {
            "refactor": 3.0,
            "restructure": 2.5,
            "reorganize": 2.0,
            "simplify": 1.5,
            "clean up": 2.0,
            "cleanup": 2.0,
            "deduplicate": 1.5,
        },
        "test": {
            "test": 3.0,
            "tests": 3.0,
            "testing": 2.5,
            "coverage": 2.0,
            "spec": 1.5,
            "unit test": 3.0,
            "integration test": 3.0,
            "e2e": 2.0,
        },
        "document": {
            "document": 3.0,
            "documentation": 3.0,
            "docs": 2.5,
            "docstring": 2.5,
            "readme": 2.0,
            "explain": 1.5,
            "annotate": 1.5,
            "api docs": 3.0,
        },
        "build": {
            "build": 2.0,
            "add": 1.5,
            "implement": 2.5,
            "create": 2.0,
            "develop": 1.5,
            "feature": 1.5,
            "new": 1.0,
        },
        "optimize": {
            "optimize": 3.0,
            "performance": 3.0,
            "slow": 2.5,
            "speed up": 2.5,
            "bottleneck": 2.5,
            "latency": 2.0,
            "memory": 2.0,
            "profile": 2.0,
            "benchmark": 2.0,
            "efficient": 1.5,
        },
        "deploy": {
            "deploy": 3.0,
            "deployment": 3.0,
            "ci/cd": 3.0,
            "pipeline": 2.5,
            "docker": 2.5,
            "kubernetes": 2.5,
            "release": 2.0,
            "publish": 2.0,
            "ship": 1.5,
            "infrastructure": 2.0,
            "terraform": 2.5,
            "github actions": 2.5,
        },
    }

    # Plan types that can append an extra test phase when "test" keywords
    # co-occur with another primary plan type.
    _TEST_APPENDABLE_PLANS = {"debug", "build", "refactor", "document", "optimize"}

    def _score_keyword_groups(self, task: str) -> dict[str, float]:
        """Score each keyword group against *task* and return the totals."""
        task_lower = task.lower()
        scores: dict[str, float] = {}
        for group_name, keywords in self.KEYWORD_GROUPS.items():
            total = 0.0
            for keyword, weight in keywords.items():
                if keyword in task_lower:
                    total += weight
            scores[group_name] = total
        return scores

    def craft_plan(self, task: str) -> SwarmPlan:
        """Create a task-appropriate phase plan based on weighted keyword analysis.

        Each keyword group (review, debug, refactor, test, document, build)
        has multiple keywords with numeric weights.  The task is scored
        against every group and the highest-scoring group selects the plan.
        If no group scores above zero, the *build* pipeline is chosen as
        the default.

        Combined keywords are supported: when the winning plan type is in
        ``_TEST_APPENDABLE_PLANS`` **and** the "test" group also scores
        above zero (but is not the winner), an extra test-verification
        phase is appended to the plan.
        """
        scores = self._score_keyword_groups(task)

        # Pick the winning plan type (highest score, "build" as default)
        best_type = max(scores, key=lambda k: scores[k])
        if scores[best_type] == 0:
            best_type = "build"

        plan_map = {
            "review": self._plan_review,
            "debug": self._plan_debug,
            "refactor": self._plan_refactor,
            "test": self._plan_test,
            "document": self._plan_document,
            "build": self._plan_build,
            "optimize": self._plan_optimize,
            "deploy": self._plan_deploy,
        }

        plan = plan_map[best_type](task)

        # Combined keyword support: append a test phase when test keywords
        # are present but test is not the primary plan.
        if (
            best_type in self._TEST_APPENDABLE_PLANS
            and scores.get("test", 0) > 0
            and best_type != "test"
        ):
            max_id = max(p.id for p in plan.phases)
            last_id = max_id
            plan.phases.append(
                Phase(
                    id=max_id + 1,
                    name="Test Verification",
                    agent="tester",
                    objective=(
                        "Write and run tests to verify the changes. "
                        "Cover edge cases and ensure no regressions."
                    ),
                    blocked_by=[last_id],
                )
            )

        return plan

    def _plan_review(self, task: str) -> SwarmPlan:
        return SwarmPlan(
            task=task,
            phases=[
                Phase(
                    id=1,
                    name="Architecture Analysis",
                    agent="architect",
                    objective=(
                        "Analyze the project structure and codebase relevant to the review. "
                        "Identify key files, dependencies, and areas of concern."
                    ),
                ),
                Phase(
                    id=2,
                    name="Code Review",
                    agent="code_reviewer",
                    objective=(
                        "Perform a thorough review of the codebase for correctness, security, performance, "
                        "and adherence to project conventions. Classify findings as Critical/Major/Minor/Suggestion."
                    ),
                    blocked_by=[1],
                ),
                Phase(
                    id=3,
                    name="Summary",
                    agent="architect",
                    objective=(
                        "Synthesize review findings into an actionable summary with prioritized recommendations."
                    ),
                    blocked_by=[2],
                ),
            ],
        )

    def _plan_debug(self, task: str) -> SwarmPlan:
        return SwarmPlan(
            task=task,
            phases=[
                Phase(
                    id=1,
                    name="Bug Analysis",
                    agent="debugger",
                    objective=(
                        "Investigate the reported issue. Reproduce the bug, identify root cause, "
                        "and propose a fix strategy with affected files."
                    ),
                ),
                Phase(
                    id=2,
                    name="Implementation",
                    agent="coder",
                    objective=(
                        "Implement the fix based on the debugger's analysis. "
                        "Follow established code patterns and conventions."
                    ),
                    blocked_by=[1],
                ),
                Phase(
                    id=3,
                    name="Test Verification",
                    agent="tester",
                    objective=(
                        "Verify the fix resolves the issue. Write regression tests to prevent recurrence. "
                        "Check for side effects in related code paths."
                    ),
                    blocked_by=[2],
                ),
                Phase(
                    id=4,
                    name="Code Review",
                    agent="code_reviewer",
                    objective=(
                        "Review the fix for correctness, security, and adherence to project conventions. "
                        "Classify findings as Critical/Major/Minor/Suggestion."
                    ),
                    blocked_by=[3],
                ),
            ],
        )

    def _plan_refactor(self, task: str) -> SwarmPlan:
        return SwarmPlan(
            task=task,
            phases=[
                Phase(
                    id=1,
                    name="Architecture Analysis",
                    agent="architect",
                    objective=(
                        "Analyze the current structure and propose a refactoring plan. "
                        "Identify code smells, coupling issues, and improvement opportunities."
                    ),
                ),
                Phase(
                    id=2,
                    name="Refactoring",
                    agent="refactor",
                    objective=(
                        "Execute the refactoring plan. Apply structural improvements while "
                        "preserving external behavior and maintaining test coverage."
                    ),
                    blocked_by=[1],
                ),
                Phase(
                    id=3,
                    name="Test Verification",
                    agent="tester",
                    objective=(
                        "Verify that all existing tests still pass after refactoring. "
                        "Add tests for any newly exposed interfaces or edge cases."
                    ),
                    blocked_by=[2],
                ),
                Phase(
                    id=4,
                    name="Code Review",
                    agent="code_reviewer",
                    objective=(
                        "Review refactored code for correctness, clarity, and adherence to conventions. "
                        "Verify no behavioral regressions were introduced."
                    ),
                    blocked_by=[3],
                ),
            ],
        )

    def _plan_build(self, task: str) -> SwarmPlan:
        return SwarmPlan(
            task=task,
            phases=[
                Phase(
                    id=1,
                    name="Architecture Analysis",
                    agent="architect",
                    objective=(
                        "Analyze the project structure and create an architectural plan for the task. "
                        "Identify key files, dependencies, integration points, and propose an implementation approach."
                    ),
                ),
                Phase(
                    id=2,
                    name="Security Audit",
                    agent="security_engineer",
                    objective=(
                        "Review the architect's plan and the relevant codebase for security vulnerabilities. "
                        "Identify injection risks, authentication gaps, data exposure, and insecure patterns. "
                        "Report findings with severity levels."
                    ),
                    parallel=True,
                    blocked_by=[1],
                ),
                Phase(
                    id=3,
                    name="Quality Audit",
                    agent="tester",
                    objective=(
                        "Review the architect's plan for testability concerns. "
                        "Identify edge cases, missing error handling, and areas that need test coverage. "
                        "Propose a test strategy."
                    ),
                    parallel=True,
                    blocked_by=[1],
                ),
                Phase(
                    id=4,
                    name="Implementation",
                    agent="coder",
                    objective=(
                        "Implement the task based on the architect's plan, incorporating security and quality findings. "
                        "Follow established code patterns and conventions."
                    ),
                    blocked_by=[2, 3],
                ),
                Phase(
                    id=5,
                    name="Code Review",
                    agent="code_reviewer",
                    objective=(
                        "Review all code changes for correctness, security, performance, and adherence to project conventions. "
                        "Classify findings as Critical/Major/Minor/Suggestion."
                    ),
                    blocked_by=[4],
                ),
            ],
        )

    def _plan_test(self, task: str) -> SwarmPlan:
        return SwarmPlan(
            task=task,
            phases=[
                Phase(
                    id=1,
                    name="Test Design",
                    agent="tester",
                    objective=(
                        "Analyze the codebase and design a comprehensive test strategy. "
                        "Identify units, integration points, and edge cases that need coverage."
                    ),
                ),
                Phase(
                    id=2,
                    name="Test Implementation",
                    agent="coder",
                    objective=(
                        "Implement the test suite based on the tester's strategy. "
                        "Write unit tests, integration tests, and fixtures as specified."
                    ),
                    blocked_by=[1],
                ),
                Phase(
                    id=3,
                    name="Test Review",
                    agent="code_reviewer",
                    objective=(
                        "Review the test suite for completeness, correctness, and best practices. "
                        "Verify edge cases are covered and assertions are meaningful."
                    ),
                    blocked_by=[2],
                ),
            ],
        )

    def _plan_document(self, task: str) -> SwarmPlan:
        return SwarmPlan(
            task=task,
            phases=[
                Phase(
                    id=1,
                    name="Documentation",
                    agent="technical_writer",
                    objective=(
                        "Analyze the codebase and produce clear, comprehensive documentation. "
                        "Include API references, usage examples, and architecture overviews as appropriate."
                    ),
                ),
                Phase(
                    id=2,
                    name="Documentation Review",
                    agent="code_reviewer",
                    objective=(
                        "Review the documentation for technical accuracy, completeness, and clarity. "
                        "Verify code examples are correct and API references match the implementation."
                    ),
                    blocked_by=[1],
                ),
            ],
        )

    def _plan_optimize(self, task: str) -> SwarmPlan:
        return SwarmPlan(
            task=task,
            phases=[
                Phase(
                    id=1,
                    name="Performance Analysis",
                    agent="performance_engineer",
                    objective=(
                        "Profile the relevant code paths and identify bottlenecks. "
                        "Measure baseline metrics: latency, throughput, memory usage. "
                        "Rank issues by impact and propose specific optimizations."
                    ),
                ),
                Phase(
                    id=2,
                    name="Implementation",
                    agent="coder",
                    objective=(
                        "Implement the performance optimizations identified by the analysis. "
                        "Apply changes incrementally, preserving correctness. "
                        "Add benchmarks or measurements to quantify improvement."
                    ),
                    blocked_by=[1],
                ),
                Phase(
                    id=3,
                    name="Verification",
                    agent="performance_engineer",
                    objective=(
                        "Verify the optimizations achieve the expected improvement. "
                        "Compare before/after metrics and confirm no regressions were introduced."
                    ),
                    blocked_by=[2],
                ),
            ],
        )

    def _plan_deploy(self, task: str) -> SwarmPlan:
        return SwarmPlan(
            task=task,
            phases=[
                Phase(
                    id=1,
                    name="Infrastructure Analysis",
                    agent="architect",
                    objective=(
                        "Analyze the deployment requirements and current infrastructure. "
                        "Identify the target environment, dependencies, and deployment strategy."
                    ),
                ),
                Phase(
                    id=2,
                    name="Security Review",
                    agent="security_engineer",
                    objective=(
                        "Review the deployment configuration for security risks: exposed secrets, "
                        "overly permissive IAM, insecure defaults, and supply chain risks."
                    ),
                    parallel=True,
                    blocked_by=[1],
                ),
                Phase(
                    id=3,
                    name="DevOps Implementation",
                    agent="devops_engineer",
                    objective=(
                        "Implement the deployment pipeline, infrastructure configuration, "
                        "and automation scripts based on the architect's plan and security findings. "
                        "Include health checks, rollback procedures, and monitoring setup."
                    ),
                    blocked_by=[1, 2],
                ),
                Phase(
                    id=4,
                    name="Review",
                    agent="code_reviewer",
                    objective=(
                        "Review all infrastructure code and pipeline configuration for correctness, "
                        "security, and adherence to infrastructure-as-code best practices."
                    ),
                    blocked_by=[3],
                ),
            ],
        )

    def plan_summary(self, plan: SwarmPlan) -> str:
        """Return a human-readable summary of a SwarmPlan.

        The summary includes the task description, the number of phases,
        and a numbered list of each phase with its agent and status.
        Dependency relationships are noted in parentheses.
        """
        lines: list[str] = []
        lines.append(f"Plan: {plan.task}")
        lines.append(f"Phases: {len(plan.phases)}")
        lines.append("")

        for phase in plan.phases:
            dep_info = ""
            if phase.blocked_by:
                dep_names = []
                for dep_id in phase.blocked_by:
                    dep_phase = next((p for p in plan.phases if p.id == dep_id), None)
                    dep_names.append(dep_phase.name if dep_phase else f"#{dep_id}")
                dep_info = f" (after {', '.join(dep_names)})"

            status_marker = {
                "pending": "[ ]",
                "in_progress": "[~]",
                "completed": "[x]",
                "failed": "[!]",
            }.get(phase.status, "[?]")

            lines.append(
                f"  {status_marker} {phase.id}. {phase.name} [{phase.agent}]{dep_info}"
            )

        return "\n".join(lines)

    async def execute_swarm(self, task: str) -> SwarmPlan:
        """
        High-level entry point implementing the Blackboard SOP.

        Uses craft_plan() to select the appropriate phase pipeline based on
        task keywords, then executes it via execute_plan().
        """
        self._tel_wf_begin(f"swarm:{task[:50]}")
        try:
            plan = self.craft_plan(task)
            self._tel_inc("orch_swarm_phases_planned", value=float(len(plan.phases)))
            return await self.execute_plan(plan)
        finally:
            self._tel_wf_end()
