"""Contract tests validating MCP tool return types and error shapes.

These tests verify the API contract that each MCP tool function adheres to:
- Return type correctness (str vs dict)
- Structured error response consistency (success, error, error_type, tool keys)
- Key presence in dict returns
"""

import json

import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from loom.server import (
    craft,
    get_context_for_coder,
    add_file_node,
    add_bug_edge,
    blackboard_transition,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_engine_with_context():
    """Create a mock memory engine that returns valid context."""
    engine = AsyncMock()
    engine.get_context_for_coder = AsyncMock(
        return_value={"nodes": ["n1"], "active_bugs": [], "raw_edges": ["e1"]}
    )
    engine.build_indices_and_constraints = AsyncMock()

    node = MagicMock()
    node.uuid = "node-uuid-001"
    engine.add_file_node = AsyncMock(return_value=node)

    edge = MagicMock()
    edge.uuid = "edge-uuid-002"
    engine.add_bug_edge = AsyncMock(return_value=edge)

    engine.blackboard_transition = AsyncMock()
    return engine


def _mock_orchestrator():
    """Create a mock orchestrator."""
    from loom.orchestrator import SwarmPlan, Phase
    orch = AsyncMock()
    orch.execute_swarm = AsyncMock(return_value=SwarmPlan(
        task="mock", phases=[Phase(id=1, name="Mock", agent="coder", objective="x", status="completed")]
    ))
    return orch


# ---------------------------------------------------------------------------
# craft contracts
# ---------------------------------------------------------------------------


class TestCraftContract:
    """Contract: craft always returns str with structured JSON."""

    @pytest.mark.asyncio
    async def test_craft_returns_str(self):
        """Should return a string on successful execution."""
        engine = _mock_engine_with_context()
        orch = _mock_orchestrator()

        with patch("loom.server._get_engines", return_value=(engine, orch)):
            result = await craft(task="build feature X", mode="cloud")
            assert isinstance(result, str), f"Expected str, got {type(result)}"

    @pytest.mark.asyncio
    async def test_craft_error_returns_structured_json(self):
        """Should return structured error JSON when engines unavailable."""
        with patch("loom.server._get_engines", side_effect=ValueError("missing vars")):
            result = await craft(task="build feature X", mode="cloud")
            assert isinstance(result, str), f"Expected str, got {type(result)}"
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert "missing vars" in parsed["error"]
            assert parsed["tool"] == "craft"
            assert "error_type" in parsed

    @pytest.mark.asyncio
    async def test_craft_exception_returns_structured_json(self):
        """Should return structured error JSON when an exception occurs."""
        engine = _mock_engine_with_context()
        orch = AsyncMock()
        orch.execute_swarm = AsyncMock(side_effect=RuntimeError("db down"))

        with patch("loom.server._get_engines", return_value=(engine, orch)):
            result = await craft(task="build feature X", mode="cloud")
            assert isinstance(result, str), f"Expected str, got {type(result)}"
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert parsed["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# get_context_for_coder contracts
# ---------------------------------------------------------------------------


class TestGetContextForCoderContract:
    """Contract: get_context_for_coder always returns dict."""

    @pytest.mark.asyncio
    async def test_get_context_for_coder_returns_dict(self):
        """Should return a dict with nodes, active_bugs, raw_edges keys on success."""
        engine = _mock_engine_with_context()

        with patch("loom.server._get_engines", return_value=(engine, _mock_orchestrator())):
            result = await get_context_for_coder(target_file="main.py")
            assert isinstance(result, dict), f"Expected dict, got {type(result)}"
            assert "nodes" in result
            assert "active_bugs" in result
            assert "raw_edges" in result

    @pytest.mark.asyncio
    async def test_get_context_for_coder_error_returns_structured_dict(self):
        """Should return a dict with structured error fields when engines unavailable."""
        with patch("loom.server._get_engines", side_effect=ValueError("no config")):
            result = await get_context_for_coder(target_file="main.py")
            assert isinstance(result, dict), f"Expected dict, got {type(result)}"
            assert result["success"] is False
            assert isinstance(result["error"], str)
            assert result["tool"] == "get_context_for_coder"
            assert "error_type" in result

    @pytest.mark.asyncio
    async def test_get_context_for_coder_exception_returns_structured_dict(self):
        """Should return a dict with structured error fields when an exception occurs."""
        engine = AsyncMock()
        engine.get_context_for_coder = AsyncMock(side_effect=RuntimeError("graph error"))

        with patch("loom.server._get_engines", return_value=(engine, _mock_orchestrator())):
            result = await get_context_for_coder(target_file="main.py")
            assert isinstance(result, dict), f"Expected dict, got {type(result)}"
            assert result["success"] is False
            assert result["error_type"] == "RuntimeError"


# ---------------------------------------------------------------------------
# add_file_node contracts
# ---------------------------------------------------------------------------


class TestAddFileNodeContract:
    """Contract: add_file_node always returns str."""

    @pytest.mark.asyncio
    async def test_add_file_node_returns_str(self):
        """Should return a string containing the UUID on success."""
        engine = _mock_engine_with_context()

        with patch("loom.server._get_engines", return_value=(engine, _mock_orchestrator())):
            result = await add_file_node(file_path="test.py", summary="Test file")
            assert isinstance(result, str), f"Expected str, got {type(result)}"
            assert "node-uuid-001" in result

    @pytest.mark.asyncio
    async def test_add_file_node_error_returns_structured_json(self):
        """Should return structured error JSON when engines unavailable."""
        with patch("loom.server._get_engines", side_effect=ValueError("no config")):
            result = await add_file_node(file_path="test.py", summary="Test file")
            assert isinstance(result, str), f"Expected str, got {type(result)}"
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert parsed["tool"] == "add_file_node"


# ---------------------------------------------------------------------------
# add_bug_edge contracts
# ---------------------------------------------------------------------------


class TestAddBugEdgeContract:
    """Contract: add_bug_edge always returns str."""

    @pytest.mark.asyncio
    async def test_add_bug_edge_returns_str(self):
        """Should return a string containing the UUID on success."""
        engine = _mock_engine_with_context()

        with patch("loom.server._get_engines", return_value=(engine, _mock_orchestrator())):
            result = await add_bug_edge(source_uuid="s1", file_uuid="f1", description="Bug A")
            assert isinstance(result, str), f"Expected str, got {type(result)}"
            assert "edge-uuid-002" in result

    @pytest.mark.asyncio
    async def test_add_bug_edge_error_returns_structured_json(self):
        """Should return structured error JSON when engines unavailable."""
        with patch("loom.server._get_engines", side_effect=ValueError("no config")):
            result = await add_bug_edge(source_uuid="s1", file_uuid="f1", description="Bug A")
            assert isinstance(result, str), f"Expected str, got {type(result)}"
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert parsed["tool"] == "add_bug_edge"


# ---------------------------------------------------------------------------
# blackboard_transition contracts
# ---------------------------------------------------------------------------


class TestBlackboardTransitionContract:
    """Contract: blackboard_transition always returns str."""

    @pytest.mark.asyncio
    async def test_blackboard_transition_returns_str(self):
        """Should return a string on success."""
        engine = _mock_engine_with_context()

        with patch("loom.server._get_engines", return_value=(engine, _mock_orchestrator())):
            result = await blackboard_transition(edge_uuids=["e1"], agent_name="coder")
            assert isinstance(result, str), f"Expected str, got {type(result)}"

    @pytest.mark.asyncio
    async def test_blackboard_transition_error_returns_structured_json(self):
        """Should return structured error JSON when engines unavailable."""
        with patch("loom.server._get_engines", side_effect=ValueError("no config")):
            result = await blackboard_transition(edge_uuids=["e1"], agent_name="coder")
            assert isinstance(result, str), f"Expected str, got {type(result)}"
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert parsed["tool"] == "blackboard_transition"

    @pytest.mark.asyncio
    async def test_blackboard_transition_exception_returns_structured_json(self):
        """Should return structured error JSON when blackboard_transition raises."""
        engine = AsyncMock()
        engine.blackboard_transition = AsyncMock(side_effect=ValueError("uuid not found"))

        with patch("loom.server._get_engines", return_value=(engine, _mock_orchestrator())):
            result = await blackboard_transition(edge_uuids=["bad"], agent_name="coder")
            assert isinstance(result, str), f"Expected str, got {type(result)}"
            parsed = json.loads(result)
            assert parsed["success"] is False
            assert "uuid not found" in parsed["error"]
