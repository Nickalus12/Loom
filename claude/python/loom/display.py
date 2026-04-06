"""Rich terminal display for Loom agent and orchestration output.

Provides beautiful, real-time terminal feedback for:
- Agent tool calls with spinners and progress
- Phase execution with multi-task progress bars
- Safety pipeline results with colored panels
- Summary tables and diff displays
"""

import json
import logging
from contextlib import contextmanager
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.logging import RichHandler
from rich.markup import escape
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

console = Console()

# ---------------------------------------------------------------------------
# Logging integration
# ---------------------------------------------------------------------------

def setup_rich_logging(level: int = logging.INFO) -> None:
    """Replace default logging with Rich-formatted output."""
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
        force=True,
    )


# ---------------------------------------------------------------------------
# Agent display
# ---------------------------------------------------------------------------

class AgentDisplay:
    """Real-time terminal display for LocalAgent execution."""

    def __init__(self) -> None:
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=30),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
        )
        self._task_id: TaskID | None = None
        self._live: Live | None = None

    def start(self, task_description: str, max_turns: int) -> None:
        """Start the live display for an agent run."""
        self._task_id = self._progress.add_task(
            f"[cyan]Agent:[/] {escape(task_description[:60])}",
            total=max_turns,
        )
        self._live = Live(self._progress, console=console, refresh_per_second=4)
        self._live.start()

    def update_turn(self, turn: int, tool_name: str, cached: bool = False) -> None:
        """Update progress after a tool call."""
        if self._task_id is not None:
            label = f"[green]cached[/] " if cached else ""
            self._progress.update(
                self._task_id,
                advance=1,
                description=f"[cyan]Turn {turn}:[/] {label}[yellow]{escape(tool_name)}[/]",
            )

    def update_phase(self, phase_name: str) -> None:
        """Update the display for a new execution phase."""
        if self._task_id is not None:
            self._progress.update(
                self._task_id,
                description=f"[magenta]Phase:[/] {escape(phase_name)}",
            )

    def stop(self) -> None:
        """Stop the live display."""
        if self._live is not None:
            self._live.stop()
            self._live = None


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def print_agent_result(result: dict[str, Any]) -> None:
    """Print a formatted agent result to the terminal."""
    success = result.get("success", False)
    status_style = "bold green" if success else "bold red"
    status_text = "SUCCESS" if success else "FAILED"

    # Header panel
    console.print()
    console.print(Panel(
        f"[{status_style}]{status_text}[/] | "
        f"[cyan]{result.get('turns_used', 0)}[/] turns | "
        f"[yellow]{result.get('tool_calls_made', 0)}[/] tool calls",
        title="[bold]Loom Agent Result[/]",
        border_style="blue",
    ))

    # Response
    response = result.get("response", "")
    if response:
        console.print(Panel(
            escape(response[:2000]),
            title="[bold]Response[/]",
            border_style="green" if success else "red",
        ))

    # Files changed
    files = result.get("files_changed", [])
    if files:
        table = Table(title="Files Changed", border_style="cyan")
        table.add_column("File", style="yellow")
        for f in files:
            table.add_row(escape(f))
        console.print(table)

    # Git info
    branch = result.get("git_branch")
    diff = result.get("git_diff")
    if branch:
        console.print(f"  [dim]Branch:[/] [cyan]{escape(branch)}[/]")
    if diff:
        console.print(Panel(escape(diff[:1000]), title="Git Diff", border_style="dim"))

    # Validation results
    validations = result.get("validation_results", [])
    if validations:
        for v in validations:
            icon = "[green]OK[/]" if v.get("valid") else "[red]FAIL[/]"
            console.print(f"  {icon} {escape(v.get('path', '?'))}")

    # Tool log
    tool_log = result.get("tool_log", [])
    if tool_log:
        table = Table(title="Tool Log", border_style="dim")
        table.add_column("Turn", style="cyan", width=5)
        table.add_column("Tool", style="yellow")
        table.add_column("Cached", style="dim", width=6)
        table.add_column("Retried", style="dim", width=7)
        table.add_column("Preview", style="dim", max_width=50)
        for entry in tool_log[:20]:
            table.add_row(
                str(entry.get("turn", "")),
                escape(entry.get("tool", "")),
                "yes" if entry.get("cached") else "",
                "yes" if entry.get("retried") else "",
                escape(str(entry.get("result_preview", ""))[:50]),
            )
        if len(tool_log) > 20:
            table.add_row("...", f"({len(tool_log) - 20} more)", "", "", "")
        console.print(table)

    console.print()


