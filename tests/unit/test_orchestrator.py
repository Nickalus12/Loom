"""Unit tests for LoomOrchestrator with mocked OpenAI client."""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from loom.orchestrator import LoomOrchestrator, Phase, SwarmPlan
from loom.agent_registry import AgentConfig


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_agent_config(name="test_agent", tier="heavy", temperature=0.2, timeout_mins=5):
    return AgentConfig(
        name=name,
        description=f"Test {name}",
        tools=["read_file"],
        temperature=temperature,
        max_turns=15,
        timeout_mins=timeout_mins,
        tier=tier,
        model="",
        methodology=f"You are {name}. Do your job.",
    )


@pytest.fixture
def mock_registry():
    """Mock AgentRegistry that returns configs for known agents."""
    configs = {
        "architect": _make_agent_config("architect", "heavy", 0.3, 5),
        "security_engineer": _make_agent_config("security_engineer", "heavy", 0.2, 8),
        "tester": _make_agent_config("tester", "light", 0.2, 10),
        "coder": _make_agent_config("coder", "heavy", 0.2, 10),
        "code_reviewer": _make_agent_config("code_reviewer", "light", 0.2, 5),
    }
    reg = MagicMock()
    reg.get = MagicMock(side_effect=lambda name: configs[name])
    reg.list_agents = MagicMock(return_value=sorted(configs.keys()))
    reg.__len__ = MagicMock(return_value=len(configs))
    reg.__contains__ = MagicMock(side_effect=lambda name: name in configs)
    return reg


@pytest.fixture
def mock_memory(mock_graphiti):
    """Create a mock memory engine."""
    from loom.memory_engine import LoomSwarmMemory
    return LoomSwarmMemory(graphiti=mock_graphiti)


def _make_llm_response(content: str) -> MagicMock:
    """Helper to build a mock OpenAI chat completion response."""
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


def _make_mock_client(content: str = "ok") -> AsyncMock:
    """Create a mock AsyncOpenAI client with chat.completions.create mocked."""
    client = AsyncMock()
    client.chat.completions.create = AsyncMock(return_value=_make_llm_response(content))
    return client


@pytest.fixture
def orchestrator(mock_memory, mock_registry):
    """Create a LoomOrchestrator with mock memory, registry, and OpenAI client."""
    orch = LoomOrchestrator(mock_memory, mock_registry)
    orch._client = _make_mock_client()
    return orch


AGENT_RESPONSE = """Done.

## Task Report
- **Status**: success
- **Objective Achieved**: Completed the task.
- **Files Created**: `src/new.py`
- **Files Modified**: `src/existing.py`

## Downstream Context
- **Key Interfaces Introduced**: NewService class in src/new.py
- **Patterns Established**: Repository pattern
"""


# ---------------------------------------------------------------------------
# dispatch_agent tests
# ---------------------------------------------------------------------------


class TestDispatchAgent:
    """Verify dispatch_agent calls the OpenAI client with agent config from registry."""

    @pytest.mark.asyncio
    async def test_dispatch_agent_success(self, orchestrator):
        """Should return the LLM response content on success."""
        orchestrator._client = _make_mock_client("Architect plan complete.")

        result = await orchestrator.dispatch_agent("architect", "Design the system.")

        assert result == "Architect plan complete."
        orchestrator._client.chat.completions.create.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_dispatch_agent_failure(self, orchestrator):
        """Should raise RuntimeError with agent name and tier when client fails."""
        orchestrator._client.chat.completions.create = AsyncMock(side_effect=Exception("Connection refused"))

        with pytest.raises(RuntimeError, match="architect.*heavy"):
            await orchestrator.dispatch_agent("architect", "Design the system.")

    @pytest.mark.asyncio
    async def test_dispatch_uses_agent_tier(self, orchestrator):
        """Should use the agent's tier from the registry for model string."""
        await orchestrator.dispatch_agent("tester", "Write tests.")

        call_kwargs = orchestrator._client.chat.completions.create.call_args.kwargs
        assert call_kwargs["model"] == "light/default"

    @pytest.mark.asyncio
    async def test_dispatch_uses_agent_temperature(self, orchestrator):
        """Should use the agent's temperature from the registry."""
        await orchestrator.dispatch_agent("architect", "Analyze.")

        call_kwargs = orchestrator._client.chat.completions.create.call_args.kwargs
        assert call_kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_dispatch_uses_agent_timeout(self, orchestrator):
        """Should convert timeout_mins to seconds."""
        await orchestrator.dispatch_agent("coder", "Build it.")

        call_kwargs = orchestrator._client.chat.completions.create.call_args.kwargs
        assert call_kwargs["timeout"] == 600  # 10 mins * 60

    @pytest.mark.asyncio
    async def test_dispatch_uses_methodology_as_system_prompt(self, orchestrator):
        """Should use the agent's methodology as the system prompt."""
        await orchestrator.dispatch_agent("architect", "Analyze.")

        messages = orchestrator._client.chat.completions.create.call_args.kwargs["messages"]
        assert messages[0]["role"] == "system"
        assert "You are architect" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_dispatch_includes_context(self, orchestrator):
        """Should include context in user message when provided."""
        await orchestrator.dispatch_agent("coder", "Build it.", context="Prior work done.")

        messages = orchestrator._client.chat.completions.create.call_args.kwargs["messages"]
        assert "Prior work done." in messages[1]["content"]
        assert "Build it." in messages[1]["content"]


