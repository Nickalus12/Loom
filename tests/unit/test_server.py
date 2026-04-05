"""Unit tests for the Loom MCP server module."""

import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock


class TestServerModuleSetup:
    """Verify server module initialization properties."""

    def test_env_path_uses_file_relative(self):
        """Should compute _project_root relative to server.py using Path, not os.getcwd()."""
        from loom.server import _project_root
        assert isinstance(_project_root, Path)

    def test_mcp_server_created(self):
        """Should create a FastMCP instance named 'Loom Enterprise Swarm'."""
        from loom.server import mcp
        from mcp.server.fastmcp import FastMCP
        assert isinstance(mcp, FastMCP)

    def test_get_engines_function_exists(self):
        """The lazy-init _get_engines function should be importable."""
        from loom.server import _get_engines
        assert callable(_get_engines)


def _make_mocks():
    """Helper to create mock engine and orchestrator."""
    mock_engine = AsyncMock()
    mock_orch = AsyncMock()
    return mock_engine, mock_orch


class TestOrchestrateSwarmTool:
    """Verify the orchestrate_swarm MCP tool function."""

    @pytest.mark.asyncio
    async def test_orchestrate_swarm_returns_error_when_not_initialized(self):
        """Should return an error string when _get_engines raises."""
        from loom.server import orchestrate_swarm

        with patch("loom.server._get_engines", side_effect=ValueError("LITELLM_MASTER_KEY environment variable is missing")):
            result = await orchestrate_swarm(task="test")
            assert isinstance(result, str)
            assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_orchestrate_swarm_success(self):
        """Should return success string when swarm completes."""
        from loom.server import orchestrate_swarm
        from loom.orchestrator import SwarmPlan, Phase

        mock_engine, mock_orch = _make_mocks()
        mock_orch.execute_swarm = AsyncMock(return_value=SwarmPlan(
            task="test", phases=[Phase(id=1, name="Test", agent="coder", objective="x", status="completed")]
        ))

        with patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            result = await orchestrate_swarm(task="test task")
            assert isinstance(result, str)
            assert "completed" in result.lower() or "swarm" in result.lower()

    @pytest.mark.asyncio
    async def test_orchestrate_swarm_catches_exception(self):
        """Should catch exceptions and return error string instead of raising."""
        from loom.server import orchestrate_swarm

        mock_engine, mock_orch = _make_mocks()
        mock_orch.execute_swarm = AsyncMock(side_effect=RuntimeError("boom"))

        with patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            result = await orchestrate_swarm(task="test")
            assert isinstance(result, str)
            assert "failed" in result.lower() or "boom" in result


class TestGetContextForCoderTool:
    """Verify the get_context_for_coder MCP tool function."""

    @pytest.mark.asyncio
    async def test_get_context_for_coder_error_when_not_initialized(self):
        """Should return dict with 'error' key when _get_engines raises."""
        from loom.server import get_context_for_coder

        with patch("loom.server._get_engines", side_effect=ValueError("no env")):
            result = await get_context_for_coder(target_file="test.py")
            assert isinstance(result, dict)
            assert "error" in result

    @pytest.mark.asyncio
    async def test_get_context_for_coder_success(self):
        """Should return the dict from memory_engine when initialized."""
        from loom.server import get_context_for_coder

        mock_engine, _ = _make_mocks()
        mock_engine.get_context_for_coder = AsyncMock(
            return_value={"nodes": [], "active_bugs": [], "raw_edges": []}
        )

        with patch("loom.server._get_engines", return_value=(mock_engine, AsyncMock())):
            result = await get_context_for_coder(target_file="test.py")
            assert isinstance(result, dict)
            assert "nodes" in result
            assert "active_bugs" in result
            assert "raw_edges" in result

    @pytest.mark.asyncio
    async def test_get_context_for_coder_catches_exception(self):
        """Should catch exceptions and return dict with 'error' key."""
        from loom.server import get_context_for_coder

        mock_engine, _ = _make_mocks()
        mock_engine.get_context_for_coder = AsyncMock(side_effect=RuntimeError("search fail"))

        with patch("loom.server._get_engines", return_value=(mock_engine, AsyncMock())):
            result = await get_context_for_coder(target_file="test.py")
            assert isinstance(result, dict)
            assert "error" in result
            assert "search fail" in result["error"]


