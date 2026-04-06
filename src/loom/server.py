import asyncio
import json
import os
from pathlib import Path
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

_project_root = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_project_root / ".env")


def _escape_ps(value: str) -> str:
    """Escape a value for safe interpolation inside PowerShell single-quoted strings."""
    return value.replace("'", "''")


_RECOVERY_HINTS: dict[str, str] = {
    "ConnectionRefusedError": "Service is not running. Check Docker (neo4j, litellm) or Ollama.",
    "FileNotFoundError": "File does not exist. Check the path and try again.",
    "TimeoutError": "Operation timed out. The service may be overloaded.",
    "PermissionError": "Permission denied. Check file permissions.",
    "JSONDecodeError": "Invalid JSON response from service.",
    "ConnectionError": "Network connection failed. Check that the target service is reachable.",
    "OSError": "OS-level error. Check disk space, permissions, or network interfaces.",
    "ValueError": "Invalid input or configuration. Check environment variables and arguments.",
}


def _error_response(tool_name: str, error: Exception, recovery_hint: str = "") -> str:
    """Standard structured error response for MCP tools."""
    result = {
        "success": False,
        "error": str(error),
        "error_type": type(error).__name__,
        "tool": tool_name,
    }
    if recovery_hint:
        result["recovery_hint"] = recovery_hint
    return json.dumps(result, default=str)

from loom.memory_engine import LoomSwarmMemory
from loom.orchestrator import LoomOrchestrator
from loom.agent_registry import AgentRegistry
from loom.local_inference import LocalInferenceEngine
from loom.powershell_tools import PowerShellREPLManager
from loom.powershell_tools.kan_engine import PowerShellKANEngine
from loom.local_agent import LocalAgent

mcp = FastMCP(
    "Loom Enterprise Swarm",
    dependencies=[
        "mcp", "litellm", "graphiti-core", "python-dotenv",
        "tree-sitter", "tree-sitter-python", "tree-sitter-typescript", "tree-sitter-javascript",
    ]
)

_memory_engine: LoomSwarmMemory | None = None
_swarm_orchestrator: LoomOrchestrator | None = None
_local_engine: LocalInferenceEngine | None = None
_ps_manager: PowerShellREPLManager | None = None
_kan_engine: PowerShellKANEngine | None = None
_local_agent: LocalAgent | None = None


def _get_engines() -> tuple[LoomSwarmMemory, LoomOrchestrator]:
    """Lazy-initialize engines on first use. Retries if services weren't ready earlier."""
    global _memory_engine, _swarm_orchestrator
    if _memory_engine is None or _swarm_orchestrator is None:
        _memory_engine = LoomSwarmMemory()
        registry = AgentRegistry()
        _swarm_orchestrator = LoomOrchestrator(_memory_engine, registry)
    return _memory_engine, _swarm_orchestrator


def _get_local_engine() -> LocalInferenceEngine:
    """Lazy-initialize the local inference engine on first use."""
    global _local_engine
    if _local_engine is None:
        memory, _ = _get_engines()
        _local_engine = LocalInferenceEngine(memory_engine=memory)
        asyncio.get_running_loop().create_task(_local_engine.start_background_worker())
    return _local_engine


def _get_kan_engine() -> PowerShellKANEngine:
    """Lazy-initialize the KAN engine on first use."""
    global _kan_engine
    if _kan_engine is None:
        memory, _ = _get_engines()
        _kan_engine = PowerShellKANEngine(memory_engine=memory)
    return _kan_engine


def _get_ps_manager() -> PowerShellREPLManager:
    """Lazy-initialize the PowerShell REPL manager on first use."""
    global _ps_manager
    if _ps_manager is None:
        memory, _ = _get_engines()
        local = _get_local_engine()
        kan = _get_kan_engine()
        _ps_manager = PowerShellREPLManager(
            project_root=_project_root,
            local_engine=local,
            memory_engine=memory,
            kan_engine=kan,
        )
    return _ps_manager


def _get_local_agent() -> LocalAgent:
    """Lazy-initialize the local agent on first use."""
    global _local_agent
    if _local_agent is None:
        memory, _ = _get_engines()
        engine = _get_local_engine()
        manager = _get_ps_manager()
        _local_agent = LocalAgent(
            inference_engine=engine,
            ps_manager=manager,
            memory_engine=memory,
        )
    return _local_agent