# ---------------------------------------------------------------------------
# Handoff parsing tests
# ---------------------------------------------------------------------------


class TestParseHandoff:
    """Verify _parse_handoff extracts Task Report and Downstream Context."""

    def test_parse_full_handoff(self, orchestrator):
        result = orchestrator._parse_handoff(AGENT_RESPONSE)
        assert result["task_report"]["status"] == "success"
        assert "src/new.py" in result["task_report"]["files_created"]
        assert "NewService" in result["downstream_context"]["text"]

    def test_parse_missing_sections(self, orchestrator):
        result = orchestrator._parse_handoff("Just some text.")
        assert result["task_report"] == {}
        assert result["downstream_context"] == {}

    def test_parse_preserves_raw(self, orchestrator):
        result = orchestrator._parse_handoff("anything")
        assert result["raw"] == "anything"


# ---------------------------------------------------------------------------
# Phase dependency resolution
# ---------------------------------------------------------------------------


class TestDependencyResolution:
    """Verify _get_ready_phases and _build_context_chain."""

    def test_get_ready_no_deps(self, orchestrator):
        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="A", agent="architect", objective="Do A"),
            Phase(id=2, name="B", agent="coder", objective="Do B", blocked_by=[1]),
        ])
        assert [p.id for p in orchestrator._get_ready_phases(plan)] == [1]

    def test_get_ready_after_completion(self, orchestrator):
        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="A", agent="architect", objective="Do A", status="completed"),
            Phase(id=2, name="B", agent="coder", objective="Do B", blocked_by=[1]),
        ])
        assert [p.id for p in orchestrator._get_ready_phases(plan)] == [2]

    def test_parallel_both_ready(self, orchestrator):
        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="A", agent="architect", objective="Do A", status="completed"),
            Phase(id=2, name="B", agent="tester", objective="B", blocked_by=[1], parallel=True),
            Phase(id=3, name="C", agent="security_engineer", objective="C", blocked_by=[1], parallel=True),
        ])
        assert sorted(p.id for p in orchestrator._get_ready_phases(plan)) == [2, 3]

    def test_build_context_chain(self, orchestrator):
        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="Arch", agent="architect", objective="Analyze",
                  status="completed", downstream_context={"text": "Use Repository pattern."}),
            Phase(id=2, name="Code", agent="coder", objective="Build", blocked_by=[1]),
        ])
        assert "Repository pattern" in orchestrator._build_context_chain(plan, plan.phases[1])


# ---------------------------------------------------------------------------
# execute_plan tests
# ---------------------------------------------------------------------------


class TestExecutePlan:
    """Verify execute_plan runs phases in correct order."""

    @pytest.mark.asyncio
    async def test_execute_plan_sequential(self, orchestrator):
        orchestrator._client = _make_mock_client(AGENT_RESPONSE)

        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="Design", agent="architect", objective="Design"),
            Phase(id=2, name="Build", agent="coder", objective="Build", blocked_by=[1]),
        ])
        result = await orchestrator.execute_plan(plan)
        assert all(p.status == "completed" for p in result.phases)
        assert orchestrator._client.chat.completions.create.await_count == 2

    @pytest.mark.asyncio
    async def test_execute_plan_parallel_batch(self, orchestrator):
        orchestrator._client = _make_mock_client(AGENT_RESPONSE)

        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="Design", agent="architect", objective="Design"),
            Phase(id=2, name="Sec", agent="security_engineer", objective="Audit", parallel=True, blocked_by=[1]),
            Phase(id=3, name="Test", agent="tester", objective="Test", parallel=True, blocked_by=[1]),
            Phase(id=4, name="Build", agent="coder", objective="Build", blocked_by=[2, 3]),
        ])
        result = await orchestrator.execute_plan(plan)
        assert all(p.status == "completed" for p in result.phases)
        assert orchestrator._client.chat.completions.create.await_count == 4


# ---------------------------------------------------------------------------
# execute_swarm tests
# ---------------------------------------------------------------------------


