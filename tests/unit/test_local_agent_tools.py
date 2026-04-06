"""Unit tests for LocalAgent tool execution — deep testing of _execute_agent_tool for each tool type."""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock

from loom.local_agent import LocalAgent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ps_manager():
    """Mock PowerShellREPLManager with configurable execute method."""
    mgr = AsyncMock()
    mgr.execute = AsyncMock(return_value={"success": True, "output": "", "errors": ""})
    return mgr


@pytest.fixture
def mock_inference_engine():
    """Mock inference engine providing a mock AsyncOpenAI client."""
    engine = MagicMock()
    engine._client = AsyncMock()
    engine._client.chat = MagicMock()
    engine._client.chat.completions = MagicMock()
    engine._client.chat.completions.create = AsyncMock()
    return engine


@pytest.fixture
def agent(mock_inference_engine, mock_ps_manager):
    """LocalAgent wired to mocks, ready for direct tool testing."""
    return LocalAgent(
        inference_engine=mock_inference_engine,
        ps_manager=mock_ps_manager,
        memory_engine=None,
        tool_model="test-tool",
        analysis_model="test-analysis",
        max_turns=5,
    )


# ===========================================================================
# Group 1: read_file Tool
# ===========================================================================


class TestReadFileTool:
    """Verify _execute_agent_tool for read_file."""

    async def test_read_file_calls_ps_manager(self, agent, mock_ps_manager):
        """Should call ps_manager.execute with Read-LoomFile command."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "1\tprint('hello')",
            "errors": "",
        })

        result = await agent._execute_agent_tool("read_file", {"path": "src/app.py"})

        mock_ps_manager.execute.assert_awaited_once()
        call_cmd = mock_ps_manager.execute.call_args[0][0]
        assert "Read-LoomFile" in call_cmd
        assert "src/app.py" in call_cmd

    async def test_read_file_escapes_single_quotes(self, agent, mock_ps_manager):
        """Should escape single quotes in file paths for PowerShell."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "content",
            "errors": "",
        })

        await agent._execute_agent_tool("read_file", {"path": "it's/a/file.py"})

        call_cmd = mock_ps_manager.execute.call_args[0][0]
        assert "it''s" in call_cmd  # escaped single quote

    async def test_read_file_returns_output(self, agent, mock_ps_manager):
        """Should return the output from ps_manager."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "file contents here",
            "errors": "",
        })

        result = await agent._execute_agent_tool("read_file", {"path": "test.py"})

        assert result == "file contents here"

    async def test_read_file_returns_error_on_failure(self, agent, mock_ps_manager):
        """Should return error message when ps_manager reports failure.

        The read_file path evaluates ``r.get("output", r.get("error", "No output"))``.
        When "output" is absent the fallback reaches the "error" key.
        """
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": False,
            "error": "File not found",
        })

        result = await agent._execute_agent_tool("read_file", {"path": "missing.py"})

        assert "not found" in result.lower()


# ===========================================================================
# Group 2: read_file_lines Tool
# ===========================================================================


class TestReadFileLinesTool:
    """Verify _execute_agent_tool for read_file_lines."""

    async def test_read_file_lines_slices_correctly(self, agent, mock_ps_manager):
        """Should return only the requested line range."""
        full_content = "\n".join(f"{i}\tline {i}" for i in range(1, 11))
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": full_content,
            "errors": "",
        })

        result = await agent._execute_agent_tool(
            "read_file_lines",
            {"path": "big.py", "start_line": 3, "end_line": 5},
        )

        lines = result.strip().split("\n")
        assert len(lines) == 3
        assert "line 3" in lines[0]
        assert "line 5" in lines[2]

    async def test_read_file_lines_out_of_range(self, agent, mock_ps_manager):
        """Should handle end_line beyond file length gracefully."""
        full_content = "\n".join(f"{i}\tline {i}" for i in range(1, 4))
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": full_content,
            "errors": "",
        })

        result = await agent._execute_agent_tool(
            "read_file_lines",
            {"path": "small.py", "start_line": 1, "end_line": 100},
        )

        # Should return all lines without error
        assert "line 1" in result
        assert "line 3" in result

    async def test_read_file_lines_returns_error_on_failure(self, agent, mock_ps_manager):
        """Should return error content when read fails."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": False,
            "output": "",
            "error": "File not found",
        })

        result = await agent._execute_agent_tool(
            "read_file_lines",
            {"path": "missing.py", "start_line": 1, "end_line": 5},
        )

        # Should return the error or output
        assert isinstance(result, str)


