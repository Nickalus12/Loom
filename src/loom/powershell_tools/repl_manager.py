import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loom.powershell_tools.kan_engine import PowerShellKANEngine

logger = logging.getLogger(__name__)

_DANGEROUS_COMMANDS: frozenset[str] = frozenset({
    # Hard-blocked: destructive system commands that should never run
    "Remove-Item -Recurse -Force /",
    "Format-Volume",
    "Stop-Computer",
    "Restart-Computer",
    "Clear-RecycleBin",
    "rm -rf",
    "del /s /q C:\\",
})

_ELEVATED_REVIEW_COMMANDS: frozenset[str] = frozenset({
    # These commands are legitimate but risky — force Gemma LLM review
    # even when KAN scores them as safe. If Gemma (or Ollama) is unavailable,
    # the fail-closed handler in _execute_inner blocks them.
    # Network operations
    "invoke-webrequest",
    "invoke-restmethod",
    "send-mailmessage",
    "start-bitstransfer",
    # Process / service manipulation
    "stop-service",
    "set-service",
    "new-service",
    "start-process",
    # Firewall / network config
    "new-netfirewallrule",
    "remove-netfirewallrule",
    "disable-netadapter",
    # Execution bypass
    "invoke-expression",
    "set-executionpolicy",
    # Registry modification
    "set-itemproperty",
    "new-itemproperty",
    "remove-itemproperty",
})

_PWSH_CANDIDATES: tuple[str, ...] = ("pwsh-preview", "pwsh", "powershell")

_MODULE_PATH = str(Path(__file__).parent / "LoomAgentTools.psm1").replace("\\", "/")

_SESSION_INIT_TEMPLATE = """\
$ErrorActionPreference = 'Continue'
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
# Note: ConstrainedLanguage mode cannot be set programmatically from FullLanguage.
# Security is enforced via: (1) local Gemma safety review, (2) path allowlist,
# (3) dangerous command blocklist, and (4) project-root working directory.
Set-Location '__LOOM_PROJECT_ROOT__'
try {
    Import-Module '__LOOM_MODULE_PATH__' -Force -ErrorAction Stop
} catch {
    Write-Warning "Loom module failed to load: $($_.Exception.Message). Loom cmdlets will be unavailable."
}
"""

_EXEC_WRAPPER_TEMPLATE = """\
$__loom_marker = '__LOOM_MARKER__'
Write-Host $__loom_marker
try {
    __LOOM_SCRIPT__
} catch {
    Write-Error $_.Exception.Message
}
Write-Host "LOOM_EXIT:$($?):$LASTEXITCODE"
Write-Host $__loom_marker
"""


