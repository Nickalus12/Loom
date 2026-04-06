"""Lightweight telemetry for Loom agent and orchestration operations.

Zero external dependencies — stdlib only. Thread-safe via Lock.
All counter increments are O(1). Duration observations append to a list
and statistics are computed lazily on summary request.

Metrics are persisted as JSON snapshots to docs/loom/metrics/.
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    name: str
    value: float
    labels: dict[str, str] = field(default_factory=dict)
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class LoomTelemetry:
    """Lightweight telemetry collector for Loom operations.

    Supports three metric types:
    - Counters: monotonically increasing values (inc)
    - Labeled counters: counters partitioned by string labels (inc with kwargs)
    - Durations: observed float values with computed statistics (observe / timer)
    """

    def __init__(self, state_dir: str = "docs/loom") -> None:
        self._counters: dict[str, float] = defaultdict(float)
        self._labels: dict[str, dict[str, float]] = defaultdict(
            lambda: defaultdict(float)
        )
        self._durations: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()
        self._state_dir = Path(state_dir)
        self._start_time = time.monotonic()

    def inc(self, name: str, value: float = 1.0, **labels: str) -> None:
        with self._lock:
            self._counters[name] += value
            if labels:
                key = json.dumps(labels, sort_keys=True)
                self._labels[name][key] += value

    def observe(self, name: str, value: float, **labels: str) -> None:
        with self._lock:
            self._durations[name].append(value)
            if labels:
                key = json.dumps(labels, sort_keys=True)
                self._labels[name][key] += 1

    def timer(self, name: str, **labels: str) -> "_Timer":
        return _Timer(self, name, labels)

    def get_counter(self, name: str) -> float:
        with self._lock:
            return self._counters.get(name, 0.0)

    def get_summary(self) -> dict[str, Any]:
        with self._lock:
            summary: dict[str, Any] = {
                "uptime_seconds": round(time.monotonic() - self._start_time, 1),
                "counters": dict(self._counters),
                "labeled_counters": {},
                "durations": {},
            }

            for name, label_map in self._labels.items():
                summary["labeled_counters"][name] = {
                    k: v for k, v in label_map.items()
                }

            for name, values in self._durations.items():
                if not values:
                    continue
                sorted_v = sorted(values)
                n = len(sorted_v)
                p95_index = int(n * 0.95) if n >= 20 else n - 1
                summary["durations"][name] = {
                    "count": n,
                    "min": round(sorted_v[0], 3),
                    "max": round(sorted_v[-1], 3),
                    "avg": round(sum(sorted_v) / n, 3),
                    "p95": round(sorted_v[p95_index], 3),
                    "total": round(sum(sorted_v), 3),
                }

            return summary

    def save(self) -> Path:
        metrics_dir = self._state_dir / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        path = metrics_dir / f"telemetry-{ts}.json"

        summary = self.get_summary()
        summary["saved_at"] = datetime.now(timezone.utc).isoformat()

        path.write_text(json.dumps(summary, indent=2, default=str))
        logger.info("Telemetry saved to %s", path)
        return path

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._labels.clear()
            self._durations.clear()
            self._start_time = time.monotonic()


class _Timer:
    def __init__(
        self, telemetry: LoomTelemetry, name: str, labels: dict[str, str]
    ) -> None:
        self._telemetry = telemetry
        self._name = name
        self._labels = labels
        self._start = 0.0

    def __enter__(self) -> "_Timer":
        self._start = time.monotonic()
        return self

    def __exit__(self, *args: Any) -> None:
        elapsed = time.monotonic() - self._start
        self._telemetry.observe(self._name, elapsed, **self._labels)


_telemetry: LoomTelemetry | None = None


def get_telemetry(state_dir: str = "docs/loom") -> LoomTelemetry:
    global _telemetry
    if _telemetry is None:
        _telemetry = LoomTelemetry(state_dir=state_dir)
    return _telemetry