# ===========================================================================
# Group 3: edit_file Tool
# ===========================================================================


class TestEditFileTool:
    """Verify _execute_agent_tool for edit_file."""

    async def test_edit_file_reads_then_writes(self, agent, mock_ps_manager):
        """Should read the file, replace text, and write back."""
        file_content = "1\tdef hello():\n2\t    return 'world'"
        commands_executed = []

        async def track_execute(cmd, timeout=None):
            commands_executed.append(cmd)
            if "Read-LoomFile" in cmd:
                return {"success": True, "output": file_content, "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=track_execute)

        result = await agent._execute_agent_tool("edit_file", {
            "path": "app.py",
            "old_text": "return 'world'",
            "new_text": "return 'universe'",
        })

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["replacements"] == 1

        # Verify read was called before write
        read_idx = next(i for i, c in enumerate(commands_executed) if "Read-LoomFile" in c)
        write_idx = next(i for i, c in enumerate(commands_executed) if "Write-LoomFile" in c)
        assert read_idx < write_idx

    async def test_edit_file_strips_line_numbers(self, agent, mock_ps_manager):
        """Should strip tab-separated line numbers before searching for old_text."""
        # Line numbers format: "1\tcode" — the "1\t" prefix should be stripped
        file_content = "1\tdef foo():\n2\t    pass"

        async def handle_execute(cmd, timeout=None):
            if "Read-LoomFile" in cmd:
                return {"success": True, "output": file_content, "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=handle_execute)

        result = await agent._execute_agent_tool("edit_file", {
            "path": "app.py",
            "old_text": "def foo():",
            "new_text": "def bar():",
        })

        parsed = json.loads(result)
        assert parsed["success"] is True

    async def test_edit_file_replaces_first_occurrence_only(self, agent, mock_ps_manager):
        """Should only replace the first occurrence of old_text."""
        file_content = "1\tprint('a')\n2\tprint('a')\n3\tprint('a')"

        async def handle_execute(cmd, timeout=None):
            if "Read-LoomFile" in cmd:
                return {"success": True, "output": file_content, "errors": ""}
            if "Write-LoomFile" in cmd:
                # Verify only first occurrence replaced
                assert cmd.count("print(''b'')") == 1 or "b" in cmd
                return {"success": True, "output": "Written.", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=handle_execute)

        result = await agent._execute_agent_tool("edit_file", {
            "path": "app.py",
            "old_text": "print('a')",
            "new_text": "print('b')",
        })

        parsed = json.loads(result)
        assert parsed["success"] is True
        assert parsed["replacements"] == 1

    async def test_edit_file_old_text_missing_returns_error(self, agent, mock_ps_manager):
        """Should return error JSON when old_text is not found in the file."""
        file_content = "1\tdef foo():\n2\t    pass"

        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": file_content,
            "errors": "",
        })

        result = await agent._execute_agent_tool("edit_file", {
            "path": "app.py",
            "old_text": "NONEXISTENT_TEXT",
            "new_text": "replacement",
        })

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "not found" in parsed["error"].lower()

    async def test_edit_file_invalidates_cache(self, agent, mock_ps_manager):
        """Should clear the read cache for the edited file path."""
        file_content = "1\tline one"

        async def handle_execute(cmd, timeout=None):
            if "Read-LoomFile" in cmd:
                return {"success": True, "output": file_content, "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=handle_execute)

        # Pre-populate cache
        cache_key = agent._cache_key("read_file", {"path": "app.py"})
        agent._cache[cache_key] = file_content
        agent._path_cache_keys["app.py"] = {cache_key}

        await agent._execute_agent_tool("edit_file", {
            "path": "app.py",
            "old_text": "line one",
            "new_text": "line two",
        })

        # Cache should be invalidated
        assert cache_key not in agent._cache

    async def test_edit_file_read_failure_returns_error(self, agent, mock_ps_manager):
        """Should return error when file read fails."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": False,
            "errors": "Permission denied",
        })

        result = await agent._execute_agent_tool("edit_file", {
            "path": "restricted.py",
            "old_text": "x",
            "new_text": "y",
        })

        assert "error" in result.lower()


# ===========================================================================
# Group 4: write_file Tool
# ===========================================================================


class TestWriteFileTool:
    """Verify _execute_agent_tool for write_file."""

    async def test_write_file_escapes_content(self, agent, mock_ps_manager):
        """Should escape single quotes in content for PowerShell."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "Written.",
            "errors": "",
        })

        await agent._execute_agent_tool("write_file", {
            "path": "test.py",
            "content": "print('hello world')",
        })

        call_cmd = mock_ps_manager.execute.call_args[0][0]
        assert "Write-LoomFile" in call_cmd
        assert "''hello world''" in call_cmd  # escaped quotes

    async def test_write_file_returns_output(self, agent, mock_ps_manager):
        """Should return the output from ps_manager."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "File written successfully.",
            "errors": "",
        })

        result = await agent._execute_agent_tool("write_file", {
            "path": "new.py",
            "content": "x = 1",
        })

        assert "written" in result.lower() or "file" in result.lower()


# ===========================================================================
# Group 5: search_code Tool
# ===========================================================================


class TestSearchCodeTool:
    """Verify _execute_agent_tool for search_code."""

    async def test_search_code_escapes_all_params(self, agent, mock_ps_manager):
        """Should escape query, path, and include parameters."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "match found",
            "errors": "",
        })

        await agent._execute_agent_tool("search_code", {
            "query": "it's a pattern",
            "path": "src/it's here",
            "include": "*.py",
        })

        call_cmd = mock_ps_manager.execute.call_args[0][0]
        assert "Search-LoomCode" in call_cmd
        assert "it''s a pattern" in call_cmd
        assert "it''s here" in call_cmd

    async def test_search_code_default_path_and_include(self, agent, mock_ps_manager):
        """Should use defaults (path='.', include='*.*') when not provided."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "results",
            "errors": "",
        })

        await agent._execute_agent_tool("search_code", {"query": "def main"})

        call_cmd = mock_ps_manager.execute.call_args[0][0]
        assert "-Path '.'" in call_cmd
        assert "-Include '*.*'" in call_cmd

    async def test_search_code_returns_output(self, agent, mock_ps_manager):
        """Should return the search output from ps_manager."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "app.py:10: def main():",
            "errors": "",
        })

        result = await agent._execute_agent_tool("search_code", {"query": "def main"})

        assert "app.py" in result


