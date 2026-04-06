"""Minimal test: Python asyncio <-> PowerShell named pipe round-trip.

Bypasses all Loom machinery. Proves whether loop.create_pipe_connection
can send AND receive data over a Windows named pipe with pwsh.

Usage:
    python -X utf8 scripts/test_pipe_minimal.py
"""
import asyncio
import json
import logging
import struct
import sys
import time

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s.%(msecs)03d [%(levelname)-5s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
    force=True,
)
log = logging.getLogger("pipe_test")

PIPE_NAME = "loom-minimal-test-001"
PIPE_PATH = f"\\\\.\\pipe\\{PIPE_NAME}"

# Simple PS pipe server — no module imports, just echo JSON back
PS_SERVER = rf"""
$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$pipe = [System.IO.Pipes.NamedPipeServerStream]::new(
    '{PIPE_NAME}',
    [System.IO.Pipes.PipeDirection]::InOut,
    1,
    [System.IO.Pipes.PipeTransmissionMode]::Byte,
    [System.IO.Pipes.PipeOptions]::None,
    65536, 65536
)

Write-Host "PIPE_READY:{PIPE_NAME}"
[Console]::Out.Flush()

[Console]::SetOut([System.IO.TextWriter]::Null)
[Console]::SetError([System.IO.TextWriter]::Null)

$pipe.WaitForConnection()

$reader = [System.IO.BinaryReader]::new($pipe, [System.Text.Encoding]::UTF8, $true)
$writer = [System.IO.BinaryWriter]::new($pipe, [System.Text.Encoding]::UTF8, $true)

while ($pipe.IsConnected) {{
    try {{
        $len = $reader.ReadInt32()
        if ($len -le 0 -or $len -gt 1048576) {{ break }}
        $bytes = $reader.ReadBytes($len)
        $msg = [System.Text.Encoding]::UTF8.GetString($bytes) | ConvertFrom-Json
        $resp = @{{ echo = $msg.text; ok = $true }} | ConvertTo-Json -Compress
        $respBytes = [System.Text.Encoding]::UTF8.GetBytes($resp)
        $writer.Write([int]$respBytes.Length)
        $writer.Write($respBytes, 0, $respBytes.Length)
        $writer.Flush()
    }} catch [System.IO.EndOfStreamException] {{ break
    }} catch {{ break }}
}}
$pipe.Dispose()
"""


class _TestProtocol(asyncio.Protocol):
    def __init__(self):
        self._buf = bytearray()
        self._transport = None
        self._queue: asyncio.Queue = asyncio.Queue()
        self.connected = False

    def connection_made(self, transport):
        log.debug("connection_made() called — transport=%r", type(transport).__name__)
        self._transport = transport
        self.connected = True

    def data_received(self, data: bytes):
        log.debug("data_received() called — %d bytes", len(data))
        self._buf.extend(data)
        while len(self._buf) >= 4:
            (length,) = struct.unpack_from("<I", self._buf, 0)
            if len(self._buf) < 4 + length:
                break
            payload = bytes(self._buf[4: 4 + length])
            del self._buf[: 4 + length]
            try:
                self._queue.put_nowait(json.loads(payload))
                log.debug("Queued message: %r", json.loads(payload))
            except json.JSONDecodeError:
                log.warning("JSON decode error for payload: %r", payload)

    def connection_lost(self, exc):
        log.debug("connection_lost() — exc=%r", exc)
        self.connected = False

    def send(self, msg: dict):
        payload = json.dumps(msg).encode("utf-8")
        frame = struct.pack("<I", len(payload)) + payload
        log.debug("send() — writing %d bytes to transport", len(frame))
        self._transport.write(frame)

    async def recv(self, timeout: float = 10.0) -> dict:
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)


async def run_test():
    log.info("Starting PowerShell pipe server...")
    proc = await asyncio.create_subprocess_exec(
        "pwsh", "-NoProfile", "-NonInteractive", "-Command", "-",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    log.info("PS process started (pid=%d)", proc.pid)

    # Send server script
    proc.stdin.write(PS_SERVER.encode("utf-8") + b"\n")
    await proc.stdin.drain()
    log.debug("Server script written to stdin (%d bytes)", len(PS_SERVER))

    # Drain stderr while waiting for PIPE_READY
    ready_marker = f"PIPE_READY:{PIPE_NAME}"

    async def drain_stderr():
        try:
            while True:
                line = await asyncio.wait_for(proc.stderr.readline(), timeout=15)
                if not line:
                    break
                log.debug("[stderr] %r", line.decode(errors="replace").rstrip())
        except (asyncio.TimeoutError, Exception):
            pass

    async def wait_ready():
        while True:
            raw = await proc.stdout.readline()
            if not raw:
                return False
            line = raw.decode("utf-8", errors="replace").strip()
            log.debug("[stdout] %r", line)
            if line == ready_marker:
                return True

    stderr_task = asyncio.create_task(drain_stderr())
    try:
        ready = await asyncio.wait_for(asyncio.shield(asyncio.create_task(wait_ready())), timeout=15)
    except asyncio.TimeoutError:
        log.error("Timed out waiting for PIPE_READY")
        proc.kill()
        return False
    finally:
        stderr_task.cancel()

    if not ready:
        log.error("stdout closed before PIPE_READY")
        proc.kill()
        return False

    log.info("PIPE_READY received! Connecting client...")

    loop = asyncio.get_running_loop()
    proto = _TestProtocol()
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        try:
            await loop.create_pipe_connection(lambda: proto, PIPE_PATH)
            await asyncio.sleep(0)  # yield so connection_made() fires before we use transport
            break
        except (FileNotFoundError, OSError) as e:
            log.debug("connect attempt failed: %s — retrying...", e)
            await asyncio.sleep(0.05)
    else:
        log.error("Failed to connect to pipe within 5s")
        proc.kill()
        return False

    log.info("Pipe connected! connection_made called=%s", proto.connected)

    # Start stdout drain background task
    async def drain_stdout():
        try:
            while True:
                data = await proc.stdout.read(4096)
                if not data:
                    break
                log.debug("[stdout drain] %d bytes", len(data))
        except Exception:
            pass

    asyncio.create_task(drain_stdout())

    # Send a message and wait for echo
    log.info("Sending test message...")
    proto.send({"text": "hello from Python"})
    log.info("Message sent. Waiting for response (10s timeout)...")

    try:
        resp = await proto.recv(timeout=10.0)
        log.info("SUCCESS! Response: %r", resp)
        result = True
    except asyncio.TimeoutError:
        log.error("TIMEOUT — no response received within 10s")
        log.error("data_received was NEVER called — pipe write not reaching PS")
        result = False

    # Cleanup
    if proto._transport:
        proto._transport.close()
    proc.kill()
    await proc.wait()
    return result


async def main():
    log.info("=== Minimal Named Pipe Test ===")
    log.info("Python %s", sys.version)
    log.info("Platform: %s", sys.platform)
    log.info("Event loop: %s", type(asyncio.get_event_loop()).__name__)

    ok = await run_test()
    if ok:
        log.info("RESULT: PASS — named pipe round-trip works")
    else:
        log.error("RESULT: FAIL — named pipe does not work")
        log.error("Possible causes:")
        log.error("  1. create_pipe_connection returns read-only transport")
        log.error("  2. PS server not entering WaitForConnection in time")
        log.error("  3. Asyncio IOCP write not flushing before recv()")
    return ok


if __name__ == "__main__":
    # Windows: ProactorEventLoop is default in Python 3.8+ for asyncio.run()
    result = asyncio.run(main())
    sys.exit(0 if result else 1)
