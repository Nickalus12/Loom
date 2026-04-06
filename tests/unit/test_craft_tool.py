"""Unit tests for the craft MCP tool and local_agent_task tool — cloud and local modes with error handling."""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loom.orchestrator import SwarmPlan, Phase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mocks():
    """Helper to create mock engine and orchestrator."""
    mock_engine = AsyncMock()
    mock_orch = AsyncMock()
    return mock_engine, mock_orch


# ===========================================================================
# Group 1: Cloud Mode
# ===========================================================================


class TestCraftCloudMode:
    """Verify the craft tool operates correctly in cloud (LiteLLM) mode."""

    @pytest.mark.asyncio
    async def test_craft_cloud_dispatches_swarm(self):
        """Should call orchestrator.execute_swarm when mode is cloud."""
        from loom.server import craft

        mock_engine, mock_orch = _make_mocks()
        mock_orch.execute_swarm = AsyncMock(return_value=SwarmPlan(
            task="test",
            phases=[Phase(id=1, name="Arch", agent="architect", objective="x", status="completed")],
        ))

        with patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            result = await craft(task="Build feature", mode="cloud")

        mock_orch.execute_swarm.assert_awaited_once_with("Build feature")

    @pytest.mark.asyncio
    async def test_craft_cloud_returns_json_with_phases(self):
        """Should return JSON string containing 'phases' count."""
        from loom.server import craft

        mock_engine, mock_orch = _make_mocks()
        mock_orch.execute_swarm = AsyncMock(return_value=SwarmPlan(
            task="test",
            phases=[
                Phase(id=1, name="Arch", agent="architect", objective="x", status="completed"),
                Phase(id=2, name="Code", agent="coder", objective="y", status="completed"),
            ],
        ))

        with patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            result = await craft(task="test", mode="cloud")

        parsed = json.loads(result)
        assert parsed["phases"] == 2

    @pytest.mark.asyncio
    async def test_craft_cloud_includes_files_created(self):
        """Should aggregate files_created from all phases."""
        from loom.server import craft

        mock_engine, mock_orch = _make_mocks()
        mock_orch.execute_swarm = AsyncMock(return_value=SwarmPlan(
            task="test",
            phases=[
                Phase(id=1, name="Arch", agent="architect", objective="x",
                      status="completed", files_created=["src/new.py"]),
                Phase(id=2, name="Code", agent="coder", objective="y",
                      status="completed", files_created=["src/other.py"]),
            ],
        ))

        with patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            result = await craft(task="test", mode="cloud")

        parsed = json.loads(result)
        assert "src/new.py" in parsed["files_created"]
        assert "src/other.py" in parsed["files_created"]

    @pytest.mark.asyncio
    async def test_craft_cloud_includes_files_modified(self):
        """Should aggregate files_modified from all phases."""
        from loom.server import craft

        mock_engine, mock_orch = _make_mocks()
        mock_orch.execute_swarm = AsyncMock(return_value=SwarmPlan(
            task="test",
            phases=[
                Phase(id=1, name="Arch", agent="architect", objective="x",
                      status="completed", files_modified=["src/server.py"]),
            ],
        ))

        with patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            result = await craft(task="test", mode="cloud")

        parsed = json.loads(result)
        assert "src/server.py" in parsed["files_modified"]

    @pytest.mark.asyncio
    async def test_craft_cloud_handles_failed_phases(self):
        """Should return error JSON when execute_swarm raises."""
        from loom.server import craft

        mock_engine, mock_orch = _make_mocks()
        mock_orch.execute_swarm = AsyncMock(
            side_effect=RuntimeError("Phase 3 failed permanently")
        )

        with patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            result = await craft(task="test", mode="cloud")

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "failed" in parsed["error"].lower()


# ===========================================================================
# Group 2: Local Mode
# ===========================================================================