def print_craft_result(result: dict[str, Any]) -> None:
    """Print a formatted craft/orchestration result."""
    success = result.get("success", False)
    status_style = "bold green" if success else "bold red"

    console.print()
    console.print(Panel(
        f"[{status_style}]{'COMPLETE' if success else 'FAILED'}[/] | "
        f"[cyan]{result.get('phases', '?')}[/] phases",
        title="[bold]Loom Craft Result[/]",
        border_style="magenta",
    ))

    summary = result.get("summary", "")
    if summary:
        console.print(f"  {escape(summary)}")

    files_created = result.get("files_created", [])
    files_modified = result.get("files_modified", [])
    if files_created or files_modified:
        table = Table(title="Files", border_style="cyan")
        table.add_column("Action", style="green", width=8)
        table.add_column("File", style="yellow")
        for f in files_created:
            table.add_row("created", escape(f))
        for f in files_modified:
            table.add_row("modified", escape(f))
        console.print(table)

    error = result.get("error")
    if error:
        console.print(Panel(escape(str(error)), title="Error", border_style="red"))

    console.print()


def print_safety_result(result: dict[str, Any]) -> None:
    """Print a formatted KAN/safety scoring result."""
    risk_level = result.get("risk_level", "unknown")
    risk_score = result.get("risk_score", 0)

    colors = {"safe": "green", "caution": "yellow", "blocked": "red"}
    color = colors.get(risk_level, "white")

    console.print(Panel(
        f"[{color} bold]{risk_level.upper()}[/] (score: {risk_score:.2f}) | "
        f"model: {result.get('model', '?')}",
        title=f"[bold]Safety: {escape(result.get('command_preview', '')[:60])}[/]",
        border_style=color,
    ))

    features = result.get("features", {})
    if features:
        flagged = {k: v for k, v in features.items() if v > 0}
        if flagged:
            table = Table(border_style="dim", show_header=False)
            table.add_column("Feature", style="dim")
            table.add_column("Value", style=color)
            for k, v in flagged.items():
                table.add_row(k, f"{v:.2f}")
            console.print(table)


def print_phase_tree(phases: list[dict[str, Any]]) -> None:
    """Print a tree view of orchestration phases."""
    tree = Tree("[bold magenta]Loom Craft Pipeline[/]")
    for phase in phases:
        status = phase.get("status", "pending")
        icons = {"completed": "[green]OK[/]", "in_progress": "[yellow]...[/]", "failed": "[red]X[/]", "pending": "[dim]-[/]"}
        icon = icons.get(status, "[dim]?[/]")
        agent = phase.get("agent", "?")
        name = phase.get("name", f"Phase {phase.get('id', '?')}")
        branch = tree.add(f"{icon} [bold]{escape(name)}[/] [dim]({escape(agent)})[/]")
        for f in phase.get("files_created", []):
            branch.add(f"[green]+[/] {escape(f)}")
        for f in phase.get("files_modified", []):
            branch.add(f"[yellow]~[/] {escape(f)}")
    console.print(tree)


# ---------------------------------------------------------------------------
# Context manager for full agent run display
# ---------------------------------------------------------------------------

