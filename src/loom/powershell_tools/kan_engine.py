"""KAN-based intelligence engine for PowerShell command analysis.

Uses a small Kolmogorov-Arnold Network to provide:
- Instant (<1ms) safety risk scoring as a pre-filter before Gemma LLM review
- Command quality/pattern scoring
- Self-improvement from Graphiti command history
"""

import asyncio
import copy
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
    # Exploration / read-only
    "-whatif", "-confirm", "get-help", "get-command", "get-member",
    "get-childitem", "get-content", "get-date", "get-process",
    "get-item", "get-location", "get-service", "test-path",
    "test-connection", "measure-object", "select-string",
    # Output / formatting (read-only transforms)
    "write-host", "write-output", "write-verbose",
    "select-object", "where-object", "sort-object",
    "format-table", "format-list", "format-wide",
    "convertto-json", "convertto-csv", "convertto-xml",
    "out-string", "out-null",
    # Loom-specific safe patterns
    "read-loomfile", "find-loomfiles", "search-loomcode",
    "get-loomgitstatus", "get-loomgitlog", "get-loomgitdiff",
    "get-loomgpustatus", "get-loomdiskusage", "get-loommemoryusage",
})

_SAFE_PIPELINE_TERMINATORS: frozenset[str] = frozenset({
    "select-object", "where-object", "sort-object",
    "format-table", "format-list", "format-wide",
    "measure-object", "convertto-json", "convertto-csv",
    "out-string", "out-null", "out-file",
    "select-string", "group-object", "tee-object",
})

