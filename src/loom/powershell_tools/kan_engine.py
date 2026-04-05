"""KAN-based intelligence engine for PowerShell command analysis.

Uses a small Kolmogorov-Arnold Network to provide:
- Instant (<1ms) safety risk scoring as a pre-filter before Gemma LLM review
- Command quality/pattern scoring
- Self-improvement from Graphiti command history
"""

import asyncio
import logging
import math
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DANGEROUS_CMDLETS: frozenset[str] = frozenset({
    "remove-item", "format-volume", "stop-computer", "restart-computer",
    "clear-recyclebin", "invoke-expression", "start-process", "invoke-webrequest",
    "invoke-restmethod", "new-psdrive", "set-executionpolicy", "uninstall-module",
    "stop-service", "set-itemproperty",
})

_NETWORK_CMDLETS: frozenset[str] = frozenset({
    "invoke-webrequest", "invoke-restmethod", "test-netconnection",
    "new-psdrive", "send-mailmessage",
})

_SAFE_INDICATORS: frozenset[str] = frozenset({
    "-whatif", "-confirm", "get-help", "get-command", "get-member",
    "get-childitem", "get-content", "get-date", "get-process",
    "write-host", "write-output", "write-verbose",
})

NUM_FEATURES: int = 16

_FEATURE_NAMES: tuple[str, ...] = (
    "command_length",
    "pipe_count",
    "semicolon_count",
    "has_invoke_expression",
    "has_deletion",
    "recursive_force",
    "has_absolute_paths",
    "network_operations",
    "registry_operations",
    "process_operations",
    "variable_expansion",
    "string_interpolation",
    "cmdlet_count",
    "error_redirection",
    "safe_indicators",
    "nesting_complexity",
)

try:
    import torch
    import torch.nn.functional as F
    import torch.optim as optim

    from loom.powershell_tools.kan import KAN

    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False
    logger.info("PyTorch not available - KAN engine will use heuristic fallback")


