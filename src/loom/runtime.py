"""Runtime capability detection for Loom.

Auto-detects available services and selects the optimal execution strategy.
No more manual mode selection — the system probes Ollama, LiteLLM, PowerShell,
Neo4j, and Nia, then picks the best combination automatically.
"""

import asyncio
import logging
import os
import shutil
from typing import Any

logger = logging.getLogger(__name__)


class RuntimeCapabilities:
    """Detects and caches available runtime services."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._checked = False

    async def detect(self) -> dict[str, Any]:
        """Probe all services and return capability map."""
        if self._checked:
            return self._cache

        caps: dict[str, Any] = {
            "ollama": await self._check_ollama(),
            "litellm": await self._check_litellm(),
            "powershell": self._check_powershell(),
            "neo4j": await self._check_neo4j(),
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

        self._cache = caps
        self._checked = True
        logger.info(
            "[Runtime] Detected: local=%s cloud=%s -> mode=%s",
            caps["local_available"],
            caps["cloud_available"],
            caps["recommended_mode"],
        )
        return caps

    async def _check_ollama(self) -> dict:
        """Probe Ollama for available models."""
        try:
            from openai import AsyncOpenAI

            base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            client = AsyncOpenAI(base_url=base + "/v1", api_key="ollama")
            models = await asyncio.wait_for(client.models.list(), timeout=5.0)
            model_ids = [m.id for m in models.data]
            return {"available": True, "models": model_ids, "url": base}
        except Exception:
            return {"available": False, "models": [], "url": ""}

    async def _check_litellm(self) -> dict:
        """Probe LiteLLM proxy for availability."""
        key = os.getenv("LITELLM_MASTER_KEY", "")
        base = os.getenv("LITELLM_BASE_URL", "http://localhost:4000/v1")
        if not key:
            return {"available": False, "reason": "LITELLM_MASTER_KEY not set"}
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(base_url=base, api_key=key)
            await asyncio.wait_for(client.models.list(), timeout=5.0)
            return {"available": True, "url": base}
        except Exception:
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
        try:
            from neo4j import AsyncGraphDatabase

            driver = AsyncGraphDatabase.driver(uri, auth=("neo4j", password))
            await asyncio.wait_for(driver.verify_connectivity(), timeout=5.0)
            await driver.close()
            return {"available": True, "uri": uri}
        except Exception:
            return {"available": False, "reason": "Neo4j not reachable"}

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

    def invalidate(self) -> None:
        """Clear cached detection results so next call re-probes."""
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
