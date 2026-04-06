"""Unit tests for LocalAgent -- multi-turn agent loop with tool calling, caching, and git safety.

Call-flow reference for mock setup:
- Non-qwen3 agent (tool_model != analysis_model): planning(1) + loop turns(N) + analysis(1) = N+2 LLM calls
- Non-qwen3 agent (tool_model == analysis_model): planning(1) + loop turns(N) = N+1 LLM calls
- Qwen3 agent (tool_model != analysis_model): loop turns(N) + analysis(1) = N+1 LLM calls
- Qwen3 agent (tool_model == analysis_model): loop turns(N) = N LLM calls

ps_manager.execute is only called by tool execution, git branch, git diff, and validation.
The planning turn and analysis turn only call self._client.chat.completions.create.
"""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from loom.local_agent import LocalAgent, AgentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_tool_call_response(tool_calls=None, content=None):
    """Create a mock OpenAI response with optional tool calls.

    Each entry in *tool_calls* should be a dict with 'name' and optionally 'args'.
    """
    msg = MagicMock()
    msg.content = content or ""
    if tool_calls:
        tc_mocks = []
        for i, tc in enumerate(tool_calls):
            func_mock = MagicMock()
            # MagicMock(name=...) sets the mock's internal name, not .name attribute.
            # We must set .name explicitly after construction.
            func_mock.name = tc["name"]
            func_mock.arguments = json.dumps(tc.get("args", {}))
            tc_mock = MagicMock()
            tc_mock.id = f"call_{i}"
            tc_mock.function = func_mock
            tc_mocks.append(tc_mock)
        msg.tool_calls = tc_mocks
    else:
        msg.tool_calls = None

    choice = MagicMock()
    choice.message = msg

    response = MagicMock()
    response.choices = [choice]
    return response


def make_final_response(content="Done."):
    """Create a mock OpenAI response with no tool calls (terminal turn)."""
    return make_tool_call_response(tool_calls=None, content=content)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ps_manager():
    """Mock PowerShellREPLManager with a default-successful execute method."""
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
    engine._client.chat.completions.create = AsyncMock(return_value=make_final_response())
    engine._analysis_model = "test-analysis-model"
    return engine


@pytest.fixture
def mock_memory():
    """Mock Graphiti-backed memory engine for session memory."""
    mem = MagicMock()
    mem.memory = AsyncMock()
    mem.memory.search = AsyncMock(return_value=[])
    mem.memory.add_episode = AsyncMock()
    return mem


@pytest.fixture
def agent(mock_inference_engine, mock_ps_manager, mock_memory):
    """LocalAgent wired to all mocks with distinct tool and analysis models.

    Call flow: planning(1) + loop(N) + analysis(1) = N+2 LLM calls.
    """
    return LocalAgent(
        inference_engine=mock_inference_engine,
        ps_manager=mock_ps_manager,
        memory_engine=mock_memory,
        tool_model="test-tool-model",
        analysis_model="test-analysis-model",
        max_turns=5,
    )


@pytest.fixture
def qwen3_agent(mock_inference_engine, mock_ps_manager, mock_memory):
    """LocalAgent whose tool_model is qwen3 (triggers thinking prompt, skips planning).

    Call flow: loop(N) + analysis(1) = N+1 LLM calls.
    """
    return LocalAgent(
        inference_engine=mock_inference_engine,
        ps_manager=mock_ps_manager,
        memory_engine=mock_memory,
        tool_model="qwen3:4b",
        analysis_model="test-analysis-model",
        max_turns=5,
    )


@pytest.fixture
def same_model_agent(mock_inference_engine, mock_ps_manager, mock_memory):
    """LocalAgent where tool_model == analysis_model (no analysis turn).

    Call flow: planning(1) + loop(N) = N+1 LLM calls.
    """
    return LocalAgent(
        inference_engine=mock_inference_engine,
        ps_manager=mock_ps_manager,
        memory_engine=mock_memory,
        tool_model="same-model",
        analysis_model="same-model",
        max_turns=5,
    )


