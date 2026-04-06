"""Unit tests for the Loom runtime capability detection module."""

import json

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from loom.runtime import RuntimeCapabilities, get_runtime


# ---------------------------------------------------------------------------
# RuntimeCapabilities — construction and state
# ---------------------------------------------------------------------------


class TestRuntimeCapabilitiesInit:
    """Verify initial state of RuntimeCapabilities."""

    def test_starts_unchecked(self):
        """Should start with _checked=False and empty cache."""
        rt = RuntimeCapabilities()
        assert rt._checked is False
        assert rt._cache == {}

    def test_invalidate_clears_state(self):
        """invalidate() should reset _checked and clear cache."""
        rt = RuntimeCapabilities()
        rt._checked = True
        rt._cache = {"foo": "bar"}
        rt.invalidate()
        assert rt._checked is False
        assert rt._cache == {}


# ---------------------------------------------------------------------------
# RuntimeCapabilities — detect()
# ---------------------------------------------------------------------------


class TestRuntimeDetect:
    """Verify the detect() method probes services correctly."""

    @pytest.mark.asyncio
    async def test_detect_returns_dict(self):
        """Should return a dict with expected keys."""
        rt = RuntimeCapabilities()
        with patch.object(rt, "_check_ollama", new_callable=AsyncMock, return_value={"available": False, "models": [], "url": ""}), \
             patch.object(rt, "_check_litellm", new_callable=AsyncMock, return_value={"available": False, "reason": "not set"}), \
             patch.object(rt, "_check_powershell", return_value={"available": True, "path": "/usr/bin/pwsh"}), \
             patch.object(rt, "_check_neo4j", new_callable=AsyncMock, return_value={"available": False, "reason": "no pass"}):
            caps = await rt.detect()

        assert isinstance(caps, dict)
        assert "ollama" in caps
        assert "litellm" in caps
        assert "powershell" in caps
        assert "neo4j" in caps
        assert "nia" in caps
        assert "recommended_mode" in caps
        assert "reason" in caps

    @pytest.mark.asyncio
    async def test_detect_caches_result(self):
        """Should only probe once — second call returns cached result."""
        rt = RuntimeCapabilities()
        with patch.object(rt, "_check_ollama", new_callable=AsyncMock, return_value={"available": False, "models": [], "url": ""}) as mock_ollama, \
             patch.object(rt, "_check_litellm", new_callable=AsyncMock, return_value={"available": False}), \
             patch.object(rt, "_check_powershell", return_value={"available": False, "path": ""}), \
             patch.object(rt, "_check_neo4j", new_callable=AsyncMock, return_value={"available": False}):
            caps1 = await rt.detect()
            caps2 = await rt.detect()

        assert caps1 is caps2
        assert mock_ollama.await_count == 1

    @pytest.mark.asyncio
    async def test_detect_hybrid_when_both_available(self):
        """Should recommend 'hybrid' when both Ollama and LiteLLM are available."""
        rt = RuntimeCapabilities()
        with patch.object(rt, "_check_ollama", new_callable=AsyncMock, return_value={"available": True, "models": ["qwen3:4b"], "url": "http://localhost:11434"}), \
             patch.object(rt, "_check_litellm", new_callable=AsyncMock, return_value={"available": True, "url": "http://localhost:4000/v1"}), \
             patch.object(rt, "_check_powershell", return_value={"available": True, "path": "/usr/bin/pwsh"}), \
             patch.object(rt, "_check_neo4j", new_callable=AsyncMock, return_value={"available": False}):
            caps = await rt.detect()

        assert caps["recommended_mode"] == "hybrid"
        assert caps["local_available"] is True
        assert caps["cloud_available"] is True

    @pytest.mark.asyncio
    async def test_detect_local_when_only_ollama(self):
        """Should recommend 'local' when only Ollama is available."""
        rt = RuntimeCapabilities()
        with patch.object(rt, "_check_ollama", new_callable=AsyncMock, return_value={"available": True, "models": ["qwen3:4b"], "url": "http://localhost:11434"}), \
             patch.object(rt, "_check_litellm", new_callable=AsyncMock, return_value={"available": False, "reason": "not set"}), \
             patch.object(rt, "_check_powershell", return_value={"available": True, "path": "/usr/bin/pwsh"}), \
             patch.object(rt, "_check_neo4j", new_callable=AsyncMock, return_value={"available": False}):
            caps = await rt.detect()

        assert caps["recommended_mode"] == "local"
        assert caps["local_available"] is True
        assert caps["cloud_available"] is False

    @pytest.mark.asyncio
    async def test_detect_cloud_when_only_litellm(self):
        """Should recommend 'cloud' when only LiteLLM is available."""
        rt = RuntimeCapabilities()
        with patch.object(rt, "_check_ollama", new_callable=AsyncMock, return_value={"available": False, "models": [], "url": ""}), \
             patch.object(rt, "_check_litellm", new_callable=AsyncMock, return_value={"available": True, "url": "http://localhost:4000/v1"}), \
             patch.object(rt, "_check_powershell", return_value={"available": True, "path": "/usr/bin/pwsh"}), \
             patch.object(rt, "_check_neo4j", new_callable=AsyncMock, return_value={"available": False}):
            caps = await rt.detect()

        assert caps["recommended_mode"] == "cloud"
        assert caps["local_available"] is False
        assert caps["cloud_available"] is True

    @pytest.mark.asyncio
    async def test_detect_none_when_nothing_available(self):
        """Should recommend 'none' when no backends are available."""
        rt = RuntimeCapabilities()
        with patch.object(rt, "_check_ollama", new_callable=AsyncMock, return_value={"available": False, "models": [], "url": ""}), \
             patch.object(rt, "_check_litellm", new_callable=AsyncMock, return_value={"available": False, "reason": "not set"}), \
             patch.object(rt, "_check_powershell", return_value={"available": False, "path": ""}), \
             patch.object(rt, "_check_neo4j", new_callable=AsyncMock, return_value={"available": False}):
            caps = await rt.detect()

        assert caps["recommended_mode"] == "none"

    @pytest.mark.asyncio
    async def test_detect_sets_local_models(self):
        """Should populate local_models from Ollama response."""
        rt = RuntimeCapabilities()
        with patch.object(rt, "_check_ollama", new_callable=AsyncMock, return_value={"available": True, "models": ["qwen3:4b", "gemma4:e2b"], "url": "http://localhost:11434"}), \
             patch.object(rt, "_check_litellm", new_callable=AsyncMock, return_value={"available": False}), \
             patch.object(rt, "_check_powershell", return_value={"available": False, "path": ""}), \
             patch.object(rt, "_check_neo4j", new_callable=AsyncMock, return_value={"available": False}):
            caps = await rt.detect()

        assert caps["local_models"] == ["qwen3:4b", "gemma4:e2b"]

    @pytest.mark.asyncio
    async def test_detect_nia_from_env(self):
        """Should set nia=True when NIA_API_KEY is set."""
        rt = RuntimeCapabilities()
        with patch.object(rt, "_check_ollama", new_callable=AsyncMock, return_value={"available": False, "models": [], "url": ""}), \
             patch.object(rt, "_check_litellm", new_callable=AsyncMock, return_value={"available": False}), \
             patch.object(rt, "_check_powershell", return_value={"available": False, "path": ""}), \
             patch.object(rt, "_check_neo4j", new_callable=AsyncMock, return_value={"available": False}), \
             patch.dict("os.environ", {"NIA_API_KEY": "test-key-123"}):
            caps = await rt.detect()

        assert caps["nia"] is True


