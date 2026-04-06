import asyncio
import logging
import os
import re
from dataclasses import dataclass, field

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


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

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=model_string,
                    messages=[
                        {"role": "system", "content": config.methodology},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=config.temperature,
                    timeout=config.timeout_mins * 60,
                )
                result = response.choices[0].message.content
                if not result:
                    raise RuntimeError(f"Agent '{agent_name}' returned empty response")
                return result
            except Exception as e:
                last_error = e
                if attempt < self.max_retries:
                    logger.warning(
                        "Agent '%s' dispatch attempt %d/%d failed: %s",
                        agent_name, attempt + 1, self.max_retries + 1, e,
                    )
                    continue
                break

        raise RuntimeError(
            f"Agent '{agent_name}' dispatch failed after {self.max_retries + 1} attempts "
            f"on {config.tier} tier (model={model_string}): {last_error}"
        ) from last_error

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

    async def _execute_phase(self, plan: SwarmPlan, phase: Phase) -> None:
        """
        Executes a single phase: dispatches the agent, parses the handoff
        response, and updates phase state. Retries up to max_retries on failure.
        """
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
            phase.status = "completed"

            logger.info("Phase %d (%s) completed by %s", phase.id, phase.name, phase.agent)

        except Exception as e:
            phase.retry_count += 1
            if phase.retry_count <= self.max_retries:
                logger.warning(
                    "Phase %d failed (attempt %d/%d): %s",
                    phase.id, phase.retry_count, self.max_retries, e,
                )
                phase.status = "pending"
            else:
                phase.status = "failed"
                logger.error("Phase %d failed permanently: %s", phase.id, e)
                raise

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

        await self.memory.build_indices_and_constraints()

        while True:
            ready = self._get_ready_phases(plan)
            if not ready:
                break

            parallel_batch = [p for p in ready if p.parallel]
            sequential = [p for p in ready if not p.parallel]

            if parallel_batch:
                logger.info("Dispatching parallel batch: %s", [p.name for p in parallel_batch])
                tasks = [self._execute_phase(plan, p) for p in parallel_batch]
                await asyncio.gather(*tasks, return_exceptions=True)
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

        logger.info("Plan execution complete: all %d phases succeeded", len(plan.phases))
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
    }

    # Plan types that can append an extra test phase when "test" keywords
    # co-occur with another primary plan type.
    _TEST_APPENDABLE_PLANS = {"debug", "build", "refactor", "document"}

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
        plan = self.craft_plan(task)
        return await self.execute_plan(plan)
