"""Loom CLI — run local agents and orchestration from the terminal.

Usage:
    python -m loom.cli agent "Review src/loom/server.py for bugs"
    python -m loom.cli craft "Add rate limiting to the API" --mode local
    python -m loom.cli safety "Invoke-WebRequest -Uri http://example.com"
    python -m loom.cli status
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

from loom.display import (
    AgentDisplay,
    console,
    print_agent_result,
    print_craft_result,
    print_safety_result,
    setup_rich_logging,
)


def _get_banner() -> str:
    return (
        "[bold magenta]"
        "  _                          \n"
        " | |    ___   ___  _ __ ___  \n"
        " | |   / _ \\ / _ \\| '_ ` _ \\ \n"
        " | |__| (_) | (_) | | | | | |\n"
        " |_____\\___/ \\___/|_| |_| |_|\n"
        "[/][dim] Multi-agent orchestration platform[/]\n"
    )


async def cmd_agent(args: argparse.Namespace) -> None:
    """Run a local Ollama agent task."""
    from loom.local_agent import LocalAgent
    from loom.local_inference import LocalInferenceEngine
    from loom.powershell_tools.kan_engine import PowerShellKANEngine
    from loom.powershell_tools.repl_manager import PowerShellREPLManager

    task = " ".join(args.task)
    if not task:
        console.print("[red]Error:[/] No task provided. Usage: loom agent \"your task here\"")
        sys.exit(1)

    console.print(_get_banner())
    console.print(f"[bold cyan]Task:[/] {task}\n")

    project_root = Path.cwd()
    kan = PowerShellKANEngine()

    # Minimal setup without Neo4j/Graphiti
    class _StubMemory:
        memory = None

    engine = LocalInferenceEngine(memory_engine=_StubMemory())
    manager = PowerShellREPLManager(
        project_root=project_root,
        local_engine=engine,
        memory_engine=None,
        kan_engine=kan,
    )

    agent = LocalAgent(
        inference_engine=engine,
        ps_manager=manager,
        memory_engine=None,
        tool_model=args.tool_model or "qwen3:4b",
        analysis_model=args.analysis_model or "deepseek-coder-v2:16b",
        max_turns=args.max_turns,
    )

    display = AgentDisplay()
    display.start(task, args.max_turns)

    # Monkey-patch the agent's progress logging to feed the display
    original_log = agent._tool_log
    _original_execute = agent._execute_with_retry

    async def _patched_execute(tool_name, tool_args):
        result, retried = await _original_execute(tool_name, tool_args)
        turn = len(agent._tool_log)
        cached = any(
            e.get("tool") == tool_name and e.get("cached")
            for e in agent._tool_log
        )
        display.update_turn(turn, tool_name, cached=cached)
        return result, retried

    agent._execute_with_retry = _patched_execute

    try:
        result = await agent.run(task)
    finally:
        display.stop()
        await manager.close_all_sessions()

    print_agent_result(result)


async def cmd_craft(args: argparse.Namespace) -> None:
    """Run the Loom Craft multi-agent pipeline."""
    task = " ".join(args.task)
    if not task:
        console.print("[red]Error:[/] No task provided. Usage: loom craft \"your task here\"")
        sys.exit(1)

    console.print(_get_banner())
    console.print(f"[bold magenta]Craft:[/] {task}")
    console.print(f"[dim]Mode: {args.mode}[/]\n")

    if args.mode == "local":
        # Run through LocalAgent
        await cmd_agent(args)
    else:
        from loom.server import craft as craft_tool
        result_json = await craft_tool(task=task, mode="cloud")
        result = json.loads(result_json)
        print_craft_result(result)


async def cmd_safety(args: argparse.Namespace) -> None:
    """Score a PowerShell command with the KAN safety engine."""
    command = " ".join(args.ps_command)
    if not command:
        console.print("[red]Error:[/] No command provided.")
        sys.exit(1)

    console.print(_get_banner())

    from loom.powershell_tools.kan_engine import PowerShellKANEngine

    kan = PowerShellKANEngine()
    result = await kan.score_risk(command)
    print_safety_result(result)


async def cmd_status(args: argparse.Namespace) -> None:
    """Show the current Loom system status."""
    console.print(_get_banner())

    from rich.table import Table

    # Check services
    status_table = Table(title="System Status", border_style="cyan")
    status_table.add_column("Service", style="bold")
    status_table.add_column("Status")
    status_table.add_column("Details", style="dim")

    # Ollama
    try:
        from openai import AsyncOpenAI
        import os

        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        client = AsyncOpenAI(base_url=base_url + "/v1", api_key="ollama")
        models = await client.models.list()
        model_names = [m.id for m in models.data]
        status_table.add_row("Ollama", "[green]Online[/]", f"{len(model_names)} models")
    except Exception:
        status_table.add_row("Ollama", "[red]Offline[/]", "Start with: ollama serve")

    # PowerShell
    import shutil
    pwsh = shutil.which("pwsh") or shutil.which("pwsh-preview")
    if pwsh:
        status_table.add_row("PowerShell", "[green]Available[/]", pwsh)
    else:
        status_table.add_row("PowerShell", "[red]Not Found[/]", "Install PowerShell 7+")

    # Neo4j
    try:
        from neo4j import AsyncGraphDatabase

        driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
        await driver.verify_connectivity()
        await driver.close()
        status_table.add_row("Neo4j", "[green]Online[/]", "bolt://localhost:7687")
    except Exception:
        status_table.add_row("Neo4j", "[yellow]Offline[/]", "Optional — for session memory")

    # KAN
    try:
        import torch
        status_table.add_row("KAN Model", "[green]Neural[/]", f"PyTorch {torch.__version__}")
    except ImportError:
        status_table.add_row("KAN Model", "[yellow]Heuristic[/]", "Install torch for neural scoring")

    console.print(status_table)

    # Tools summary
    console.print()
    tools_table = Table(title="Available Commands", border_style="magenta")
    tools_table.add_column("Command", style="cyan")
    tools_table.add_column("Description")
    tools_table.add_row("loom agent", "Run local Ollama agent with tool-calling")
    tools_table.add_row("loom craft", "Multi-agent pipeline (cloud or local)")
    tools_table.add_row("loom safety", "Score a PowerShell command's risk")
    tools_table.add_row("loom status", "Show system status (this screen)")
    console.print(tools_table)


async def cmd_tools(args: argparse.Namespace) -> None:
    """List all MCP tools from the Loom server."""
    console.print(_get_banner())

    from rich.table import Table

    from loom.server import mcp

    table = Table(title="Loom MCP Tools", border_style="cyan", show_lines=False)
    table.add_column("#", style="dim", width=3)
    table.add_column("Tool", style="cyan bold")
    table.add_column("Description", style="dim", max_width=70)

    tools = sorted(mcp._tool_manager._tools.values(), key=lambda t: t.name)
    for i, tool in enumerate(tools, 1):
        desc = (tool.description or "").split("\n")[0][:70]
        table.add_row(str(i), tool.name, desc)

    console.print(table)
    console.print(f"\n[dim]{len(tools)} tools available[/]")


async def cmd_test(args: argparse.Namespace) -> None:
    """Run the test suite with Rich output."""
    import subprocess

    console.print(_get_banner())
    console.print("[bold cyan]Running test suite...[/]\n")

    cmd = [sys.executable, "-m", "pytest", "tests/unit/", "-v", "--tb=short"]
    if hasattr(args, "filter") and args.filter:
        cmd.extend(["-k", args.filter])

    result = subprocess.run(cmd, cwd=str(Path.cwd()))
    sys.exit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="loom",
        description="Loom — Multi-agent orchestration platform",
    )
    subparsers = parser.add_subparsers(dest="command")

    # agent
    p_agent = subparsers.add_parser("agent", help="Run a local Ollama agent task")
    p_agent.add_argument("task", nargs="*", help="Task description")
    p_agent.add_argument("--tool-model", default="", help="Ollama model for tool calls")
    p_agent.add_argument("--analysis-model", default="", help="Ollama model for analysis")
    p_agent.add_argument("--max-turns", type=int, default=15, help="Max agent turns")

    # craft
    p_craft = subparsers.add_parser("craft", help="Run multi-agent pipeline")
    p_craft.add_argument("task", nargs="*", help="Task description")
    p_craft.add_argument("--mode", choices=["cloud", "local"], default="cloud")
    p_craft.add_argument("--tool-model", default="")
    p_craft.add_argument("--analysis-model", default="")
    p_craft.add_argument("--max-turns", type=int, default=15)

    # safety
    p_safety = subparsers.add_parser("safety", help="Score a command's safety risk")
    p_safety.add_argument("ps_command", nargs="*", help="PowerShell command to score")

    # status
    subparsers.add_parser("status", help="Show system status")

    # tools
    subparsers.add_parser("tools", help="List all MCP tools")

    # test
    p_test = subparsers.add_parser("test", help="Run the test suite")
    p_test.add_argument("--filter", default="", help="Test filter pattern")

    args = parser.parse_args()

    if not args.command:
        # No subcommand — show status
        setup_rich_logging()
        asyncio.run(cmd_status(args))
        return

    setup_rich_logging()

    commands = {
        "agent": cmd_agent,
        "craft": cmd_craft,
        "safety": cmd_safety,
        "status": cmd_status,
        "tools": cmd_tools,
        "test": cmd_test,
    }

    handler = commands.get(args.command)
    if handler:
        asyncio.run(handler(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