# ---------------------------------------------------------------------------
# Model selection
# ---------------------------------------------------------------------------


class TestModelSelection:
    """Verify get_best_tool_model and get_best_analysis_model."""

    def test_best_tool_model_prefers_qwen3_4b(self):
        """Should prefer qwen3:4b when available."""
        rt = RuntimeCapabilities()
        rt._cache = {"local_models": ["gemma4:e2b", "qwen3:4b", "llama3:8b"]}
        assert rt.get_best_tool_model() == "qwen3:4b"

    def test_best_tool_model_falls_back_to_first(self):
        """Should use first available model when no preferred model found."""
        rt = RuntimeCapabilities()
        rt._cache = {"local_models": ["llama3:8b", "mistral:7b"]}
        assert rt.get_best_tool_model() == "llama3:8b"

    def test_best_tool_model_default_when_empty(self):
        """Should return qwen3:4b as default when no models available."""
        rt = RuntimeCapabilities()
        rt._cache = {"local_models": []}
        assert rt.get_best_tool_model() == "qwen3:4b"

    def test_best_analysis_model_prefers_cloud(self):
        """Should prefer cloud model when cloud is available."""
        rt = RuntimeCapabilities()
        rt._cache = {"cloud_available": True, "local_models": ["qwen3:4b"]}
        result = rt.get_best_analysis_model()
        assert result == "heavy/default"

    def test_best_analysis_model_uses_env_override(self):
        """Should respect LOOM_HEAVY_MODEL env var for cloud analysis."""
        rt = RuntimeCapabilities()
        rt._cache = {"cloud_available": True, "local_models": []}
        with patch.dict("os.environ", {"LOOM_HEAVY_MODEL": "gpt-4o"}):
            result = rt.get_best_analysis_model()
        assert result == "gpt-4o"

    def test_best_analysis_model_local_fallback(self):
        """Should pick best local model when cloud not available."""
        rt = RuntimeCapabilities()
        rt._cache = {"cloud_available": False, "local_models": ["qwen3:4b", "deepseek-coder-v2:16b"]}
        assert rt.get_best_analysis_model() == "deepseek-coder-v2:16b"

    def test_best_analysis_model_local_default(self):
        """Should return deepseek-coder-v2:16b as default when no models."""
        rt = RuntimeCapabilities()
        rt._cache = {"cloud_available": False, "local_models": []}
        assert rt.get_best_analysis_model() == "deepseek-coder-v2:16b"


