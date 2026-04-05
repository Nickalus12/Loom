import asyncio
import logging
import os
from datetime import datetime, timezone

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

ANALYSIS_SYSTEM_PROMPT = (
    "You are a code analysis assistant. Analyze the following code for bugs, "
    "anti-patterns, security issues, and coding conventions. Be specific and "
    "actionable. Rate your confidence in each finding."
)

BRAINSTORM_SYSTEM_PROMPT = (
    "You are a creative programming assistant. Generate diverse, practical "
    "approaches and ideas for the given task. Think laterally. Include "
    "unconventional solutions."
)

REVIEW_SYSTEM_PROMPT = (
    "You are a code reviewer. Identify bugs, anti-patterns, missing error "
    "handling, security issues, and style inconsistencies. Be specific with "
    "line references. Rate confidence for each finding."
)

DEBUG_SYSTEM_PROMPT = (
    "You are a debugging assistant. Analyze the error and context to identify "
    "probable root causes. Suggest specific fixes. Order suggestions by likelihood."
)

POWERSHELL_SAFETY_SYSTEM_PROMPT = (
    "You are a PowerShell security reviewer. Evaluate the following PowerShell command "
    "for safety risks. Classify as: SAFE (no risk), CAUTION (mild risk, proceed with "
    "logging), or BLOCKED (dangerous — do not execute). Consider: file deletion, system "
    "modification, network exfiltration, privilege escalation, registry changes, and "
    "service manipulation. Respond in this exact format:\n"
    "RISK_LEVEL: SAFE|CAUTION|BLOCKED\n"
    "REASON: <one-line explanation>\n"
    "DETAILS: <specific concerns if any>"
)

_CODE_EXTENSIONS = frozenset({".py", ".js", ".ts", ".tsx", ".jsx"})
_MAX_FILE_SIZE = 50 * 1024

_LOW_INDICATORS = ("might", "possibly", "i'm not sure", "maybe", "could be", "uncertain")
_MEDIUM_INDICATORS = ("likely", "appears to", "seems", "probably", "suggests")