class PowerShellKANEngine:
    """KAN-based intelligence layer for PowerShell command risk scoring.

    Provides instant pre-filter scoring before the Gemma LLM safety review.
    Degrades gracefully to a weighted heuristic when PyTorch is not installed.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        memory_engine: Any = None,
    ) -> None:
        self._memory = memory_engine
        self._model_path = (
            Path(model_path) if model_path else Path(__file__).parent / "kan_model.pt"
        )
        self._model: Any = None
        self._training_data: list[tuple[list[float], float]] = []
        self._command_count: int = 0
        self._retrain_threshold: int = 50
        self._initialized: bool = False
        self._initialize()

    def _initialize(self) -> None:
        if not _TORCH_AVAILABLE:
            self._initialized = False
            return

        self._model = KAN(
            layers_hidden=[NUM_FEATURES, 8, 4, 1],
            grid_size=3,
            spline_order=2,
        )
        self._model.eval()

        if self._model_path.exists():
            try:
                self._model.load_state_dict(
                    torch.load(self._model_path, weights_only=True)
                )
                logger.info("KAN model loaded from %s", self._model_path)
            except Exception as exc:
                logger.warning("Failed to load KAN model weights: %s", exc)

        self._initialized = True

    def extract_features(self, command: str) -> list[float]:
        lower = command.lower()

        features: list[float] = [
            min(len(command) / 500.0, 1.0),
            min(command.count("|") / 5.0, 1.0),
            min(command.count(";") / 5.0, 1.0),
            float(bool(re.search(r"invoke-expression|iex\s", lower))),
            float(bool(re.search(r"remove-item|ri\s|del\s|rm\s", lower))),
            float("-recurse" in lower and "-force" in lower),
            float(bool(re.search(r"[a-zA-Z]:\\|/usr|/etc|/home|\$env:", command))),
            min(sum(1 for c in _NETWORK_CMDLETS if c in lower) / 3.0, 1.0),
            float(bool(re.search(r"registry|hklm:|hkcu:|set-itemproperty", lower))),
            float(bool(re.search(r"start-process|stop-process|get-process.*stop", lower))),
            min(command.count("$") / 10.0, 1.0),
            float('"' in command and "$" in command),
            min(len(re.findall(r"[A-Z][a-z]+-[A-Z][a-z]+", command)) / 5.0, 1.0),
            float(bool(re.search(r"2>&1|2>\s*\$", command))),
            float(any(s in lower for s in _SAFE_INDICATORS)),
            min((command.count("{") + command.count("(")) / 10.0, 1.0),
        ]

        return features

    async def score_risk(self, command: str) -> dict[str, Any]:
        features = self.extract_features(command)

        if self._initialized and _TORCH_AVAILABLE:
            with torch.no_grad():
                features_tensor = torch.tensor([features], dtype=torch.float32)
                risk_raw = self._model(features_tensor).item()
                risk_score = 1.0 / (1.0 + math.exp(-risk_raw))
        else:
            risk_score = (
                features[3] * 0.3
                + features[4] * 0.25
                + features[5] * 0.3
                + features[7] * 0.15
                + features[8] * 0.2
                + features[9] * 0.15
                + features[15] * 0.1
                - features[14] * 0.2
            )
            risk_score = max(0.0, min(1.0, risk_score))

        if risk_score < 0.3:
            level = "safe"
        elif risk_score < 0.7:
            level = "caution"
        else:
            level = "blocked"

        return {
            "risk_score": round(risk_score, 4),
            "risk_level": level,
            "features": dict(
                zip(_FEATURE_NAMES, [round(f, 3) for f in features])
            ),
            "model": "kan" if self._initialized else "heuristic",
            "command_preview": command[:100],
        }

    def record_outcome(self, command: str, success: bool, risk_level: str) -> None:
        features = self.extract_features(command)
        target = 0.0 if success and risk_level != "blocked" else 1.0
        self._training_data.append((features, target))
        self._command_count += 1

        if self._command_count >= self._retrain_threshold:
            asyncio.get_event_loop().create_task(self.retrain())

    async def retrain(self) -> dict[str, Any]:
        if not _TORCH_AVAILABLE or not self._initialized:
            return {"success": False, "reason": "PyTorch not available or model not initialized"}

        if len(self._training_data) < 10:
            return {"success": False, "reason": "insufficient data", "samples": len(self._training_data)}

        try:
            self._model.train()
            optimizer = optim.Adam(self._model.parameters(), lr=0.01)

            X = torch.tensor([d[0] for d in self._training_data], dtype=torch.float32)
            y = torch.tensor([[d[1]] for d in self._training_data], dtype=torch.float32)

            losses: list[float] = []
            for _ in range(100):
                optimizer.zero_grad()
                output = self._model(X)
                loss = F.binary_cross_entropy_with_logits(output, y)
                loss.backward()
                optimizer.step()
                losses.append(loss.item())

            self._model.eval()
            torch.save(self._model.state_dict(), self._model_path)

            sample_count = len(self._training_data)
            self._training_data.clear()
            self._command_count = 0

            logger.info(
                "KAN model retrained: %d samples, final_loss=%.4f",
                sample_count,
                losses[-1],
            )

            return {
                "success": True,
                "samples": sample_count,
                "final_loss": losses[-1],
                "epochs": 100,
            }
        except Exception as exc:
            logger.error("KAN retrain failed: %s", exc, exc_info=True)
            self._model.eval()
            return {"success": False, "reason": str(exc)}

    async def learn_from_history(self, limit: int = 200) -> dict[str, Any]:
        if self._memory is None:
            return {"success": False, "reason": "no memory engine configured"}

        try:
            results = await self._memory.memory.search(
                "PowerShell command execution history",
                num_results=limit,
            )

            parsed_count = 0
            for episode in results:
                content = getattr(episode, "fact", "") or getattr(episode, "content", "")
                if not content:
                    continue

                match = re.search(r"PS Command:\s*(.+?)(?:\n|$)", content)
                if not match:
                    continue

                cmd = match.group(1).strip()
                success = "error" not in content.lower()
                features = self.extract_features(cmd)
                target = 0.0 if success else 1.0
                self._training_data.append((features, target))
                parsed_count += 1

            if parsed_count == 0:
                return {"success": False, "reason": "no command history found", "episodes_searched": len(results)}

            retrain_result = await self.retrain()
            retrain_result["episodes_parsed"] = parsed_count
            return retrain_result

        except Exception as exc:
            logger.error("learn_from_history failed: %s", exc, exc_info=True)
            return {"success": False, "reason": str(exc)}

    def get_status(self) -> dict[str, Any]:
        return {
            "initialized": self._initialized,
            "model": "kan" if self._initialized else "heuristic",
            "torch_available": _TORCH_AVAILABLE,
            "training_buffer_size": len(self._training_data),
            "commands_since_retrain": self._command_count,
            "retrain_threshold": self._retrain_threshold,
            "model_path": str(self._model_path),
            "model_file_exists": self._model_path.exists(),
        }