NUM_FEATURES: int = 24

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
    # Extended features (v2)
    "pipeline_depth",
    "quoted_string_count",
    "environment_access",
    "credential_patterns",
    "base64_patterns",
    "compression_patterns",
    "scheduled_task_ops",
    "output_redirect",
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
            layers_hidden=[NUM_FEATURES, 12, 6, 1],
            grid_size=3,
            spline_order=2,
        )
        self._model.eval()

        if self._model_path.exists():
            try:
                state = torch.load(self._model_path, weights_only=True)
                migrated = self._migrate_model(state)
                if migrated is not None:
                    self._model.load_state_dict(migrated)
                    logger.info("KAN model loaded from %s", self._model_path)
                else:
                    logger.info(
                        "KAN model architecture changed (16→24 features) — starting fresh"
                    )
            except Exception as exc:
                logger.warning("Failed to load KAN model weights: %s", exc)

        self._initialized = True

    def _migrate_model(self, state_dict: dict) -> dict | None:
        """Attempt to load saved weights into current architecture.

        If the saved model has the same architecture, returns it unchanged.
        If the input dimensions differ (e.g., old 16-feature model), returns None
        so the caller starts with fresh random weights rather than crashing.
        """
        if not _TORCH_AVAILABLE:
            return None
        try:
            # Probe: temporarily load into a fresh model to check compatibility
            probe = KAN(
                layers_hidden=[NUM_FEATURES, 12, 6, 1],
                grid_size=3,
                spline_order=2,
            )
            probe.load_state_dict(state_dict)
            return state_dict  # architecture matches
        except Exception:
            return None  # shape mismatch — caller will use fresh weights

    def extract_features(self, command: str) -> list[float]:
        lower = command.lower()

        # Smart detection: -WhatIf makes any command a dry run (safe)
        has_whatif = "-whatif" in lower

        # Smart deletion: only flag actual cmdlet-based deletion, not variable names
        has_real_deletion = bool(re.search(r"(?:^|\||\;)\s*(?:remove-item|ri|del|rm)\s", lower))

        # Pipeline safety: if the last command in a pipeline is a safe terminator,
        # the whole pipeline is read-only (e.g., Get-Process | Select-Object Name)
        pipeline_is_safe = False
        if "|" in command:
            last_segment = command.split("|")[-1].strip().lower()
            pipeline_is_safe = any(t in last_segment for t in _SAFE_PIPELINE_TERMINATORS)

        # Count safe indicators (weighted by count, not binary)
        safe_count = sum(1 for s in _SAFE_INDICATORS if s in lower)
        safe_score = min(safe_count / 3.0, 1.0)  # 3+ safe indicators = max safety

        # Extended v2 features
        subexpr_depth = command.count("$(")
        pipeline_depth = min((command.count("|") + subexpr_depth) / 8.0, 1.0)

        quoted_count = len(re.findall(r"'[^']*'|\"[^\"]*\"", command))
        quoted_string_count = min(quoted_count / 10.0, 1.0)

        environment_access = float(bool(
            re.search(r"\$env:|^\[environment\]::|get-item\s+env:", lower)
        ))

        credential_patterns = float(bool(
            re.search(
                r"password|securestring|get-credential|convertto-securestring|pscredential",
                lower,
            )
        )) if not has_whatif else 0.0

        base64_patterns = float(bool(
            re.search(r"\[convert\]::(from|to)base64|base64", lower)
        ))

        compression_patterns = float(bool(
            re.search(r"compress-archive|expand-archive|zipfile|gzipstream", lower)
        )) if not has_whatif else 0.0

        scheduled_task_ops = float(bool(
            re.search(r"register-scheduledtask|new-scheduledtask|set-scheduledtask|schtasks", lower)
        )) if not has_whatif else 0.0

        # Output redirect: > or >> to a file path (not 2>&1 stderr redirect)
        output_redirect = float(bool(
            re.search(r"(?<![=<>!2])\s*>>?\s*['\"\w\$\.]", command)
            or re.search(r"out-file\s", lower)
        )) if not has_whatif else 0.0

        features: list[float] = [
            min(len(command) / 500.0, 1.0),
            min(command.count("|") / 5.0, 1.0),
            min(command.count(";") / 5.0, 1.0),
            float(bool(re.search(r"invoke-expression|iex\s", lower))) if not has_whatif else 0.0,
            float(has_real_deletion) if not has_whatif else 0.0,
            float("-recurse" in lower and "-force" in lower) if not has_whatif else 0.0,
            float(bool(re.search(r"[a-zA-Z]:\\|/usr|/etc|/home|\$env:", command))),
            float(any(c in lower for c in _NETWORK_CMDLETS)) if not has_whatif else 0.0,
            float(bool(re.search(r"registry|hklm:|hkcu:|set-itemproperty", lower))) if not has_whatif else 0.0,
            float(bool(re.search(r"start-process|stop-process|get-process.*stop|stop-service|set-service|new-service|new-netfirewallrule|disable-netadapter", lower))) if not has_whatif else 0.0,
            min(command.count("$") / 10.0, 1.0),
            float('"' in command and "$" in command),
            min(len(re.findall(r"[A-Z][a-z]+-[A-Z][a-z]+", command)) / 5.0, 1.0),
            float(bool(re.search(r"2>&1|2>\s*\$", command))),
            safe_score + (0.3 if pipeline_is_safe else 0.0) + (0.5 if has_whatif else 0.0),
            min((command.count("{") + command.count("(")) / 10.0, 1.0),
            # Extended v2
            pipeline_depth,
            quoted_string_count,
            environment_access,
            credential_patterns,
            base64_patterns,
            compression_patterns,
            scheduled_task_ops,
            output_redirect,
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
                features[3] * 0.4     # invoke-expression: high risk
                + features[4] * 0.35  # deletion commands
                + features[5] * 0.35  # recursive + force
                + features[7] * 0.45  # network operations: exfiltration risk
                + features[8] * 0.4   # registry operations: system tampering
                + features[9] * 0.35  # process operations: execution risk
                + features[15] * 0.1  # nesting complexity
                - features[14] * 0.2  # safe indicators reduce score
                # Extended v2
                + features[19] * 0.5  # credential patterns: very high risk
                + features[20] * 0.4  # base64: obfuscation indicator
                + features[22] * 0.35 # scheduled task: persistence mechanism
                + features[23] * 0.2  # output redirect: potential exfiltration
                + features[18] * 0.15 # environment access: moderate risk
                + features[21] * 0.1  # compression: minor risk signal
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
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.retrain())
            except RuntimeError:
                pass  # no running loop (e.g. called from sync context)

    def _retrain_sync(self, data: list[tuple[list[float], float]]) -> dict[str, Any]:
        """CPU-bound training — runs on a thread-pool executor to avoid blocking the event loop.

        Trains a *deep copy* of the model so inference on the main thread is never
        interrupted by in-place gradient operations. The trained weights are then
        loaded back into the live model under no_grad.
        """
        if not _TORCH_AVAILABLE or not self._initialized:
            return {"success": False, "reason": "PyTorch not available or model not initialized"}
        try:
            # Work on an isolated copy — keeps the live model safe for concurrent inference
            train_model = copy.deepcopy(self._model)
            train_model.train()
            optimizer = optim.Adam(train_model.parameters(), lr=0.01)

            X = torch.tensor([d[0] for d in data], dtype=torch.float32)
            y = torch.tensor([[d[1]] for d in data], dtype=torch.float32)

            losses: list[float] = []
            for _ in range(100):
                optimizer.zero_grad()
                output = train_model(X)
                loss = F.binary_cross_entropy_with_logits(output, y)
                loss.backward()
                optimizer.step()
                losses.append(loss.item())

            train_model.eval()
            # Atomically copy trained weights back into the live model
            with torch.no_grad():
                for live_p, trained_p in zip(self._model.parameters(), train_model.parameters()):
                    live_p.copy_(trained_p)
            torch.save(self._model.state_dict(), self._model_path)
            return {
                "success": True,
                "samples": len(data),
                "final_loss": losses[-1],
                "epochs": 100,
            }
        except Exception as exc:
            logger.error("KAN retrain failed: %s", exc, exc_info=True)
            self._model.eval()
            return {"success": False, "reason": str(exc)}

    async def retrain(self) -> dict[str, Any]:
        if not _TORCH_AVAILABLE or not self._initialized:
            return {"success": False, "reason": "PyTorch not available or model not initialized"}

        if len(self._training_data) < 10:
            return {"success": False, "reason": "insufficient data", "samples": len(self._training_data)}

        # Snapshot training data and reset counters *before* going to thread pool
        # so new commands accumulate uninterrupted while training runs.
        data = list(self._training_data)
        self._training_data.clear()
        self._command_count = 0

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, self._retrain_sync, data)

        if result.get("success"):
            logger.info(
                "KAN model retrained: %d samples, final_loss=%.4f",
                result["samples"], result["final_loss"],
            )
        return result

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
            "num_features": NUM_FEATURES,
            "architecture": f"[{NUM_FEATURES}, 12, 6, 1]",
            "training_buffer_size": len(self._training_data),
            "commands_since_retrain": self._command_count,
            "retrain_threshold": self._retrain_threshold,
            "model_path": str(self._model_path),
            "model_file_exists": self._model_path.exists(),
        }
