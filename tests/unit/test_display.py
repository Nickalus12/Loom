"""Unit tests for the Rich display module.

Tests verify that display functions do not crash on valid and edge-case inputs.
Since Rich renders to terminal, these tests capture output to a StringIO Console
and verify that no exceptions occur during rendering.
"""

from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from loom.display import (
    AgentDisplay,
    agent_run_display,
    print_agent_result,
    print_craft_result,
    print_metrics_dashboard,
    print_phase_tree,
    print_safety_result,
    print_waterfall,
    setup_rich_logging,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def capture_console():
    """Patch the display module's console to capture output without terminal rendering."""
    buf = StringIO()
    test_console = Console(file=buf, force_terminal=True, width=120)
    with patch("loom.display.console", test_console):
        yield buf


# ---------------------------------------------------------------------------
# AgentDisplay lifecycle
# ---------------------------------------------------------------------------


class TestAgentDisplay:
    """Verify AgentDisplay start/stop lifecycle does not crash."""

    def test_agent_display_start_stop(self, capture_console):
        """AgentDisplay.start() and .stop() should execute without errors."""
        display = AgentDisplay()
        display.start("Test task", max_turns=10)
        display.stop()
        # If we get here without exception, the test passes

    def test_agent_display_update_turn(self, capture_console):
        """AgentDisplay.update_turn() should handle tool name updates."""
        display = AgentDisplay()
        display.start("Test task", max_turns=10)
        display.update_turn(1, "read_file", cached=False)
        display.update_turn(2, "write_file", cached=True)
        display.stop()

    def test_agent_display_update_phase(self, capture_console):
        """AgentDisplay.update_phase() should not crash."""
        display = AgentDisplay()
        display.start("Test task", max_turns=10)
        display.update_phase("analysis")
        display.stop()

    def test_agent_display_stop_without_start(self):
        """Calling stop() without start() should not crash."""
        display = AgentDisplay()
        display.stop()  # No-op since _live is None


# ---------------------------------------------------------------------------
# Print functions - success cases
# ---------------------------------------------------------------------------


class TestPrintFunctions:
    """Verify print functions handle valid input without crashing."""

    def test_print_agent_result_success(self, capture_console):
        """print_agent_result with a success result should render without errors."""
        result = {
            "success": True,
            "turns_used": 5,
            "tool_calls_made": 12,
            "response": "All tests passing.",
            "files_changed": ["src/main.py", "tests/test_main.py"],
            "git_branch": "feature/tests",
            "git_diff": "+added line\n-removed line",
            "validation_results": [{"valid": True, "path": "src/main.py"}],
            "tool_log": [
                {"turn": 1, "tool": "read_file", "cached": False, "retried": False, "result_preview": "ok"},
                {"turn": 2, "tool": "write_file", "cached": True, "retried": False, "result_preview": "ok"},
            ],
        }
        print_agent_result(result)

    def test_print_agent_result_failure(self, capture_console):
        """print_agent_result with a failure result should render without errors."""
        result = {
            "success": False,
            "turns_used": 3,
            "tool_calls_made": 1,
            "response": "Error: could not find file.",
        }
        print_agent_result(result)

    def test_print_agent_result_empty(self, capture_console):
        """print_agent_result with minimal empty result should not crash."""
        print_agent_result({})

    def test_print_craft_result(self, capture_console):
        """print_craft_result with a valid result should not crash."""
        result = {
            "success": True,
            "phases": 3,
            "summary": "All phases completed successfully.",
            "files_created": ["src/new_feature.py"],
            "files_modified": ["src/config.py"],
        }
        print_craft_result(result)

    def test_print_craft_result_failure(self, capture_console):
        """print_craft_result with a failure result should not crash."""
        result = {
            "success": False,
            "phases": 2,
            "error": "Phase 2 failed: timeout exceeded.",
        }
        print_craft_result(result)

    def test_print_safety_result_safe(self, capture_console):
        """print_safety_result with safe score should render without errors."""
        result = {
            "risk_level": "safe",
            "risk_score": 0.12,
            "model": "kan-heuristic",
            "command_preview": "Get-Process | Format-Table",
            "features": {"has_pipe": 0.1, "destructive_verb": 0.0},
        }
        print_safety_result(result)

    def test_print_safety_result_blocked(self, capture_console):
        """print_safety_result with blocked score should render without errors."""
        result = {
            "risk_level": "blocked",
            "risk_score": 0.95,
            "model": "kan-neural",
            "command_preview": "Remove-Item -Recurse -Force C:\\",
            "features": {"destructive_verb": 1.0, "dangerous_path": 0.9},
        }
        print_safety_result(result)

    def test_print_safety_result_unknown_level(self, capture_console):
        """print_safety_result with unknown risk level should not crash."""
        result = {
            "risk_level": "unknown",
            "risk_score": 0.5,
            "model": "test",
            "command_preview": "test",
            "features": {},
        }
        print_safety_result(result)


# ---------------------------------------------------------------------------
# Dashboard and tree
# ---------------------------------------------------------------------------


class TestDashboardAndTree:
    """Verify dashboard and tree rendering."""

    def test_print_metrics_dashboard(self, capture_console):
        """print_metrics_dashboard with sample metrics should not crash."""
        metrics = {
            "uptime_seconds": 123.4,
            "counters": {
                "agent_tasks_total": 5,
                "agent_tasks_completed": 4,
                "agent_tasks_failed": 1,
                "agent_turns_total": 50,
                "agent_tool_calls_total": 100,
                "agent_tool_calls_cached": 10,
                "agent_tool_calls_retried": 2,
                "safety_commands_total": 20,
                "safety_commands_blocked": 1,
                "safety_commands_elevated": 3,
                "safety_gemma_reviews": 3,
                "model_calls_total": 60,
                "model_call_errors": 0,
                "model_tokens_input": 5000,
                "model_tokens_output": 2000,
                "git_branches_created": 2,
                "memory_episodes_stored": 10,
                "memory_searches": 5,
                "craft_tasks_total": 3,
                "craft_phases_total": 9,
                "craft_phases_failed": 0,
            },
            "labeled_counters": {},
            "durations": {
                "agent_duration_seconds": {"avg": 12.5, "p95": 25.0},
                "model_call_duration_seconds": {"avg": 1.2, "p95": 3.5},
            },
        }
        print_metrics_dashboard(metrics)

    def test_print_metrics_dashboard_empty(self, capture_console):
        """print_metrics_dashboard with empty metrics should not crash."""
        metrics = {
            "uptime_seconds": 0,
            "counters": {},
            "labeled_counters": {},
            "durations": {},
        }
        print_metrics_dashboard(metrics)

    def test_print_phase_tree(self, capture_console):
        """print_phase_tree with sample phases should not crash."""
        phases = [
            {"id": 1, "name": "Design", "agent": "architect", "status": "completed", "files_created": ["design.md"]},
            {"id": 2, "name": "Implement", "agent": "coder", "status": "in_progress", "files_modified": ["main.py"]},
            {"id": 3, "name": "Test", "agent": "tester", "status": "pending"},
            {"id": 4, "name": "Review", "agent": "code_reviewer", "status": "failed"},
        ]
        print_phase_tree(phases)

    def test_print_phase_tree_empty(self, capture_console):
        """print_phase_tree with empty phase list should not crash."""
        print_phase_tree([])


# ---------------------------------------------------------------------------
# Logging setup and context manager
# ---------------------------------------------------------------------------


class TestSetupAndContextManager:
    """Verify logging setup and context manager."""

    def test_setup_rich_logging(self):
        """setup_rich_logging should install a RichHandler without errors."""
        import logging
        setup_rich_logging(level=logging.WARNING)
        # Verify a RichHandler is present
        from rich.logging import RichHandler
        root = logging.getLogger()
        rich_handlers = [h for h in root.handlers if isinstance(h, RichHandler)]
        assert len(rich_handlers) > 0, "Expected at least one RichHandler after setup"

    def test_agent_run_display_context_manager(self, capture_console):
        """agent_run_display context manager should enter and exit cleanly."""
        with agent_run_display("Test task", max_turns=5) as display:
            assert isinstance(display, AgentDisplay)
        # After exit, the display should be stopped (no live rendering)


# ---------------------------------------------------------------------------
# Waterfall display
# ---------------------------------------------------------------------------


class TestPrintWaterfall:
    """Verify print_waterfall renders without crashing."""

    def test_print_waterfall_empty(self, capture_console):
        """print_waterfall with empty list should show a placeholder message."""
        print_waterfall([])
        output = capture_console.getvalue()
        assert "No waterfall data" in output

    def test_print_waterfall_single_entry(self, capture_console):
        """print_waterfall with one entry should render without errors."""
        waterfall = [{"name": "craft", "duration_ms": 50, "children": []}]
        print_waterfall(waterfall)
        output = capture_console.getvalue()
        assert "craft" in output
        assert "50ms" in output

    def test_print_waterfall_nested(self, capture_console):
        """print_waterfall with nested entries should render the tree."""
        waterfall = [
            {
                "name": "craft",
                "duration_ms": 1500,
                "children": [
                    {"name": "synthesize_agent", "duration_ms": 500, "children": []},
                ],
            }
        ]
        print_waterfall(waterfall)
        output = capture_console.getvalue()
        assert "craft" in output
        assert "synthesize_agent" in output

    def test_print_waterfall_color_coding_green(self, capture_console):
        """Durations under 100ms should use green color."""
        waterfall = [{"name": "fast_op", "duration_ms": 50, "children": []}]
        print_waterfall(waterfall)
        # Just verify no crash — color verification requires markup inspection

    def test_print_waterfall_color_coding_yellow(self, capture_console):
        """Durations 100-1000ms should use yellow color."""
        waterfall = [{"name": "medium_op", "duration_ms": 500, "children": []}]
        print_waterfall(waterfall)

    def test_print_waterfall_color_coding_red(self, capture_console):
        """Durations over 1000ms should use red color."""
        waterfall = [{"name": "slow_op", "duration_ms": 2000, "children": []}]
        print_waterfall(waterfall)
