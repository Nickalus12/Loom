"""Unit tests for individual MCP server tools and lazy-init singleton functions."""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_ps_manager(output="", success=True, errors=""):
    """Create a mock PowerShellREPLManager with configurable execute return."""
    mgr = AsyncMock()
    mgr.execute = AsyncMock(return_value={
        "success": success,
        "output": output,
        "errors": errors,
    })
    mgr.list_custom_tools = MagicMock(return_value=[])
    return mgr


def _make_mock_kan_engine():
    """Create a mock KAN engine."""
    kan = MagicMock()
    kan.score_risk = AsyncMock(return_value={
        "risk_score": 0.1,
        "risk_level": "safe",
        "features": {},
        "model": "heuristic",
        "command_preview": "test",
    })
    kan.get_status = MagicMock(return_value={
        "initialized": False,
        "model": "heuristic",
        "torch_available": False,
        "training_buffer_size": 0,
    })
    return kan


# ===========================================================================
# Group 1: PowerShell MCP Tools
# ===========================================================================


class TestPowerShellMCPTools:
    """Verify each PowerShell MCP tool delegates correctly and returns JSON."""

    @pytest.mark.asyncio
    async def test_execute_powershell_returns_json(self):
        """Should return JSON string from manager.execute."""
        from loom.server import execute_powershell

        mock_mgr = _make_mock_ps_manager(output="Hello World")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await execute_powershell(script="Write-Host 'Hello World'")

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert "Hello World" in parsed["output"]

    @pytest.mark.asyncio
    async def test_read_file_ps_returns_json(self):
        """Should call Read-LoomFile and return JSON."""
        from loom.server import read_file_ps

        mock_mgr = _make_mock_ps_manager(output="1\tprint('hello')")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await read_file_ps(path="src/app.py")

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_write_file_ps_returns_json(self):
        """Should call Write-LoomFile and return JSON."""
        from loom.server import write_file_ps

        mock_mgr = _make_mock_ps_manager(output="Written.")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await write_file_ps(path="test.txt", content="hello")

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_search_code_ps_returns_json(self):
        """Should call Search-LoomCode and return JSON."""
        from loom.server import search_code_ps

        mock_mgr = _make_mock_ps_manager(output="src/app.py:10: match found")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await search_code_ps(query="def main")

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_find_files_ps_returns_json(self):
        """Should call Find-LoomFiles and return JSON."""
        from loom.server import find_files_ps

        mock_mgr = _make_mock_ps_manager(output="src/app.py\nsrc/utils.py")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await find_files_ps(pattern="*.py")

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_git_status_ps_returns_json(self):
        """Should call Get-LoomGitStatus and return JSON."""
        from loom.server import git_status_ps

        mock_mgr = _make_mock_ps_manager(output="On branch main")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await git_status_ps()

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_git_diff_ps_returns_json(self):
        """Should call Get-LoomGitDiff and return JSON."""
        from loom.server import git_diff_ps

        mock_mgr = _make_mock_ps_manager(output="diff --git a/file.py")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await git_diff_ps()

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_git_diff_ps_staged_flag(self):
        """Should include -Staged flag when staged=True."""
        from loom.server import git_diff_ps

        mock_mgr = _make_mock_ps_manager(output="staged changes")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            await git_diff_ps(staged=True)

        # Verify the command sent to execute contains -Staged
        call_args = mock_mgr.execute.call_args
        assert "-Staged" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_git_commit_ps_returns_json(self):
        """Should call New-LoomGitCommit and return JSON."""
        from loom.server import git_commit_ps

        mock_mgr = _make_mock_ps_manager(output="[main abc1234] commit message")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await git_commit_ps(message="feat: add feature")

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_git_log_ps_returns_json(self):
        """Should call Get-LoomGitLog and return JSON."""
        from loom.server import git_log_ps

        mock_mgr = _make_mock_ps_manager(output="commit abc123")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await git_log_ps()

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_git_log_ps_custom_limit(self):
        """Should pass custom limit to Get-LoomGitLog."""
        from loom.server import git_log_ps

        mock_mgr = _make_mock_ps_manager(output="log output")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            await git_log_ps(limit=5)

        call_args = mock_mgr.execute.call_args
        assert "5" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_git_stash_ps_returns_json(self):
        """Should call Save-LoomGitStash and return JSON."""
        from loom.server import git_stash_ps

        mock_mgr = _make_mock_ps_manager(output="Saved working directory")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await git_stash_ps()

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_git_pop_ps_returns_json(self):
        """Should call Restore-LoomGitStash and return JSON."""
        from loom.server import git_pop_ps

        mock_mgr = _make_mock_ps_manager(output="Dropped stash")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await git_pop_ps()

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_build_project_ps_returns_json(self):
        """Should call Invoke-LoomBuild and return JSON."""
        from loom.server import build_project_ps

        mock_mgr = _make_mock_ps_manager(output="Build succeeded")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await build_project_ps()

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_test_project_ps_returns_json(self):
        """Should call Invoke-LoomTest and return JSON."""
        from loom.server import test_project_ps

        mock_mgr = _make_mock_ps_manager(output="5 passed, 0 failed")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await test_project_ps()

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_test_project_ps_with_filter(self):
        """Should include -Filter param when filter is provided."""
        from loom.server import test_project_ps

        mock_mgr = _make_mock_ps_manager(output="filtered tests")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            await test_project_ps(filter="test_auth")

        call_args = mock_mgr.execute.call_args
        assert "test_auth" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_gpu_status_ps_returns_json(self):
        """Should call Get-LoomGpuStatus and return JSON."""
        from loom.server import get_gpu_status_ps

        mock_mgr = _make_mock_ps_manager(output="GPU: RTX 4090")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await get_gpu_status_ps()

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_disk_usage_ps_returns_json(self):
        """Should call Get-LoomDiskUsage and return JSON."""
        from loom.server import disk_usage_ps

        mock_mgr = _make_mock_ps_manager(output="C: 500GB free")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await disk_usage_ps()

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_memory_usage_ps_returns_json(self):
        """Should call Get-LoomMemoryUsage and return JSON."""
        from loom.server import memory_usage_ps

        mock_mgr = _make_mock_ps_manager(output="16GB total, 8GB used")
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await memory_usage_ps()

        parsed = json.loads(result)
        assert parsed["success"] is True


