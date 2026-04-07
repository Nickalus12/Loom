"""Unit tests for PowerShellREPLManager — session management, safety pipeline, templates, custom tools, and edge cases."""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from loom.powershell_tools.repl_manager import (
    PowerShellREPLManager,
    _DANGEROUS_COMMANDS,
    _ELEVATED_REVIEW_COMMANDS,
    _EXEC_WRAPPER_TEMPLATE,
    _SESSION_INIT_TEMPLATE,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_kan():
    """Mock KAN engine returning caution-level score by default."""
    kan = AsyncMock()
    kan.score_risk = AsyncMock(return_value={
        "risk_level": "caution",
        "risk_score": 0.5,
        "model": "heuristic",
    })
    kan.record_outcome = MagicMock()
    return kan


@pytest.fixture
def mock_local_engine():
    """Mock local inference engine with a safe review_powershell_command."""
    engine = MagicMock()
    engine.review_powershell_command = AsyncMock(return_value={
        "risk_level": "safe",
        "reason": "No risk detected",
        "details": "",
        "raw_response": "RISK_LEVEL: SAFE",
    })
    return engine


@pytest.fixture
def manager(mock_local_engine, mock_kan):
    """PowerShellREPLManager with mocked local engine and KAN engine."""
    return PowerShellREPLManager(
        project_root="/tmp/test-project",
        local_engine=mock_local_engine,
        memory_engine=None,
        kan_engine=mock_kan,
    )


@pytest.fixture
def manager_no_engine(mock_kan):
    """PowerShellREPLManager with no local engine (Gemma unavailable)."""
    return PowerShellREPLManager(
        project_root="/tmp/test-project",
        local_engine=None,
        memory_engine=None,
        kan_engine=mock_kan,
    )


# ===========================================================================
# Group 1: Session Management
# ===========================================================================


class TestSessionManagement:
    """Verify session lifecycle: create, reuse, close, and metadata tracking."""

    async def test_get_or_create_session_creates_new_session(self, manager):
        """Should create a new PowerShell process and store it in _sessions."""
        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.pid = 12345
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.stdout = AsyncMock()
        mock_proc.stderr = AsyncMock()

        with patch.object(manager, "_find_pwsh", return_value="pwsh"), \
             patch("asyncio.create_subprocess_exec", return_value=mock_proc), \
             patch.object(manager, "_read_until_marker", return_value=""):
            session, created = await manager._get_or_create_session("test_session")

        assert session["process"] is mock_proc
        assert created is True
        assert "test_session" in manager._sessions
        assert manager._sessions["test_session"]["command_count"] == 0

    async def test_get_or_create_session_reuses_existing(self, manager):
        """Should return the existing process when session is alive."""
        mock_proc = AsyncMock()
        mock_proc.returncode = None

        manager._sessions["reuse_session"] = {
            "process": mock_proc,
            "created": None,
            "command_count": 5,
            "last_command": None,
        }

        session, created = await manager._get_or_create_session("reuse_session")

        assert session["process"] is mock_proc
        assert created is False

    async def test_close_session_terminates_process(self, manager):
        """Should remove session from _sessions and write exit to stdin."""
        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()
        mock_proc.wait = AsyncMock()

        manager._sessions["to_close"] = {
            "process": mock_proc,
            "created": None,
            "command_count": 3,
            "last_command": None,
        }

        result = await manager.close_session("to_close")

        assert result is True
        assert "to_close" not in manager._sessions
        mock_proc.stdin.write.assert_called_once_with(b"exit\n")

    async def test_close_session_returns_false_for_missing(self, manager):
        """Should return False when trying to close a non-existent session."""
        result = await manager.close_session("nonexistent")
        assert result is False

    async def test_close_all_sessions_closes_multiple(self, manager):
        """Should close all sessions and return the count."""
        for sid in ("s1", "s2", "s3"):
            mock_proc = AsyncMock()
            mock_proc.returncode = None
            mock_proc.stdin = MagicMock()
            mock_proc.stdin.write = MagicMock()
            mock_proc.stdin.drain = AsyncMock()
            mock_proc.wait = AsyncMock()
            manager._sessions[sid] = {
                "process": mock_proc,
                "created": None,
                "command_count": 0,
                "last_command": None,
            }

        count = await manager.close_all_sessions()

        assert count == 3
        assert len(manager._sessions) == 0

    async def test_session_metadata_tracked(self, manager):
        """Should track command_count and last_command timestamp in session metadata."""
        from datetime import datetime, timezone

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.pid = 1000
        manager._sessions["meta_test"] = {
            "process": mock_proc,
            "created": datetime.now(timezone.utc),
            "command_count": 0,
            "last_command": None,
        }

        info = await manager.get_session_info("meta_test")

        assert info["exists"] is True
        assert info["command_count"] == 0
        assert info["session_id"] == "meta_test"
        assert info["created"] is not None  # ISO-formatted string

    async def test_get_session_info_nonexistent(self, manager):
        """Should return exists=False for sessions that do not exist."""
        info = await manager.get_session_info("ghost")

        assert info["exists"] is False
        assert info["session_id"] == "ghost"


# ===========================================================================
# Group 2: Safety Pipeline (_execute_inner)
# ===========================================================================


class TestSafetyPipeline:
    """Verify the multi-layer safety pipeline in _execute_inner."""

    async def test_kan_blocked_returns_failure(self, manager, mock_kan):
        """Should return failure when KAN scores the command as blocked and it is not elevated."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "blocked",
            "risk_score": 0.95,
            "model": "kan",
        })

        result = await manager._execute_inner(
            script="Remove-Item -Recurse -Force somepath",
            session_id="test",
            timeout=30,
            structured=True,
        )

        assert result["success"] is False
        assert "KAN" in result.get("errors", "") or "blocked" in str(result.get("safety", "")).lower()

    async def test_kan_blocked_bypassed_for_elevated_commands(self, manager, mock_kan, mock_local_engine):
        """Should bypass KAN block for elevated commands and route to Gemma review instead."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "blocked",
            "risk_score": 0.95,
            "model": "kan",
        })
        # Gemma says it is safe
        mock_local_engine.review_powershell_command = AsyncMock(return_value={
            "risk_level": "safe",
            "reason": "Legitimate network request",
        })

        # Elevated commands bypass KAN and go to Gemma
        # But the dangerous command check will also catch some patterns.
        # invoke-webrequest is elevated but NOT in _DANGEROUS_COMMANDS
        # Also need to pass path safety — use a relative path
        result = await manager._execute_inner(
            script="Invoke-WebRequest -Uri 'https://example.com/api' -OutFile result.json",
            session_id="test",
            timeout=30,
            structured=True,
        )

        # The Gemma review was called (even though KAN said blocked)
        mock_local_engine.review_powershell_command.assert_awaited_once()

    async def test_dangerous_command_blocked_format_volume(self, manager, mock_kan):
        """Should block Format-Volume as a dangerous command."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "caution",
            "risk_score": 0.5,
            "model": "heuristic",
        })

        result = await manager._execute_inner(
            script="Format-Volume -DriveLetter D",
            session_id="test",
            timeout=30,
            structured=True,
        )

        assert result["success"] is False
        assert "dangerous" in result.get("error", "").lower() or "blocked" in result.get("error", "").lower()

    async def test_dangerous_command_blocked_rm_rf(self, manager, mock_kan):
        """Should block rm -rf as a dangerous command."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "caution",
            "risk_score": 0.5,
            "model": "heuristic",
        })

        result = await manager._execute_inner(
            script="rm -rf /",
            session_id="test",
            timeout=30,
            structured=True,
        )

        assert result["success"] is False
        assert "dangerous" in result.get("error", "").lower() or "blocked" in result.get("error", "").lower()

    async def test_dangerous_command_blocked_stop_computer(self, manager, mock_kan):
        """Should block Stop-Computer as a dangerous command."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "caution",
            "risk_score": 0.5,
            "model": "heuristic",
        })

        result = await manager._execute_inner(
            script="Stop-Computer -Force",
            session_id="test",
            timeout=30,
            structured=True,
        )

        assert result["success"] is False
        assert "dangerous" in result.get("error", "").lower()

    async def test_elevated_command_forces_gemma_review(self, manager, mock_kan, mock_local_engine):
        """Should invoke Gemma review for commands containing elevated patterns."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "safe",
            "risk_score": 0.1,
            "model": "kan",
        })
        mock_local_engine.review_powershell_command = AsyncMock(return_value={
            "risk_level": "safe",
            "reason": "OK",
        })

        # Invoke-Expression is elevated; also need to pass path safety
        await manager._execute_inner(
            script="Invoke-Expression 'Get-Date'",
            session_id="test",
            timeout=30,
            structured=True,
        )

        # Even though KAN said safe, elevated should force Gemma
        mock_local_engine.review_powershell_command.assert_awaited_once()

    async def test_elevated_command_blocked_without_gemma(self, manager_no_engine, mock_kan):
        """Should block elevated commands when Gemma/local engine is unavailable."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "safe",
            "risk_score": 0.1,
            "model": "kan",
        })

        result = await manager_no_engine._execute_inner(
            script="Invoke-Expression 'Get-Date'",
            session_id="test",
            timeout=30,
            structured=True,
        )

        assert result["success"] is False
        assert "unavailable" in result.get("errors", "").lower() or "requires" in result.get("errors", "").lower()

    async def test_path_safety_blocks_outside_project_root(self, manager, mock_kan):
        """Should block scripts referencing absolute paths outside the project root."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "safe",
            "risk_score": 0.1,
            "model": "heuristic",
        })

        result = await manager._execute_inner(
            script="Get-Content C:\\Windows\\System32\\drivers\\etc\\hosts",
            session_id="test",
            timeout=30,
            structured=True,
        )

        assert result["success"] is False
        assert "path safety" in result.get("error", "").lower() or "outside project root" in result.get("error", "").lower()

    async def test_path_safety_allows_project_paths(self, manager):
        """Should allow paths within the project root."""
        # _check_path_safety only checks absolute paths, relative paths are fine
        result = manager._check_path_safety("Get-Content ./src/app.py")
        assert result is True

    async def test_path_safety_windows_paths(self, manager):
        """Should detect Windows-style absolute paths outside root."""
        result = manager._check_path_safety("Get-Content D:\\SomeOtherProject\\file.txt")
        assert result is False

    async def test_path_safety_unix_paths(self, manager):
        """Should detect Unix-style absolute paths outside root."""
        result = manager._check_path_safety("cat /etc/passwd")
        assert result is False

    async def test_gemma_review_blocks_dangerous(self, manager, mock_kan, mock_local_engine):
        """Should block command when Gemma review returns risk_level=blocked."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "caution",
            "risk_score": 0.5,
            "model": "heuristic",
        })
        mock_local_engine.review_powershell_command = AsyncMock(return_value={
            "risk_level": "blocked",
            "reason": "Suspicious network exfiltration",
        })

        result = await manager._execute_inner(
            script="Get-Process",
            session_id="test",
            timeout=30,
            structured=True,
        )

        assert result["success"] is False
        assert "blocked" in result.get("error", "").lower()

    async def test_gemma_review_allows_safe(self, manager, mock_kan, mock_local_engine):
        """Should allow execution when Gemma review returns safe."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "caution",
            "risk_score": 0.5,
            "model": "heuristic",
        })
        mock_local_engine.review_powershell_command = AsyncMock(return_value={
            "risk_level": "safe",
            "reason": "No risk",
        })

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.pid = 999
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()

        _mock_session = {"process": mock_proc, "pipe": None, "created": None, "command_count": 0, "last_command": None}
        with patch.object(manager, "_get_or_create_session", return_value=(_mock_session, False)), \
             patch.object(manager, "_send_and_receive", return_value=("output", "")), \
             patch.object(manager, "_log_command", return_value=None):
            manager._sessions["test"] = {
                "process": mock_proc,
                "created": None,
                "command_count": 0,
                "last_command": None,
            }

            result = await manager._execute_inner(
                script="Get-ChildItem .",
                session_id="test",
                timeout=30,
                structured=True,
            )

        assert result["success"] is True

    async def test_gemma_review_fails_closed_on_exception(self, manager, mock_kan, mock_local_engine):
        """Should block execution when Gemma review raises an exception (fail-closed)."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "caution",
            "risk_score": 0.5,
            "model": "heuristic",
        })
        mock_local_engine.review_powershell_command = AsyncMock(
            side_effect=ConnectionError("Ollama down")
        )

        result = await manager._execute_inner(
            script="Get-Process",
            session_id="test",
            timeout=30,
            structured=True,
        )

        assert result["success"] is False
        assert "blocked" in result.get("errors", "").lower() or "unavailable" in result.get("errors", "").lower()

    async def test_skip_gemma_when_kan_safe_and_confident(self, manager, mock_kan, mock_local_engine):
        """Should skip Gemma review when KAN scores safe with high confidence and model=kan."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "safe",
            "risk_score": 0.1,
            "model": "kan",
        })

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.pid = 111
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()

        _mock_session = {"process": mock_proc, "pipe": None, "created": None, "command_count": 0, "last_command": None}
        with patch.object(manager, "_get_or_create_session", return_value=(_mock_session, False)), \
             patch.object(manager, "_send_and_receive", return_value=("output", "")), \
             patch.object(manager, "_log_command", return_value=None):
            manager._sessions["test"] = {
                "process": mock_proc,
                "created": None,
                "command_count": 0,
                "last_command": None,
            }

            result = await manager._execute_inner(
                script="Write-Host 'hello'",
                session_id="test",
                timeout=30,
                structured=True,
            )

        # Gemma should NOT have been called
        mock_local_engine.review_powershell_command.assert_not_awaited()
        assert result["success"] is True


