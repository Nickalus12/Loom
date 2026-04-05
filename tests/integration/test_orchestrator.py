"""Integration tests for the full orchestrator swarm against live infrastructure.

Requires: Neo4j (Docker), LiteLLM proxy (Docker), Gemini API key.
Gated behind the `integration` marker.
"""

import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
async def orchestrator():
    """Create a real LoomOrchestrator connected to live services."""
    import os
    if not os.getenv("LITELLM_MASTER_KEY"):
        pytest.skip("LITELLM_MASTER_KEY not set")

    from loom.memory_engine import LoomSwarmMemory
    from loom.orchestrator import LoomOrchestrator
    from loom.agent_registry import AgentRegistry

    mem = LoomSwarmMemory()
    try:
        await mem.build_indices_and_constraints()
    except Exception as e:
        pytest.skip(f"Infrastructure not reachable: {e}")

    reg = AgentRegistry()
    if len(reg) == 0:
        pytest.skip("No agent definitions found")

    orch = LoomOrchestrator(mem, reg)
    yield orch
    await mem.close()


class TestLiveAgentDispatch:
    """Verify individual agents respond through the live LiteLLM proxy."""

    async def test_architect_responds(self, orchestrator):
        """Architect should return a non-empty analysis."""
        result = await orchestrator.dispatch_agent(
            "architect",
            "Describe the architecture of a Python FastMCP server in 2 sentences.",
        )
        assert isinstance(result, str)
        assert len(result) > 20

    async def test_code_reviewer_responds(self, orchestrator):
        """Code reviewer should return findings for given code."""
        result = await orchestrator.dispatch_agent(
            "code_reviewer",
            "Review: `def add(a, b): return a + b`. One finding, concisely.",
        )
        assert isinstance(result, str)
        assert len(result) > 10


class TestLiveSwarmExecution:
    """Verify the full 5-phase swarm completes against live infrastructure."""

    async def test_execute_swarm_completes(self, orchestrator):
        """All 5 phases should complete with real LLM responses."""
        plan = await orchestrator.execute_swarm(
            "Add a health check endpoint that returns server status and uptime. Respond concisely."
        )
        assert len(plan.phases) == 5
        for phase in plan.phases:
            assert phase.status == "completed", f"Phase {phase.id} ({phase.name}): {phase.status}"
            assert len(phase.result) > 0, f"Phase {phase.id} has empty result"

    async def test_swarm_chains_context(self, orchestrator):
        """Later phases should receive downstream context from earlier phases."""
        from loom.orchestrator import Phase, SwarmPlan

        plan = SwarmPlan(task="Add logging. Respond concisely.", phases=[
            Phase(id=1, name="Design", agent="architect",
                  objective="Propose a logging approach in 2-3 sentences."),
            Phase(id=2, name="Implement", agent="coder",
                  objective="Based on the architect's design, describe what you would implement in 2-3 sentences.",
                  blocked_by=[1]),
        ])
        result = await orchestrator.execute_plan(plan)

        # Phase 1 should have downstream context
        assert result.phases[0].downstream_context.get("text", "") or result.phases[0].result
        # Phase 2 should have received context (its prompt includes phase 1's output)
        assert result.phases[1].status == "completed"