class TestExecuteSwarm:
    """Verify execute_swarm creates a default plan and runs it."""

    @pytest.mark.asyncio
    async def test_execute_swarm_returns_plan(self, orchestrator):
        orchestrator._client = _make_mock_client(AGENT_RESPONSE)

        plan = await orchestrator.execute_swarm("Build a feature")
        assert isinstance(plan, SwarmPlan)
        assert len(plan.phases) == 5
        assert all(p.status == "completed" for p in plan.phases)

    @pytest.mark.asyncio
    async def test_execute_swarm_uses_all_agents(self, orchestrator):
        orchestrator._client = _make_mock_client(AGENT_RESPONSE)

        plan = await orchestrator.execute_swarm("Build a feature")
        assert {p.agent for p in plan.phases} == {"architect", "security_engineer", "tester", "coder", "code_reviewer"}

    @pytest.mark.asyncio
    async def test_execute_swarm_propagates_failure(self, orchestrator):
        orchestrator._client.chat.completions.create = AsyncMock(side_effect=Exception("LLM down"))

        with pytest.raises(RuntimeError):
            await orchestrator.execute_swarm("Build a feature")


# ---------------------------------------------------------------------------
# Plan validation tests
# ---------------------------------------------------------------------------


class TestValidatePlan:
    """Verify validate_plan catches invalid plans before execution."""

    def test_valid_plan(self, orchestrator):
        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="A", agent="architect", objective="Do A"),
            Phase(id=2, name="B", agent="coder", objective="Do B", blocked_by=[1]),
        ])
        assert orchestrator.validate_plan(plan) == []

    def test_duplicate_phase_ids(self, orchestrator):
        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="A", agent="architect", objective="Do A"),
            Phase(id=1, name="B", agent="coder", objective="Do B"),
        ])
        errors = orchestrator.validate_plan(plan)
        assert any("Duplicate phase ID" in e for e in errors)

    def test_missing_agent(self, orchestrator):
        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="A", agent="nonexistent_agent", objective="Do A"),
        ])
        errors = orchestrator.validate_plan(plan)
        assert any("not found in registry" in e for e in errors)

    def test_missing_dependency(self, orchestrator):
        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="A", agent="architect", objective="Do A", blocked_by=[99]),
        ])
        errors = orchestrator.validate_plan(plan)
        assert any("non-existent phase 99" in e for e in errors)

    def test_cycle_detection(self, orchestrator):
        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="A", agent="architect", objective="Do A", blocked_by=[2]),
            Phase(id=2, name="B", agent="coder", objective="Do B", blocked_by=[1]),
        ])
        errors = orchestrator.validate_plan(plan)
        assert any("cycle" in e.lower() for e in errors)

    @pytest.mark.asyncio
    async def test_execute_plan_rejects_invalid(self, orchestrator):
        """execute_plan should raise ValueError for invalid plans."""
        plan = SwarmPlan(task="test", phases=[
            Phase(id=1, name="A", agent="nonexistent", objective="Fail"),
        ])
        with pytest.raises(ValueError, match="Invalid plan"):
            await orchestrator.execute_plan(plan)


# ---------------------------------------------------------------------------
# Improved handoff parsing tests
# ---------------------------------------------------------------------------


class TestHandoffParsingMultiLine:
    """Verify _parse_handoff handles multi-line file lists."""

    def test_multiline_files_created(self, orchestrator):
        response = """## Task Report
- **Status**: success
- **Objective Achieved**: Done
- **Files Created**:
  - `src/auth.py` — auth module
  - `src/auth_test.py` — tests
- **Files Modified**: none

## Downstream Context
- **Key Interfaces Introduced**: none
"""
        result = orchestrator._parse_handoff(response)
        assert "src/auth.py" in result["task_report"]["files_created"]
        assert "src/auth_test.py" in result["task_report"]["files_created"]

    def test_multiline_files_modified(self, orchestrator):
        response = """## Task Report
- **Status**: success
- **Files Created**: none
- **Files Modified**:
  - `src/server.py` — added validation
  - `src/config.py` — new defaults
- **Decisions Made**: none

## Downstream Context
- none
"""
        result = orchestrator._parse_handoff(response)
        assert "src/server.py" in result["task_report"]["files_modified"]
        assert "src/config.py" in result["task_report"]["files_modified"]

    def test_inline_files(self, orchestrator):
        """Single-line format should still work."""
        response = """## Task Report
- **Status**: success
- **Files Created**: `a.py`, `b.py`
- **Files Modified**: `c.py`

## Downstream Context
- none
"""
        result = orchestrator._parse_handoff(response)
        assert set(result["task_report"]["files_created"]) == {"a.py", "b.py"}
        assert result["task_report"]["files_modified"] == ["c.py"]

    def test_none_files(self, orchestrator):
        """'none' with no backticks should return empty list."""
        response = """## Task Report
- **Status**: success
- **Files Created**: none
- **Files Modified**: none

## Downstream Context
- none
"""
        result = orchestrator._parse_handoff(response)
        assert result["task_report"]["files_created"] == []
        assert result["task_report"]["files_modified"] == []