@mcp.tool()
async def craft(
    task: str = Field(description="The engineering task to craft via multi-agent pipeline."),
    mode: str = Field(default="cloud", description="Execution mode: 'cloud' (LiteLLM proxy) or 'local' (Ollama LocalAgent)."),
) -> str:
    """Craft a solution using Loom's multi-agent pipeline.
    Runs: Architect → Security + Quality (parallel) → Coder → Code Review.
    Use mode='local' to execute phases with the local Ollama agent (tool-calling, git safety, caching)."""
    from loom.telemetry import get_telemetry
    tel = get_telemetry()
    tel.waterfall.begin("craft")
    try:
        effective_mode = mode or os.getenv("LOOM_CRAFT_MODE", "cloud")
        if effective_mode == "local":
            agent = _get_local_agent()
            tel.waterfall.begin("synthesize_agent")
            result = await agent.run(
                f"You are orchestrating a multi-phase engineering task. "
                f"First analyze the architecture, then implement, then review your work.\n\nTask: {task}"
            )
            tel.waterfall.end()
            return json.dumps(result, default=str)
        else:
            memory, orchestrator = _get_engines()
            tel.waterfall.begin("synthesize_agent")
            plan = await orchestrator.execute_swarm(task)
            tel.waterfall.end()
            phases_summary = "; ".join(
                f"Phase {p.id} ({p.name}): {p.status}" for p in plan.phases
            )
            return json.dumps({
                "success": True,
                "phases": len(plan.phases),
                "summary": phases_summary,
                "files_created": [f for p in plan.phases for f in p.files_created],
                "files_modified": [f for p in plan.phases for f in p.files_modified],
            }, default=str)
    except Exception as e:
        return _error_response("craft", e, _RECOVERY_HINTS.get(type(e).__name__, ""))
    finally:
        tel.waterfall.end()

@mcp.tool()
async def get_context_for_coder(target_file: str = Field(description="The file path to retrieve context and bugs for.")) -> dict:
    """
    Retrieves temporal context, dependencies, and active bugs for a specific file.
    Mandatory for the Coder agent before starting any work.
    """
    try:
        memory, _ = _get_engines()
        return await memory.get_context_for_coder(target_file)
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__, "tool": "get_context_for_coder"}