class LocalInferenceEngine:
    """Manages local Ollama inference for background analysis and on-demand tasks."""

    def __init__(
        self,
        memory_engine,
        ollama_base_url: str | None = None,
        analysis_model: str | None = None,
        creative_model: str | None = None,
    ):
        self._base_url = ollama_base_url or os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        self._analysis_model = analysis_model or os.getenv(
            "LOOM_LOCAL_ANALYSIS_MODEL", "gemma4:e2b"
        )
        self._creative_model = creative_model or os.getenv(
            "LOOM_LOCAL_CREATIVE_MODEL", "gemma4:e2b"
        )
        self._memory = memory_engine
        self._client = AsyncOpenAI(
            base_url=self._base_url + "/v1",
            api_key="ollama",
        )
        self._interval = int(os.getenv("LOOM_BACKGROUND_INTERVAL", "30"))
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._last_seen_commit: str | None = None
        self._last_analysis_time: datetime | None = None
        self._lock = asyncio.Lock()
        self._backoff_seconds = self._interval

    async def start_background_worker(self) -> None:
        """Starts the background file analysis loop."""
        self._running = True
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("Background analysis worker started (interval=%ds)", self._interval)

    async def stop_background_worker(self) -> None:
        """Stops the background file analysis loop gracefully."""
        self._running = False
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None
        logger.info("Background analysis worker stopped")

    async def _worker_loop(self) -> None:
        """Main loop for background file analysis with exponential backoff on failure."""
        while self._running:
            try:
                changed_files = await self._poll_changes()
                for file_path in changed_files:
                    try:
                        content = await asyncio.to_thread(self._read_file, file_path)
                    except (OSError, ValueError):
                        logger.debug("Skipping unreadable file: %s", file_path)
                        continue

                    async with self._lock:
                        analysis = await self._chat(
                            self._analysis_model,
                            ANALYSIS_SYSTEM_PROMPT,
                            f"File: {file_path}\n\n{content}",
                        )

                    confidence = self._tag_confidence(analysis)
                    category = self._classify_analysis(analysis)

                    try:
                        await self._memory.add_local_insight(
                            file_path=file_path,
                            analysis=analysis,
                            confidence=confidence,
                            category=category,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to persist insight for %s", file_path, exc_info=True
                        )

                self._last_analysis_time = datetime.now(timezone.utc)
                self._backoff_seconds = self._interval
                await asyncio.sleep(self._interval)

            except (ConnectionError, OSError) as exc:
                logger.warning(
                    "Ollama connection error, backing off %ds: %s",
                    self._backoff_seconds,
                    exc,
                )
                await asyncio.sleep(self._backoff_seconds)
                self._backoff_seconds = min(self._backoff_seconds * 2, 300)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("Unexpected error in background worker", exc_info=True)
                await asyncio.sleep(self._backoff_seconds)
                self._backoff_seconds = min(self._backoff_seconds * 2, 300)

    async def _poll_changes(self) -> list[str]:
        """Detects changed code files since the last seen commit via git."""
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "HEAD",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("git rev-parse failed (rc=%d)", proc.returncode)
            return []
        current_head = stdout.decode().strip()

        if self._last_seen_commit is None:
            self._last_seen_commit = current_head
            return []

        if current_head == self._last_seen_commit:
            return []

        proc = await asyncio.create_subprocess_exec(
            "git", "diff", "--name-only", self._last_seen_commit, current_head,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            logger.warning("git diff failed (rc=%d)", proc.returncode)
            return []
        self._last_seen_commit = current_head

        all_files = stdout.decode().strip().splitlines()
        return [
            f for f in all_files
            if os.path.splitext(f)[1] in _CODE_EXTENSIONS
        ]

    @staticmethod
    def _read_file(file_path: str) -> str:
        """Reads a file synchronously, raising ValueError if it exceeds the size limit."""
        size = os.path.getsize(file_path)
        if size > _MAX_FILE_SIZE:
            raise ValueError(f"File too large: {size} bytes")
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    async def brainstorm(self, task: str, context: str = "") -> str:
        """Generates creative approaches for a given task using the local model."""
        user_message = task
        if context:
            user_message = f"{task}\n\nContext:\n{context}"

        try:
            return await self._chat(
                self._creative_model, BRAINSTORM_SYSTEM_PROMPT, user_message
            )
        except Exception as exc:
            logger.error("brainstorm failed: %s", exc)
            return f"Local brainstorm unavailable: {exc}"

    async def review(self, code: str, file_path: str) -> dict:
        """Reviews code for bugs, anti-patterns, and style issues."""
        user_message = f"File: {file_path}\n\n{code}"

        try:
            response = await self._chat(
                self._analysis_model, REVIEW_SYSTEM_PROMPT, user_message
            )
            confidence = self._tag_confidence(response)
            return {
                "findings": response,
                "confidence": confidence,
                "file_path": file_path,
            }
        except Exception as exc:
            logger.error("review failed: %s", exc)
            return {
                "findings": f"Local review unavailable: {exc}",
                "confidence": "low",
                "file_path": file_path,
            }

    async def debug_assist(self, error: str, context: str = "") -> str:
        """Analyzes an error and suggests probable root causes and fixes."""
        user_message = error
        if context:
            user_message = f"{error}\n\nContext:\n{context}"

        try:
            return await self._chat(
                self._analysis_model, DEBUG_SYSTEM_PROMPT, user_message
            )
        except Exception as exc:
            logger.error("debug_assist failed: %s", exc)
            return f"Local debug assist unavailable: {exc}"

    async def review_powershell_command(self, command: str) -> dict:
        """Reviews a PowerShell command for safety risks using the local Gemma analyst.

        Returns dict with keys: risk_level (safe/caution/blocked), reason, details, raw_response.
        """
        try:
            response = await self._chat(
                self._analysis_model,
                POWERSHELL_SAFETY_SYSTEM_PROMPT,
                f"PowerShell command to review:\n```powershell\n{command}\n```",
            )
            return self._parse_safety_response(response)
        except Exception as exc:
            logger.error("PowerShell safety review failed: %s", exc)
            return {
                "risk_level": "caution",
                "reason": f"Safety review unavailable: {exc}",
                "details": "Proceeding with caution due to review failure",
                "raw_response": "",
            }

    def _parse_safety_response(self, response: str) -> dict:
        """Parses the structured safety review response from the local model."""
        result = {
            "risk_level": "caution",
            "reason": "Unable to parse safety response",
            "details": "",
            "raw_response": response,
        }

        lower = response.lower()

        if "risk_level: blocked" in lower or "risk_level:blocked" in lower:
            result["risk_level"] = "blocked"
        elif "risk_level: safe" in lower or "risk_level:safe" in lower:
            result["risk_level"] = "safe"
        elif "risk_level: caution" in lower or "risk_level:caution" in lower:
            result["risk_level"] = "caution"

        for line in response.splitlines():
            stripped = line.strip()
            if stripped.upper().startswith("REASON:"):
                result["reason"] = stripped[7:].strip()
            elif stripped.upper().startswith("DETAILS:"):
                result["details"] = stripped[8:].strip()

        return result

    def _tag_confidence(self, response: str) -> str:
        """Assigns a confidence level based on keyword heuristics in the response."""
        lower = response.lower()
        low_count = sum(1 for indicator in _LOW_INDICATORS if indicator in lower)
        if low_count > 2:
            return "low"
        medium_count = sum(1 for indicator in _MEDIUM_INDICATORS if indicator in lower)
        if medium_count > 2:
            return "medium"
        return "high"

    def _classify_analysis(self, analysis: str) -> str:
        """Classifies an analysis response into a category by keyword detection."""
        lower = analysis.lower()
        if any(kw in lower for kw in ("bug", "error", "fix")):
            return "bug"
        if any(kw in lower for kw in ("security", "vulnerability", "injection")):
            return "security"
        if any(kw in lower for kw in ("pattern", "convention", "style")):
            return "pattern"
        return "observation"

    async def get_status(self) -> dict:
        """Returns the current status of the local inference engine."""
        available = False
        models_loaded: list[str] = []

        try:
            response = await self._client.models.list()
            available = True
            models_loaded = [m.id for m in response.data]
        except Exception:
            logger.debug("Ollama status check failed", exc_info=True)

        return {
            "available": available,
            "models_loaded": models_loaded,
            "worker_active": self._running,
            "last_analysis": self._last_analysis_time,
            "ollama_url": self._base_url,
        }

    async def _chat(self, model: str, system_prompt: str, user_message: str) -> str:
        """Shared helper for OpenAI-compatible chat completion calls to Ollama."""
        response = await asyncio.wait_for(
            self._client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            ),
            timeout=30.0,
        )
        content = response.choices[0].message.content
        return content or ""
