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
        "debugger": _make_agent_config("debugger", "heavy", 0.2, 10),
        "refactor": _make_agent_config("refactor", "heavy", 0.2, 10),
        "technical_writer": _make_agent_config("technical_writer", "light", 0.2, 8),
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
    async def test_dispatch_uses_capped_timeout(self, orchestrator):
        """Should cap timeout at 45s even if agent config says 10 minutes."""
        await orchestrator.dispatch_agent("coder", "Build it.")

        call_kwargs = orchestrator._client.chat.completions.create.call_args.kwargs
        assert call_kwargs["timeout"] == 45  # capped for fast failure

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


# ---------------------------------------------------------------------------
# Weighted craft_plan tests
# ---------------------------------------------------------------------------


class TestCraftPlanWeighted:
    """Verify craft_plan uses weighted keyword scoring."""

    def test_review_keywords(self, orchestrator):
        """'review' and 'audit' should select the review pipeline."""
        plan = orchestrator.craft_plan("Review the authentication module")
        assert plan.phases[0].name == "Architecture Analysis"
        assert plan.phases[0].agent == "architect"
        assert len(plan.phases) == 3

    def test_audit_keyword(self, orchestrator):
        plan = orchestrator.craft_plan("Audit the codebase for quality")
        assert len(plan.phases) == 3
        assert plan.phases[1].agent == "code_reviewer"

    def test_debug_keywords(self, orchestrator):
        """'fix', 'bug', 'debug' should select the debug pipeline."""
        plan = orchestrator.craft_plan("Fix the login bug")
        assert plan.phases[0].agent == "debugger"
        assert len(plan.phases) == 4

    def test_crash_keyword(self, orchestrator):
        plan = orchestrator.craft_plan("The server keeps crashing")
        assert plan.phases[0].agent == "debugger"

    def test_refactor_keywords(self, orchestrator):
        """'refactor' and 'restructure' should select the refactor pipeline."""
        plan = orchestrator.craft_plan("Refactor the data layer")
        assert plan.phases[0].agent == "architect"
        assert plan.phases[1].agent == "refactor"
        assert len(plan.phases) == 4

    def test_restructure_keyword(self, orchestrator):
        plan = orchestrator.craft_plan("Restructure the module hierarchy")
        assert plan.phases[1].agent == "refactor"

    def test_test_keywords(self, orchestrator):
        """'test' should select the test-focused pipeline."""
        plan = orchestrator.craft_plan("Write tests for the auth module")
        assert plan.phases[0].agent == "tester"
        assert plan.phases[1].agent == "coder"
        assert plan.phases[2].agent == "code_reviewer"
        assert len(plan.phases) == 3

    def test_coverage_keyword(self, orchestrator):
        plan = orchestrator.craft_plan("Improve test coverage")
        assert plan.phases[0].agent == "tester"
        assert len(plan.phases) == 3

    def test_document_keywords(self, orchestrator):
        """'document' and 'docs' should select the document pipeline."""
        plan = orchestrator.craft_plan("Document the API endpoints")
        assert plan.phases[0].agent == "technical_writer"
        assert plan.phases[1].agent == "code_reviewer"
        assert len(plan.phases) == 2

    def test_docs_keyword(self, orchestrator):
        plan = orchestrator.craft_plan("Write docs for the SDK")
        assert plan.phases[0].agent == "technical_writer"

    def test_readme_keyword(self, orchestrator):
        plan = orchestrator.craft_plan("Update the readme")
        assert plan.phases[0].agent == "technical_writer"

    def test_build_default(self, orchestrator):
        """Unknown tasks should fall back to the build pipeline."""
        plan = orchestrator.craft_plan("Do something arbitrary")
        assert len(plan.phases) == 5
        assert plan.phases[0].agent == "architect"

    def test_build_explicit(self, orchestrator):
        plan = orchestrator.craft_plan("Build a new feature")
        assert len(plan.phases) == 5

    def test_highest_score_wins(self, orchestrator):
        """When multiple groups match, the highest total score should win."""
        # 'fix' (3.0) + 'bug' (3.0) = 6.0 for debug
        # vs. 'check' (1.0) for review
        plan = orchestrator.craft_plan("Fix the bug and check results")
        assert plan.phases[0].agent == "debugger"

    def test_combined_fix_and_test(self, orchestrator):
        """'fix and test' should pick debug pipeline + extra test phase."""
        plan = orchestrator.craft_plan("Fix the bug and write tests")
        # Debug pipeline is 4 phases; combined adds 1 more = 5
        assert plan.phases[0].agent == "debugger"
        assert len(plan.phases) == 5
        assert plan.phases[-1].agent == "tester"
        assert plan.phases[-1].name == "Test Verification"

    def test_combined_build_and_test(self, orchestrator):
        """'build' + 'test' keywords should add extra test phase to build plan."""
        plan = orchestrator.craft_plan("Implement the feature and add unit tests")
        # 'implement' (2.5) for build vs 'unit test' (3.0) + 'tests' (3.0) for test
        # test wins here, so no extra phase appended -- it's a test plan
        assert plan.phases[0].agent == "tester"

    def test_combined_refactor_and_test(self, orchestrator):
        """Refactor plan with test keywords should get an extra test phase."""
        plan = orchestrator.craft_plan("Refactor and improve test coverage")
        # 'refactor' (3.0) for refactor vs 'test' (3.0) + 'coverage' (2.0) = 5.0 for test
        # Test wins here because score is higher
        assert plan.phases[0].agent == "tester"

    def test_combined_document_and_test(self, orchestrator):
        """Document with test co-occurrence appends test phase."""
        plan = orchestrator.craft_plan("Write documentation and explain the e2e coverage approach")
        # 'documentation' (3.0) + 'explain' (1.5) = 4.5 for document
        # 'e2e' (2.0) + 'coverage' (2.0) = 4.0 for test
        # Document wins; test also scores > 0 so extra phase appended
        assert plan.phases[0].agent == "technical_writer"
        assert len(plan.phases) == 3
        assert plan.phases[-1].name == "Test Verification"

    def test_extra_test_phase_blocked_by_last(self, orchestrator):
        """The appended test phase should be blocked by the last original phase."""
        plan = orchestrator.craft_plan("Fix the crash and add test coverage")
        # debug wins (crash=2.5 + fix=3.0 = 5.5) over test (test=3.0 + coverage=2.0 = 5.0)
        test_phase = plan.phases[-1]
        second_to_last = plan.phases[-2]
        assert test_phase.name == "Test Verification"
        assert second_to_last.id in test_phase.blocked_by