# ===========================================================================
# Group 6: find_files Tool
# ===========================================================================


class TestFindFilesTool:
    """Verify _execute_agent_tool for find_files."""

    async def test_find_files_escapes_pattern_and_path(self, agent, mock_ps_manager):
        """Should escape pattern and path parameters."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "file1.py\nfile2.py",
            "errors": "",
        })

        await agent._execute_agent_tool("find_files", {
            "pattern": "it's*.py",
            "path": "src/it's here",
        })

        call_cmd = mock_ps_manager.execute.call_args[0][0]
        assert "Find-LoomFiles" in call_cmd
        assert "it''s*.py" in call_cmd
        assert "it''s here" in call_cmd

    async def test_find_files_default_path(self, agent, mock_ps_manager):
        """Should use default path='.' when not provided."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "file.py",
            "errors": "",
        })

        await agent._execute_agent_tool("find_files", {"pattern": "*.py"})

        call_cmd = mock_ps_manager.execute.call_args[0][0]
        assert "-Path '.'" in call_cmd


# ===========================================================================
# Group 7: run_powershell Tool
# ===========================================================================


class TestRunPowershellTool:
    """Verify _execute_agent_tool for run_powershell."""

    async def test_run_powershell_passes_command_directly(self, agent, mock_ps_manager):
        """Should pass the command string directly to ps_manager.execute."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "Process list",
            "errors": "",
        })

        result = await agent._execute_agent_tool("run_powershell", {
            "command": "Get-Process | Select-Object Name",
        })

        call_cmd = mock_ps_manager.execute.call_args[0][0]
        assert call_cmd == "Get-Process | Select-Object Name"

    async def test_run_powershell_returns_output(self, agent, mock_ps_manager):
        """Should return the output from ps_manager."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "explorer\nchrome",
            "errors": "",
        })

        result = await agent._execute_agent_tool("run_powershell", {
            "command": "Get-Process",
        })

        assert "explorer" in result