# ---------------------------------------------------------------------------
# Service probes — edge cases
# ---------------------------------------------------------------------------


class TestServiceProbes:
    """Verify individual service probe methods handle failures."""

    @pytest.mark.asyncio
    async def test_check_ollama_returns_unavailable_on_error(self):
        """_check_ollama should return available=False when connection fails."""
        rt = RuntimeCapabilities()
        with patch("openai.AsyncOpenAI", side_effect=Exception("connection refused")):
            result = await rt._check_ollama()
        assert result["available"] is False

    @pytest.mark.asyncio
    async def test_check_litellm_returns_unavailable_without_key(self):
        """_check_litellm should return available=False when LITELLM_MASTER_KEY not set."""
        rt = RuntimeCapabilities()
        with patch.dict("os.environ", {}, clear=True):
            result = await rt._check_litellm()
        assert result["available"] is False
        assert "not set" in result.get("reason", "").lower()

    def test_check_powershell_available(self):
        """_check_powershell should detect pwsh when present."""
        rt = RuntimeCapabilities()
        with patch("loom.runtime.shutil.which", return_value="/usr/bin/pwsh"):
            result = rt._check_powershell()
        assert result["available"] is True
        assert result["path"] == "/usr/bin/pwsh"

    def test_check_powershell_not_available(self):
        """_check_powershell should return available=False when pwsh not found."""
        rt = RuntimeCapabilities()
        with patch("loom.runtime.shutil.which", return_value=None):
            result = rt._check_powershell()
        assert result["available"] is False

    @pytest.mark.asyncio
    async def test_check_neo4j_returns_unavailable_without_password(self):
        """_check_neo4j should return available=False when NEO4J_PASSWORD not set."""
        rt = RuntimeCapabilities()
        with patch.dict("os.environ", {}, clear=True):
            result = await rt._check_neo4j()
        assert result["available"] is False