@pytest.fixture
def qwen3_same_model_agent(mock_inference_engine, mock_ps_manager, mock_memory):
    """Qwen3 agent where tool_model == analysis_model (no planning, no analysis).

    Call flow: loop(N) = N LLM calls.
    """
    return LocalAgent(
        inference_engine=mock_inference_engine,
        ps_manager=mock_ps_manager,
        memory_engine=mock_memory,
        tool_model="qwen3:4b",
        analysis_model="qwen3:4b",
        max_turns=5,
    )


# ---------------------------------------------------------------------------
# 1. TestEditTool
# ---------------------------------------------------------------------------


class TestEditTool:
    """Verify the edit_file tool reads, replaces, and writes back file content."""

    async def test_edit_file_replaces_text(self, agent, mock_ps_manager):
        """Should read the file, replace old_text with new_text, and write the result."""
        file_content = "1\tdef hello():\n2\t    return 'world'"
        edit_args = {
            "path": "src/app.py",
            "old_text": "return 'world'",
            "new_text": "return 'universe'",
        }

        # LLM calls: planning(1) + tool_turn(1) + final_turn(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan: edit file."),          # planning
                make_tool_call_response([{"name": "edit_file", "args": edit_args}]),  # loop turn 0
                make_final_response("Edit complete."),            # loop turn 1 (no tools)
                make_final_response("Synthesis."),                # analysis turn
            ]
        )

        executed_commands = []

        async def track_execute(cmd, timeout=None):
            executed_commands.append(cmd)
            if "git checkout" in cmd:
                return {"success": True, "output": "", "errors": ""}
            if "Read-LoomFile" in cmd:
                return {"success": True, "output": file_content, "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            if "python -c" in cmd:
                return {"success": True, "output": "OK", "errors": ""}
            if "git diff" in cmd:
                return {"success": True, "output": "1 file changed", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=track_execute)

        result = await agent.run("Edit hello function")

        assert result["success"] is True
        # Verify Write-LoomFile was called with the replaced content
        write_call_args = [c for c in executed_commands if "Write-LoomFile" in c]
        assert len(write_call_args) >= 1
        assert "universe" in write_call_args[0]

    async def test_edit_file_old_text_not_found(self, agent, mock_ps_manager):
        """Should return an error JSON when old_text is not present in the file."""
        file_content = "1\tdef hello():\n2\t    return 'world'"
        edit_args = {
            "path": "src/app.py",
            "old_text": "NONEXISTENT_TEXT",
            "new_text": "replacement",
        }

        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([{"name": "edit_file", "args": edit_args}]),
                make_final_response("Could not edit."),
                make_final_response("Synthesis."),
            ]
        )

        executed_commands = []

        async def track_execute(cmd, timeout=None):
            executed_commands.append(cmd)
            if "git checkout" in cmd:
                return {"success": True, "output": "", "errors": ""}
            if "Read-LoomFile" in cmd:
                return {"success": True, "output": file_content, "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=track_execute)

        result = await agent.run("Edit something")

        assert result["success"] is True
        edit_log = [e for e in result["tool_log"] if e["tool"] == "edit_file"]
        assert len(edit_log) == 1
        assert "not found" in edit_log[0]["result_preview"].lower()

    async def test_edit_file_invalidates_cache(self, agent, mock_ps_manager):
        """After a successful edit, the read cache for that path should be cleared."""
        file_content = "1\tprint('hello')"
        read_args = {"path": "src/app.py"}
        edit_args = {
            "path": "src/app.py",
            "old_text": "print('hello')",
            "new_text": "print('bye')",
        }

        # LLM: planning(1) + turn0(read+edit) + turn1(read) + turn2(final) + analysis(1) = 5
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                # Turn 0: read then edit
                make_tool_call_response([
                    {"name": "read_file", "args": read_args},
                    {"name": "edit_file", "args": edit_args},
                ]),
                # Turn 1: read again (should NOT be cached after edit invalidation)
                make_tool_call_response([
                    {"name": "read_file", "args": read_args},
                ]),
                make_final_response("Done."),
                make_final_response("Synthesis."),
            ]
        )

        async def track_execute(cmd, timeout=None):
            if "git checkout" in cmd:
                return {"success": True, "output": "", "errors": ""}
            if "Read-LoomFile" in cmd:
                return {"success": True, "output": file_content, "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            if "python -c" in cmd:
                return {"success": True, "output": "OK", "errors": ""}
            if "git diff" in cmd:
                return {"success": True, "output": "1 file changed", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=track_execute)

        result = await agent.run("Read edit read")

        read_logs = [e for e in result["tool_log"] if e["tool"] == "read_file"]
        assert len(read_logs) == 2
        assert read_logs[0]["cached"] is False  # first read: miss
        assert read_logs[1]["cached"] is False  # second read: cache invalidated by edit


# ---------------------------------------------------------------------------
# 2. TestPlanningStep
# ---------------------------------------------------------------------------


class TestPlanningStep:
    """Verify planning behavior differs between qwen3 and non-qwen3 models."""

    async def test_qwen3_system_prompt_includes_thinking(self, qwen3_agent):
        """When tool_model contains 'qwen3', the system prompt should include thinking instructions."""
        captured_messages = []

        async def capture_create(**kwargs):
            captured_messages.append(kwargs.get("messages", []))
            return make_final_response("Task done.")

        qwen3_agent._client.chat.completions.create = AsyncMock(side_effect=capture_create)

        await qwen3_agent.run("Test task")

        # The first call (tool loop, no planning for qwen3) should have thinking in system msg
        assert len(captured_messages) >= 1
        system_msg = captured_messages[0][0]["content"]
        assert "thinking" in system_msg.lower()

    async def test_non_qwen3_runs_planning_turn(self, agent):
        """When tool_model does NOT contain 'qwen3', a planning call should be made."""
        call_models = []

        async def capture_create(**kwargs):
            call_models.append(kwargs.get("model", ""))
            return make_final_response("Planned or done.")

        agent._client.chat.completions.create = AsyncMock(side_effect=capture_create)

        await agent.run("Some task")

        # call_models: planning(analysis_model) + loop(tool_model) + analysis(analysis_model) = 3
        assert len(call_models) >= 2
        assert call_models[0] == "test-analysis-model"  # planning turn
        assert call_models[1] == "test-tool-model"       # agent loop

    async def test_qwen3_skips_planning_turn(self, qwen3_agent):
        """When tool_model contains 'qwen3', no separate planning call should be made."""
        call_models = []

        async def capture_create(**kwargs):
            call_models.append(kwargs.get("model", ""))
            return make_final_response("Done.")

        qwen3_agent._client.chat.completions.create = AsyncMock(side_effect=capture_create)

        await qwen3_agent.run("Some task")

        # For qwen3: loop(tool_model) + analysis(analysis_model) = 2 calls
        # First call should be tool_model (no planning preceding it)
        assert call_models[0] == "qwen3:4b"
        # No planning call to analysis_model before the tool loop
        assert call_models[0] != "test-analysis-model"


# ---------------------------------------------------------------------------
# 3. TestGitSafety
# ---------------------------------------------------------------------------


class TestGitSafety:
    """Verify git branch creation only for file-mutating tools and git diff on completion."""

    async def test_git_branch_created_before_write(self, agent, mock_ps_manager):
        """Should create a git branch before executing a write_file tool call."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan: write a file."),
                make_tool_call_response([
                    {"name": "write_file", "args": {"path": "new.py", "content": "x = 1"}}
                ]),
                make_final_response("File written."),
                make_final_response("Synthesis."),
            ]
        )

        executed_commands = []

        async def track_execute(cmd, timeout=None):
            executed_commands.append(cmd)
            if "git checkout" in cmd:
                return {"success": True, "output": "", "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            if "python -c" in cmd:
                return {"success": True, "output": "OK", "errors": ""}
            if "git diff" in cmd:
                return {"success": True, "output": "1 file changed", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=track_execute)

        result = await agent.run("Create a file")

        git_idx = next(
            (i for i, c in enumerate(executed_commands) if "git checkout" in c), None
        )
        write_idx = next(
            (i for i, c in enumerate(executed_commands) if "Write-LoomFile" in c), None
        )
        assert git_idx is not None, "Expected git checkout to be called"
        assert write_idx is not None, "Expected Write-LoomFile to be called"
        assert git_idx < write_idx, "git checkout should happen before Write-LoomFile"
        assert result["git_branch"] is not None

    async def test_no_branch_for_read_only_tasks(self, agent, mock_ps_manager):
        """Should NOT create a git branch when only read tools are called."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan: read file."),
                make_tool_call_response([
                    {"name": "read_file", "args": {"path": "src/app.py"}}
                ]),
                make_final_response("File contents reviewed."),
                make_final_response("Synthesis."),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={"success": True, "output": "1\tprint('hi')", "errors": ""}
        )

        result = await agent.run("Read a file")

        assert result["git_branch"] is None
        git_calls = [
            call for call in mock_ps_manager.execute.call_args_list
            if "git checkout" in str(call)
        ]
        assert len(git_calls) == 0

    async def test_git_diff_on_completion(self, agent, mock_ps_manager):
        """When a git branch was created, git diff should be called at the end."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan: write."),
                make_tool_call_response([
                    {"name": "write_file", "args": {"path": "x.py", "content": "a=1"}}
                ]),
                make_final_response("Done."),
                make_final_response("Synthesis."),
            ]
        )

        executed_commands = []

        async def track_execute(cmd, timeout=None):
            executed_commands.append(cmd)
            if "git checkout" in cmd:
                return {"success": True, "output": "", "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            if "python -c" in cmd:
                return {"success": True, "output": "OK", "errors": ""}
            if "git diff" in cmd:
                return {"success": True, "output": "1 file changed, 1 insertion", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=track_execute)

        result = await agent.run("Write something")

        assert result["git_diff"] is not None
        assert "1 file changed" in result["git_diff"]
        diff_calls = [c for c in executed_commands if "git diff" in c]
        assert len(diff_calls) == 1


# ---------------------------------------------------------------------------
# 4. TestDualModel
# ---------------------------------------------------------------------------


class TestDualModel:
    """Verify tool turns use tool_model and analysis turn uses analysis_model."""

    async def test_tool_turns_use_tool_model(self, agent):
        """The main agent loop LLM call should use tool_model."""
        call_models = []

        async def capture_create(**kwargs):
            call_models.append(kwargs.get("model", ""))
            return make_final_response("Done.")

        agent._client.chat.completions.create = AsyncMock(side_effect=capture_create)

        await agent.run("Do something")

        # planning(analysis), loop(tool), analysis(analysis) -> 3 calls
        assert "test-tool-model" in call_models

    async def test_analysis_turn_uses_analysis_model(self, agent):
        """When tool_model != analysis_model, the final synthesis should use analysis_model."""
        call_models = []

        async def capture_create(**kwargs):
            call_models.append(kwargs.get("model", ""))
            return make_final_response("Synthesis complete.")

        agent._client.chat.completions.create = AsyncMock(side_effect=capture_create)

        await agent.run("Analyze code")

        # Planning (analysis_model), tool loop (tool_model), analysis turn (analysis_model) = 3
        assert len(call_models) == 3
        assert call_models[-1] == "test-analysis-model"

    async def test_no_analysis_turn_when_same_model(self, same_model_agent):
        """When tool_model == analysis_model, no separate analysis turn should run."""
        call_count = 0

        async def capture_create(**kwargs):
            nonlocal call_count
            call_count += 1
            return make_final_response("Done.")

        same_model_agent._client.chat.completions.create = AsyncMock(
            side_effect=capture_create
        )

        result = await same_model_agent.run("Do something")

        # planning(1) + loop(1) = 2 calls (no analysis turn)
        assert call_count == 2
        assert result["success"] is True


# ---------------------------------------------------------------------------
# 5. TestChunkedReading
# ---------------------------------------------------------------------------


class TestChunkedReading:
    """Verify read_file_lines returns the correct line range and caches properly."""

    async def test_read_file_lines_returns_range(self, agent, mock_ps_manager):
        """Should return only lines within the requested start/end range."""
        full_content = "\n".join(f"{i}\tline {i}" for i in range(1, 11))

        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan: read lines."),
                make_tool_call_response([{
                    "name": "read_file_lines",
                    "args": {"path": "big.py", "start_line": 3, "end_line": 5},
                }]),
                make_final_response("Lines read."),
                make_final_response("Synthesis."),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={"success": True, "output": full_content, "errors": ""}
        )

        result = await agent.run("Read lines 3-5")

        read_logs = [e for e in result["tool_log"] if e["tool"] == "read_file_lines"]
        assert len(read_logs) == 1
        preview = read_logs[0]["result_preview"]
        assert "line 3" in preview
        assert "line 5" in preview

    async def test_read_file_lines_caches_full_file(self, agent, mock_ps_manager):
        """After read_file_lines, a subsequent read_file_lines for same args should hit cache."""
        full_content = "\n".join(f"{i}\tline {i}" for i in range(1, 6))
        read_args = {"path": "big.py", "start_line": 1, "end_line": 2}

        # LLM: planning(1) + turn0(read_file_lines) + turn1(same read_file_lines) + final(1) + analysis(1) = 5
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([{
                    "name": "read_file_lines",
                    "args": read_args,
                }]),
                make_tool_call_response([{
                    "name": "read_file_lines",
                    "args": read_args,
                }]),
                make_final_response("Done."),
                make_final_response("Synthesis."),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={"success": True, "output": full_content, "errors": ""}
        )

        result = await agent.run("Read lines then same lines again")

        read_logs = [e for e in result["tool_log"] if e["tool"] == "read_file_lines"]
        assert len(read_logs) == 2
        assert read_logs[0]["cached"] is False  # first: cache miss
        assert read_logs[1]["cached"] is True   # second: cache hit


# ---------------------------------------------------------------------------
# 6. TestRetry
# ---------------------------------------------------------------------------


class TestRetry:
    """Verify the retry-on-error mechanism in _execute_with_retry."""

    async def test_retry_on_tool_failure(self, agent, mock_ps_manager):
        """Should retry when the first tool execution returns an error (not 'not found')."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([{
                    "name": "run_powershell",
                    "args": {"command": "Get-Process"},
                }]),
                make_final_response("Process list retrieved."),
                make_final_response("Synthesis."),
            ]
        )

        ps_call_count = 0

        async def fail_then_succeed(cmd, timeout=None):
            nonlocal ps_call_count
            ps_call_count += 1
            if "Get-Process" in cmd:
                if ps_call_count == 1:
                    return {"success": False, "output": "Error: access denied", "errors": ""}
                return {"success": True, "output": "System\nExplorer", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=fail_then_succeed)

        result = await agent.run("List processes")

        retried_logs = [e for e in result["tool_log"] if e["retried"]]
        assert len(retried_logs) == 1

    async def test_no_retry_on_not_found(self, agent, mock_ps_manager):
        """Should NOT retry when the error contains 'not found'."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([{
                    "name": "read_file",
                    "args": {"path": "nonexistent.py"},
                }]),
                make_final_response("File not found."),
                make_final_response("Synthesis."),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={
                "success": False,
                "output": "Error: file not found",
                "errors": "not found",
            }
        )

        result = await agent.run("Read nonexistent file")

        retried_logs = [e for e in result["tool_log"] if e["retried"]]
        assert len(retried_logs) == 0


# ---------------------------------------------------------------------------
# 7. TestCaching
# ---------------------------------------------------------------------------


class TestCaching:
    """Verify the read cache: hits, invalidation on write, and clearing between runs."""

    async def test_cache_hit_on_repeated_read(self, agent, mock_ps_manager):
        """Calling read_file twice for the same path should hit the cache on the second call."""
        # LLM: planning(1) + tool_turn0(2 reads) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "read_file", "args": {"path": "src/a.py"}},
                    {"name": "read_file", "args": {"path": "src/a.py"}},
                ]),
                make_final_response("Done."),
                make_final_response("Synthesis."),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={"success": True, "output": "1\tcode here", "errors": ""}
        )

        result = await agent.run("Read file twice")

        read_logs = [e for e in result["tool_log"] if e["tool"] == "read_file"]
        assert len(read_logs) == 2
        assert read_logs[0]["cached"] is False  # first: cache miss
        assert read_logs[1]["cached"] is True   # second: cache hit

    async def test_cache_invalidated_on_write(self, agent, mock_ps_manager):
        """Reading a file, then writing to it, then reading again should miss the cache."""
        # LLM: planning(1) + turn0(read+write+read) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "read_file", "args": {"path": "src/a.py"}},
                    {"name": "write_file", "args": {"path": "src/a.py", "content": "new"}},
                    {"name": "read_file", "args": {"path": "src/a.py"}},
                ]),
                make_final_response("Done."),
                make_final_response("Synthesis."),
            ]
        )

        async def track_execute(cmd, timeout=None):
            if "git checkout" in cmd:
                return {"success": True, "output": "", "errors": ""}
            if "Read-LoomFile" in cmd:
                return {"success": True, "output": "1\tcode", "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            if "python -c" in cmd:
                return {"success": True, "output": "OK", "errors": ""}
            if "git diff" in cmd:
                return {"success": True, "output": "diff", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=track_execute)

        result = await agent.run("Read, write, read")

        read_logs = [e for e in result["tool_log"] if e["tool"] == "read_file"]
        assert len(read_logs) == 2
        assert read_logs[0]["cached"] is False  # first read: miss
        assert read_logs[1]["cached"] is False  # second read: cache invalidated by write

    async def test_cache_cleared_between_runs(self, agent, mock_ps_manager):
        """Cache from the first run should not persist into the second run."""
        # Run 1: planning(1) + tool(1) + final(1) + analysis(1) = 4
        # Run 2: planning(1) + tool(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                # Run 1
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "read_file", "args": {"path": "src/a.py"}}
                ]),
                make_final_response("Done."),
                make_final_response("Synthesis."),
                # Run 2
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "read_file", "args": {"path": "src/a.py"}}
                ]),
                make_final_response("Done."),
                make_final_response("Synthesis."),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={"success": True, "output": "1\tcode", "errors": ""}
        )

        result1 = await agent.run("First run")
        result2 = await agent.run("Second run")

        read_log1 = [e for e in result1["tool_log"] if e["tool"] == "read_file"]
        read_log2 = [e for e in result2["tool_log"] if e["tool"] == "read_file"]
        assert len(read_log1) == 1
        assert len(read_log2) == 1
        assert read_log1[0]["cached"] is False
        assert read_log2[0]["cached"] is False  # cache was cleared at start of run 2


# ---------------------------------------------------------------------------
# 8. TestProgressLogging
# ---------------------------------------------------------------------------


class TestProgressLogging:
    """Verify tool_log is populated and logger.info is called with tool names."""

    async def test_tool_log_populated(self, agent, mock_ps_manager):
        """After running the agent, tool_log should contain entries with expected fields."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "read_file", "args": {"path": "f.py"}},
                    {"name": "search_code", "args": {"query": "TODO"}},
                ]),
                make_final_response("Summary."),
                make_final_response("Synthesis."),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={"success": True, "output": "1\tsome code", "errors": ""}
        )

        result = await agent.run("Read and search")

        assert len(result["tool_log"]) == 2
        for entry in result["tool_log"]:
            assert "turn" in entry
            assert "tool" in entry
            assert "args" in entry
            assert "result_preview" in entry
            assert "cached" in entry
            assert "retried" in entry

    async def test_logging_output(self, agent, mock_ps_manager, caplog):
        """Should produce logger.info messages containing tool names during execution."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "find_files", "args": {"pattern": "*.py"}},
                ]),
                make_final_response("Found files."),
                make_final_response("Synthesis."),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={"success": True, "output": "src/main.py", "errors": ""}
        )

        with caplog.at_level(logging.INFO, logger="loom.local_agent"):
            await agent.run("Find python files")

        tool_log_messages = [r.message for r in caplog.records if "find_files" in r.message]
        assert len(tool_log_messages) >= 1


# ---------------------------------------------------------------------------
# 9. TestValidation
# ---------------------------------------------------------------------------


class TestValidation:
    """Verify Python file validation after write and skip for non-Python files."""

    async def test_py_file_validated_after_write(self, agent, mock_ps_manager):
        """When write_file is called on a .py file, ast.parse validation should run."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "write_file", "args": {"path": "module.py", "content": "x = 1"}}
                ]),
                make_final_response("Written."),
                make_final_response("Synthesis."),
            ]
        )

        executed_commands = []

        async def track_execute(cmd, timeout=None):
            executed_commands.append(cmd)
            if "git checkout" in cmd:
                return {"success": True, "output": "", "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            if "python -c" in cmd:
                return {"success": True, "output": "OK", "errors": ""}
            if "git diff" in cmd:
                return {"success": True, "output": "diff", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=track_execute)

        result = await agent.run("Write python file")

        ast_calls = [c for c in executed_commands if "ast.parse" in c]
        assert len(ast_calls) == 1
        assert len(result["validation_results"]) == 1
        assert result["validation_results"][0]["valid"] is True

    async def test_non_py_file_skips_validation(self, agent, mock_ps_manager):
        """When write_file is called on a non-.py file, no ast.parse validation should run."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "write_file", "args": {"path": "script.js", "content": "var x = 1;"}}
                ]),
                make_final_response("Written."),
                make_final_response("Synthesis."),
            ]
        )

        executed_commands = []

        async def track_execute(cmd, timeout=None):
            executed_commands.append(cmd)
            if "git checkout" in cmd:
                return {"success": True, "output": "", "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            if "git diff" in cmd:
                return {"success": True, "output": "diff", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=track_execute)

        result = await agent.run("Write JS file")

        ast_calls = [c for c in executed_commands if "ast.parse" in c]
        assert len(ast_calls) == 0
        assert len(result["validation_results"]) == 0

    async def test_failed_validation_in_results(self, agent, mock_ps_manager):
        """When ast.parse fails, validation_results should contain a failure entry."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "write_file", "args": {"path": "bad.py", "content": "def ("}}
                ]),
                make_final_response("Written with errors."),
                make_final_response("Synthesis."),
            ]
        )

        async def track_execute(cmd, timeout=None):
            if "git checkout" in cmd:
                return {"success": True, "output": "", "errors": ""}
            if "Write-LoomFile" in cmd:
                return {"success": True, "output": "Written.", "errors": ""}
            if "python -c" in cmd:
                return {"success": False, "output": "", "errors": "SyntaxError: invalid syntax"}
            if "git diff" in cmd:
                return {"success": True, "output": "diff", "errors": ""}
            return {"success": True, "output": "", "errors": ""}

        mock_ps_manager.execute = AsyncMock(side_effect=track_execute)

        result = await agent.run("Write bad python")

        assert len(result["validation_results"]) == 1
        assert result["validation_results"][0]["valid"] is False