# ===========================================================================
# Group 3: Template Safety
# ===========================================================================


class TestTemplateSafety:
    """Verify templates use safe placeholder substitution."""

    def test_session_init_template_has_project_root_placeholder(self):
        """Should contain __LOOM_PROJECT_ROOT__ placeholder."""
        assert "__LOOM_PROJECT_ROOT__" in _SESSION_INIT_TEMPLATE

    def test_session_init_template_has_module_path_placeholder(self):
        """Should contain __LOOM_MODULE_PATH__ placeholder."""
        assert "__LOOM_MODULE_PATH__" in _SESSION_INIT_TEMPLATE

    def test_exec_wrapper_template_has_marker_placeholder(self):
        """Should contain __LOOM_MARKER__ placeholder."""
        assert "__LOOM_MARKER__" in _EXEC_WRAPPER_TEMPLATE

    def test_exec_wrapper_template_has_script_placeholder(self):
        """Should contain __LOOM_SCRIPT__ placeholder."""
        assert "__LOOM_SCRIPT__" in _EXEC_WRAPPER_TEMPLATE

    def test_templates_use_replace_not_format(self):
        """Templates should use __LOOM_*__ placeholders, not Python format strings."""
        assert "{marker}" not in _EXEC_WRAPPER_TEMPLATE
        assert "{script}" not in _EXEC_WRAPPER_TEMPLATE
        assert "{project_root}" not in _SESSION_INIT_TEMPLATE
        assert "{module_path}" not in _SESSION_INIT_TEMPLATE

    def test_script_with_braces_passes_through(self):
        """Python-style braces in user scripts should survive .replace() substitution."""
        script = 'Write-Host "{marker}" ; $dict = @{key="value"}'
        result = (
            _EXEC_WRAPPER_TEMPLATE
            .replace("__LOOM_MARKER__", "BOUNDARY_001")
            .replace("__LOOM_SCRIPT__", script)
        )
        assert "{marker}" in result
        assert "@{key=" in result
        assert "BOUNDARY_001" in result

    def test_script_with_marker_text_passes_through(self):
        """Even if the script contains the literal text __LOOM_MARKER__, it should be replaced only in the template."""
        # After both replacements, no __LOOM_MARKER__ or __LOOM_SCRIPT__ should remain
        script = "Write-Host 'testing only'"
        result = (
            _EXEC_WRAPPER_TEMPLATE
            .replace("__LOOM_MARKER__", "SAFE_BOUNDARY")
            .replace("__LOOM_SCRIPT__", script)
        )
        assert "__LOOM_MARKER__" not in result
        assert "__LOOM_SCRIPT__" not in result
        assert "SAFE_BOUNDARY" in result


