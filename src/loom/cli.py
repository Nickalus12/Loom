"""Loom CLI — run local agents and orchestration from the terminal.

Usage:
    python -m loom.cli agent "Review src/loom/server.py for bugs"
    python -m loom.cli craft "Add rate limiting to the API" --mode local
    python -m loom.cli safety "Invoke-WebRequest -Uri http://example.com"
    python -m loom.cli status
    python -m loom.cli info
    python -m loom.cli doctor
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
    print_waterfall,
    setup_rich_logging,
)


LOOM_VERSION = "Silk.1.0"

def _get_banner() -> str:
    return (
        "[bold magenta]"
        "  _                          \n"
        " | |    ___   ___  _ __ ___  \n"
        " | |   / _ \\ / _ \\| '_ ` _ \\ \n"
        " | |__| (_) | (_) | | | | | |\n"
        " |_____\\___/ \\___/|_| |_| |_|\n"
        f"[/][bold #C9A96E] {LOOM_VERSION}[/] [dim]Multi-agent orchestration platform[/]\n"
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

    effective_mode = args.mode
    if effective_mode == "auto":
        from loom.runtime import get_runtime
        runtime = await get_runtime()
        effective_mode = runtime._cache.get("recommended_mode", "cloud")
        if effective_mode == "none":
            console.print("[red]Error:[/] No inference backends available. Start Ollama or configure LiteLLM.")
            sys.exit(1)
        console.print(f"[dim]Mode: auto -> {effective_mode} ({runtime._cache.get('reason', '')})[/]\n")
    else:
        console.print(f"[dim]Mode: {effective_mode}[/]\n")

    if effective_mode in ("local", "hybrid"):
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


async def cmd_runtime(args: argparse.Namespace) -> None:
    """Show detected runtime capabilities in a Rich table."""
    from rich.table import Table

    from loom.runtime import get_runtime

    console.print(_get_banner())
    console.print("[bold cyan]Detecting runtime capabilities...[/]\n")

    runtime = await get_runtime()
    caps = runtime._cache

    table = Table(title="Runtime Capabilities", border_style="cyan", show_lines=True)
    table.add_column("Service", style="bold", width=22)
    table.add_column("Status", width=14)
    table.add_column("Details", style="dim")

    # Ollama
    ollama = caps.get("ollama", {})
    if isinstance(ollama, dict) and ollama.get("available"):
        model_list = caps.get("local_models", [])
        table.add_row(
            "Ollama",
            "[green]Online[/]",
            f"{len(model_list)} models at {ollama.get('url', '?')}\n  "
            + ", ".join(model_list[:8]) + ("..." if len(model_list) > 8 else ""),
        )
    else:
        table.add_row("Ollama", "[red]Offline[/]", "Start with: ollama serve")

    # LiteLLM
    litellm = caps.get("litellm", {})
    if isinstance(litellm, dict) and litellm.get("available"):
        table.add_row("LiteLLM", "[green]Online[/]", litellm.get("url", "?"))
    else:
        reason = litellm.get("reason", "Not configured") if isinstance(litellm, dict) else "Not configured"
        table.add_row("LiteLLM", "[red]Offline[/]", reason)

    # PowerShell
    ps = caps.get("powershell", {})
    if isinstance(ps, dict) and ps.get("available"):
        table.add_row("PowerShell", "[green]Available[/]", ps.get("path", "?"))
    else:
        table.add_row("PowerShell", "[red]Not Found[/]", "Install PowerShell 7+")

    # Neo4j
    neo4j = caps.get("neo4j", {})
    if isinstance(neo4j, dict) and neo4j.get("available"):
        table.add_row("Neo4j", "[green]Online[/]", neo4j.get("uri", "?"))
    else:
        reason = neo4j.get("reason", "Not configured") if isinstance(neo4j, dict) else "Not configured"
        table.add_row("Neo4j", "[yellow]Offline[/]", reason)

    # Nia
    nia = caps.get("nia", False)
    if nia:
        table.add_row("Nia", "[green]Configured[/]", "NIA_API_KEY set")
    else:
        table.add_row("Nia", "[yellow]Not Configured[/]", "Set NIA_API_KEY to enable")

    console.print(table)
    console.print()

    # Recommendation panel
    mode = caps.get("recommended_mode", "none")
    reason = caps.get("reason", "")
    mode_colors = {"hybrid": "green", "local": "cyan", "cloud": "magenta", "none": "red"}
    color = mode_colors.get(mode, "white")

    rec_table = Table(title="Recommended Configuration", border_style=color)
    rec_table.add_column("Setting", style="bold", width=22)
    rec_table.add_column("Value")

    rec_table.add_row("Execution Mode", f"[bold {color}]{mode}[/]")
    rec_table.add_row("Reason", reason)
    rec_table.add_row("Best Tool Model", runtime.get_best_tool_model())
    rec_table.add_row("Best Analysis Model", runtime.get_best_analysis_model())

    console.print(rec_table)
    console.print()


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


async def cmd_waterfall(args: argparse.Namespace) -> None:
    """Display the timing waterfall from the latest telemetry snapshot."""
    console.print(_get_banner())

    metrics_dir = Path(args.metrics_dir) / "metrics"
    if not metrics_dir.exists():
        console.print("[red]No metrics directory found.[/]")
        sys.exit(1)

    files = sorted(metrics_dir.glob("telemetry-*.json"), reverse=True)
    if not files:
        console.print("[red]No telemetry snapshots found.[/]")
        sys.exit(1)

    import json as _json
    data = _json.loads(files[0].read_text())
    waterfall_data = data.get("waterfall", [])

    console.print(f"[dim]Source: {files[0].name}[/]\n")
    print_waterfall(waterfall_data)


async def cmd_trace(args: argparse.Namespace) -> None:
    """Show the latest execution trace."""
    console.print(_get_banner())

    trace_dir = Path(getattr(args, "trace_dir", "docs/loom") + "/traces")
    if not trace_dir.exists():
        console.print("[yellow]No traces found. Run an agent task first.[/]")
        return

    files = sorted(trace_dir.glob("trace-*.json"), reverse=True)
    if not files:
        console.print("[yellow]No trace files found.[/]")
        return

    import json as _json
    data = _json.loads(files[0].read_text())
    events = data.get("events", [])

    console.print(f"[dim]Source: {files[0].name} | {data.get('total_events', 0)} events | {data.get('total_duration_ms', 0)}ms total[/]\n")

    from loom.tracer import ExecutionTracer, TraceEvent, EventType, print_trace
    tracer = ExecutionTracer()
    for evt in events:
        te = TraceEvent(
            event_type=EventType(evt["type"]),
            name=evt["name"],
            timestamp_ms=evt["ts_ms"],
            duration_ms=evt.get("duration_ms"),
            data=evt.get("data", {}),
            parent_idx=evt.get("parent"),
        )
        tracer._events.append(te)
    print_trace(tracer)


async def cmd_info(args: argparse.Namespace) -> None:
    """Print a comprehensive Loom system overview."""
    import subprocess

    from rich.panel import Panel
    from rich.table import Table

    console.print(_get_banner())

    project_root = Path(__file__).resolve().parents[2]

    info_table = Table(title="Loom System Overview", border_style="cyan", show_lines=True)
    info_table.add_column("Category", style="bold cyan", width=22)
    info_table.add_column("Value", style="white")

    # -- Version --
    info_table.add_row("Version", f"[bold #C9A96E]{LOOM_VERSION}[/]")

    # -- Traits --
    traits_dir = project_root / "traits"
    trait_files = list(traits_dir.rglob("*.trait.md")) if traits_dir.exists() else []
    archetype_files = list(traits_dir.rglob("*.archetype.md")) if traits_dir.exists() else []
    info_table.add_row(
        "Traits",
        f"{len(trait_files)} traits, {len(archetype_files)} archetypes"
    )

    # -- MCP Tools --
    try:
        from loom.server import mcp as _mcp
        tool_count = len(_mcp._tool_manager._tools)
        info_table.add_row("MCP Tools", f"{tool_count} tools registered")
    except Exception as exc:
        info_table.add_row("MCP Tools", f"[yellow]Could not load: {exc}[/]")

    # -- Tests --
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q", "--no-header"],
            capture_output=True, text=True, cwd=str(project_root), timeout=30,
        )
        # The last non-empty line from pytest -q --collect-only is like "684 tests collected"
        lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
        count_line = ""
        for ln in reversed(lines):
            if "test" in ln and ("collected" in ln or "selected" in ln):
                count_line = ln
                break
        if count_line:
            info_table.add_row("Tests", count_line)
        elif lines:
            # Count lines that look like test items (contain ::)
            test_items = [ln for ln in lines if "::" in ln]
            info_table.add_row("Tests", f"{len(test_items)} tests collected")
        else:
            info_table.add_row("Tests", "[yellow]0 tests found[/]")
    except Exception as exc:
        info_table.add_row("Tests", f"[yellow]Could not collect: {exc}[/]")

    # -- Agents --
    agents_dir = project_root / "agents"
    agent_files = list(agents_dir.glob("*.md")) if agents_dir.exists() else []
    info_table.add_row("Agent Definitions", f"{len(agent_files)} agents")

    # -- Telemetry --
    metrics_dir = project_root / "docs" / "loom" / "metrics"
    if metrics_dir.exists():
        telem_files = sorted(metrics_dir.glob("telemetry-*.json"), reverse=True)
        if telem_files:
            import json as _json
            try:
                data = _json.loads(telem_files[0].read_text())
                counters = data.get("counters", {})
                uptime = data.get("uptime_seconds", 0)
                tasks = int(counters.get("agent_tasks_total", 0))
                tools_called = int(counters.get("agent_tool_calls_total", 0))
                info_table.add_row(
                    "Latest Telemetry",
                    f"{telem_files[0].name}\n"
                    f"  Uptime: {uptime:.1f}s | Tasks: {tasks} | Tool calls: {tools_called}"
                )
            except Exception:
                info_table.add_row("Latest Telemetry", f"{telem_files[0].name} [yellow](parse error)[/]")
        else:
            info_table.add_row("Latest Telemetry", "[dim]No snapshots[/]")
    else:
        info_table.add_row("Latest Telemetry", "[dim]No metrics directory[/]")

    # -- Traces --
    traces_dir = project_root / "docs" / "loom" / "traces"
    if traces_dir.exists():
        trace_files = sorted(traces_dir.glob("trace-*.json"), reverse=True)
        if trace_files:
            import json as _json2
            try:
                data = _json2.loads(trace_files[0].read_text())
                total_events = data.get("total_events", len(data.get("events", [])))
                total_dur = data.get("total_duration_ms", 0)
                info_table.add_row(
                    "Latest Trace",
                    f"{trace_files[0].name}\n"
                    f"  Events: {total_events} | Duration: {total_dur}ms"
                )
            except Exception:
                info_table.add_row("Latest Trace", f"{trace_files[0].name} [yellow](parse error)[/]")
        else:
            info_table.add_row("Latest Trace", "[dim]No traces[/]")
    else:
        info_table.add_row("Latest Trace", "[dim]No traces directory[/]")

    # -- Git --
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(project_root), timeout=10,
        )
        last_commit = subprocess.run(
            ["git", "log", "-1", "--oneline"],
            capture_output=True, text=True, cwd=str(project_root), timeout=10,
        )
        git_info = f"Branch: {branch.stdout.strip()}"
        if last_commit.stdout.strip():
            git_info += f"\n  Last commit: {last_commit.stdout.strip()}"
        info_table.add_row("Git", git_info)
    except Exception:
        info_table.add_row("Git", "[yellow]Not available[/]")

    console.print(info_table)
    console.print()


async def cmd_doctor(args: argparse.Namespace) -> None:
    """Check that the Loom development environment is healthy."""
    import importlib
    import shutil
    import subprocess

    from rich.table import Table

    console.print(_get_banner())
    console.print("[bold cyan]Running health checks...[/]\n")

    project_root = Path(__file__).resolve().parents[2]
    checks: list[tuple[str, str, str]] = []  # (name, status, detail)

    # --- 1. Python version >= 3.12 ---
    py_ver = sys.version_info
    if py_ver >= (3, 12):
        checks.append(("Python >= 3.12", "[green]PASS[/]", f"{py_ver.major}.{py_ver.minor}.{py_ver.micro}"))
    else:
        checks.append(("Python >= 3.12", "[red]FAIL[/]", f"{py_ver.major}.{py_ver.minor}.{py_ver.micro} — upgrade required"))

    # --- 2. Required packages ---
    required_packages = {
        "graphiti-core": "graphiti_core",
        "litellm": "litellm",
        "mcp": "mcp",
        "rich": "rich",
    }
    for pkg_name, import_name in required_packages.items():
        try:
            mod = importlib.import_module(import_name)
            ver = getattr(mod, "__version__", "installed")
            checks.append((f"Package: {pkg_name}", "[green]PASS[/]", str(ver)))
        except ImportError:
            checks.append((f"Package: {pkg_name}", "[red]FAIL[/]", f"pip install {pkg_name}"))

    # --- 3. Ollama reachable and has required models ---
    try:
        import os

        from openai import AsyncOpenAI

        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        client = AsyncOpenAI(base_url=base_url + "/v1", api_key="ollama")
        models_resp = await client.models.list()
        model_names = [m.id for m in models_resp.data]

        checks.append(("Ollama reachable", "[green]PASS[/]", f"{len(model_names)} models available"))

        required_models = ["qwen3:4b", "deepseek-coder-v2:16b"]
        for model in required_models:
            # Check prefix match (tags may differ)
            base = model.split(":")[0]
            found = any(base in m for m in model_names)
            if found:
                checks.append((f"Model: {model}", "[green]PASS[/]", "Available"))
            else:
                checks.append((f"Model: {model}", "[yellow]WARN[/]", f"Not found — ollama pull {model}"))
    except Exception as exc:
        checks.append(("Ollama reachable", "[red]FAIL[/]", f"Cannot connect: {exc}"))

    # --- 4. PowerShell 7+ ---
    pwsh_path = shutil.which("pwsh") or shutil.which("pwsh-preview")
    if pwsh_path:
        try:
            ps_result = subprocess.run(
                [pwsh_path, "-Command", "$PSVersionTable.PSVersion.Major"],
                capture_output=True, text=True, timeout=10,
            )
            major = int(ps_result.stdout.strip())
            if major >= 7:
                checks.append(("PowerShell 7+", "[green]PASS[/]", f"v{major} at {pwsh_path}"))
            else:
                checks.append(("PowerShell 7+", "[yellow]WARN[/]", f"v{major} found — upgrade to 7+"))
        except Exception:
            checks.append(("PowerShell 7+", "[yellow]WARN[/]", f"Found at {pwsh_path} but version check failed"))
    else:
        checks.append(("PowerShell 7+", "[red]FAIL[/]", "Not found — install PowerShell 7+"))

    # --- 5. Neo4j (optional) ---
    try:
        from neo4j import AsyncGraphDatabase

        driver = AsyncGraphDatabase.driver("bolt://localhost:7687", auth=("neo4j", "password"))
        await driver.verify_connectivity()
        await driver.close()
        checks.append(("Neo4j (optional)", "[green]PASS[/]", "bolt://localhost:7687"))
    except Exception:
        checks.append(("Neo4j (optional)", "[yellow]WARN[/]", "Offline — session memory unavailable"))

    # --- 6. Trait files valid (parse frontmatter) ---
    traits_dir = project_root / "traits"
    if traits_dir.exists():
        trait_files = list(traits_dir.rglob("*.trait.md")) + list(traits_dir.rglob("*.archetype.md"))
        invalid_traits: list[str] = []
        for tf in trait_files:
            try:
                content = tf.read_text(encoding="utf-8")
                if not content.startswith("---"):
                    invalid_traits.append(f"{tf.name}: missing frontmatter delimiter")
                    continue
                # Check frontmatter has closing ---
                parts = content.split("---", 2)
                if len(parts) < 3:
                    invalid_traits.append(f"{tf.name}: unclosed frontmatter")
                    continue
                # Basic YAML parse check
                frontmatter = parts[1].strip()
                if "name:" not in frontmatter:
                    invalid_traits.append(f"{tf.name}: missing 'name' field")
            except Exception as exc:
                invalid_traits.append(f"{tf.name}: {exc}")
        if not invalid_traits:
            checks.append(("Trait files valid", "[green]PASS[/]", f"{len(trait_files)} files parsed OK"))
        else:
            detail = f"{len(invalid_traits)}/{len(trait_files)} invalid: {invalid_traits[0]}"
            checks.append(("Trait files valid", "[red]FAIL[/]", detail))
    else:
        checks.append(("Trait files valid", "[yellow]WARN[/]", "No traits/ directory found"))

    # --- 7. Smoke test (5 random tests) ---
    try:
        # First collect all test node IDs
        collect_result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit/", "--collect-only", "-q", "--no-header"],
            capture_output=True, text=True, cwd=str(project_root), timeout=30,
        )
        test_ids = [
            ln.strip() for ln in collect_result.stdout.splitlines()
            if ln.strip() and "::" in ln
        ]
        if test_ids:
            import random
            sample = random.sample(test_ids, min(5, len(test_ids)))
            smoke_cmd = [sys.executable, "-m", "pytest", "--tb=line", "-q", "--no-header"] + sample
            smoke_result = subprocess.run(
                smoke_cmd, capture_output=True, text=True,
                cwd=str(project_root), timeout=60,
            )
            if smoke_result.returncode == 0:
                checks.append(("Smoke tests (5 random)", "[green]PASS[/]", f"{len(sample)} tests passed"))
            else:
                # Extract failure summary
                fail_lines = [
                    ln for ln in smoke_result.stdout.splitlines()
                    if "FAILED" in ln or "ERROR" in ln
                ]
                detail = fail_lines[0] if fail_lines else "Tests failed"
                checks.append(("Smoke tests (5 random)", "[red]FAIL[/]", detail[:80]))
        else:
            checks.append(("Smoke tests (5 random)", "[yellow]WARN[/]", "No tests collected"))
    except Exception as exc:
        checks.append(("Smoke tests (5 random)", "[yellow]WARN[/]", f"Could not run: {exc}"))

    # --- Render results ---
    table = Table(title="Loom Doctor", border_style="cyan", show_lines=False)
    table.add_column("Check", style="bold", width=26)
    table.add_column("Status", width=12)
    table.add_column("Details", style="dim")

    pass_count = 0
    warn_count = 0
    fail_count = 0
    for name, status, detail in checks:
        table.add_row(name, status, detail)
        if "PASS" in status:
            pass_count += 1
        elif "WARN" in status:
            warn_count += 1
        else:
            fail_count += 1

    console.print(table)

    # Summary
    console.print()
    parts = [f"[green]{pass_count} passed[/]"]
    if warn_count:
        parts.append(f"[yellow]{warn_count} warnings[/]")
    if fail_count:
        parts.append(f"[red]{fail_count} failed[/]")
    console.print(f"  {' | '.join(parts)}")

    if fail_count == 0 and warn_count == 0:
        console.print("  [bold green]All systems healthy.[/]")
    elif fail_count == 0:
        console.print("  [bold yellow]System functional with warnings.[/]")
    else:
        console.print("  [bold red]Some checks failed — see above for details.[/]")
    console.print()


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
    p_craft.add_argument("--mode", choices=["auto", "cloud", "local", "hybrid"], default="auto")
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

    # trace
    p_trace = subparsers.add_parser("trace", help="Show latest agent execution trace")
    p_trace.add_argument("--trace-dir", default="docs/loom", help="Metrics directory")

    # waterfall
    p_waterfall = subparsers.add_parser("waterfall", help="Show timing waterfall from latest metrics")
    p_waterfall.add_argument("--metrics-dir", default="docs/loom", help="Metrics state directory")

    # test
    p_test = subparsers.add_parser("test", help="Run the test suite")
    p_test.add_argument("--filter", default="", help="Test filter pattern")

    # runtime
    subparsers.add_parser("runtime", help="Detect and display runtime capabilities")

    # info
    subparsers.add_parser("info", help="Print comprehensive system overview")

    # doctor
    subparsers.add_parser("doctor", help="Run health checks on the environment")

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
        "trace": cmd_trace,
        "waterfall": cmd_waterfall,
        "test": cmd_test,
        "runtime": cmd_runtime,
        "info": cmd_info,
        "doctor": cmd_doctor,
    }

    handler = commands.get(args.command)
    if handler:
        asyncio.run(handler(args))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