class TestScoreKeywordGroups:
    """Verify _score_keyword_groups returns correct scores."""

    def test_empty_task(self, orchestrator):
        scores = orchestrator._score_keyword_groups("")
        assert all(v == 0.0 for v in scores.values())

    def test_single_keyword(self, orchestrator):
        scores = orchestrator._score_keyword_groups("fix the thing")
        assert scores["debug"] >= 3.0
        assert scores["build"] == 0.0

    def test_multiple_keywords_same_group(self, orchestrator):
        scores = orchestrator._score_keyword_groups("fix the bug and debug it")
        # fix(3) + bug(3) + debug(3) = 9
        assert scores["debug"] == 9.0

    def test_cross_group_scoring(self, orchestrator):
        scores = orchestrator._score_keyword_groups("review and fix")
        assert scores["review"] >= 3.0
        assert scores["debug"] >= 3.0


# ---------------------------------------------------------------------------
# plan_summary tests
# ---------------------------------------------------------------------------


class TestPlanSummary:
    """Verify plan_summary produces human-readable output."""

    def test_summary_includes_task(self, orchestrator):
        plan = orchestrator.craft_plan("Build a feature")
        summary = orchestrator.plan_summary(plan)
        assert "Build a feature" in summary

    def test_summary_includes_phase_count(self, orchestrator):
        plan = orchestrator.craft_plan("Build a feature")
        summary = orchestrator.plan_summary(plan)
        assert "Phases: 5" in summary

    def test_summary_includes_all_phases(self, orchestrator):
        plan = orchestrator.craft_plan("Write tests for auth")
        summary = orchestrator.plan_summary(plan)
        assert "Test Design" in summary
        assert "Test Implementation" in summary
        assert "Test Review" in summary

    def test_summary_includes_agents(self, orchestrator):
        plan = orchestrator.craft_plan("Write tests for auth")
        summary = orchestrator.plan_summary(plan)
        assert "[tester]" in summary
        assert "[coder]" in summary
        assert "[code_reviewer]" in summary

    def test_summary_shows_dependencies(self, orchestrator):
        plan = orchestrator.craft_plan("Build a feature")
        summary = orchestrator.plan_summary(plan)
        # Phase 2 depends on Phase 1, should show "(after Architecture Analysis)"
        assert "(after Architecture Analysis)" in summary

    def test_summary_status_pending(self, orchestrator):
        plan = orchestrator.craft_plan("Build a feature")
        summary = orchestrator.plan_summary(plan)
        # All phases should be pending
        assert "[ ]" in summary
        assert "[x]" not in summary

    def test_summary_status_completed(self, orchestrator):
        plan = orchestrator.craft_plan("Build a feature")
        for phase in plan.phases:
            phase.status = "completed"
        summary = orchestrator.plan_summary(plan)
        assert "[x]" in summary
        assert "[ ]" not in summary

    def test_summary_status_failed(self, orchestrator):
        plan = orchestrator.craft_plan("Build a feature")
        plan.phases[0].status = "failed"
        summary = orchestrator.plan_summary(plan)
        assert "[!]" in summary

    def test_summary_status_in_progress(self, orchestrator):
        plan = orchestrator.craft_plan("Build a feature")
        plan.phases[0].status = "in_progress"
        summary = orchestrator.plan_summary(plan)
        assert "[~]" in summary

    def test_summary_document_plan(self, orchestrator):
        plan = orchestrator.craft_plan("Document the API")
        summary = orchestrator.plan_summary(plan)
        assert "Phases: 2" in summary
        assert "[technical_writer]" in summary

    def test_summary_combined_plan(self, orchestrator):
        """Combined plans should show the appended test phase."""
        plan = orchestrator.craft_plan("Fix the crash and add test coverage")
        summary = orchestrator.plan_summary(plan)
        assert "Test Verification" in summary
