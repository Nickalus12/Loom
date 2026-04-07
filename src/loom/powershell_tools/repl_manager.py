import asyncio
import hashlib
import json
import logging
import os
import re
import struct
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loom.powershell_tools.kan_engine import PowerShellKANEngine

try:
    from loom.telemetry import get_telemetry as _get_telemetry
except Exception:
    _get_telemetry = None  # type: ignore[assignment]

# Safety verdict cache — avoids repeating Gemma review for identical commands
_SAFETY_CACHE_TTL = 300  # seconds
_SAFETY_CACHE_MAX = 256

# Commands that are provably read-only: skip Gemma review, KAN + blocklist still run
_READONLY_PREFIXES: frozenset[str] = frozenset({
    "get-content",
    "get-childitem",
    "get-item",
    "select-string",
    "read-loomfile",
    "search-loomcode",
    "find-loomfiles",
    "get-loomgitlog",
    "get-loomgitstatus",
    "get-loomgitdiff",
    "get-loomdiskusage",
    "get-loommemoryusage",
    "get-loomgpustatus",
    "rg ",
    "git log",
    "git diff",
    "git status",
    "git show",
    "git branch",
})

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

# Named-pipe server embedded in the PS session.
# Replaces the stdin/stdout marker protocol after session startup.
# Communication: 4-byte LE uint32 length prefix + UTF-8 JSON body (both directions).
_PIPE_SERVER_TEMPLATE = r"""
$ErrorActionPreference = 'Continue'
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location '__LOOM_PROJECT_ROOT__'
try {
    Import-Module '__LOOM_MODULE_PATH__' -Force -ErrorAction Stop
} catch {
    Write-Warning "Loom module failed to load: $($_.Exception.Message)"
}

$__loomPipeName = '__LOOM_PIPE_NAME__'
$__loomPipe = [System.IO.Pipes.NamedPipeServerStream]::new(
    $__loomPipeName,
    [System.IO.Pipes.PipeDirection]::InOut,
    1,
    [System.IO.Pipes.PipeTransmissionMode]::Byte,
    [System.IO.Pipes.PipeOptions]::None,
    65536, 65536
)

# Signal Python that the pipe is ready to accept connections
Write-Host "PIPE_READY:$__loomPipeName"
[Console]::Out.Flush()

# Redirect host streams to null — prevents stdout buffer deadlock
# after Python stops reading stdout (all data flows through the pipe)
[Console]::SetOut([System.IO.TextWriter]::Null)
[Console]::SetError([System.IO.TextWriter]::Null)

$__loomPipe.WaitForConnection()
$__loomReader = [System.IO.BinaryReader]::new($__loomPipe, [System.Text.Encoding]::UTF8, $true)
$__loomWriter = [System.IO.BinaryWriter]::new($__loomPipe, [System.Text.Encoding]::UTF8, $true)

function __LoomExec($__script) {
    $__outLines = [System.Collections.Generic.List[string]]::new()
    $__errLines = [System.Collections.Generic.List[string]]::new()
    $__t = [System.Diagnostics.Stopwatch]::GetTimestamp()
    try {
        $__sb = [scriptblock]::Create($__script)
        $__raw = & $__sb 2>&1
        foreach ($__item in $__raw) {
            if ($__item -is [System.Management.Automation.ErrorRecord]) {
                $__errLines.Add($__item.Exception.Message)
            } else {
                $__outLines.Add($__item.ToString())
            }
        }
    } catch {
        $__errLines.Add($_.Exception.Message)
    }
    $__ms = [int](([System.Diagnostics.Stopwatch]::GetTimestamp() - $__t) * 1000 / [System.Diagnostics.Stopwatch]::Frequency)
    return @{
        output     = [string]::Join("`n", $__outLines).TrimEnd()
        errors     = [string]::Join("`n", $__errLines).TrimEnd()
        success    = ($__errLines.Count -eq 0)
        duration_ms = $__ms
    }
}

while ($__loomPipe.IsConnected) {
    try {
        $__msgLen = $__loomReader.ReadInt32()
        if ($__msgLen -le 0 -or $__msgLen -gt 67108864) { break }  # sanity: 64MB max
        $__msgBytes = $__loomReader.ReadBytes($__msgLen)
        $__msg = [System.Text.Encoding]::UTF8.GetString($__msgBytes) | ConvertFrom-Json

        $__resp = switch ($__msg.type) {
            'exec' {
                $__r = __LoomExec $__msg.script
                @{ id = $__msg.id; type = 'result'
                   output = $__r.output; errors = $__r.errors
                   success = $__r.success; duration_ms = $__r.duration_ms
                } | ConvertTo-Json -Compress -Depth 2
            }
            'batch' {
                $__results = @($__msg.scripts | ForEach-Object { __LoomExec $_ })
                @{ id = $__msg.id; type = 'batch_result'; results = $__results
                } | ConvertTo-Json -Compress -Depth 4
            }
            'exit' { break }
            default {
                @{ id = $__msg.id; type = 'error'
                   error = "Unknown type: $($__msg.type)"
                } | ConvertTo-Json -Compress
            }
        }
        if (-not $__resp) { break }

        $__respBytes = [System.Text.Encoding]::UTF8.GetBytes($__resp)
        $__loomWriter.Write([int]$__respBytes.Length)
        $__loomWriter.Write($__respBytes, 0, $__respBytes.Length)
        $__loomWriter.Flush()
    } catch [System.IO.EndOfStreamException] { break
    } catch { break }
}

try { $__loomPipe.Disconnect() } catch {}
$__loomPipe.Dispose()
"""