# ---------------------------------------------------------------------------
# 10. TestSessionMemory
# ---------------------------------------------------------------------------


class TestSessionMemory:
    """Verify session memory retrieval, storage, and graceful degradation."""

    async def test_memory_retrieved_on_start(self, agent, mock_memory):
        """Should call memory.search with the task at the start of the run."""
        # LLM: planning(1) + loop(1) + analysis(1) = 3
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_final_response("Done."),
                make_final_response("Synthesis."),
            ]
        )

        await agent.run("Fix authentication bug")

        mock_memory.memory.search.assert_awaited_once_with(
            "Fix authentication bug", num_results=3
        )

    async def test_memory_stored_on_completion(self, agent, mock_memory):
        """Should call memory.add_episode after task completes."""
        # LLM: planning(1) + loop(1) + analysis(1) = 3
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_final_response("Task completed successfully."),
                make_final_response("Synthesis."),
            ]
        )

        mock_episode_type = MagicMock()
        mock_episode_type.json = "json"
        with patch.dict("sys.modules", {
            "graphiti_core": MagicMock(),
            "graphiti_core.nodes": MagicMock(EpisodeType=mock_episode_type),
        }):
            result = await agent.run("Some task")

        assert result["memory_stored"] is True
        mock_memory.memory.add_episode.assert_awaited_once()

    async def test_graceful_degradation_no_memory(self, mock_inference_engine, mock_ps_manager):
        """Should run without error when memory_engine is None."""
        agent = LocalAgent(
            inference_engine=mock_inference_engine,
            ps_manager=mock_ps_manager,
            memory_engine=None,
            tool_model="test-tool-model",
            analysis_model="test-analysis-model",
            max_turns=5,
        )

        # LLM: planning(1) + loop(1) + analysis(1) = 3
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_final_response("Done without memory."),
                make_final_response("Synthesis."),
            ]
        )

        result = await agent.run("Task without memory")

        assert result["success"] is True
        assert result["memory_stored"] is False

    async def test_memory_search_results_included_in_system_prompt(self, agent, mock_memory):
        """When memory.search returns results, they should be added to the system prompt."""
        mock_episode = MagicMock()
        mock_episode.fact = "Previously fixed auth bug in login.py"
        mock_memory.memory.search = AsyncMock(return_value=[mock_episode])

        captured_messages = []

        async def capture_create(**kwargs):
            captured_messages.append(kwargs.get("messages", []))
            return make_final_response("Done.")

        agent._client.chat.completions.create = AsyncMock(side_effect=capture_create)

        await agent.run("Fix auth bug again")

        found_context = False
        for msgs in captured_messages:
            for msg in msgs:
                if msg.get("role") == "system" and "Previous Context" in msg.get("content", ""):
                    found_context = True
                    assert "auth bug" in msg["content"].lower()
        assert found_context, "Memory context should appear in system prompt"

    async def test_memory_search_failure_does_not_break_agent(self, agent, mock_memory):
        """If memory.search raises, the agent should still run successfully."""
        mock_memory.memory.search = AsyncMock(side_effect=Exception("Neo4j down"))

        # LLM: planning(1) + loop(1) + analysis(1) = 3
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_final_response("Done despite memory failure."),
                make_final_response("Synthesis."),
            ]
        )

        result = await agent.run("Task with broken memory")

        assert result["success"] is True