class PowerShellREPLManager:
    """Manages persistent PowerShell 7.6 sessions for agent-native command execution.

    Each session is a long-running pwsh process communicating via stdin/stdout
    using a marker-based protocol. Commands are safety-checked before execution,
    and results are optionally logged to Graphiti via the memory engine.
    """

    def __init__(
        self,
        project_root: str | Path | None = None,
        local_engine: Any = None,
        memory_engine: Any = None,
        kan_engine: PowerShellKANEngine | None = None,
    ) -> None:
        self._project_root = Path(project_root) if project_root else Path.cwd()
        self._local_engine = local_engine
        self._memory = memory_engine
        self._kan = kan_engine or PowerShellKANEngine(memory_engine=memory_engine)
        self._sessions: dict[str, dict] = {}
        self._custom_tools: dict[str, str] = {}
        self._dangerous_commands = _DANGEROUS_COMMANDS
        self._elevated_review_commands = _ELEVATED_REVIEW_COMMANDS
        self._allowed_root = str(self._project_root.resolve())
        self._pwsh_path: str | None = None

    async def _find_pwsh(self) -> str:
        if self._pwsh_path is not None:
            return self._pwsh_path

        for candidate in _PWSH_CANDIDATES:
            try:
                proc = await asyncio.create_subprocess_exec(
                    candidate, "--version",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode == 0:
                    self._pwsh_path = candidate
                    logger.info("Found PowerShell executable: %s", candidate)
                    return candidate
            except (FileNotFoundError, OSError):
                continue
            except asyncio.TimeoutError:
                logger.debug("Timeout checking %s", candidate)
                continue

        raise RuntimeError(
            "PowerShell 7.6+ not found. Install from https://github.com/PowerShell/PowerShell"
        )

    async def _get_or_create_session(self, session_id: str = "default") -> asyncio.subprocess.Process:
        existing = self._sessions.get(session_id)
        if existing is not None:
            proc = existing["process"]
            if proc.returncode is None:
                return proc
            logger.warning("Session '%s' process exited (rc=%s), restarting", session_id, proc.returncode)

        pwsh_path = await self._find_pwsh()

        proc = await asyncio.create_subprocess_exec(
            pwsh_path, "-NoProfile", "-NonInteractive", "-Command", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        init_script = _SESSION_INIT_TEMPLATE.replace(
            "__LOOM_PROJECT_ROOT__", str(self._project_root).replace("'", "''")
        ).replace(
            "__LOOM_MODULE_PATH__", _MODULE_PATH
        )
        init_marker = f"___LOOM_INIT_{uuid.uuid4().hex[:12]}___"
        wrapped_init = f"Write-Host '{init_marker}'\n{init_script}\nWrite-Host '{init_marker}'\n"

        proc.stdin.write(wrapped_init.encode("utf-8"))
        await proc.stdin.drain()

        try:
            await self._read_until_marker(proc, init_marker, timeout=15)
        except asyncio.TimeoutError:
            logger.warning("Session '%s' initialization timed out, proceeding anyway", session_id)

        self._sessions[session_id] = {
            "process": proc,
            "created": datetime.now(timezone.utc),
            "command_count": 0,
            "last_command": None,
        }

        logger.info("PowerShell session '%s' created (pid=%d)", session_id, proc.pid)
        return proc

    async def _read_until_marker(
        self,
        proc: asyncio.subprocess.Process,
        marker: str,
        timeout: int = 120,
    ) -> str:
        lines: list[str] = []
        marker_count = 0

        async def _reader() -> str:
            nonlocal marker_count
            while True:
                raw_line = await proc.stdout.readline()
                if not raw_line:
                    break
                line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                if marker in line:
                    marker_count += 1
                    if marker_count >= 2:
                        return "\n".join(lines)
                    continue
                if marker_count >= 1:
                    lines.append(line)
            return "\n".join(lines)

        return await asyncio.wait_for(_reader(), timeout=timeout)

    async def _collect_stderr(self, proc: asyncio.subprocess.Process) -> str:
        collected: list[str] = []
        try:
            while True:
                raw = await asyncio.wait_for(proc.stderr.readline(), timeout=0.1)
                if not raw:
                    break
                collected.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        except asyncio.TimeoutError:
            pass
        return "\n".join(collected)

    async def _send_and_receive(
        self,
        proc: asyncio.subprocess.Process,
        wrapped_script: str,
        marker: str,
        timeout: int,
    ) -> tuple[str, str]:
        proc.stdin.write(wrapped_script.encode("utf-8"))
        await proc.stdin.drain()

        stdout_content = await self._read_until_marker(proc, marker, timeout=timeout)
        stderr_content = await self._collect_stderr(proc)

        return stdout_content, stderr_content

    async def execute(
        self,
        script: str,
        session_id: str = "default",
        timeout: int = 120,
        structured: bool = True,
    ) -> dict:
        try:
            return await self._execute_inner(script, session_id, timeout, structured)
        except RuntimeError as exc:
            error_msg = str(exc)
            if "not found" in error_msg.lower():
                return {"success": False, "error": "PowerShell 7.6+ not available"}
            return {"success": False, "error": error_msg}
        except Exception as exc:
            logger.error("Unexpected error in execute: %s", exc, exc_info=True)
            return {"success": False, "error": f"Execution failed: {exc}"}

    async def _execute_inner(
        self,
        script: str,
        session_id: str,
        timeout: int,
        structured: bool,
    ) -> dict:
        safety_start = time.monotonic()
        safety_timing: dict[str, int] = {}

        # --- Tier 1: KAN Neural Scoring ---
        kan_start = time.monotonic()
        kan_result = await self._kan.score_risk(script)
        safety_timing["kan_ms"] = int((time.monotonic() - kan_start) * 1000)

        # Check elevated review BEFORE KAN blocking — elevated commands bypass
        # the KAN hard-block and route to Gemma for intelligent review instead.
        elevated_match = self._check_elevated_review(script)
        requires_gemma = elevated_match is not None

        if kan_result.get("risk_level") == "blocked" and not requires_gemma:
            logger.warning("KAN pre-filter blocked command: %s", kan_result.get("risk_score"))
            return {
                "success": False,
                "output": "",
                "errors": "Command blocked by KAN safety pre-filter",
                "session_id": session_id,
                "execution_time_ms": 0,
                "command": script,
                "safety": kan_result,
            }

        skip_gemma = (
            not requires_gemma
            and kan_result.get("risk_level") == "safe"
            and kan_result.get("risk_score", 1.0) < 0.2
            and kan_result.get("model") == "kan"
        )

        # --- Tier 2: Dangerous Command Blocklist ---
        blocklist_start = time.monotonic()
        dangerous_match = self._check_dangerous_commands(script)
        safety_timing["blocklist_ms"] = int((time.monotonic() - blocklist_start) * 1000)
        if dangerous_match is not None:
            return {
                "success": False,
                "error": f"Dangerous command blocked: '{dangerous_match}'",
            }

        if requires_gemma:
            logger.info("Elevated command '%s' detected — forcing Gemma safety review", elevated_match)

        # --- Path Safety Check ---
        path_start = time.monotonic()
        path_safe = self._check_path_safety(script)
        safety_timing["path_check_ms"] = int((time.monotonic() - path_start) * 1000)
        if not path_safe:
            return {
                "success": False,
                "error": f"Path safety check failed: script references paths outside project root ({self._allowed_root})",
            }

        if not skip_gemma:
            if self._local_engine is None or not hasattr(self._local_engine, "review_powershell_command"):
                if requires_gemma:
                    logger.warning("Elevated command '%s' requires Gemma review but no local engine is available", elevated_match)
                    return {
                        "success": False,
                        "output": "",
                        "errors": f"Elevated command '{elevated_match}' requires Gemma safety review, but Ollama is unavailable. Start Ollama to enable execution.",
                        "session_id": session_id,
                        "execution_time_ms": 0,
                        "command": script,
                        "safety": {"risk_level": "blocked", "reason": "Elevated command requires unavailable safety review"},
                    }
            # --- Tier 3: Gemma LLM Safety Review ---
            if self._local_engine is not None and hasattr(self._local_engine, "review_powershell_command"):
                gemma_start = time.monotonic()
                try:
                    safety_result = await self._local_engine.review_powershell_command(script)
                    safety_timing["gemma_review_ms"] = int((time.monotonic() - gemma_start) * 1000)
                    if isinstance(safety_result, dict) and safety_result.get("risk_level") == "blocked":
                        return {
                            "success": False,
                            "error": "Command blocked by safety review",
                            "safety": safety_result,
                        }
                except Exception as exc:
                    safety_timing["gemma_review_ms"] = int((time.monotonic() - gemma_start) * 1000)
                    logger.warning("Safety review unavailable — blocking command execution for safety: %s", exc)
                    return {
                        "success": False,
                        "output": "",
                        "errors": "Command blocked: local safety review is unavailable. Start Ollama to enable command execution.",
                        "session_id": session_id,
                        "execution_time_ms": 0,
                        "command": script,
                        "safety": {"risk_level": "blocked", "reason": "Safety review service unavailable"},
                    }

        safety_timing["total_safety_ms"] = int((time.monotonic() - safety_start) * 1000)
        logger.info("[Safety] Pipeline: KAN=%dms | Blocklist=%dms | Path=%dms | Gemma=%dms | Total=%dms",
                     safety_timing.get("kan_ms", 0), safety_timing.get("blocklist_ms", 0),
                     safety_timing.get("path_check_ms", 0), safety_timing.get("gemma_review_ms", 0),
                     safety_timing["total_safety_ms"])

        start_time = time.monotonic()

        proc = await self._get_or_create_session(session_id)

        marker = f"___LOOM_BOUNDARY_{uuid.uuid4().hex[:12]}___"
        wrapped_script = _EXEC_WRAPPER_TEMPLATE.replace("__LOOM_MARKER__", marker).replace("__LOOM_SCRIPT__", script)
        wrapped_script += "\n"

        try:
            stdout_content, stderr_content = await self._send_and_receive(
                proc, wrapped_script, marker, timeout
            )
        except asyncio.TimeoutError:
            logger.warning("Command timed out after %ds in session '%s' — killing session", timeout, session_id)
            await self.close_session(session_id)
            return {
                "success": False,
                "output": "",
                "errors": f"Command timed out after {timeout}s. Session was reset.",
                "session_id": session_id,
                "execution_time_ms": int((time.monotonic() - start_time) * 1000),
                "command": script,
            }
        except Exception as exc:
            self._sessions.pop(session_id, None)
            logger.warning("Session '%s' communication failed, removing: %s", session_id, exc)
            return {
                "success": False,
                "error": f"Session communication failed: {exc}",
                "session_id": session_id,
                "execution_time_ms": int((time.monotonic() - start_time) * 1000),
                "command": script,
            }

        elapsed_ms = int((time.monotonic() - start_time) * 1000)

        session_meta = self._sessions.get(session_id)
        if session_meta is not None:
            session_meta["command_count"] += 1
            session_meta["last_command"] = datetime.now(timezone.utc)

        success = not bool(stderr_content.strip())
        output_lines = stdout_content.splitlines()
        filtered_lines: list[str] = []
        for line in output_lines:
            if line.startswith("LOOM_EXIT:"):
                parts = line.split(":")
                if len(parts) >= 2:
                    ps_success_str = parts[1]
                    success = ps_success_str == "True" and not bool(stderr_content.strip())
            else:
                filtered_lines.append(line)

        result = {
            "success": success,
            "output": "\n".join(filtered_lines),
            "errors": stderr_content,
            "session_id": session_id,
            "execution_time_ms": elapsed_ms,
            "safety_timing": safety_timing,
            "command": script,
        }

        self._kan.record_outcome(script, result.get("success", False), kan_result.get("risk_level", "caution"))

        await self._log_command(script, result)

        return result

    async def close_session(self, session_id: str = "default") -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False

        proc: asyncio.subprocess.Process = session["process"]

        try:
            if proc.returncode is None:
                proc.stdin.write(b"exit\n")
                await proc.stdin.drain()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.terminate()
                    try:
                        await asyncio.wait_for(proc.wait(), timeout=3)
                    except asyncio.TimeoutError:
                        proc.kill()
        except (ProcessLookupError, OSError) as exc:
            logger.debug("Process cleanup for session '%s': %s", session_id, exc)

        logger.info("Session '%s' closed", session_id)
        return True

    async def close_all_sessions(self) -> int:
        session_ids = list(self._sessions.keys())
        count = 0
        for sid in session_ids:
            if await self.close_session(sid):
                count += 1
        return count

    async def register_custom_tool(self, name: str, script: str) -> None:
        ps_function = f"function {name} {{\n{script}\n}}"
        self._custom_tools[name] = ps_function

        for sid, session in list(self._sessions.items()):
            proc = session["process"]
            if proc.returncode is not None:
                continue
            try:
                inject_marker = f"___LOOM_INJECT_{uuid.uuid4().hex[:12]}___"
                wrapped = f"Write-Host '{inject_marker}'\n{ps_function}\nWrite-Host '{inject_marker}'\n"
                proc.stdin.write(wrapped.encode("utf-8"))
                await proc.stdin.drain()
                await self._read_until_marker(proc, inject_marker, timeout=10)
            except Exception as exc:
                logger.warning("Failed to inject tool '%s' into session '%s': %s", name, sid, exc)

        logger.info("Custom tool registered: %s", name)

    def list_custom_tools(self) -> list[str]:
        return list(self._custom_tools.keys())

    async def get_session_info(self, session_id: str = "default") -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            return {
                "exists": False,
                "session_id": session_id,
            }

        proc: asyncio.subprocess.Process = session["process"]
        return {
            "exists": True,
            "session_id": session_id,
            "pid": proc.pid,
            "alive": proc.returncode is None,
            "created": session["created"].isoformat(),
            "command_count": session["command_count"],
            "last_command": session["last_command"].isoformat() if session["last_command"] else None,
        }

    async def _log_command(self, command: str, result: dict) -> None:
        if self._memory is None:
            return

        try:
            truncated_output = result.get("output", "")[:500]
            await self._memory.add_local_insight(
                file_path="powershell_session",
                analysis=f"PS Command: {command}\nResult: {truncated_output}",
                confidence="high",
                category="command_log",
            )
        except Exception as exc:
            logger.warning("Failed to log command to memory: %s", exc)

    def _check_path_safety(self, script: str) -> bool:
        windows_paths = re.findall(r'[A-Za-z]:\\[^\s\'"`;]+', script)
        unix_paths = re.findall(r'(?<!\w)/(?:usr|etc|var|tmp|home|root|opt|bin|sbin)[^\s\'"`;]*', script)

        for path_str in windows_paths:
            normalized = os.path.normpath(path_str)
            if not normalized.lower().startswith(self._allowed_root.lower()):
                logger.warning("Path outside project root detected: %s", path_str)
                return False

        for path_str in unix_paths:
            normalized = os.path.normpath(path_str)
            if not normalized.startswith(self._allowed_root):
                logger.warning("Path outside project root detected: %s", path_str)
                return False

        return True

    def _check_dangerous_commands(self, script: str) -> str | None:
        script_lower = script.lower()
        for pattern in self._dangerous_commands:
            if pattern.lower() in script_lower:
                logger.warning("Dangerous command pattern detected: %s", pattern)
                return pattern
        return None

    def _check_elevated_review(self, script: str) -> str | None:
        """Check if the script contains commands that require elevated Gemma review."""
        script_lower = script.lower()
        for pattern in self._elevated_review_commands:
            if pattern in script_lower:
                return pattern
        return None