# ---------------------------------------------------------------------------
# Named-pipe async protocol (Windows ProactorEventLoop)
# ---------------------------------------------------------------------------

class _PipeProtocol(asyncio.Protocol):
    """Length-prefixed JSON framing over a Windows named pipe."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._transport: asyncio.BaseTransport | None = None
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self.closed = False

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self._transport = transport

    def data_received(self, data: bytes) -> None:
        self._buf.extend(data)
        while len(self._buf) >= 4:
            (length,) = struct.unpack_from("<I", self._buf, 0)
            if len(self._buf) < 4 + length:
                break
            payload = bytes(self._buf[4 : 4 + length])
            del self._buf[: 4 + length]
            try:
                self._queue.put_nowait(json.loads(payload))
            except json.JSONDecodeError:
                pass

    def connection_lost(self, exc: Exception | None) -> None:
        self.closed = True

    def send(self, msg: dict) -> None:
        if self._transport and not self.closed:
            payload = json.dumps(msg).encode("utf-8")
            frame = struct.pack("<I", len(payload)) + payload
            self._transport.write(frame)

    async def recv(self, timeout: float = 120.0) -> dict:
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    def close(self) -> None:
        if self._transport:
            self._transport.close()


class _NamedPipeClient:
    """Async client for the embedded PS named-pipe server."""

    def __init__(self, pipe_name: str) -> None:
        self._pipe_name = pipe_name
        self._proto: _PipeProtocol | None = None

    @property
    def connected(self) -> bool:
        return self._proto is not None and not self._proto.closed

    async def connect(self, timeout: float = 10.0) -> None:
        pipe_path = f"\\\\.\\pipe\\{self._pipe_name}"
        loop = asyncio.get_running_loop()
        deadline = time.monotonic() + timeout
        last_exc: Exception = OSError("pipe not ready")
        while time.monotonic() < deadline:
            try:
                proto = _PipeProtocol()
                await loop.create_pipe_connection(lambda: proto, pipe_path)
                # Yield one tick so connection_made() fires before we use the transport.
                # create_pipe_connection resolves the future but schedules connection_made()
                # as a callback — _transport is None until we yield to the event loop.
                await asyncio.sleep(0)
                self._proto = proto
                return
            except (FileNotFoundError, OSError) as exc:
                last_exc = exc
                await asyncio.sleep(0.05)
        raise TimeoutError(
            f"Cannot connect to pipe {pipe_path} within {timeout}s: {last_exc}"
        )

    async def execute(self, script: str, timeout: float = 120.0) -> dict:
        msg_id = uuid.uuid4().hex[:12]
        assert self._proto is not None
        self._proto.send({"id": msg_id, "type": "exec", "script": script})
        return await self._proto.recv(timeout=timeout)

    async def execute_batch(
        self, scripts: list[str], timeout: float = 120.0
    ) -> list[dict]:
        msg_id = uuid.uuid4().hex[:12]
        assert self._proto is not None
        self._proto.send({"id": msg_id, "type": "batch", "scripts": scripts})
        resp = await self._proto.recv(timeout=timeout)
        return resp.get("results", [])

    def close(self) -> None:
        if self._proto:
            try:
                self._proto.send({"id": "bye", "type": "exit"})
            except Exception:
                pass
            self._proto.close()


class _ResultCache:
    """LRU cache for read-only command results. TTL=30s, max=128 entries."""

    def __init__(self, ttl: float = 30.0, max_size: int = 128) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._data: dict[str, tuple[dict, float]] = {}
        self._order: list[str] = []

    def _key(self, script: str, session_id: str) -> str:
        return hashlib.sha256(f"{session_id}:{script}".encode()).hexdigest()[:32]

    def get(self, script: str, session_id: str) -> dict | None:
        key = self._key(script, session_id)
        entry = self._data.get(key)
        if entry is None:
            return None
        result, expire = entry
        if time.monotonic() > expire:
            self._data.pop(key, None)
            if key in self._order:
                self._order.remove(key)
            return None
        self._order.remove(key)
        self._order.append(key)
        return result

    def put(self, script: str, session_id: str, result: dict) -> None:
        key = self._key(script, session_id)
        if key in self._data and key in self._order:
            self._order.remove(key)
        elif len(self._data) >= self._max_size and self._order:
            lru_key = self._order.pop(0)
            self._data.pop(lru_key, None)
        self._data[key] = (result, time.monotonic() + self._ttl)
        self._order.append(key)

    def invalidate(self) -> None:
        self._data.clear()
        self._order.clear()


class PowerShellSessionPool:
    """Pre-warmed pool of named-pipe PS sessions for fast parallel execution."""

    def __init__(self, pool_size: int = 3) -> None:
        self._pool_size = pool_size
        self._available: asyncio.Queue = asyncio.Queue()
        self._all_sessions: list[str] = []
        self.initialized: bool = False

    async def initialize(self, manager: "PowerShellREPLManager") -> None:
        for i in range(self._pool_size):
            session_id = f"__pool_{i}__"
            await manager._get_or_create_session(session_id)
            await self._available.put(session_id)
            self._all_sessions.append(session_id)
        self.initialized = True
        logger.info("PowerShell session pool initialized: %d sessions", self._pool_size)

    async def checkout(self, timeout: float = 5.0) -> str:
        return await asyncio.wait_for(self._available.get(), timeout=timeout)

    def checkin(self, session_id: str) -> None:
        self._available.put_nowait(session_id)

    async def execute_pooled(
        self, script: str, manager: "PowerShellREPLManager", **kwargs: Any
    ) -> dict:
        session_id = await self.checkout()
        try:
            return await manager.execute(script, session_id=session_id, **kwargs)
        finally:
            self.checkin(session_id)


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
        # Safety verdict cache: sha256(script) -> {"verdict": str, "ts": float}
        self._safety_cache: dict[str, dict] = {}
        # Read-only result cache (30s TTL)
        self._result_cache: _ResultCache = _ResultCache()
        # Session pool (lazily initialized)
        self._pool: PowerShellSessionPool | None = None
        # Allow overriding the safety root to a parent directory (e.g., D:\Projects)
        # so agents can work across sibling projects
        env_root = os.getenv("LOOM_ALLOWED_ROOT", "")
        if env_root:
            self._allowed_root = str(Path(env_root).resolve())
        else:
            self._allowed_root = str(self._project_root.resolve())
        self._pwsh_path: str | None = None

    # ------------------------------------------------------------------ cache

    def _safety_cache_key(self, script: str) -> str:
        return hashlib.sha256(script.encode()).hexdigest()[:48]

    def _get_cached_verdict(self, script: str) -> str | None:
        key = self._safety_cache_key(script)
        entry = self._safety_cache.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry["ts"] > _SAFETY_CACHE_TTL:
            self._safety_cache.pop(key, None)
            return None
        return entry["verdict"]

    def _cache_verdict(self, script: str, verdict: str) -> None:
        if len(self._safety_cache) >= _SAFETY_CACHE_MAX:
            # Evict LRU by popping oldest insertion
            oldest = next(iter(self._safety_cache))
            self._safety_cache.pop(oldest, None)
        self._safety_cache[self._safety_cache_key(script)] = {
            "verdict": verdict,
            "ts": time.monotonic(),
        }

    def _is_readonly_command(self, script: str) -> bool:
        lowered = script.lower().strip()
        return any(lowered.startswith(p) for p in _READONLY_PREFIXES)

    # ----------------------------------------------------------------- telemetry

    def _emit_safety_telemetry(self, safety_timing: dict[str, int], session_created: bool) -> None:
        if _get_telemetry is None:
            return
        try:
            tel = _get_telemetry()
            tel.observe("ps_safety_kan_seconds", safety_timing.get("kan_ms", 0) / 1000)
            if "gemma_review_ms" in safety_timing:
                tel.observe("ps_safety_gemma_seconds", safety_timing["gemma_review_ms"] / 1000)
            tel.observe("ps_safety_total_seconds", safety_timing.get("total_safety_ms", 0) / 1000)
            tel.inc("ps_commands_total")
            tel.inc("ps_sessions_created" if session_created else "ps_sessions_reused")
        except Exception:
            pass

    def _emit_cache_telemetry(self, hit: bool) -> None:
        if _get_telemetry is None:
            return
        try:
            tel = _get_telemetry()
            tel.inc("ps_result_cache_hits_total" if hit else "ps_result_cache_misses_total")
        except Exception:
            pass

    def _emit_output_telemetry(self, output_bytes: int) -> None:
        if _get_telemetry is None:
            return
        try:
            tel = _get_telemetry()
            tel.observe("ps_command_output_bytes", output_bytes)
        except Exception:
            pass

    def _emit_pool_batch_telemetry(self) -> None:
        if _get_telemetry is None:
            return
        try:
            tel = _get_telemetry()
            tel.inc("ps_parallel_batch_total")
            tel.inc("ps_pool_checkouts_total")
        except Exception:
            pass

    async def get_pool(self, pool_size: int = 3) -> "PowerShellSessionPool":
        """Lazily initialize and return the session pool."""
        if self._pool is None:
            self._pool = PowerShellSessionPool(pool_size=pool_size)
            await self._pool.initialize(self)
        return self._pool

    async def _nia_ground_command(self, command: str) -> str | None:
        """Query Nia AI for codebase context relevant to this command (best-effort)."""
        nia_key = os.getenv("NIA_API_KEY", "")
        nia_enabled = os.getenv("NIA_ENABLED", "false").lower() == "true"
        if not nia_key or not nia_enabled:
            return None
        try:
            import aiohttp  # optional dep
            async with aiohttp.ClientSession() as sess:
                async with sess.post(
                    "https://api.nia.ai/v1/ground",
                    headers={"Authorization": f"Bearer {nia_key}", "Content-Type": "application/json"},
                    json={"query": f"PowerShell command safety context: {command[:300]}"},
                    timeout=aiohttp.ClientTimeout(total=3.0),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("context") or data.get("text")
        except Exception:
            pass
        return None

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

    async def _get_or_create_session(
        self, session_id: str = "default"
    ) -> tuple[dict, bool]:
        """Returns (session_dict, was_created)."""
        existing = self._sessions.get(session_id)
        if existing is not None:
            proc = existing["process"]
            if proc.returncode is None:
                return existing, False
            logger.warning(
                "Session '%s' process exited (rc=%s), restarting",
                session_id,
                proc.returncode,
            )
            # Clean up dead pipe client before restarting
            pipe: _NamedPipeClient | None = existing.get("pipe")
            if pipe:
                pipe.close()

        pwsh_path = await self._find_pwsh()

        proc = await asyncio.create_subprocess_exec(
            pwsh_path, "-NoProfile", "-NonInteractive", "-Command", "-",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Try named-pipe session first (fast path)
        pipe_client, drain_task = await self._try_pipe_session(proc, session_id)
        if pipe_client is None:
            # Fall back to legacy stdin/stdout marker protocol
            await self._init_legacy_session(proc, session_id)

        session: dict = {
            "process": proc,
            "pipe": pipe_client,          # _NamedPipeClient | None
            "drain_task": drain_task,     # asyncio.Task | None
            "created": datetime.now(timezone.utc),
            "command_count": 0,
            "last_command": None,
        }
        self._sessions[session_id] = session
        mode = "pipe" if pipe_client else "stdin/stdout"
        logger.info(
            "PowerShell session '%s' created (pid=%d, mode=%s)",
            session_id, proc.pid, mode,
        )
        return session, True

    async def _try_pipe_session(
        self,
        proc: asyncio.subprocess.Process,
        session_id: str,
    ) -> tuple[_NamedPipeClient | None, asyncio.Task | None]:
        """Start the pipe server in the PS process and connect to it.

        Returns (client, drain_task) on success, (None, None) on failure.

        Deadlock prevention: stderr is drained concurrently while waiting for
        the PIPE_READY signal. Without this, PS stderr from module loading can
        fill the pipe buffer and block stdout, causing _wait_ready() to hang.
        """
        pipe_name = f"loom-{session_id}-{uuid.uuid4().hex[:12]}"
        server_script = (
            _PIPE_SERVER_TEMPLATE
            .replace("__LOOM_PROJECT_ROOT__", str(self._project_root).replace("'", "''"))
            .replace("__LOOM_MODULE_PATH__", _MODULE_PATH)
            .replace("__LOOM_PIPE_NAME__", pipe_name)
        )
        try:
            logger.debug("[Pipe] Writing server script to stdin (%d bytes)", len(server_script))
            proc.stdin.write(server_script.encode("utf-8") + b"\n")
            await proc.stdin.drain()

            ready_marker = f"PIPE_READY:{pipe_name}"

            async def _wait_ready() -> bool:
                logger.debug("[Pipe] Waiting for '%s' on stdout…", ready_marker)
                while True:
                    raw = await proc.stdout.readline()
                    if not raw:
                        logger.debug("[Pipe] stdout EOF before PIPE_READY")
                        return False
                    line = raw.decode("utf-8", errors="replace").strip()
                    logger.debug("[Pipe] stdout line: %r", line)
                    if line == ready_marker:
                        return True

            async def _drain_stderr_init() -> None:
                """Drain stderr during startup to prevent buffer-full deadlock."""
                try:
                    while True:
                        raw = await asyncio.wait_for(proc.stderr.readline(), timeout=20)
                        if not raw:
                            break
                        logger.debug("[Pipe] stderr: %r", raw.decode("utf-8", errors="replace").rstrip())
                except asyncio.TimeoutError:
                    pass
                except Exception:
                    pass

            # Race: wait for PIPE_READY while draining stderr concurrently
            ready_task = asyncio.create_task(_wait_ready())
            stderr_drain = asyncio.create_task(_drain_stderr_init())
            try:
                ready = await asyncio.wait_for(asyncio.shield(ready_task), timeout=15)
            except asyncio.TimeoutError:
                ready_task.cancel()
                logger.warning("[Pipe] Timed out waiting for PIPE_READY — falling back to stdin/stdout")
                stderr_drain.cancel()
                return None, None
            finally:
                stderr_drain.cancel()

            if not ready:
                logger.warning("[Pipe] stdout closed before PIPE_READY — falling back")
                return None, None

            logger.debug("[Pipe] PIPE_READY received, connecting client…")
            client = _NamedPipeClient(pipe_name)
            await client.connect(timeout=10)
            logger.info("[Pipe] Session '%s' connected via named pipe (%s)", session_id, pipe_name)

            # Background task: drain stdout to prevent buffer deadlock
            drain_task = asyncio.create_task(
                self._drain_stdout(proc), name=f"drain-{session_id}"
            )
            return client, drain_task

        except Exception as exc:
            logger.warning("[Pipe] Init failed, falling back to stdin/stdout: %s", exc, exc_info=True)
            return None, None

    async def _init_legacy_session(
        self, proc: asyncio.subprocess.Process, session_id: str
    ) -> None:
        """Initialize a stdin/stdout marker-based session (legacy fallback)."""
        init_script = _SESSION_INIT_TEMPLATE.replace(
            "__LOOM_PROJECT_ROOT__", str(self._project_root).replace("'", "''")
        ).replace("__LOOM_MODULE_PATH__", _MODULE_PATH)
        init_marker = f"___LOOM_INIT_{uuid.uuid4().hex[:12]}___"
        wrapped = (
            f"Write-Host '{init_marker}'\n{init_script}\nWrite-Host '{init_marker}'\n"
        )
        proc.stdin.write(wrapped.encode("utf-8"))
        await proc.stdin.drain()
        try:
            await self._read_until_marker(proc, init_marker, timeout=15)
        except asyncio.TimeoutError:
            logger.warning(
                "Session '%s' legacy init timed out, proceeding anyway", session_id
            )

    @staticmethod
    async def _drain_stdout(proc: asyncio.subprocess.Process) -> None:
        """Continuously drain and discard PS stdout after pipe handshake."""
        try:
            while proc.returncode is None:
                chunk = await proc.stdout.read(4096)
                if not chunk:
                    break
        except Exception:
            pass

    async def _read_until_marker(
        self,
        proc: asyncio.subprocess.Process,
        marker: str,
        timeout: int = 120,
    ) -> str:
        lines: list[str] = []
        marker_count = 0
        tail = ""  # partial line carried across chunks

        async def _reader() -> str:
            nonlocal marker_count, tail
            while True:
                chunk = await proc.stdout.read(8192)
                if not chunk:
                    break
                text = tail + chunk.decode("utf-8", errors="replace")
                # Split on newlines but keep a possible partial last line
                parts = text.split("\n")
                tail = parts[-1]  # incomplete final segment — carry forward
                for raw_line in parts[:-1]:
                    line = raw_line.rstrip("\r")
                    if marker in line:
                        marker_count += 1
                        if marker_count >= 2:
                            return "\n".join(lines)
                        continue
                    if marker_count >= 1:
                        lines.append(line)
            # Flush any remaining tail on EOF
            if tail:
                line = tail.rstrip("\r")
                if marker not in line and marker_count >= 1:
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

        # --- Result cache: return cached output for previously-executed read-only commands ---
        is_readonly = self._is_readonly_command(script)
        if is_readonly:
            cached_result = self._result_cache.get(script, session_id)
            if cached_result is not None:
                logger.debug("[ResultCache] Hit for session=%s", session_id)
                self._emit_cache_telemetry(hit=True)
                return cached_result
            self._emit_cache_telemetry(hit=False)

        # --- Safety verdict cache: skip full pipeline for previously-approved commands ---
        cached_verdict = self._get_cached_verdict(script)
        if cached_verdict == "safe":
            logger.debug("[Safety] Cache hit — skipping pipeline")
            safety_timing["kan_ms"] = 0
            safety_timing["blocklist_ms"] = 0
            safety_timing["path_check_ms"] = 0
            safety_timing["total_safety_ms"] = 0
        else:
            cached_verdict = None  # force full pipeline

        # --- Tier 1: KAN Neural Scoring ---
        kan_start = time.monotonic()
        if cached_verdict is None:
            kan_result = await self._kan.score_risk(script)
        else:
            kan_result = {"risk_level": "safe", "risk_score": 0.0, "model": "cache"}
        safety_timing["kan_ms"] = int((time.monotonic() - kan_start) * 1000)

        # Check elevated review BEFORE KAN blocking — elevated commands bypass
        # the KAN hard-block and route to Gemma for intelligent review instead.
        elevated_match = self._check_elevated_review(script) if cached_verdict is None else None
        requires_gemma = elevated_match is not None

        if cached_verdict is None and kan_result.get("risk_level") == "blocked" and not requires_gemma:
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
            cached_verdict == "safe"
            or is_readonly
            or (
                not requires_gemma
                and kan_result.get("risk_level") == "safe"
                and kan_result.get("risk_score", 1.0) < 0.2
                and kan_result.get("model") == "kan"
            )
        )

        # --- Tier 2: Dangerous Command Blocklist ---
        blocklist_start = time.monotonic()
        dangerous_match = self._check_dangerous_commands(script) if cached_verdict is None else None
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
        path_safe = self._check_path_safety(script) if cached_verdict is None else True
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
            # --- Tier 3: Gemma LLM Safety Review (+ Nia grounding in parallel) ---
            if self._local_engine is not None and hasattr(self._local_engine, "review_powershell_command"):
                gemma_start = time.monotonic()
                try:
                    # Run Nia grounding concurrently with Gemma review (best-effort)
                    gemma_task = asyncio.create_task(
                        self._local_engine.review_powershell_command(script)
                    )
                    nia_task = asyncio.create_task(self._nia_ground_command(script))
                    safety_result, nia_context = await asyncio.gather(
                        gemma_task, nia_task, return_exceptions=True
                    )
                    safety_timing["gemma_review_ms"] = int((time.monotonic() - gemma_start) * 1000)
                    if isinstance(safety_result, Exception):
                        raise safety_result
                    if nia_context and not isinstance(nia_context, Exception):
                        logger.debug("[Nia] Grounding context received (%d chars)", len(nia_context))
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
        logger.info(
            "[Safety] Pipeline: KAN=%dms | Blocklist=%dms | Path=%dms | Gemma=%dms | Total=%dms | cache=%s | readonly=%s",
            safety_timing.get("kan_ms", 0), safety_timing.get("blocklist_ms", 0),
            safety_timing.get("path_check_ms", 0), safety_timing.get("gemma_review_ms", 0),
            safety_timing["total_safety_ms"],
            cached_verdict == "safe",
            is_readonly,
        )
        # Cache approved verdict for future identical commands
        if cached_verdict != "safe" and not requires_gemma:
            self._cache_verdict(script, "safe")

        start_time = time.monotonic()

        session, session_created = await self._get_or_create_session(session_id)
        proc: asyncio.subprocess.Process = session["process"]
        pipe: _NamedPipeClient | None = session.get("pipe")
        self._emit_safety_telemetry(safety_timing, session_created)

        try:
            if pipe and pipe.connected:
                resp = await pipe.execute(script, timeout=float(timeout))
                elapsed_ms = int((time.monotonic() - start_time) * 1000)
                result = {
                    "success": resp.get("success", True),
                    "output": resp.get("output", ""),
                    "errors": resp.get("errors", ""),
                    "session_id": session_id,
                    "execution_time_ms": elapsed_ms,
                    "ps_exec_ms": resp.get("duration_ms", 0),
                    "safety_timing": safety_timing,
                    "command": script,
                    "protocol": "pipe",
                }
            else:
                # Legacy stdin/stdout marker protocol
                marker = f"___LOOM_BOUNDARY_{uuid.uuid4().hex[:12]}___"
                wrapped = (
                    _EXEC_WRAPPER_TEMPLATE
                    .replace("__LOOM_MARKER__", marker)
                    .replace("__LOOM_SCRIPT__", script)
                ) + "\n"
                stdout_content, stderr_content = await self._send_and_receive(
                    proc, wrapped, marker, timeout
                )
                elapsed_ms = int((time.monotonic() - start_time) * 1000)

                success = not bool(stderr_content.strip())
                filtered: list[str] = []
                for line in stdout_content.splitlines():
                    if line.startswith("LOOM_EXIT:"):
                        parts = line.split(":")
                        if len(parts) >= 2:
                            success = parts[1] == "True" and not bool(stderr_content.strip())
                    else:
                        filtered.append(line)

                result = {
                    "success": success,
                    "output": "\n".join(filtered),
                    "errors": stderr_content,
                    "session_id": session_id,
                    "execution_time_ms": elapsed_ms,
                    "safety_timing": safety_timing,
                    "command": script,
                    "protocol": "stdin/stdout",
                }

        except asyncio.TimeoutError:
            logger.warning(
                "Command timed out after %ds in session '%s' — killing session",
                timeout, session_id,
            )
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
            logger.warning(
                "Session '%s' communication failed, removing: %s", session_id, exc
            )
            return {
                "success": False,
                "error": f"Session communication failed: {exc}",
                "session_id": session_id,
                "execution_time_ms": int((time.monotonic() - start_time) * 1000),
                "command": script,
            }

        session["command_count"] += 1
        session["last_command"] = datetime.now(timezone.utc)

        self._kan.record_outcome(
            script, result.get("success", False), kan_result.get("risk_level", "caution")
        )

        # Update result cache: store readonly results, invalidate on writes
        if result.get("success"):
            if is_readonly:
                self._result_cache.put(script, session_id, result)
            else:
                self._result_cache.invalidate()

        # Emit output size telemetry
        output_bytes = len((result.get("output") or "").encode("utf-8"))
        self._emit_output_telemetry(output_bytes)

        await self._log_command(script, result)
        return result

    async def close_session(self, session_id: str = "default") -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False

        # Close named pipe (sends exit message + closes transport)
        pipe: _NamedPipeClient | None = session.get("pipe")
        if pipe:
            pipe.close()

        # Cancel stdout drain task
        drain: asyncio.Task | None = session.get("drain_task")
        if drain and not drain.done():
            drain.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(drain), timeout=1)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass

        proc: asyncio.subprocess.Process = session["process"]
        try:
            if proc.returncode is None:
                try:
                    proc.stdin.write(b"exit\n")
                    await proc.stdin.drain()
                except OSError:
                    pass
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

    async def execute_batch(
        self,
        scripts: list[str],
        session_id: str = "default",
        timeout: int = 120,
    ) -> list[dict]:
        """Execute multiple PS scripts in a single round-trip (pipe sessions only).

        Each script goes through the full safety pipeline independently.
        Blocked scripts get an inline error result; approved scripts are sent
        together in one named-pipe message.  Falls back to sequential execution
        for legacy stdin/stdout sessions.
        """
        if not scripts:
            return []

        # --- Parallel fast path: all-readonly batch over pool ---
        all_readonly = all(self._is_readonly_command(s) for s in scripts)
        if all_readonly and self._pool is not None and self._pool.initialized:
            logger.debug("[Batch] All-readonly batch — dispatching %d scripts in parallel", len(scripts))
            self._emit_pool_batch_telemetry()
            tasks = [
                asyncio.create_task(self._pool.execute_pooled(s, manager=self, timeout=timeout))
                for s in scripts
            ]
            raw = await asyncio.gather(*tasks, return_exceptions=True)
            return [
                r if isinstance(r, dict) else {"success": False, "error": str(r)}
                for r in raw
            ]

        # --- Safety check every script ---
        approved_indices: list[int] = []
        results: list[dict | None] = [None] * len(scripts)

        for i, script in enumerate(scripts):
            blocked = await self._safety_check_only(script, session_id)
            if blocked is not None:
                results[i] = blocked
            else:
                approved_indices.append(i)

        if not approved_indices:
            return [r or {} for r in results]

        approved_scripts = [scripts[i] for i in approved_indices]

        session, session_created = await self._get_or_create_session(session_id)
        pipe: _NamedPipeClient | None = session.get("pipe")
        self._emit_safety_telemetry({}, session_created)

        start = time.monotonic()

        if pipe and pipe.connected:
            try:
                batch_results = await pipe.execute_batch(
                    approved_scripts, timeout=float(timeout)
                )
                elapsed_ms = int((time.monotonic() - start) * 1000)
                for local_i, global_i in enumerate(approved_indices):
                    r = batch_results[local_i] if local_i < len(batch_results) else {}
                    results[global_i] = {
                        "success": r.get("success", False),
                        "output": r.get("output", ""),
                        "errors": r.get("errors", ""),
                        "session_id": session_id,
                        "execution_time_ms": r.get("duration_ms", 0),
                        "batch_total_ms": elapsed_ms,
                        "command": scripts[global_i],
                        "protocol": "pipe/batch",
                    }
            except Exception as exc:
                logger.warning("Batch execute failed: %s — falling back to sequential", exc)
                for i, script in zip(approved_indices, approved_scripts):
                    results[i] = await self.execute(script, session_id, timeout)
        else:
            # Legacy fallback: sequential
            for i, script in zip(approved_indices, approved_scripts):
                results[i] = await self.execute(script, session_id, timeout)

        session["command_count"] += len(approved_indices)
        session["last_command"] = datetime.now(timezone.utc)
        return [r or {} for r in results]

    async def _safety_check_only(self, script: str, session_id: str) -> dict | None:
        """Run the safety pipeline only. Returns a blocked-result dict or None (approved)."""
        cached = self._get_cached_verdict(script)
        if cached == "safe":
            return None

        is_readonly = self._is_readonly_command(script)
        kan_result = await self._kan.score_risk(script)
        elevated_match = self._check_elevated_review(script)
        requires_gemma = elevated_match is not None

        if kan_result.get("risk_level") == "blocked" and not requires_gemma:
            return {"success": False, "errors": "Blocked by KAN safety pre-filter", "output": "", "command": script}

        dangerous = self._check_dangerous_commands(script)
        if dangerous:
            return {"success": False, "errors": f"Dangerous command blocked: '{dangerous}'", "output": "", "command": script}

        if not self._check_path_safety(script):
            return {"success": False, "errors": "Path safety check failed", "output": "", "command": script}

        skip_gemma = (
            is_readonly
            or (not requires_gemma and kan_result.get("risk_level") == "safe"
                and kan_result.get("risk_score", 1.0) < 0.2)
        )

        if not skip_gemma and self._local_engine is not None and hasattr(self._local_engine, "review_powershell_command"):
            try:
                safety_result = await self._local_engine.review_powershell_command(script)
                if isinstance(safety_result, dict) and safety_result.get("risk_level") == "blocked":
                    return {"success": False, "errors": "Blocked by safety review", "output": "", "command": script}
            except Exception:
                if requires_gemma:
                    return {"success": False, "errors": "Elevated command blocked: safety review unavailable", "output": "", "command": script}

        if not requires_gemma:
            self._cache_verdict(script, "safe")
        return None  # approved

    async def get_session_info(self, session_id: str = "default") -> dict:
        session = self._sessions.get(session_id)
        if session is None:
            return {"exists": False, "session_id": session_id}

        proc: asyncio.subprocess.Process = session["process"]
        pipe: _NamedPipeClient | None = session.get("pipe")
        return {
            "exists": True,
            "session_id": session_id,
            "pid": proc.pid,
            "alive": proc.returncode is None,
            "protocol": "pipe" if (pipe and pipe.connected) else "stdin/stdout",
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