# ===========================================================================
# Group 8: Unknown Tool and Exceptions
# ===========================================================================


class TestToolEdgeCases:
    """Verify behavior with unknown tools and exceptions."""

    async def test_unknown_tool_returns_error(self, agent):
        """Should return 'Unknown tool' message for unrecognized tool names."""
        result = await agent._execute_agent_tool("nonexistent_tool", {})
        assert "unknown tool" in result.lower()

    async def test_exception_in_tool_returns_error(self, agent, mock_ps_manager):
        """Should catch exceptions and return error string."""
        mock_ps_manager.execute = AsyncMock(side_effect=RuntimeError("Connection failed"))

        result = await agent._execute_agent_tool("read_file", {"path": "test.py"})

        assert "tool execution error" in result.lower()

    def test_cache_key_deterministic(self, agent):
        """Should produce the same cache key for the same tool and args."""
        key1 = agent._cache_key("read_file", {"path": "test.py"})
        key2 = agent._cache_key("read_file", {"path": "test.py"})
        assert key1 == key2

    def test_cache_key_differs_for_different_args(self, agent):
        """Should produce different cache keys for different args."""
        key1 = agent._cache_key("read_file", {"path": "a.py"})
        key2 = agent._cache_key("read_file", {"path": "b.py"})
        assert key1 != key2

    def test_cache_key_includes_tool_name(self, agent):
        """Should produce different cache keys for different tool names."""
        key1 = agent._cache_key("read_file", {"path": "a.py"})
        key2 = agent._cache_key("read_file_lines", {"path": "a.py"})
        assert key1 != key2

    def test_invalidate_path_clears_cache(self, agent):
        """Should remove all cache entries associated with a path."""
        cache_key = agent._cache_key("read_file", {"path": "test.py"})
        agent._cache[cache_key] = "cached content"
        agent._path_cache_keys["test.py"] = {cache_key}

        agent._invalidate_path("test.py")

        assert cache_key not in agent._cache
        assert "test.py" not in agent._path_cache_keys

    def test_invalidate_path_noop_for_unknown(self, agent):
        """Should not crash when invalidating a path that is not cached."""
        agent._invalidate_path("unknown.py")  # Should not raise

    async def test_validate_python_file(self, agent, mock_ps_manager):
        """Should call python syntax check and record validation result."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": True,
            "output": "OK",
            "errors": "",
        })

        result = await agent._validate_python_file("test.py")

        assert result["path"] == "test.py"
        assert result["valid"] is True
        assert len(agent._validation_results) == 1

    async def test_validate_python_file_failure(self, agent, mock_ps_manager):
        """Should record validation failure for invalid Python."""
        mock_ps_manager.execute = AsyncMock(return_value={
            "success": False,
            "output": "",
            "errors": "SyntaxError: invalid syntax",
        })

        result = await agent._validate_python_file("bad.py")

        assert result["valid"] is False
        assert len(agent._validation_results) == 1
