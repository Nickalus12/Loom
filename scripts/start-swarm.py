"""Loom swarm MCP server launcher — self-diagnosing, zero-config.

This script is the entry point for the loom-swarm MCP server. It:
1. Auto-detects the Loom project root (works from plugin dir OR dev dir)
2. Validates Python environment and dependencies
3. Prints actionable errors on failure instead of silent MCP disconnects
4. Starts the FastMCP server on stdio

Used by: claude/.mcp.json, mcp.json, Claude Desktop, Gemini CLI
"""
import os
import sys
from pathlib import Path


def find_loom_root() -> Path:
    """Find the Loom project root by searching for pyproject.toml with name='loom'."""
    # Priority 1: LOOM_PLUGIN_ROOT env var (set by .mcp.json via ${CLAUDE_PLUGIN_ROOT}/..)
    env_root = os.getenv("LOOM_PLUGIN_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if (p / "src" / "loom" / "server.py").exists():
            return p

    # Priority 2: script's own location (scripts/ is inside the repo)
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    if (repo_root / "src" / "loom" / "server.py").exists():
        return repo_root

    # Priority 3: current working directory
    cwd = Path.cwd()
    if (cwd / "src" / "loom" / "server.py").exists():
        return cwd

    # Priority 4: walk up from cwd looking for pyproject.toml
    check = cwd
    for _ in range(5):
        if (check / "pyproject.toml").exists() and (check / "src" / "loom").exists():
            return check
        check = check.parent

    return repo_root  # best guess


def validate_environment(root: Path) -> list[str]:
    """Check that the Python environment can run the swarm server."""
    errors = []

    # Check Python version
    if sys.version_info < (3, 11):
        errors.append(f"Python 3.11+ required, found {sys.version_info.major}.{sys.version_info.minor}")

    # Check source directory exists
    src = root / "src" / "loom"
    if not src.exists():
        errors.append(f"Loom source not found at {src}")
        return errors

    # Check key modules exist
    required = ["server.py", "orchestrator.py", "local_agent.py", "runtime.py",
                 "telemetry.py", "local_inference.py"]
    missing = [f for f in required if not (src / f).exists()]
    if missing:
        errors.append(f"Missing modules in {src}: {', '.join(missing)}")
        errors.append("Your Loom plugin may be outdated. Reinstall from GitHub:")
        errors.append("  claude plugin update loom")

    # Check critical dependencies
    for pkg, import_name in [("mcp", "mcp"), ("openai", "openai")]:
        try:
            __import__(import_name)
        except ImportError:
            errors.append(f"Missing dependency: {pkg}. Install with: pip install {pkg}")

    return errors


def main():
    root = find_loom_root()

    # Ensure src/ is on the path
    src_path = str(root / "src")
    if src_path not in sys.path:
        sys.path.insert(0, src_path)

    # Validate environment
    errors = validate_environment(root)
    if errors:
        # Print errors to stderr (MCP clients capture this for diagnostics)
        for err in errors:
            print(f"[loom-swarm] ERROR: {err}", file=sys.stderr)
        print(f"[loom-swarm] Loom root: {root}", file=sys.stderr)
        print(f"[loom-swarm] Python: {sys.executable}", file=sys.stderr)
        print(f"[loom-swarm] sys.path[0]: {sys.path[0]}", file=sys.stderr)
        sys.exit(1)

    # Set LOOM_ALLOWED_ROOT if not already set — default to parent of Loom dir
    if not os.getenv("LOOM_ALLOWED_ROOT"):
        os.environ["LOOM_ALLOWED_ROOT"] = str(root.parent)

    # Change to Loom root so relative paths work
    os.chdir(root)

    # Start the server
    try:
        from loom.server import mcp
        mcp.run()
    except Exception as exc:
        print(f"[loom-swarm] FATAL: Server failed to start: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