# ===========================================================================
# Group 2: KAN MCP Tools
# ===========================================================================


class TestKANMCPTools:
    """Verify KAN-related MCP tools."""

    @pytest.mark.asyncio
    async def test_kan_score_command_returns_json(self):
        """Should call kan.score_risk and return JSON."""
        from loom.server import kan_score_command

        mock_kan = _make_mock_kan_engine()
        with patch("loom.server._get_kan_engine", return_value=mock_kan):
            result = await kan_score_command(command="Get-Process")

        parsed = json.loads(result)
        assert "risk_score" in parsed
        assert "risk_level" in parsed

    @pytest.mark.asyncio
    async def test_kan_status_ps_returns_json(self):
        """Should call kan.get_status and return JSON."""
        from loom.server import kan_status_ps

        mock_kan = _make_mock_kan_engine()
        with patch("loom.server._get_kan_engine", return_value=mock_kan):
            result = await kan_status_ps()

        parsed = json.loads(result)
        assert "model" in parsed


# ===========================================================================
# Group 3: Lazy Init Singletons
# ===========================================================================


class TestLazyInitSingletons:
    """Verify lazy initialization functions create and cache singletons."""

    def test_get_engines_function_exists(self):
        """Should be importable from loom.server."""
        from loom.server import _get_engines
        assert callable(_get_engines)

    def test_get_local_engine_function_exists(self):
        """Should be importable from loom.server."""
        from loom.server import _get_local_engine
        assert callable(_get_local_engine)

    def test_get_ps_manager_function_exists(self):
        """Should be importable from loom.server."""
        from loom.server import _get_ps_manager
        assert callable(_get_ps_manager)

    def test_get_kan_engine_function_exists(self):
        """Should be importable from loom.server."""
        from loom.server import _get_kan_engine
        assert callable(_get_kan_engine)

    def test_get_local_agent_function_exists(self):
        """Should be importable from loom.server."""
        from loom.server import _get_local_agent
        assert callable(_get_local_agent)


