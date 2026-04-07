"""Runtime capability detection for Loom.

Auto-detects available services and selects the optimal execution strategy.
No more manual mode selection — the system probes Ollama, LiteLLM, PowerShell,
Neo4j, and Nia, then picks the best combination automatically.
"""

import asyncio
import logging
import os
import shutil
import time
from collections import defaultdict
from typing import Any

logger = logging.getLogger(__name__)

_CIRCUIT_BREAKER_THRESHOLD = 3
_CIRCUIT_BREAKER_RESET_SECONDS = 60


class _BackendCircuitBreaker:
    """Trips after N consecutive failures; auto-resets after a cooldown window."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._failures = 0
        self._open_since: float | None = None

    @property
    def is_open(self) -> bool:
        if self._open_since is None:
            return False
        if time.monotonic() - self._open_since > _CIRCUIT_BREAKER_RESET_SECONDS:
            logger.info("[CircuitBreaker] %s cooldown expired — resetting", self.name)
            self._failures = 0
            self._open_since = None
            return False
        return True

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= _CIRCUIT_BREAKER_THRESHOLD and self._open_since is None:
            logger.warning(
                "[CircuitBreaker] %s tripped after %d consecutive failures — backing off %ds",
                self.name, self._failures, _CIRCUIT_BREAKER_RESET_SECONDS,
            )
            self._open_since = time.monotonic()

    def record_success(self) -> None:
        if self._failures > 0:
            logger.info("[CircuitBreaker] %s recovered", self.name)
        self._failures = 0
        self._open_since = None


class RuntimeCapabilities:
    """Detects and caches available runtime services."""

    _CACHE_TTL: float = 60.0  # re-probe after 60 seconds

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._checked = False
        self._checked_at: float = 0.0
        self._circuit_breakers: dict[str, _BackendCircuitBreaker] = {
            "ollama": _BackendCircuitBreaker("ollama"),
            "litellm": _BackendCircuitBreaker("litellm"),
        }
        # Per-model latency samples (seconds) for p95 routing
        self._model_latency: dict[str, list[float]] = defaultdict(list)

    async def detect(self) -> dict[str, Any]:
        """Probe all services and return capability map. Re-probes after TTL."""
        import time as _time
        if self._checked and (_time.monotonic() - self._checked_at) < self._CACHE_TTL:
            return self._cache

        # Probe all services IN PARALLEL — saves 10-15s vs sequential
        ollama_r, litellm_r, neo4j_r = await asyncio.gather(
            self._check_ollama(),
            self._check_litellm(),
            self._check_neo4j(),
            return_exceptions=True,
        )
        caps: dict[str, Any] = {
            "ollama": ollama_r if not isinstance(ollama_r, BaseException) else {"available": False},
            "litellm": litellm_r if not isinstance(litellm_r, BaseException) else {"available": False},
            "powershell": self._check_powershell(),
            "neo4j": neo4j_r if not isinstance(neo4j_r, BaseException) else {"available": False},
            "nia": bool(os.getenv("NIA_API_KEY")),
        }

        # Determine available models
        caps["local_models"] = (
            caps["ollama"].get("models", [])
            if isinstance(caps["ollama"], dict)
            else []
        )
        caps["cloud_available"] = (
            isinstance(caps["litellm"], dict) and caps["litellm"].get("available", False)
        )
        caps["local_available"] = (
            isinstance(caps["ollama"], dict) and caps["ollama"].get("available", False)
        )

        # Select optimal mode
        if caps["local_available"] and caps["cloud_available"]:
            caps["recommended_mode"] = "hybrid"
            caps["reason"] = (
                "Both local and cloud available — hybrid gives best quality with local speed"
            )
        elif caps["local_available"]:
            caps["recommended_mode"] = "local"
            caps["reason"] = "Only Ollama available — using local models"
        elif caps["cloud_available"]:
            caps["recommended_mode"] = "cloud"
            caps["reason"] = "Only cloud available — using LiteLLM proxy"
        else:
            caps["recommended_mode"] = "none"
            caps["reason"] = "No models available — start Ollama or configure LiteLLM"

        import time as _time
        self._cache = caps
        self._checked = True
        self._checked_at = _time.monotonic()
        logger.info(
            "[Runtime] Detected: local=%s cloud=%s -> mode=%s",
            caps["local_available"],
            caps["cloud_available"],
            caps["recommended_mode"],
        )
        return caps

    async def _check_ollama(self) -> dict:
        """Probe Ollama for available models. Circuit-breaker aware."""
        cb = self._circuit_breakers["ollama"]
        if cb.is_open:
            logger.debug("[Runtime] Ollama circuit open — skipping probe")
            return {"available": False, "models": [], "url": "", "circuit_open": True}
        try:
            from openai import AsyncOpenAI

            base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            client = AsyncOpenAI(base_url=base + "/v1", api_key="ollama")
            models = await asyncio.wait_for(client.models.list(), timeout=5.0)
            model_ids = [m.id for m in models.data]
            cb.record_success()
            return {"available": True, "models": model_ids, "url": base}
        except Exception:
            cb.record_failure()
            return {"available": False, "models": [], "url": ""}

    async def _check_litellm(self) -> dict:
        """Probe LiteLLM proxy for availability. Circuit-breaker aware."""
        key = os.getenv("LITELLM_MASTER_KEY", "")
        base = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1")
        if not key:
            return {"available": False, "reason": "LITELLM_MASTER_KEY not set"}
        cb = self._circuit_breakers["litellm"]
        if cb.is_open:
            logger.debug("[Runtime] LiteLLM circuit open — skipping probe")
            return {"available": False, "reason": "circuit open", "circuit_open": True}
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(base_url=base, api_key=key)
            await asyncio.wait_for(client.models.list(), timeout=5.0)
            cb.record_success()
            return {"available": True, "url": base}
        except Exception:
            cb.record_failure()
            return {"available": False, "reason": "LiteLLM proxy not reachable"}

    def _check_powershell(self) -> dict:
        """Check if PowerShell 7+ is installed."""
        pwsh = shutil.which("pwsh") or shutil.which("pwsh-preview")
        return {"available": bool(pwsh), "path": pwsh or ""}

    async def _check_neo4j(self) -> dict:
        """Probe Neo4j for connectivity."""
        uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        password = os.getenv("NEO4J_PASSWORD", "")
        if not password:
            return {"available": False, "reason": "NEO4J_PASSWORD not set"}
        driver = None
        try:
            from neo4j import AsyncGraphDatabase

            driver = AsyncGraphDatabase.driver(uri, auth=("neo4j", password))
            await asyncio.wait_for(driver.verify_connectivity(), timeout=5.0)
            return {"available": True, "uri": uri}
        except Exception:
            return {"available": False, "reason": "Neo4j not reachable"}
        finally:
            if driver is not None:
                try:
                    await driver.close()
                except Exception:
                    pass

    def get_best_tool_model(self) -> str:
        """Pick the best available tool-calling model."""
        models = self._cache.get("local_models", [])
        # Preference order for tool calling
        for preferred in ["qwen3:4b", "qwen3:1.7b", "gemma4:e2b"]:
            if preferred in models:
                return preferred
        return models[0] if models else "qwen3:4b"

    def get_best_analysis_model(self) -> str:
        """Pick the best analysis model (cloud if hybrid, local otherwise)."""
        if self._cache.get("cloud_available"):
            return os.getenv("LOOM_HEAVY_MODEL", "heavy/default")
        models = self._cache.get("local_models", [])
        for preferred in ["deepseek-coder-v2:16b", "gemma4:e2b", "qwen3:4b"]:
            if preferred in models:
                return preferred
        return models[0] if models else "deepseek-coder-v2:16b"

    def record_model_call(self, model: str, latency_seconds: float, success: bool) -> None:
        """Record a model call for latency-aware routing. Call after each LLM inference."""
        if success:
            samples = self._model_latency[model]
            samples.append(latency_seconds)
            if len(samples) > 100:  # rolling window
                self._model_latency[model] = samples[-100:]
            # Feed success back to the relevant circuit breaker
            backend = "ollama" if "ollama" in model or "/" not in model else "litellm"
            self._circuit_breakers.get(backend, _BackendCircuitBreaker("unknown")).record_success()
        else:
            backend = "ollama" if "ollama" in model or "/" not in model else "litellm"
            cb = self._circuit_breakers.get(backend)
            if cb:
                cb.record_failure()

    def get_fastest_available_model(self, tier: str = "heavy") -> str:
        """Return the model with the lowest p95 latency for the given tier.

        Falls back to ``get_best_analysis_model()`` if no latency data exists.
        """
        tier_models = [m for m in self._model_latency if tier in m or "/" in m]
        if not tier_models:
            return self.get_best_analysis_model()

        def _p95(model: str) -> float:
            samples = sorted(self._model_latency[model])
            n = len(samples)
            if n == 0:
                return float("inf")
            idx = max(0, int(n * 0.95) - 1)
            return samples[idx]

        return min(tier_models, key=_p95)

    def invalidate(self) -> None:
        """Clear cached detection results so next call re-probes all services."""
        self._checked = False
        self._cache.clear()


# Global singleton
_runtime: RuntimeCapabilities | None = None


async def get_runtime() -> RuntimeCapabilities:
    """Get or create the global RuntimeCapabilities singleton."""
    global _runtime
    if _runtime is None:
        _runtime = RuntimeCapabilities()
    if not _runtime._checked:
        await _runtime.detect()
    return _runtime