# ---------------------------------------------------------------------------
# Edge cases and regression
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Additional edge-case tests for robustness."""

    async def test_max_turns_truncation(self, mock_inference_engine, mock_ps_manager, mock_memory):
        """Should set truncated=True when max_turns is reached without a non-tool response."""
        agent = LocalAgent(
            inference_engine=mock_inference_engine,
            ps_manager=mock_ps_manager,
            memory_engine=mock_memory,
            tool_model="test-tool-model",
            analysis_model="test-analysis-model",
            max_turns=2,
        )

        # planning(1) + turn0(tools) + turn1(tools) = 3 LLM calls, then truncated (no analysis)
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "read_file", "args": {"path": "a.py"}}
                ]),
                make_tool_call_response([
                    {"name": "read_file", "args": {"path": "b.py"}}
                ]),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={"success": True, "output": "1\tcode", "errors": ""}
        )

        result = await agent.run("Infinite loop task")

        assert result["truncated"] is True
        assert result["turns_used"] == 2

    async def test_llm_call_failure_returns_error_result(self, agent):
        """When the LLM call raises, the agent should return success=False."""
        # planning(1) then exception on turn 0
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                Exception("Model timeout"),
            ]
        )

        result = await agent.run("Task that fails")

        assert result["success"] is False
        assert "failed" in result["response"].lower() or "timeout" in result["response"].lower()

    async def test_unknown_tool_returns_error_string(self, agent, mock_ps_manager):
        """When the model calls a tool name that doesn't exist, an error message should be returned."""
        # LLM: planning(1) + tool_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                make_tool_call_response([
                    {"name": "nonexistent_tool", "args": {"foo": "bar"}}
                ]),
                make_final_response("Tool not available."),
                make_final_response("Synthesis."),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={"success": True, "output": "", "errors": ""}
        )

        result = await agent.run("Use unknown tool")

        tool_logs = [e for e in result["tool_log"] if e["tool"] == "nonexistent_tool"]
        assert len(tool_logs) == 1
        assert "unknown tool" in tool_logs[0]["result_preview"].lower()

    async def test_malformed_tool_arguments_handled(self, agent, mock_ps_manager):
        """When tool arguments are not valid JSON, empty dict should be used."""
        msg = MagicMock()
        msg.content = ""
        tc = MagicMock()
        tc.id = "call_bad"
        tc.function = MagicMock()
        tc.function.name = "read_file"
        tc.function.arguments = "NOT_VALID_JSON"
        msg.tool_calls = [tc]

        choice = MagicMock()
        choice.message = msg
        bad_response = MagicMock()
        bad_response.choices = [choice]

        # LLM: planning(1) + bad_turn(1) + final(1) + analysis(1) = 4
        agent._client.chat.completions.create = AsyncMock(
            side_effect=[
                make_final_response("Plan."),
                bad_response,
                make_final_response("Handled."),
                make_final_response("Synthesis."),
            ]
        )

        mock_ps_manager.execute = AsyncMock(
            return_value={"success": True, "output": "error: missing path", "errors": ""}
        )

        result = await agent.run("Bad args task")

        assert result["success"] is True