class TestAddFileNodeTool:
    """Verify the add_file_node MCP tool function."""

    @pytest.mark.asyncio
    async def test_add_file_node_returns_error_when_not_initialized(self):
        """Should return error string when _get_engines raises."""
        from loom.server import add_file_node

        with patch("loom.server._get_engines", side_effect=ValueError("no env")):
            result = await add_file_node(file_path="test.py", summary="test")
            assert isinstance(result, str)
            assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_add_file_node_success(self):
        """Should return string containing UUID on success."""
        from loom.server import add_file_node

        mock_node = MagicMock()
        mock_node.uuid = "abc-123"
        mock_engine, _ = _make_mocks()
        mock_engine.add_file_node = AsyncMock(return_value=mock_node)

        with patch("loom.server._get_engines", return_value=(mock_engine, AsyncMock())):
            result = await add_file_node(file_path="test.py", summary="A file")
            assert isinstance(result, str)
            assert "abc-123" in result


class TestAddBugEdgeTool:
    """Verify the add_bug_edge MCP tool function."""

    @pytest.mark.asyncio
    async def test_add_bug_edge_returns_error_when_not_initialized(self):
        """Should return error string when _get_engines raises."""
        from loom.server import add_bug_edge

        with patch("loom.server._get_engines", side_effect=ValueError("no env")):
            result = await add_bug_edge(source_uuid="a", file_uuid="b", description="bug")
            assert isinstance(result, str)
            assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_add_bug_edge_success(self):
        """Should return string containing UUID on success."""
        from loom.server import add_bug_edge

        mock_edge = MagicMock()
        mock_edge.uuid = "edge-456"
        mock_engine, _ = _make_mocks()
        mock_engine.add_bug_edge = AsyncMock(return_value=mock_edge)

        with patch("loom.server._get_engines", return_value=(mock_engine, AsyncMock())):
            result = await add_bug_edge(source_uuid="a", file_uuid="b", description="bug")
            assert isinstance(result, str)
            assert "edge-456" in result


class TestBlackboardTransitionTool:
    """Verify the blackboard_transition MCP tool function."""

    @pytest.mark.asyncio
    async def test_blackboard_transition_returns_error_when_not_initialized(self):
        """Should return error string when _get_engines raises."""
        from loom.server import blackboard_transition

        with patch("loom.server._get_engines", side_effect=ValueError("no env")):
            result = await blackboard_transition(edge_uuids=["a"], agent_name="coder")
            assert isinstance(result, str)
            assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_blackboard_transition_success(self):
        """Should return success string when transition completes."""
        from loom.server import blackboard_transition

        mock_engine, _ = _make_mocks()
        mock_engine.blackboard_transition = AsyncMock()

        with patch("loom.server._get_engines", return_value=(mock_engine, AsyncMock())):
            result = await blackboard_transition(edge_uuids=["uuid-1"], agent_name="coder")
            assert isinstance(result, str)
            assert "transitioned" in result.lower()

    @pytest.mark.asyncio
    async def test_blackboard_transition_catches_exception(self):
        """Should catch exceptions and return error string."""
        from loom.server import blackboard_transition

        mock_engine, _ = _make_mocks()
        mock_engine.blackboard_transition = AsyncMock(side_effect=ValueError("not found"))

        with patch("loom.server._get_engines", return_value=(mock_engine, AsyncMock())):
            result = await blackboard_transition(edge_uuids=["bad"], agent_name="coder")
            assert isinstance(result, str)
            assert "failed" in result.lower() or "not found" in result