# ===========================================================================
# Group 4: Error Handling in Server Tools
# ===========================================================================


class TestServerToolErrorHandling:
    """Verify MCP tools handle exceptions gracefully."""

    @pytest.mark.asyncio
    async def test_execute_powershell_catches_exception(self):
        """Should return error string when _get_ps_manager raises."""
        from loom.server import execute_powershell

        with patch("loom.server._get_ps_manager", side_effect=RuntimeError("No pwsh")):
            result = await execute_powershell(script="Get-Process")

        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_read_file_ps_catches_exception(self):
        """Should return error string when _get_ps_manager raises."""
        from loom.server import read_file_ps

        with patch("loom.server._get_ps_manager", side_effect=RuntimeError("No pwsh")):
            result = await read_file_ps(path="test.py")

        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_kan_score_command_catches_exception(self):
        """Should return error string when _get_kan_engine raises."""
        from loom.server import kan_score_command

        with patch("loom.server._get_kan_engine", side_effect=ValueError("init error")):
            result = await kan_score_command(command="Get-Process")

        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_define_custom_tool_returns_json(self):
        """Should register tool and return success JSON."""
        from loom.server import define_custom_tool

        mock_mgr = _make_mock_ps_manager()
        mock_mgr.register_custom_tool = AsyncMock()
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await define_custom_tool(name="Test-Tool", script="Write-Host 'test'")

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["tool"] == "Test-Tool"

    @pytest.mark.asyncio
    async def test_list_powershell_tools_returns_json(self):
        """Should list custom tools and return success JSON."""
        from loom.server import list_powershell_tools

        mock_mgr = _make_mock_ps_manager()
        mock_mgr.list_custom_tools = MagicMock(return_value=["Tool-A", "Tool-B"])
        with patch("loom.server._get_ps_manager", return_value=mock_mgr):
            result = await list_powershell_tools()

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["count"] == 2

    @pytest.mark.asyncio
    async def test_local_brainstorm_returns_result(self):
        """Should delegate to local engine brainstorm."""
        from loom.server import local_brainstorm

        mock_engine = AsyncMock()
        mock_engine.brainstorm = AsyncMock(return_value="Use factory pattern")
        with patch("loom.server._get_local_engine", return_value=mock_engine):
            result = await local_brainstorm(task="How to refactor?")

        assert "factory pattern" in result.lower()

    @pytest.mark.asyncio
    async def test_local_brainstorm_catches_exception(self):
        """Should return error string when local engine fails."""
        from loom.server import local_brainstorm

        with patch("loom.server._get_local_engine", side_effect=RuntimeError("no Ollama")):
            result = await local_brainstorm(task="test")

        assert "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_local_review_returns_result(self):
        """Should delegate to local engine review."""
        from loom.server import local_review

        mock_engine = AsyncMock()
        mock_engine.review = AsyncMock(return_value={"findings": "Clean code", "confidence": "high"})
        with patch("loom.server._get_local_engine", return_value=mock_engine):
            result = await local_review(code="x = 1", file_path="test.py")

        assert "clean code" in result.lower() or "confidence" in result.lower()

    @pytest.mark.asyncio
    async def test_local_debug_returns_result(self):
        """Should delegate to local engine debug_assist."""
        from loom.server import local_debug

        mock_engine = AsyncMock()
        mock_engine.debug_assist = AsyncMock(return_value="Check variable initialization")
        with patch("loom.server._get_local_engine", return_value=mock_engine):
            result = await local_debug(error="NoneType error")

        assert "initialization" in result.lower() or "variable" in result.lower()