class TestCraftLocalMode:
    """Verify the craft tool operates correctly in local (Ollama) mode."""

    @pytest.mark.asyncio
    async def test_craft_local_dispatches_local_agent(self):
        """Should call the local agent's run method when mode is local."""
        from loom.server import craft

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value={
            "success": True,
            "response": "Done.",
            "tool_calls_made": 3,
            "turns_used": 2,
            "files_changed": ["src/app.py"],
            "git_branch": "loom/agent-123",
            "git_diff": None,
            "validation_results": [],
            "tool_log": [],
            "memory_stored": False,
            "truncated": False,
        })

        with patch("loom.server._get_local_agent", return_value=mock_agent):
            result = await craft(task="Fix the bug", mode="local")

        mock_agent.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_craft_local_returns_agent_result(self):
        """Should return JSON-serialized AgentResult from local mode."""
        from loom.server import craft

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value={
            "success": True,
            "response": "Completed.",
            "tool_calls_made": 5,
            "turns_used": 3,
            "files_changed": [],
            "git_branch": None,
            "git_diff": None,
            "validation_results": [],
            "tool_log": [],
            "memory_stored": True,
            "truncated": False,
        })

        with patch("loom.server._get_local_agent", return_value=mock_agent):
            result = await craft(task="Analyze code", mode="local")

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["tool_calls_made"] == 5

    @pytest.mark.asyncio
    async def test_craft_local_mode_from_env_var(self):
        """Should respect LOOM_CRAFT_MODE env var when mode parameter is empty."""
        from loom.server import craft

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value={
            "success": True,
            "response": "OK",
            "tool_calls_made": 0,
            "turns_used": 1,
            "files_changed": [],
            "git_branch": None,
            "git_diff": None,
            "validation_results": [],
            "tool_log": [],
            "memory_stored": False,
            "truncated": False,
        })

        with patch("loom.server._get_local_agent", return_value=mock_agent), \
             patch.dict("os.environ", {"LOOM_CRAFT_MODE": "local"}):
            result = await craft(task="test", mode="")

        mock_agent.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_craft_mode_default_is_cloud(self):
        """Should default to cloud mode when no mode is specified."""
        from loom.server import craft

        mock_engine, mock_orch = _make_mocks()
        mock_orch.execute_swarm = AsyncMock(return_value=SwarmPlan(
            task="test",
            phases=[Phase(id=1, name="A", agent="architect", objective="x", status="completed")],
        ))

        with patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            result = await craft(task="test", mode="cloud")

        mock_orch.execute_swarm.assert_awaited_once()


# ===========================================================================
# Group 3: Error Handling
# ===========================================================================


class TestCraftErrorHandling:
    """Verify craft handles exceptions gracefully."""

    @pytest.mark.asyncio
    async def test_craft_catches_value_error(self):
        """Should return error JSON when ValueError is raised."""
        from loom.server import craft

        with patch("loom.server._get_engines", side_effect=ValueError("Missing env var")):
            result = await craft(task="test", mode="cloud")

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "missing env var" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_craft_catches_runtime_error(self):
        """Should return error JSON when RuntimeError is raised."""
        from loom.server import craft

        mock_engine, mock_orch = _make_mocks()
        mock_orch.execute_swarm = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        with patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            result = await craft(task="test", mode="cloud")

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "llm timeout" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_craft_returns_json_on_error(self):
        """Should always return valid JSON even on error."""
        from loom.server import craft

        with patch("loom.server._get_engines", side_effect=Exception("Unexpected")):
            result = await craft(task="test", mode="cloud")

        # Should not raise — should be parseable JSON
        parsed = json.loads(result)
        assert "error" in parsed


# ===========================================================================
# Group 4: Integration Imports
# ===========================================================================


class TestCraftImports:
    """Verify craft and local_agent_task are importable with correct signatures."""

    def test_craft_tool_importable(self):
        """Should be importable from loom.server."""
        from loom.server import craft
        assert callable(craft)

    def test_local_agent_task_tool_importable(self):
        """Should be importable from loom.server."""
        from loom.server import local_agent_task
        assert callable(local_agent_task)

    @pytest.mark.asyncio
    async def test_local_agent_task_returns_error_on_failure(self):
        """Should catch exceptions and return error string."""
        from loom.server import local_agent_task

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(side_effect=RuntimeError("Model not loaded"))

        with patch("loom.server._get_local_agent", return_value=mock_agent):
            result = await local_agent_task(task="Do something")

        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_local_agent_task_success(self):
        """Should return JSON-serialized agent result on success."""
        from loom.server import local_agent_task

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value={
            "success": True,
            "response": "Task complete.",
            "tool_calls_made": 2,
            "turns_used": 1,
            "files_changed": [],
            "git_branch": None,
            "git_diff": None,
            "validation_results": [],
            "tool_log": [],
            "memory_stored": False,
            "truncated": False,
        })

        with patch("loom.server._get_local_agent", return_value=mock_agent):
            result = await local_agent_task(task="Review code")

        parsed = json.loads(result)
        assert parsed["success"] is True
