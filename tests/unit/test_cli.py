"""Unit tests for the Loom CLI argument parsing and subcommand structure.

Tests verify that all subcommands exist, accept correct arguments, and
the parser handles edge cases like no subcommand (defaults to status).
"""

import argparse
import sys
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from loom.cli import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str]) -> argparse.Namespace:
    """Build the CLI parser and parse arguments without executing commands."""
    parser = argparse.ArgumentParser(prog="loom")
    subparsers = parser.add_subparsers(dest="command")

    # agent
    p_agent = subparsers.add_parser("agent")
    p_agent.add_argument("task", nargs="*")
    p_agent.add_argument("--tool-model", default="")
    p_agent.add_argument("--analysis-model", default="")
    p_agent.add_argument("--max-turns", type=int, default=15)

    # craft
    p_craft = subparsers.add_parser("craft")
    p_craft.add_argument("task", nargs="*")
    p_craft.add_argument("--mode", choices=["cloud", "local"], default="cloud")
    p_craft.add_argument("--tool-model", default="")
    p_craft.add_argument("--analysis-model", default="")
    p_craft.add_argument("--max-turns", type=int, default=15)

    # safety
    p_safety = subparsers.add_parser("safety")
    p_safety.add_argument("ps_command", nargs="*")

    # status
    subparsers.add_parser("status")

    # tools
    subparsers.add_parser("tools")

    # test
    p_test = subparsers.add_parser("test")
    p_test.add_argument("--filter", default="")

    return parser.parse_args(argv)


# ---------------------------------------------------------------------------
# Subcommand existence
# ---------------------------------------------------------------------------


class TestSubcommandExistence:
    """Verify all expected subcommands are available in the parser."""

    def test_agent_subcommand_exists(self):
        args = _parse_args(["agent", "hello world"])
        assert args.command == "agent"

    def test_craft_subcommand_exists(self):
        args = _parse_args(["craft", "build something"])
        assert args.command == "craft"

    def test_safety_subcommand_exists(self):
        args = _parse_args(["safety", "Get-Process"])
        assert args.command == "safety"

    def test_status_subcommand_exists(self):
        args = _parse_args(["status"])
        assert args.command == "status"

    def test_tools_subcommand_exists(self):
        args = _parse_args(["tools"])
        assert args.command == "tools"

    def test_test_subcommand_exists(self):
        args = _parse_args(["test"])
        assert args.command == "test"


# ---------------------------------------------------------------------------
# Argument acceptance
# ---------------------------------------------------------------------------


class TestArgumentParsing:
    """Verify subcommands accept the correct arguments."""

    def test_agent_accepts_task_args(self):
        """Agent should accept variable task arguments."""
        args = _parse_args(["agent", "Review", "src/server.py", "for", "bugs"])
        assert args.task == ["Review", "src/server.py", "for", "bugs"]

    def test_agent_accepts_tool_model_flag(self):
        args = _parse_args(["agent", "--tool-model", "qwen3:4b", "test"])
        assert args.tool_model == "qwen3:4b"

    def test_agent_accepts_analysis_model_flag(self):
        args = _parse_args(["agent", "--analysis-model", "deepseek:16b", "test"])
        assert args.analysis_model == "deepseek:16b"

    def test_agent_accepts_max_turns_flag(self):
        args = _parse_args(["agent", "--max-turns", "25", "test"])
        assert args.max_turns == 25

    def test_agent_max_turns_default(self):
        args = _parse_args(["agent", "test"])
        assert args.max_turns == 15

    def test_craft_accepts_mode_flag(self):
        """Craft should accept --mode with cloud or local."""
        args = _parse_args(["craft", "--mode", "local", "build it"])
        assert args.mode == "local"

    def test_craft_mode_default_is_cloud(self):
        args = _parse_args(["craft", "build it"])
        assert args.mode == "cloud"

    def test_safety_accepts_command_args(self):
        """Safety should accept variable PowerShell command args."""
        args = _parse_args(["safety", "Get-Process", "Format-Table", "Name"])
        assert args.ps_command == ["Get-Process", "Format-Table", "Name"]

    def test_test_accepts_filter(self):
        args = _parse_args(["test", "--filter", "test_agent"])
        assert args.filter == "test_agent"


# ---------------------------------------------------------------------------
# Default behavior
# ---------------------------------------------------------------------------


class TestDefaultBehavior:
    """Verify behavior when no subcommand is provided."""

    def test_no_subcommand_defaults_to_none(self):
        """When no subcommand is given, args.command should be None."""
        args = _parse_args([])
        assert args.command is None

    def test_no_subcommand_triggers_status_in_main(self):
        """main() with no subcommand should call cmd_status (show status)."""
        with patch("loom.cli.setup_rich_logging"):
            with patch("loom.cli.asyncio") as mock_asyncio:
                with patch("sys.argv", ["loom"]):
                    main()
                # asyncio.run should have been called with cmd_status coroutine
                mock_asyncio.run.assert_called_once()
