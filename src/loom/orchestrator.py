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
        """
        config = self.agents.get(agent_name)
        model_string = f"{config.tier}/default"

        user_content = task
        if context:
            user_content = f"## Context from Previous Phases\n\n{context}\n\n## Current Task\n\n{task}"

        logger.info("Dispatching %s (tier=%s, temp=%.1f)", agent_name, config.tier, config.temperature)

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
            return response.choices[0].message.content
        except Exception as e:
            raise RuntimeError(
                f"Agent '{agent_name}' dispatch failed on {config.tier} tier: {e}"
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

    async def execute_swarm(self, task: str) -> SwarmPlan:
        """
        High-level entry point implementing the Blackboard SOP.

        Default 5-phase flow:
          1. OBSERVE  — Architect analyzes the task and project structure
          2. IDENTIFY — Security + Tester audit in parallel
          3. EVOLVE   — Coder implements based on all findings
          4. VALIDATE — Code reviewer checks the output
        """
        plan = SwarmPlan(
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

        return await self.execute_plan(plan)