@mcp.tool()
async def add_file_node(file_path: str, summary: str) -> str:
    """
    Creates a node in Graphiti for a file.
    In V3, this automatically triggers AST parsing to identify functions and classes.
    """
    try:
        memory, _ = _get_engines()
        node = await memory.add_file_node(file_path, summary)
        return f"File node created: {node.uuid}"
    except Exception as e:
        return _error_response("add_file_node", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def add_bug_edge(source_uuid: str, file_uuid: str, description: str) -> str:
    """Records a HAS_BUG relationship in the temporal knowledge graph."""
    try:
        memory, _ = _get_engines()
        edge = await memory.add_bug_edge(source_uuid, file_uuid, description)
        return f"Bug recorded: {edge.uuid}"
    except Exception as e:
        return _error_response("add_bug_edge", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def blackboard_transition(edge_uuids: list[str], agent_name: str) -> str:
    """Invalidates bug edges after a fix, preserving historical state."""
    try:
        memory, _ = _get_engines()
        await memory.blackboard_transition(edge_uuids, agent_name)
        return "Blackboard state transitioned."
    except Exception as e:
        return _error_response("blackboard_transition", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def list_agents() -> dict:
    """Returns the full roster of available agents with their tier, temperature, and description."""
    try:
        _, orchestrator = _get_engines()
        agents = []
        for name in orchestrator.agents.list_agents():
            config = orchestrator.agents.get(name)
            agents.append({
                "name": config.name,
                "tier": config.tier,
                "temperature": config.temperature,
                "max_turns": config.max_turns,
                "description": config.description,
            })
        return {"agents": agents, "count": len(agents)}
    except Exception as e:
        return {"success": False, "error": str(e), "error_type": type(e).__name__, "tool": "list_agents"}

@mcp.tool()
async def execute_plan(
    task: str = Field(description="High-level task description."),
    phases: list[dict] = Field(description="List of phase dicts with keys: id, name, agent, objective, parallel (bool), blocked_by (list[int])."),
) -> str:
    """Execute a custom multi-phase plan through the agent swarm."""
    try:
        _, orchestrator = _get_engines()
        from loom.orchestrator import Phase, SwarmPlan
        plan = SwarmPlan(
            task=task,
            phases=[Phase(
                id=p["id"],
                name=p["name"],
                agent=p["agent"],
                objective=p["objective"],
                parallel=p.get("parallel", False),
                blocked_by=p.get("blocked_by", []),
            ) for p in phases],
        )
        result = await orchestrator.execute_plan(plan)
        summary = "; ".join(f"Phase {p.id} ({p.name}): {p.status}" for p in result.phases)
        return f"Plan completed — {len(result.phases)} phases: {summary}"
    except Exception as e:
        return _error_response("execute_plan", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def local_brainstorm(task: str, context: str = "") -> str:
    """
    Generate creative approaches and ideas using a fast local Gemma 4 E2B model.
    Use this for quick brainstorming, ideation, and exploring alternative approaches
    before committing to a strategy. Runs locally on GPU for near-instant response.
    """
    try:
        engine = _get_local_engine()
        return await engine.brainstorm(task, context)
    except Exception as e:
        return _error_response("local_brainstorm", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def local_review(code: str, file_path: str) -> str:
    """
    Quick code review using a fast local Gemma 4 E2B model.
    Analyzes code for bugs, anti-patterns, security issues, and style problems.
    Returns findings with confidence ratings. Use for fast pre-review before
    detailed cloud-based analysis.
    """
    try:
        engine = _get_local_engine()
        result = await engine.review(code, file_path)
        return str(result)
    except Exception as e:
        return _error_response("local_review", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def local_debug(error: str, context: str = "") -> str:
    """
    Analyze errors and stack traces using a fast local Gemma 4 E2B model.
    Provides quick diagnostic suggestions and probable root causes.
    Runs locally for near-instant debugging assistance.
    """
    try:
        engine = _get_local_engine()
        return await engine.debug_assist(error, context)
    except Exception as e:
        return _error_response("local_debug", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def local_status() -> str:
    """
    Check the status of local Gemma 4 models and background analysis worker.
    Returns: model availability, loaded models, worker state, last analysis time.
    """
    try:
        engine = _get_local_engine()
        result = await engine.get_status()
        return str(result)
    except Exception as e:
        return _error_response("local_status", e, _RECOVERY_HINTS.get(type(e).__name__, ""))


# ---------------------------------------------------------------------------
# PowerShell REPL Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def execute_powershell(
    script: str = Field(description="PowerShell script or command to execute."),
    session_id: str = "default",
    timeout: int = 120,
) -> str:
    """Execute a PowerShell 7.6 command in a persistent REPL session.
    Commands are safety-reviewed by local Gemma before execution.
    State persists across calls within the same session_id."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute(script, session_id=session_id, timeout=timeout)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("execute_powershell", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def define_custom_tool(
    name: str = Field(description="Name for the custom PowerShell tool/function."),
    script: str = Field(description="PowerShell script body for the function."),
) -> str:
    """Define a persistent custom PowerShell function available in all sessions."""
    try:
        manager = _get_ps_manager()
        await manager.register_custom_tool(name, script)
        return json.dumps({"success": True, "tool": name, "message": f"Custom tool '{name}' registered"})
    except Exception as e:
        return _error_response("define_custom_tool", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def list_powershell_tools() -> str:
    """List all registered custom PowerShell tools."""
    try:
        manager = _get_ps_manager()
        tools = manager.list_custom_tools()
        return json.dumps({"success": True, "tools": tools, "count": len(tools)})
    except Exception as e:
        return _error_response("list_powershell_tools", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def get_tool_help(cmdlet: str = Field(description="PowerShell cmdlet name to get help for.")) -> str:
    """Get help documentation for a PowerShell cmdlet."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute(f"Get-Help '{_escape_ps(cmdlet)}' -Full | Out-String", timeout=30)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("get_tool_help", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def read_file_ps(path: str = Field(description="File path to read.")) -> str:
    """Read a file using PowerShell with line numbers."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute(f"Read-LoomFile '{_escape_ps(path)}'", timeout=30)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("read_file_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def write_file_ps(
    path: str = Field(description="File path to write to."),
    content: str = Field(description="Content to write."),
) -> str:
    """Write content to a file using PowerShell."""
    try:
        manager = _get_ps_manager()
        escaped = content.replace("'", "''")
        result = await manager.execute(f"Write-LoomFile '{_escape_ps(path)}' '{escaped}'", timeout=30)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("write_file_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def search_code_ps(
    query: str = Field(description="Regex pattern to search for in code files."),
    path: str = ".",
    include: str = "*.*",
) -> str:
    """Search code files for a pattern using PowerShell."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute(f"Search-LoomCode '{_escape_ps(query)}' -Path '{_escape_ps(path)}' -Include '{_escape_ps(include)}'", timeout=60)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("search_code_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def find_files_ps(
    pattern: str = Field(description="File name pattern (e.g., '*.py', '*.ts')."),
    path: str = ".",
) -> str:
    """Find files by name pattern using PowerShell."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute(f"Find-LoomFiles '{_escape_ps(pattern)}' -Path '{_escape_ps(path)}'", timeout=30)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("find_files_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def git_status_ps() -> str:
    """Get git status with structured output."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute("Get-LoomGitStatus", timeout=30)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("git_status_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def git_diff_ps(path: str = "", staged: bool = False) -> str:
    """Get git diff output, optionally for staged changes or a specific path."""
    try:
        manager = _get_ps_manager()
        cmd = "Get-LoomGitDiff"
        if staged:
            cmd += " -Staged"
        if path:
            cmd += f" -Path '{_escape_ps(path)}'"
        result = await manager.execute(cmd, timeout=30)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("git_diff_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def git_commit_ps(message: str = Field(description="Commit message.")) -> str:
    """Stage all changes and create a git commit."""
    try:
        manager = _get_ps_manager()
        escaped = message.replace("'", "''")
        result = await manager.execute(f"New-LoomGitCommit '{escaped}'", timeout=30)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("git_commit_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def git_push_ps() -> str:
    """Push commits to the remote repository."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute("git push 2>&1 | Out-String", timeout=60)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("git_push_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def git_branch_ps() -> str:
    """List git branches with current branch highlighted."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute("git branch -a 2>&1 | Out-String", timeout=15)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("git_branch_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def git_log_ps(limit: int = 20) -> str:
    """Get structured git log."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute(f"Get-LoomGitLog -Limit {limit}", timeout=15)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("git_log_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def git_stash_ps() -> str:
    """Stash current changes with auto-generated message."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute("Save-LoomGitStash", timeout=15)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("git_stash_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def git_pop_ps() -> str:
    """Pop the most recent git stash."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute("Restore-LoomGitStash", timeout=15)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("git_pop_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def build_project_ps() -> str:
    """Auto-detect and run the project build system."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute("Invoke-LoomBuild", timeout=300)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("build_project_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def test_project_ps(filter: str = "") -> str:
    """Auto-detect and run project tests, optionally with a filter."""
    try:
        manager = _get_ps_manager()
        cmd = "Invoke-LoomTest"
        if filter:
            cmd += f" -Filter '{_escape_ps(filter)}'"
        result = await manager.execute(cmd, timeout=300)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("test_project_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def run_command_ps(
    cmd: str = Field(description="Shell command to run."),
    cwd: str = "",
) -> str:
    """Run an arbitrary command in the PowerShell session."""
    try:
        manager = _get_ps_manager()
        script = cmd
        if cwd:
            script = f"Push-Location '{_escape_ps(cwd)}'; try {{ {cmd} }} finally {{ Pop-Location }}"
        result = await manager.execute(script, timeout=120)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("run_command_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def install_psresource_ps(name: str = Field(description="PowerShell module name to install.")) -> str:
    """Install a PowerShell module using PSResourceGet 1.2."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute(
            f"Install-PSResource -Name '{_escape_ps(name)}' -Scope CurrentUser -TrustRepository -Quiet 2>&1 | Out-String",
            timeout=120,
        )
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("install_psresource_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def manage_python_env_ps(
    action: str = Field(description="Action: create, activate, or list."),
    env_name: str = "venv",
) -> str:
    """Manage Python virtual environments via PowerShell."""
    try:
        manager = _get_ps_manager()
        safe_env = _escape_ps(env_name)
        if action == "create":
            script = f"python -m venv '{safe_env}'; Write-Output 'Created {safe_env}'"
        elif action == "activate":
            script = f".\\{safe_env}\\Scripts\\Activate.ps1; Write-Output 'Activated {safe_env}'"
        elif action == "list":
            script = "Get-ChildItem -Directory | Where-Object { Test-Path (Join-Path $_.FullName 'Scripts/activate') } | Select-Object -ExpandProperty Name"
        else:
            return json.dumps({"success": False, "error": f"Unknown action: {action}"})
        result = await manager.execute(script, timeout=60)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("manage_python_env_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def analyze_file_ps(path: str = Field(description="File path to analyze with local Gemma.")) -> str:
    """Read a file and analyze it using the local Gemma 4 E2B model."""
    try:
        resolved = Path(path).resolve()
        if not str(resolved).startswith(str(_project_root.resolve())):
            return json.dumps({"success": False, "error": "Path outside project root"})
        if resolved.stat().st_size > 512_000:
            return json.dumps({"success": False, "error": "File too large (>512KB)"})
        with open(resolved, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        engine = _get_local_engine()
        result = await engine.review(content, str(path))
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("analyze_file_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def background_insights_ps() -> str:
    """Get recent background analysis insights from the local Gemma model."""
    try:
        engine = _get_local_engine()
        status = await engine.get_status()
        return json.dumps(status, default=str)
    except Exception as e:
        return _error_response("background_insights_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def get_gpu_status_ps() -> str:
    """Get NVIDIA GPU status including VRAM usage."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute("Get-LoomGpuStatus", timeout=15)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("get_gpu_status_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def disk_usage_ps() -> str:
    """Get disk usage information."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute("Get-LoomDiskUsage", timeout=15)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("disk_usage_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def memory_usage_ps() -> str:
    """Get system memory usage information."""
    try:
        manager = _get_ps_manager()
        result = await manager.execute("Get-LoomMemoryUsage", timeout=15)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("memory_usage_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))



# ---------------------------------------------------------------------------
# KAN Intelligence Engine Tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def kan_score_command(command: str = Field(description="PowerShell command to score for risk.")) -> str:
    """Score a PowerShell command's risk level using the KAN neural network.
    Returns instant (<1ms) risk assessment with feature breakdown.
    Works with or without PyTorch (falls back to heuristic scoring)."""
    try:
        kan = _get_kan_engine()
        result = await kan.score_risk(command)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("kan_score_command", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def kan_train_ps() -> str:
    """Trigger KAN model retraining from accumulated command history.
    The model learns from past command outcomes to improve safety scoring."""
    try:
        kan = _get_kan_engine()
        result = await kan.retrain()
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("kan_train_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def kan_learn_history_ps(limit: int = 200) -> str:
    """Train the KAN model from Graphiti command history.
    Queries the knowledge graph for past PowerShell executions and their outcomes."""
    try:
        kan = _get_kan_engine()
        result = await kan.learn_from_history(limit=limit)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("kan_learn_history_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))

@mcp.tool()
async def kan_status_ps() -> str:
    """Get the status of the KAN intelligence engine including model type,
    training data size, and initialization state."""
    try:
        kan = _get_kan_engine()
        result = kan.get_status()
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("kan_status_ps", e, _RECOVERY_HINTS.get(type(e).__name__, ""))


@mcp.tool()
async def local_agent_task(
    task: str = Field(description="Natural language task for the local Ollama agent (e.g., 'Review src/loom/server.py for bugs' or 'Add error handling to the parse function in utils.py')."),
) -> str:
    """Run a local Ollama agent that can read, edit, search files, and execute
    PowerShell commands to accomplish a task. The agent uses tool calling to
    autonomously work through multi-step tasks like code reviews, bug fixes,
    and file updates. Features: dual-model routing, git safety branching,
    result caching, retry on failure, syntax validation, and Graphiti session memory.
    Configure models via LOOM_AGENT_TOOL_MODEL and LOOM_AGENT_ANALYSIS_MODEL env vars."""
    try:
        agent = _get_local_agent()
        result = await agent.run(task)
        return json.dumps(result, default=str)
    except Exception as e:
        return _error_response("local_agent_task", e, _RECOVERY_HINTS.get(type(e).__name__, ""))


if __name__ == "__main__":
    # Start the MCP server using stdio transport
    mcp.run()