# ---------------------------------------------------------------------------
# get_runtime() singleton
# ---------------------------------------------------------------------------


class TestGetRuntime:
    """Verify the global get_runtime() singleton function."""

    @pytest.mark.asyncio
    async def test_get_runtime_returns_capabilities(self):
        """Should return a RuntimeCapabilities instance."""
        import loom.runtime as rt_mod

        # Reset global state
        rt_mod._runtime = None

        rt = RuntimeCapabilities()
        rt._checked = True
        rt._cache = {"recommended_mode": "none"}

        with patch("loom.runtime.RuntimeCapabilities", return_value=rt):
            result = await get_runtime()

        assert isinstance(result, RuntimeCapabilities)
        assert result._checked is True

    @pytest.mark.asyncio
    async def test_get_runtime_detects_if_not_checked(self):
        """Should call detect() if instance exists but hasn't been checked."""
        import loom.runtime as rt_mod

        rt = RuntimeCapabilities()
        rt._checked = False
        rt_mod._runtime = rt

        with patch.object(rt, "detect", new_callable=AsyncMock, return_value={}):
            await get_runtime()
            rt.detect.assert_awaited_once()

        # Cleanup
        rt_mod._runtime = None


# ---------------------------------------------------------------------------
# Craft tool — auto mode integration
# ---------------------------------------------------------------------------


class TestCraftAutoMode:
    """Verify craft tool auto-mode dispatches correctly."""

    @pytest.mark.asyncio
    async def test_craft_auto_uses_runtime_detection(self):
        """Should call get_runtime() when mode is auto."""
        from loom.server import craft

        mock_runtime = MagicMock()
        mock_runtime._cache = {"recommended_mode": "cloud", "reason": "test"}

        mock_engine = AsyncMock()
        mock_orch = AsyncMock()
        from loom.orchestrator import SwarmPlan, Phase
        mock_orch.execute_swarm = AsyncMock(return_value=SwarmPlan(
            task="test",
            phases=[Phase(id=1, name="A", agent="architect", objective="x", status="completed")],
        ))

        with patch("loom.server.get_runtime", new_callable=AsyncMock, return_value=mock_runtime), \
             patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            result = await craft(task="test", mode="auto")

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_craft_auto_returns_error_when_none(self):
        """Should return error JSON when recommended_mode is 'none'."""
        from loom.server import craft

        mock_runtime = MagicMock()
        mock_runtime._cache = {
            "recommended_mode": "none",
            "reason": "No models available",
        }

        with patch("loom.server.get_runtime", new_callable=AsyncMock, return_value=mock_runtime):
            result = await craft(task="test", mode="auto")

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert "no inference" in parsed["error"].lower()

    @pytest.mark.asyncio
    async def test_craft_auto_selects_hybrid(self):
        """Should use hybrid mode when runtime recommends it."""
        from loom.server import craft

        mock_runtime = MagicMock()
        mock_runtime._cache = {"recommended_mode": "hybrid", "reason": "both available"}

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value={
            "success": True, "response": "Done.", "tool_calls_made": 1,
            "turns_used": 1, "files_changed": [], "git_branch": None,
            "git_diff": None, "validation_results": [], "tool_log": [],
            "memory_stored": False, "truncated": False,
        })

        with patch("loom.server.get_runtime", new_callable=AsyncMock, return_value=mock_runtime), \
             patch("loom.server._get_engines", return_value=(AsyncMock(), AsyncMock())), \
             patch("loom.server._get_local_engine", return_value=AsyncMock()), \
             patch("loom.server._get_ps_manager", return_value=AsyncMock()), \
             patch("loom.local_agent.LocalAgent", return_value=mock_agent):
            result = await craft(task="test", mode="auto")

        parsed = json.loads(result)
        assert parsed["success"] is True

    @pytest.mark.asyncio
    async def test_craft_explicit_cloud_skips_detection(self):
        """Should NOT call get_runtime() when mode is explicitly 'cloud'."""
        from loom.server import craft

        mock_engine = AsyncMock()
        mock_orch = AsyncMock()
        from loom.orchestrator import SwarmPlan, Phase
        mock_orch.execute_swarm = AsyncMock(return_value=SwarmPlan(
            task="test",
            phases=[Phase(id=1, name="A", agent="architect", objective="x", status="completed")],
        ))

        with patch("loom.server.get_runtime", new_callable=AsyncMock) as mock_get_rt, \
             patch("loom.server._get_engines", return_value=(mock_engine, mock_orch)):
            await craft(task="test", mode="cloud")

        mock_get_rt.assert_not_awaited()