def print_metrics_dashboard(metrics: dict[str, Any]) -> None:
    """Render the telemetry summary as a Rich dashboard with panels and tables."""
    from rich.columns import Columns
    from rich.padding import Padding

    console.print()
    console.print(Panel(
        f"[bold cyan]Loom Telemetry Dashboard[/]\n"
        f"[dim]Uptime: {metrics.get('uptime_seconds', 0):.1f}s[/]",
        border_style="magenta",
    ))

    counters = metrics.get("counters", {})
    labeled = metrics.get("labeled_counters", {})
    durations = metrics.get("durations", {})

    # --- Agent Stats ---
    agent_table = Table(title="Agent Stats", border_style="cyan", show_lines=False)
    agent_table.add_column("Metric", style="bold")
    agent_table.add_column("Value", style="cyan", justify="right")
    agent_table.add_row("Tasks Started", str(int(counters.get("agent_tasks_total", 0))))
    agent_table.add_row("Tasks Completed", str(int(counters.get("agent_tasks_completed", 0))))
    agent_table.add_row("Tasks Failed", str(int(counters.get("agent_tasks_failed", 0))))
    agent_table.add_row("Total Turns", str(int(counters.get("agent_turns_total", 0))))
    agent_table.add_row("Tool Calls", str(int(counters.get("agent_tool_calls_total", 0))))
    agent_table.add_row("Cache Hits", str(int(counters.get("agent_tool_calls_cached", 0))))
    agent_table.add_row("Retries", str(int(counters.get("agent_tool_calls_retried", 0))))
    dur = durations.get("agent_duration_seconds", {})
    if dur:
        agent_table.add_row("Avg Duration", f"{dur.get('avg', 0):.2f}s")
        agent_table.add_row("P95 Duration", f"{dur.get('p95', 0):.2f}s")

    # --- Safety Stats ---
    safety_table = Table(title="Safety Stats", border_style="yellow", show_lines=False)
    safety_table.add_column("Metric", style="bold")
    safety_table.add_column("Value", style="yellow", justify="right")
    safety_table.add_row("Commands Evaluated", str(int(counters.get("safety_commands_total", 0))))
    safety_table.add_row("Commands Blocked", str(int(counters.get("safety_commands_blocked", 0))))
    safety_table.add_row("Elevated to Gemma", str(int(counters.get("safety_commands_elevated", 0))))
    safety_table.add_row("Gemma Reviews", str(int(counters.get("safety_gemma_reviews", 0))))

    kan_labels = labeled.get("safety_kan_scores", {})
    for raw_key, count in kan_labels.items():
        try:
            parsed = json.loads(raw_key) if isinstance(raw_key, str) else raw_key
            level = parsed.get("level", raw_key)
        except (json.JSONDecodeError, AttributeError):
            level = raw_key
        safety_table.add_row(f"KAN: {level}", str(int(count)))

    # --- Model Stats ---
    model_table = Table(title="Model Stats", border_style="green", show_lines=False)
    model_table.add_column("Metric", style="bold")
    model_table.add_column("Value", style="green", justify="right")
    model_table.add_row("Total Model Calls", str(int(counters.get("model_calls_total", 0))))
    model_table.add_row("Model Errors", str(int(counters.get("model_call_errors", 0))))
    model_table.add_row("Est. Input Tokens", str(int(counters.get("model_tokens_input", 0))))
    model_table.add_row("Est. Output Tokens", str(int(counters.get("model_tokens_output", 0))))

    model_dur = durations.get("model_call_duration_seconds", {})
    if model_dur:
        model_table.add_row("Avg Latency", f"{model_dur.get('avg', 0):.2f}s")
        model_table.add_row("P95 Latency", f"{model_dur.get('p95', 0):.2f}s")

    provider_labels = labeled.get("model_calls_total", {})
    for raw_key, count in provider_labels.items():
        try:
            parsed = json.loads(raw_key) if isinstance(raw_key, str) else raw_key
            provider = parsed.get("provider", raw_key)
        except (json.JSONDecodeError, AttributeError):
            provider = raw_key
        model_table.add_row(f"  {provider}", str(int(count)))

    # --- System Stats ---
    system_table = Table(title="System Stats", border_style="dim", show_lines=False)
    system_table.add_column("Metric", style="bold")
    system_table.add_column("Value", style="dim", justify="right")
    system_table.add_row("Git Branches Created", str(int(counters.get("git_branches_created", 0))))
    system_table.add_row("Memory Episodes Stored", str(int(counters.get("memory_episodes_stored", 0))))
    system_table.add_row("Memory Searches", str(int(counters.get("memory_searches", 0))))
    system_table.add_row("Craft Tasks", str(int(counters.get("craft_tasks_total", 0))))
    system_table.add_row("Craft Phases", str(int(counters.get("craft_phases_total", 0))))
    system_table.add_row("Craft Phase Failures", str(int(counters.get("craft_phases_failed", 0))))

    console.print(Padding(Columns([agent_table, safety_table], equal=True, expand=True), (1, 0)))
    console.print(Padding(Columns([model_table, system_table], equal=True, expand=True), (1, 0)))
    console.print()


@contextmanager
def agent_run_display(task: str, max_turns: int = 15):
    """Context manager wrapping an agent run with live terminal display.

    Usage:
        with agent_run_display("Review server.py", max_turns=15) as display:
            # ... run agent, call display.update_turn() per tool call
            pass
        # display.result is set by caller, auto-printed on exit
    """
    display = AgentDisplay()
    display.start(task, max_turns)
    try:
        yield display
    finally:
        display.stop()
