"""Real-time execution tracer for Loom agent operations.

Captures structured trace events as the agent runs, enabling:
- Live Rich terminal display of what the agent is doing
- Post-mortem analysis of slow/failed runs
- Hierarchical view of operations (agent -> turn -> tool -> safety)

Zero external dependencies beyond Rich (already in deps).
"""

import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


class EventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    PLANNING = "planning"
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    LLM_CALL = "llm_call"
    LLM_RESPONSE = "llm_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SAFETY_CHECK = "safety_check"
    GIT_BRANCH = "git_branch"
    VALIDATION = "validation"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    CACHE_HIT = "cache_hit"
    ERROR = "error"
    INFO = "info"


@dataclass
class TraceEvent:
    event_type: EventType
    name: str
    timestamp_ms: int  # ms since trace start
    duration_ms: int | None = None  # filled on completion
    data: dict[str, Any] = field(default_factory=dict)
    parent_idx: int | None = None  # index of parent event


class ExecutionTracer:
    """Captures structured trace events during agent execution."""

    def __init__(self, max_events: int = 500) -> None:
        self._events: list[TraceEvent] = []
        self._start_time: float = time.monotonic()
        self._open_spans: list[int] = []  # stack of event indices for open spans
        self._lock = Lock()
        self._max_events = max_events
        self._callbacks: list[Any] = []  # real-time display callbacks

    def on_event(self, callback: Any) -> None:
        """Register a callback for real-time event streaming."""
        self._callbacks.append(callback)

    def _now_ms(self) -> int:
        return int((time.monotonic() - self._start_time) * 1000)

    def emit(self, event_type: EventType, name: str, **data: Any) -> int:
        """Emit a point-in-time event. Returns event index."""
        with self._lock:
            idx = len(self._events)
            parent = self._open_spans[-1] if self._open_spans else None
            event = TraceEvent(
                event_type=event_type,
                name=name,
                timestamp_ms=self._now_ms(),
                data=data,
                parent_idx=parent,
            )
            if len(self._events) < self._max_events:
                self._events.append(event)
            for cb in self._callbacks:
                try:
                    cb(event)
                except Exception:
                    pass
            return idx

    def begin(self, event_type: EventType, name: str, **data: Any) -> int:
        """Begin a span (has duration). Returns event index for end()."""
        idx = self.emit(event_type, name, **data)
        with self._lock:
            self._open_spans.append(idx)
        return idx

    def end(self, idx: int | None = None) -> None:
        """End the current or specified span, recording duration."""
        with self._lock:
            if idx is not None:
                if idx in self._open_spans:
                    self._open_spans.remove(idx)
            elif self._open_spans:
                idx = self._open_spans.pop()
            else:
                return
            if idx is not None and idx < len(self._events):
                self._events[idx].duration_ms = self._now_ms() - self._events[idx].timestamp_ms

    def get_events(self) -> list[dict[str, Any]]:
        """Get all events as serializable dicts."""
        with self._lock:
            return [
                {
                    "type": e.event_type.value,
                    "name": e.name,
                    "ts_ms": e.timestamp_ms,
                    "duration_ms": e.duration_ms,
                    "data": e.data,
                    "parent": e.parent_idx,
                }
                for e in self._events
            ]

    def get_timeline(self) -> list[str]:
        """Get a human-readable timeline of events."""
        lines = []
        for e in self._events:
            depth = 0
            p = e.parent_idx
            while p is not None and p < len(self._events):
                depth += 1
                p = self._events[p].parent_idx
            indent = "  " * depth
            dur = f" ({e.duration_ms}ms)" if e.duration_ms is not None else ""
            detail = ""
            if e.data:
                detail = " " + " ".join(f"{k}={v}" for k, v in list(e.data.items())[:3])
            lines.append(f"{e.timestamp_ms:>6}ms {indent}{e.event_type.value}: {e.name}{dur}{detail}")
        return lines

    def save(self, path: str | Path) -> None:
        """Save trace to JSON file."""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "trace_version": 1,
            "events": self.get_events(),
            "total_events": len(self._events),
            "total_duration_ms": self._now_ms(),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }
        p.write_text(json.dumps(data, indent=2, default=str))

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
            self._open_spans.clear()
            self._start_time = time.monotonic()


def print_trace(tracer: ExecutionTracer) -> None:
    """Print the execution trace as a Rich tree."""
    try:
        from rich.console import Console
        from rich.tree import Tree
        from rich.text import Text
    except ImportError:
        for line in tracer.get_timeline():
            print(line)
        return

    console = Console()
    events = tracer._events

    if not events:
        console.print("[dim]No trace events recorded[/]")
        return

    # Build tree from events
    root = Tree("[bold magenta]Execution Trace[/]")
    nodes: dict[int, Any] = {}

    for i, event in enumerate(events):
        dur = event.duration_ms
        if dur is not None:
            if dur < 100:
                color = "green"
            elif dur < 1000:
                color = "yellow"
            else:
                color = "red"
            dur_text = f" [{color}]{dur}ms[/{color}]"
        else:
            dur_text = ""

        type_colors = {
            EventType.AGENT_START: "bold magenta",
            EventType.AGENT_END: "bold magenta",
            EventType.TURN_START: "bold cyan",
            EventType.TURN_END: "cyan",
            EventType.LLM_CALL: "blue",
            EventType.LLM_RESPONSE: "blue",
            EventType.TOOL_CALL: "yellow",
            EventType.TOOL_RESULT: "yellow",
            EventType.SAFETY_CHECK: "red",
            EventType.CACHE_HIT: "green",
            EventType.ERROR: "bold red",
        }
        color = type_colors.get(event.event_type, "dim")

        detail_parts = []
        for k, v in list(event.data.items())[:3]:
            val = str(v)[:40]
            detail_parts.append(f"[dim]{k}={val}[/dim]")
        detail = " ".join(detail_parts)

        label = f"[{color}]{event.event_type.value}[/{color}] {event.name}{dur_text} {detail}"

        parent_node = nodes.get(event.parent_idx, root) if event.parent_idx is not None else root
        node = parent_node.add(label)
        nodes[i] = node

    console.print(root)
    total_ms = tracer._now_ms()
    console.print(f"\n[dim]Total: {total_ms}ms | {len(events)} events[/]")