# ---------------------------------------------------------------------------
# local_agent_task — auto-detection
# ---------------------------------------------------------------------------


class TestLocalAgentTaskAutoDetect:
    """Verify local_agent_task auto-detects hybrid and models."""

    @pytest.mark.asyncio
    async def test_local_agent_task_auto_detects_hybrid(self):
        """Should enable hybrid when runtime detects both local and cloud."""
        from loom.server import local_agent_task

        mock_runtime = MagicMock()
        mock_runtime._cache = {
            "cloud_available": True,
            "local_available": True,
            "local_models": ["qwen3:4b"],
            "recommended_mode": "hybrid",
        }
        mock_runtime.get_best_tool_model.return_value = "qwen3:4b"
        mock_runtime.get_best_analysis_model.return_value = "heavy/default"

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value={
            "success": True, "response": "Done.", "tool_calls_made": 1,
            "turns_used": 1, "files_changed": [], "git_branch": None,
            "git_diff": None, "validation_results": [], "tool_log": [],
            "memory_stored": False, "truncated": False,
        })

        with patch("loom.server.get_runtime", new_callable=AsyncMock, return_value=mock_runtime), \
             patch("loom.server._get_engines", return_value=(AsyncMock(), AsyncMock())), \
             patch("loom.server._get_local_engine", return_value=AsyncMock()), \
             patch("loom.server._get_ps_manager", return_value=AsyncMock()), \
             patch("loom.local_agent.LocalAgent", return_value=mock_agent) as mock_la_cls:
            result = await local_agent_task(task="Review code")

        # Verify LocalAgent was called with hybrid=True
        mock_la_cls.assert_called_once()
        call_kwargs = mock_la_cls.call_args[1]
        assert call_kwargs["hybrid"] is True

    @pytest.mark.asyncio
    async def test_local_agent_task_explicit_hybrid_false_still_autodetects(self):
        """When hybrid=False (default), auto-detection should still run."""
        from loom.server import local_agent_task

        mock_runtime = MagicMock()
        mock_runtime._cache = {
            "cloud_available": False,
            "local_available": True,
            "local_models": ["qwen3:4b"],
            "recommended_mode": "local",
        }
        mock_runtime.get_best_tool_model.return_value = "qwen3:4b"
        mock_runtime.get_best_analysis_model.return_value = "qwen3:4b"

        mock_agent = AsyncMock()
        mock_agent.run = AsyncMock(return_value={
            "success": True, "response": "OK", "tool_calls_made": 0,
            "turns_used": 1, "files_changed": [], "git_branch": None,
            "git_diff": None, "validation_results": [], "tool_log": [],
            "memory_stored": False, "truncated": False,
        })

        with patch("loom.server.get_runtime", new_callable=AsyncMock, return_value=mock_runtime), \
             patch("loom.server._get_engines", return_value=(AsyncMock(), AsyncMock())), \
             patch("loom.server._get_local_engine", return_value=AsyncMock()), \
             patch("loom.server._get_ps_manager", return_value=AsyncMock()), \
             patch("loom.local_agent.LocalAgent", return_value=mock_agent) as mock_la_cls:
            result = await local_agent_task(task="Test")

        # hybrid should remain False since cloud is not available
        mock_la_cls.assert_called_once()
        call_kwargs = mock_la_cls.call_args[1]
        assert call_kwargs["hybrid"] is False


