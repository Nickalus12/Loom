"""Unit tests for LocalInferenceEngine -- local Ollama inference for background analysis."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
def engine(mock_memory):
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


def _build_mock_client(content: str = "mock response"):
    """Return an AsyncMock that behaves like AsyncOpenAI for chat completions."""
    client = AsyncMock()

    # chat.completions.create -> returns response with choices
    mock_message = MagicMock()
    mock_message.content = content

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_response = MagicMock()
    mock_response.choices = [mock_choice]

    client.chat.completions.create = AsyncMock(return_value=mock_response)

    # models.list -> returns response with data
    mock_model = MagicMock()
    mock_model.id = "test-model"
    mock_models_response = MagicMock()
    mock_models_response.data = [mock_model]
    client.models.list = AsyncMock(return_value=mock_models_response)

    return client


# ---------------------------------------------------------------------------
# Brainstorm
# ---------------------------------------------------------------------------


class TestBrainstorm:
    """Verify brainstorm() delegates to the local model and returns its response."""

    async def test_brainstorm_returns_response(self, engine):
        """Should return the chat completion content string on success."""
        engine._client = _build_mock_client("Use a factory pattern to decouple creation logic.")

        result = await engine.brainstorm("How to refactor this module?")

        assert isinstance(result, str)
        assert "factory pattern" in result.lower()
        engine._client.chat.completions.create.assert_awaited_once()


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


class TestReview:
    """Verify review() returns a structured findings dict with confidence."""

    async def test_review_returns_findings_with_confidence(self, engine):
        """Should return dict with findings, confidence, and file_path keys.
        Confidence should be one of high, medium, or low."""
        engine._client = _build_mock_client(
            "The code is clean with no issues. Solid implementation."
        )

        result = await engine.review("def add(a, b): return a + b", "math_utils.py")

        assert isinstance(result, dict)
        assert "findings" in result
        assert "confidence" in result
        assert "file_path" in result
        assert result["confidence"] in ("high", "medium", "low")
        assert result["file_path"] == "math_utils.py"


# ---------------------------------------------------------------------------
# Debug Assist
# ---------------------------------------------------------------------------


class TestDebugAssist:
    """Verify debug_assist() returns diagnostic suggestions."""

    async def test_debug_assist_returns_suggestions(self, engine):
        """Should return a string containing diagnostic information."""
        engine._client = _build_mock_client(
            "The NoneType error suggests the variable was not initialized before use."
        )

        result = await engine.debug_assist(
            "TypeError: 'NoneType' object is not subscriptable",
            context="Line 42 in data_loader.py",
        )

        assert isinstance(result, str)
        assert "NoneType" in result


# ---------------------------------------------------------------------------
# Confidence Tagger (_tag_confidence)
# ---------------------------------------------------------------------------


class TestConfidenceTagger:
    """Verify _tag_confidence classifies responses by keyword heuristics."""

    def test_confidence_tagger_high(self, engine):
        """Should return 'high' for assertive text with no hedging indicators."""
        response = "The function correctly handles all edge cases. No issues found."
        assert engine._tag_confidence(response) == "high"

    def test_confidence_tagger_medium(self, engine):
        """Should return 'medium' when response contains 3+ medium-indicator words
        like 'likely', 'appears to', 'probably'."""
        response = (
            "This likely indicates a race condition. It appears to be caused by "
            "shared state. The deadlock probably occurs during shutdown. "
            "The pattern suggests a missing lock."
        )
        assert engine._tag_confidence(response) == "medium"

    def test_confidence_tagger_low(self, engine):
        """Should return 'low' when response contains 3+ low-indicator words
        like 'might', 'possibly', 'maybe'."""
        response = (
            "This might be a memory leak, but I'm not sure. It could be "
            "related to the GC. Possibly the finalizer is not running. "
            "Maybe the reference is still held somewhere."
        )
        assert engine._tag_confidence(response) == "low"

    def test_confidence_low_takes_precedence_over_medium(self, engine):
        """Should return 'low' when both low and medium indicators exceed threshold,
        because low is checked first."""
        response = (
            "This might be an issue, possibly caused by something. I'm not sure "
            "but it could be a bug. It likely appears to be a problem that "
            "probably suggests a pattern."
        )
        assert engine._tag_confidence(response) == "low"


# ---------------------------------------------------------------------------
# Analysis Classifier (_classify_analysis)
# ---------------------------------------------------------------------------


class TestClassifyAnalysis:
    """Verify _classify_analysis categorizes text by keyword detection."""

    def test_classify_analysis_bug(self, engine):
        """Should return 'bug' when text contains bug-related keywords."""
        assert engine._classify_analysis("There is a potential bug on line 12") == "bug"

    def test_classify_analysis_bug_via_error_keyword(self, engine):
        """Should return 'bug' when text contains 'error'."""
        assert engine._classify_analysis("An error occurs during parsing") == "bug"

    def test_classify_analysis_security(self, engine):
        """Should return 'security' when text contains 'vulnerability'."""
        assert engine._classify_analysis("SQL injection vulnerability detected") == "security"

    def test_classify_analysis_security_via_injection_keyword(self, engine):
        """Should return 'security' when text contains 'injection'."""
        assert engine._classify_analysis("User input injection risk in template") == "security"

    def test_classify_analysis_pattern(self, engine):
        """Should return 'pattern' when text contains 'pattern'."""
        assert engine._classify_analysis("Observer pattern used correctly here") == "pattern"

    def test_classify_analysis_pattern_via_convention_keyword(self, engine):
        """Should return 'pattern' when text contains 'convention'."""
        assert engine._classify_analysis("Follows naming convention for modules") == "pattern"

    def test_classify_analysis_default(self, engine):
        """Should return 'observation' for generic text without trigger keywords."""
        assert engine._classify_analysis("The code is well structured and readable") == "observation"

    def test_classify_analysis_bug_takes_precedence_over_security(self, engine):
        """Should return 'bug' when both bug and security keywords are present,
        because bug is checked first."""
        assert engine._classify_analysis("Bug in the security vulnerability handler") == "bug"


# ---------------------------------------------------------------------------
# Graceful Degradation
# ---------------------------------------------------------------------------


class TestGracefulDegradation:
    """Verify methods return error strings instead of raising when Ollama is unavailable."""

    async def test_brainstorm_returns_error_string_when_ollama_unavailable(self, engine):
        """Should return an error string (not raise) when the OpenAI client fails."""
        engine._client.chat.completions.create = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        result = await engine.brainstorm("Generate ideas")

        assert isinstance(result, str)
        assert "unavailable" in result.lower() or "connection refused" in result.lower()

    async def test_review_returns_error_dict_when_ollama_unavailable(self, engine):
        """Should return a dict with low confidence and error message on failure."""
        engine._client.chat.completions.create = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        result = await engine.review("code", "file.py")

        assert isinstance(result, dict)
        assert result["confidence"] == "low"
        assert "unavailable" in result["findings"].lower() or "connection refused" in result["findings"].lower()
        assert result["file_path"] == "file.py"

    async def test_debug_assist_returns_error_string_when_ollama_unavailable(self, engine):
        """Should return an error string (not raise) when the OpenAI client fails."""
        engine._client.chat.completions.create = AsyncMock(
            side_effect=Exception("Connection refused")
        )

        result = await engine.debug_assist("SomeError: something broke")

        assert isinstance(result, str)
        assert "unavailable" in result.lower() or "connection refused" in result.lower()


# ---------------------------------------------------------------------------
# Background Worker Lifecycle
# ---------------------------------------------------------------------------


class TestBackgroundWorker:
    """Verify background worker start/stop lifecycle management."""

    async def test_background_worker_starts_and_stops(self, engine):
        """Should set _running=True and create a task on start, then
        set _running=False and clear the task on stop."""
        # Patch _worker_loop so it does not actually poll git
        with patch.object(engine, "_worker_loop", new_callable=AsyncMock):
            await engine.start_background_worker()

            assert engine._running is True
            assert engine._worker_task is not None

            await engine.stop_background_worker()

            assert engine._running is False
            assert engine._worker_task is None

    async def test_stop_worker_is_noop_when_not_started(self, engine):
        """Should handle stop gracefully even if the worker was never started."""
        assert engine._worker_task is None
        await engine.stop_background_worker()
        assert engine._running is False
        assert engine._worker_task is None


# ---------------------------------------------------------------------------
# Get Status
# ---------------------------------------------------------------------------


class TestGetStatus:
    """Verify get_status() reports engine state including model availability."""

    async def test_get_status_reports_state(self, engine):
        """Should return dict with available, models_loaded, worker_active,
        last_analysis, and ollama_url keys."""
        result = await engine.get_status()

        assert isinstance(result, dict)
        assert "available" in result
        assert "models_loaded" in result
        assert "worker_active" in result
        assert "last_analysis" in result
        assert "ollama_url" in result

        assert result["available"] is True
        assert "test-model" in result["models_loaded"]
        assert result["worker_active"] is False
        assert result["last_analysis"] is None
        assert result["ollama_url"] == "http://localhost:11434"

    async def test_get_status_unavailable_when_models_list_fails(self, engine):
        """Should report available=False when the models.list() call raises."""
        engine._client.models.list = AsyncMock(side_effect=Exception("connection error"))

        result = await engine.get_status()

        assert result["available"] is False
        assert result["models_loaded"] == []


# ---------------------------------------------------------------------------
# Poll Changes
# ---------------------------------------------------------------------------


class TestPollChanges:
    """Verify _poll_changes() uses git to detect changed code files."""

    async def test_poll_changes_returns_modified_code_files(self, engine):
        """Should return only code files (.py, .js, .ts, .tsx, .jsx) from git diff output."""

        async def _mock_subprocess(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            cmd_args = args
            if "rev-parse" in cmd_args:
                proc.communicate = AsyncMock(return_value=(b"abc123\n", b""))
            elif "diff" in cmd_args:
                diff_output = (
                    "src/main.py\n"
                    "src/utils.js\n"
                    "README.md\n"
                    "config.yaml\n"
                    "src/types.ts\n"
                    "src/app.tsx\n"
                    "src/index.jsx\n"
                    "logo.png\n"
                )
                proc.communicate = AsyncMock(return_value=(diff_output.encode(), b""))
            return proc

        # First call sets _last_seen_commit, so prime it with a different value
        engine._last_seen_commit = "old_commit_hash"

        with patch("asyncio.create_subprocess_exec", side_effect=_mock_subprocess):
            result = await engine._poll_changes()

        assert isinstance(result, list)
        assert "src/main.py" in result
        assert "src/utils.js" in result
        assert "src/types.ts" in result
        assert "src/app.tsx" in result
        assert "src/index.jsx" in result
        # Non-code files should be filtered out
        assert "README.md" not in result
        assert "config.yaml" not in result
        assert "logo.png" not in result

    async def test_poll_changes_returns_empty_on_first_call(self, engine):
        """Should return empty list on first call (sets baseline commit)."""

        async def _mock_subprocess(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"initial_hash\n", b""))
            return proc

        assert engine._last_seen_commit is None

        with patch("asyncio.create_subprocess_exec", side_effect=_mock_subprocess):
            result = await engine._poll_changes()

        assert result == []
        assert engine._last_seen_commit == "initial_hash"

    async def test_poll_changes_returns_empty_when_no_new_commits(self, engine):
        """Should return empty list when HEAD has not changed since last poll."""

        async def _mock_subprocess(*args, **kwargs):
            proc = AsyncMock()
            proc.returncode = 0
            proc.communicate = AsyncMock(return_value=(b"same_hash\n", b""))
            return proc

        engine._last_seen_commit = "same_hash"

        with patch("asyncio.create_subprocess_exec", side_effect=_mock_subprocess):
            result = await engine._poll_changes()

        assert result == []