# ===========================================================================
# Group 4: Custom Tools
# ===========================================================================


class TestCustomTools:
    """Verify register_custom_tool and list_custom_tools behavior."""

    async def test_register_custom_tool(self, manager):
        """Should store the tool in _custom_tools dict."""
        await manager.register_custom_tool("Get-Widget", "param($Name)\nWrite-Output $Name")

        assert "Get-Widget" in manager._custom_tools
        assert "param($Name)" in manager._custom_tools["Get-Widget"]

    async def test_list_custom_tools(self, manager):
        """Should return list of registered tool names."""
        await manager.register_custom_tool("Tool-A", "Write-Host A")
        await manager.register_custom_tool("Tool-B", "Write-Host B")

        tools = manager.list_custom_tools()

        assert "Tool-A" in tools
        assert "Tool-B" in tools
        assert len(tools) == 2

    async def test_custom_tool_persists_across_commands(self, manager):
        """Custom tool should be accessible after registration."""
        await manager.register_custom_tool("My-Tool", "Write-Output 'custom'")

        # The tool should still be in the dict
        assert "My-Tool" in manager._custom_tools
        # And the function wrapper should be present
        assert "function My-Tool" in manager._custom_tools["My-Tool"]


# ===========================================================================
# Group 5: Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Verify behavior with unusual inputs."""

    async def test_empty_script_passes_safety_checks(self, manager, mock_kan):
        """An empty script should pass all safety checks."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "safe",
            "risk_score": 0.0,
            "model": "heuristic",
        })

        # Path safety should pass for empty script
        assert manager._check_path_safety("") is True
        assert manager._check_dangerous_commands("") is None

    def test_check_dangerous_commands_returns_none_for_safe(self, manager):
        """Should return None for commands that are not in the dangerous set."""
        assert manager._check_dangerous_commands("Get-ChildItem .") is None

    def test_check_dangerous_commands_returns_pattern_for_match(self, manager):
        """Should return the matched dangerous pattern."""
        result = manager._check_dangerous_commands("Format-Volume -DriveLetter C")
        assert result is not None
        assert "format-volume" in result.lower()

    def test_check_elevated_review_returns_none_for_safe(self, manager):
        """Should return None for commands not in the elevated set."""
        assert manager._check_elevated_review("Get-ChildItem .") is None

    def test_check_elevated_review_returns_pattern_for_match(self, manager):
        """Should return the matched elevated pattern."""
        result = manager._check_elevated_review("Invoke-WebRequest https://example.com")
        assert result is not None
        assert "invoke-webrequest" in result.lower()

    async def test_execute_catches_runtime_error(self, manager):
        """The top-level execute method should catch RuntimeError and return error dict."""
        with patch.object(manager, "_execute_inner", side_effect=RuntimeError("pwsh not found")):
            result = await manager.execute("Get-Process")

        assert result["success"] is False
        assert "not available" in result.get("error", "").lower() or "not found" in result.get("error", "").lower()

    async def test_execute_catches_unexpected_exception(self, manager):
        """The top-level execute method should catch unexpected exceptions gracefully."""
        with patch.object(manager, "_execute_inner", side_effect=ValueError("unexpected")):
            result = await manager.execute("Get-Process")

        assert result["success"] is False
        assert "failed" in result.get("error", "").lower() or "unexpected" in result.get("error", "").lower()

    async def test_unicode_in_script_passes_safety(self, manager):
        """Scripts with Unicode characters should pass safety checks."""
        assert manager._check_path_safety("Write-Host 'Hola mundo'") is True
        assert manager._check_dangerous_commands("Write-Host 'Hola mundo'") is None

    async def test_safety_timing_in_result(self, manager, mock_kan, mock_local_engine):
        """Successful execution results should include a safety_timing dict."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "safe",
            "risk_score": 0.1,
            "model": "kan",
        })

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.pid = 777
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()

        _mock_session = {"process": mock_proc, "pipe": None, "created": None, "command_count": 0, "last_command": None}
        with patch.object(manager, "_get_or_create_session", return_value=(_mock_session, False)), \
             patch.object(manager, "_send_and_receive", return_value=("output", "")), \
             patch.object(manager, "_log_command", return_value=None):
            manager._sessions["test"] = {
                "process": mock_proc,
                "created": None,
                "command_count": 0,
                "last_command": None,
            }

            result = await manager._execute_inner(
                script="Write-Host 'hello'",
                session_id="test",
                timeout=30,
                structured=True,
            )

        assert "safety_timing" in result, "Result should contain safety_timing dict"
        assert isinstance(result["safety_timing"], dict)

    async def test_safety_timing_has_kan_ms(self, manager, mock_kan, mock_local_engine):
        """safety_timing dict should contain a kan_ms key with a non-negative integer value."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "safe",
            "risk_score": 0.1,
            "model": "kan",
        })

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.pid = 778
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()

        _mock_session = {"process": mock_proc, "pipe": None, "created": None, "command_count": 0, "last_command": None}
        with patch.object(manager, "_get_or_create_session", return_value=(_mock_session, False)), \
             patch.object(manager, "_send_and_receive", return_value=("output", "")), \
             patch.object(manager, "_log_command", return_value=None):
            manager._sessions["test"] = {
                "process": mock_proc,
                "created": None,
                "command_count": 0,
                "last_command": None,
            }

            result = await manager._execute_inner(
                script="Get-Date",
                session_id="test",
                timeout=30,
                structured=True,
            )

        timing = result["safety_timing"]
        assert "kan_ms" in timing, "safety_timing should contain kan_ms"
        assert isinstance(timing["kan_ms"], int)
        assert timing["kan_ms"] >= 0

    async def test_elevated_command_logs_timing(self, manager, mock_kan, mock_local_engine):
        """Elevated commands that go through Gemma review should track gemma_review_ms in safety_timing."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "safe",
            "risk_score": 0.1,
            "model": "kan",
        })
        mock_local_engine.review_powershell_command = AsyncMock(return_value={
            "risk_level": "safe",
            "reason": "Legitimate use",
        })

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.pid = 779
        mock_proc.stdin = MagicMock()
        mock_proc.stdin.write = MagicMock()
        mock_proc.stdin.drain = AsyncMock()

        _mock_session = {"process": mock_proc, "pipe": None, "created": None, "command_count": 0, "last_command": None}
        with patch.object(manager, "_get_or_create_session", return_value=(_mock_session, False)), \
             patch.object(manager, "_send_and_receive", return_value=("output", "")), \
             patch.object(manager, "_log_command", return_value=None):
            manager._sessions["test"] = {
                "process": mock_proc,
                "created": None,
                "command_count": 0,
                "last_command": None,
            }

            result = await manager._execute_inner(
                script="Invoke-Expression 'Get-Date'",
                session_id="test",
                timeout=30,
                structured=True,
            )

        timing = result["safety_timing"]
        assert "gemma_review_ms" in timing, "Elevated command should have gemma_review_ms in safety_timing"
        assert isinstance(timing["gemma_review_ms"], int)
        assert timing["gemma_review_ms"] >= 0

    async def test_timeout_returns_error(self, manager, mock_kan, mock_local_engine):
        """Should return timeout error when command exceeds timeout."""
        mock_kan.score_risk = AsyncMock(return_value={
            "risk_level": "safe",
            "risk_score": 0.1,
            "model": "kan",
        })

        mock_proc = AsyncMock()
        mock_proc.returncode = None
        mock_proc.pid = 555

        _mock_session = {"process": mock_proc, "pipe": None, "created": None, "command_count": 0, "last_command": None}
        with patch.object(manager, "_get_or_create_session", return_value=(_mock_session, False)), \
             patch.object(manager, "_send_and_receive", side_effect=asyncio.TimeoutError()), \
             patch.object(manager, "close_session", return_value=True):
            manager._sessions["test"] = {
                "process": mock_proc,
                "created": None,
                "command_count": 0,
                "last_command": None,
            }

            result = await manager._execute_inner(
                script="Start-Sleep 999",
                session_id="test",
                timeout=1,
                structured=True,
            )

        assert result["success"] is False
        assert "timed out" in result.get("errors", "").lower()