# ---------------------------------------------------------------------------
# get_runtime_capabilities MCP tool
# ---------------------------------------------------------------------------


class TestGetRuntimeCapabilitiesTool:
    """Verify the get_runtime_capabilities MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_json_with_capabilities(self):
        """Should return JSON string with capability fields."""
        from loom.server import get_runtime_capabilities

        mock_runtime = MagicMock()
        mock_runtime._cache = {
            "ollama": {"available": True, "models": ["qwen3:4b"]},
            "litellm": {"available": False},
            "powershell": {"available": True},
            "neo4j": {"available": False},
            "nia": False,
            "local_models": ["qwen3:4b"],
            "cloud_available": False,
            "local_available": True,
            "recommended_mode": "local",
            "reason": "Only Ollama available",
        }
        mock_runtime.get_best_tool_model.return_value = "qwen3:4b"
        mock_runtime.get_best_analysis_model.return_value = "deepseek-coder-v2:16b"

        with patch("loom.server.get_runtime", new_callable=AsyncMock, return_value=mock_runtime):
            result = await get_runtime_capabilities()

        parsed = json.loads(result)
        assert parsed["recommended_mode"] == "local"
        assert parsed["best_tool_model"] == "qwen3:4b"
        assert parsed["best_analysis_model"] == "deepseek-coder-v2:16b"
        assert parsed["local_available"] is True

    @pytest.mark.asyncio
    async def test_returns_error_on_failure(self):
        """Should return error JSON when detection fails."""
        from loom.server import get_runtime_capabilities

        with patch("loom.server.get_runtime", new_callable=AsyncMock, side_effect=RuntimeError("fail")):
            result = await get_runtime_capabilities()

        parsed = json.loads(result)
        assert parsed["success"] is False
        assert parsed["tool"] == "get_runtime_capabilities"


# ---------------------------------------------------------------------------
# CLI runtime subcommand
# ---------------------------------------------------------------------------


class TestCLIRuntimeSubcommand:
    """Verify the CLI runtime subcommand registration."""

    def test_runtime_subcommand_parses(self):
        """Should parse 'runtime' subcommand."""
        import argparse

        parser = argparse.ArgumentParser(prog="loom")
        subparsers = parser.add_subparsers(dest="command")
        subparsers.add_parser("runtime")
        args = parser.parse_args(["runtime"])
        assert args.command == "runtime"

    def test_craft_mode_accepts_auto(self):
        """Should accept 'auto' as a valid mode for craft."""
        import argparse

        parser = argparse.ArgumentParser(prog="loom")
        subparsers = parser.add_subparsers(dest="command")
        p_craft = subparsers.add_parser("craft")
        p_craft.add_argument("task", nargs="*")
        p_craft.add_argument("--mode", choices=["auto", "cloud", "local", "hybrid"], default="auto")
        args = parser.parse_args(["craft", "--mode", "auto", "test"])
        assert args.mode == "auto"

    def test_craft_mode_accepts_hybrid(self):
        """Should accept 'hybrid' as a valid mode for craft."""
        import argparse

        parser = argparse.ArgumentParser(prog="loom")
        subparsers = parser.add_subparsers(dest="command")
        p_craft = subparsers.add_parser("craft")
        p_craft.add_argument("task", nargs="*")
        p_craft.add_argument("--mode", choices=["auto", "cloud", "local", "hybrid"], default="auto")
        args = parser.parse_args(["craft", "--mode", "hybrid", "test"])
        assert args.mode == "hybrid"

    def test_craft_mode_default_is_auto(self):
        """craft --mode should default to 'auto'."""
        import argparse

        parser = argparse.ArgumentParser(prog="loom")
        subparsers = parser.add_subparsers(dest="command")
        p_craft = subparsers.add_parser("craft")
        p_craft.add_argument("task", nargs="*")
        p_craft.add_argument("--mode", choices=["auto", "cloud", "local", "hybrid"], default="auto")
        args = parser.parse_args(["craft", "test"])
        assert args.mode == "auto"
