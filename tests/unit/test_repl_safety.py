"""Unit tests validating the 3 safety remediation fixes in repl_manager and local_inference.

Finding 1 (Module load): _SESSION_INIT_TEMPLATE uses try/catch with -ErrorAction Stop.
Finding 2 (Format string hardening): Templates use __LOOM_*__ placeholders with .replace().
Finding 3 (Safety fails-open): review_powershell_command re-raises; _execute_inner blocks.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from loom.powershell_tools.repl_manager import (
    PowerShellREPLManager,
    _EXEC_WRAPPER_TEMPLATE,
    _SESSION_INIT_TEMPLATE,
)
from loom.local_inference import LocalInferenceEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_memory():
    """Minimal mock of a memory engine with an async add_local_insight method."""
    mem = AsyncMock()
    mem.add_local_insight = AsyncMock()
    return mem


@pytest.fixture
def inference_engine(mock_memory):
    """LocalInferenceEngine wired to a mocked memory engine and mocked OpenAI client."""
    eng = LocalInferenceEngine(
        memory_engine=mock_memory,
        ollama_base_url="http://localhost:11434",
        analysis_model="test-model",
        creative_model="test-model",
    )
    # Replace the real AsyncOpenAI client with a mock
    eng._client = _build_mock_client("Default mock response.")
    return eng


@pytest.fixture
def repl_manager(inference_engine):
    """PowerShellREPLManager with a mocked local inference engine and KAN engine."""
    mock_kan = AsyncMock()
    mock_kan.score_risk = AsyncMock(return_value={
        "risk_level": "caution",
        "risk_score": 0.5,
        "model": "kan",
    })
    mock_kan.record_outcome = MagicMock()

    manager = PowerShellREPLManager(
        project_root="/tmp/test-project",
        local_engine=inference_engine,
        memory_engine=None,
        kan_engine=mock_kan,
    )
    return manager


def _build_mock_client(content: str = "mock response"):
    """Return an AsyncMock that behaves like AsyncOpenAI for chat completions."""
    client = AsyncMock()

    mock_message = MagicMock()
    mock_message.content = content

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    client.chat.completions.create = AsyncMock(return_value=mock_response)
    return client


# ===========================================================================
# Group 1: Module Load Tests (Finding 1)
# ===========================================================================


class TestModuleLoad:
    """Verify _SESSION_INIT_TEMPLATE uses robust error handling for Import-Module."""

    def test_session_init_template_uses_error_action_stop(self):
        """Should contain -ErrorAction Stop and NOT contain -ErrorAction SilentlyContinue."""
        assert "-ErrorAction Stop" in _SESSION_INIT_TEMPLATE, (
            "Expected _SESSION_INIT_TEMPLATE to contain '-ErrorAction Stop' "
            "so that module load failures raise terminating errors"
        )
        assert "-ErrorAction SilentlyContinue" not in _SESSION_INIT_TEMPLATE, (
            "Expected _SESSION_INIT_TEMPLATE to NOT contain '-ErrorAction SilentlyContinue' "
            "which would silently swallow Import-Module failures"
        )

    def test_session_init_template_has_try_catch(self):
        """Should wrap Import-Module in PowerShell try/catch blocks."""
        assert "try {" in _SESSION_INIT_TEMPLATE, (
            "Expected _SESSION_INIT_TEMPLATE to contain 'try {' block "
            "wrapping the Import-Module call"
        )
        assert "} catch {" in _SESSION_INIT_TEMPLATE, (
            "Expected _SESSION_INIT_TEMPLATE to contain '} catch {' block "
            "to handle Import-Module failures"
        )

    def test_session_init_template_has_write_warning(self):
        """Should use Write-Warning to notify when module load fails."""
        assert "Write-Warning" in _SESSION_INIT_TEMPLATE, (
            "Expected _SESSION_INIT_TEMPLATE to contain 'Write-Warning' "
            "so that module load failures produce visible warnings"
        )


# ===========================================================================
# Group 2: Format String Hardening Tests (Finding 2)
# ===========================================================================


class TestFormatStringHardening:
    """Verify templates use __LOOM_*__ placeholders with .replace() instead of .format()."""

    def test_exec_wrapper_uses_replace_not_format(self):
        """Should use __LOOM_MARKER__ and __LOOM_SCRIPT__ placeholders, not {marker}/{script}."""
        assert "__LOOM_MARKER__" in _EXEC_WRAPPER_TEMPLATE, (
            "Expected _EXEC_WRAPPER_TEMPLATE to contain '__LOOM_MARKER__' placeholder"
        )
        assert "__LOOM_SCRIPT__" in _EXEC_WRAPPER_TEMPLATE, (
            "Expected _EXEC_WRAPPER_TEMPLATE to contain '__LOOM_SCRIPT__' placeholder"
        )
        # Verify old-style format placeholders are absent
        assert "{marker}" not in _EXEC_WRAPPER_TEMPLATE, (
            "Expected _EXEC_WRAPPER_TEMPLATE to NOT contain '{marker}' format placeholder"
        )
        assert "{script}" not in _EXEC_WRAPPER_TEMPLATE, (
            "Expected _EXEC_WRAPPER_TEMPLATE to NOT contain '{script}' format placeholder"
        )

    def test_exec_wrapper_script_with_braces(self):
        """Should pass through Python-style braces literally when using .replace()."""
        script = 'Write-Host "{marker}" ; Write-Host "{unknown}"'
        result = (
            _EXEC_WRAPPER_TEMPLATE
            .replace("__LOOM_MARKER__", "test_marker_001")
            .replace("__LOOM_SCRIPT__", script)
        )
        # The braces from the user script should survive verbatim
        assert "{marker}" in result, (
            "User script containing '{marker}' should pass through literally"
        )
        assert "{unknown}" in result, (
            "User script containing '{unknown}' should pass through literally"
        )
        # The placeholder should be replaced
        assert "__LOOM_MARKER__" not in result
        assert "__LOOM_SCRIPT__" not in result
        assert "test_marker_001" in result

    def test_exec_wrapper_script_with_curly_braces(self):
        """Should handle PowerShell curly-brace constructs without error."""
        script = '$items | ForEach-Object { $_ }'
        result = (
            _EXEC_WRAPPER_TEMPLATE
            .replace("__LOOM_MARKER__", "boundary_xyz")
            .replace("__LOOM_SCRIPT__", script)
        )
        # The PowerShell expression should appear intact in the output
        assert "ForEach-Object { $_ }" in result, (
            "PowerShell curly-brace expressions should pass through literally"
        )
        assert "boundary_xyz" in result
        assert "__LOOM_MARKER__" not in result
        assert "__LOOM_SCRIPT__" not in result

    def test_session_init_uses_replace_not_format(self):
        """Should use __LOOM_PROJECT_ROOT__ and __LOOM_MODULE_PATH__ placeholders."""
        assert "__LOOM_PROJECT_ROOT__" in _SESSION_INIT_TEMPLATE, (
            "Expected _SESSION_INIT_TEMPLATE to contain '__LOOM_PROJECT_ROOT__' placeholder"
        )
        assert "__LOOM_MODULE_PATH__" in _SESSION_INIT_TEMPLATE, (
            "Expected _SESSION_INIT_TEMPLATE to contain '__LOOM_MODULE_PATH__' placeholder"
        )
        # Verify old-style format placeholders are absent
        assert "{project_root}" not in _SESSION_INIT_TEMPLATE, (
            "Expected _SESSION_INIT_TEMPLATE to NOT contain '{project_root}' format placeholder"
        )
        assert "{module_path}" not in _SESSION_INIT_TEMPLATE, (
            "Expected _SESSION_INIT_TEMPLATE to NOT contain '{module_path}' format placeholder"
        )


# ===========================================================================
# Group 3: Safety Review Tests (Finding 3)
# ===========================================================================


class TestSafetyReview:
    """Verify review_powershell_command re-raises and _execute_inner blocks on failure."""

    async def test_review_powershell_command_reraises_on_failure(self, inference_engine):
        """Should propagate ConnectionError from _chat instead of returning a fallback dict."""
        inference_engine._client.chat.completions.create = AsyncMock(
            side_effect=ConnectionError("Ollama is not running")
        )

        with pytest.raises(ConnectionError, match="Ollama is not running"):
            await inference_engine.review_powershell_command("Get-Process")

    async def test_review_powershell_command_reraises_on_timeout(self, inference_engine):
        """Should propagate asyncio.TimeoutError from _chat instead of returning a fallback dict."""
        inference_engine._client.chat.completions.create = AsyncMock(
            side_effect=asyncio.TimeoutError()
        )

        with pytest.raises(asyncio.TimeoutError):
            await inference_engine.review_powershell_command("Get-ChildItem")

    async def test_execute_inner_blocks_when_safety_unavailable(self, repl_manager):
        """Should return success=False with risk_level=blocked when safety review raises."""
        # Make the local inference engine's review raise ConnectionError
        repl_manager._local_engine.review_powershell_command = AsyncMock(
            side_effect=ConnectionError("Ollama is not running")
        )

        result = await repl_manager._execute_inner(
            script="Get-Process",
            session_id="test",
            timeout=30,
            structured=True,
        )

        assert result["success"] is False, (
            "Expected success=False when safety review is unavailable"
        )
        assert "safety" in result, (
            "Expected result to contain 'safety' key with risk information"
        )
        assert result["safety"]["risk_level"] == "blocked", (
            "Expected safety.risk_level='blocked' when review service is unavailable, "
            f"but got '{result['safety'].get('risk_level')}'"
        )
        assert "blocked" in result.get("errors", "").lower() or "unavailable" in result.get("errors", "").lower(), (
            "Expected error message to indicate the command was blocked due to unavailable safety review"
        )
