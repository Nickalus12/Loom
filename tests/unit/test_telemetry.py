"""Unit tests for the LoomTelemetry system.

Tests counter increments, labeled counters, duration observations, timer context
manager, summary structure, save/reset, singleton behavior, and thread safety.
"""

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from loom.telemetry import LoomTelemetry, get_telemetry, _Timer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def telemetry(tmp_path):
    """Fresh LoomTelemetry instance with a temporary state directory."""
    return LoomTelemetry(state_dir=str(tmp_path))


# ---------------------------------------------------------------------------
# Counter tests
# ---------------------------------------------------------------------------


class TestCounters:
    """Verify counter increment behavior."""

    def test_counter_increment(self, telemetry):
        """Counter should increment by 1 with default value."""
        telemetry.inc("requests")
        assert telemetry.get_counter("requests") == 1.0

    def test_counter_increment_by_value(self, telemetry):
        """Counter should increment by the specified value."""
        telemetry.inc("bytes", value=256.0)
        telemetry.inc("bytes", value=128.0)
        assert telemetry.get_counter("bytes") == 384.0

    def test_counter_increment_multiple_times(self, telemetry):
        """Counter should accumulate across multiple increments."""
        for _ in range(10):
            telemetry.inc("calls")
        assert telemetry.get_counter("calls") == 10.0

    def test_counter_get_nonexistent_returns_zero(self, telemetry):
        """Getting a counter that was never set should return 0.0."""
        assert telemetry.get_counter("nonexistent") == 0.0

    def test_counter_different_names_independent(self, telemetry):
        """Counters with different names should be independent."""
        telemetry.inc("alpha", value=5.0)
        telemetry.inc("beta", value=10.0)
        assert telemetry.get_counter("alpha") == 5.0
        assert telemetry.get_counter("beta") == 10.0


# ---------------------------------------------------------------------------
# Labeled counter tests
# ---------------------------------------------------------------------------


class TestLabeledCounters:
    """Verify labeled counter behavior."""

    def test_labeled_counter(self, telemetry):
        """Labeled counter should partition counts by label."""
        telemetry.inc("http_requests", provider="openai")
        telemetry.inc("http_requests", provider="openai")
        telemetry.inc("http_requests", provider="ollama")
        summary = telemetry.get_summary()
        labeled = summary["labeled_counters"]["http_requests"]
        assert labeled[json.dumps({"provider": "openai"}, sort_keys=True)] == 2.0
        assert labeled[json.dumps({"provider": "ollama"}, sort_keys=True)] == 1.0

    def test_labeled_counter_multiple_labels(self, telemetry):
        """Labeled counter should handle multiple label keys."""
        telemetry.inc("model_calls", provider="openai", model="gpt-4")
        telemetry.inc("model_calls", provider="openai", model="gpt-3.5")
        summary = telemetry.get_summary()
        labeled = summary["labeled_counters"]["model_calls"]
        key1 = json.dumps({"model": "gpt-4", "provider": "openai"}, sort_keys=True)
        key2 = json.dumps({"model": "gpt-3.5", "provider": "openai"}, sort_keys=True)
        assert labeled[key1] == 1.0
        assert labeled[key2] == 1.0

    def test_labeled_counter_also_increments_total(self, telemetry):
        """Labeled increment should also contribute to the overall counter."""
        telemetry.inc("api_calls", endpoint="/users")
        telemetry.inc("api_calls", endpoint="/orders")
        assert telemetry.get_counter("api_calls") == 2.0


# ---------------------------------------------------------------------------
# Duration observation tests
# ---------------------------------------------------------------------------


class TestDurations:
    """Verify duration observation and statistics."""

    def test_observe_duration(self, telemetry):
        """Observing a duration should record the value."""
        telemetry.observe("response_time", 0.5)
        telemetry.observe("response_time", 1.5)
        summary = telemetry.get_summary()
        dur = summary["durations"]["response_time"]
        assert dur["count"] == 2
        assert dur["min"] == 0.5
        assert dur["max"] == 1.5

    def test_duration_statistics(self, telemetry):
        """Duration stats should include min, max, avg, p95, total, count."""
        values = [0.1, 0.2, 0.3, 0.4, 0.5]
        for v in values:
            telemetry.observe("latency", v)
        summary = telemetry.get_summary()
        dur = summary["durations"]["latency"]
        assert dur["count"] == 5
        assert dur["min"] == 0.1
        assert dur["max"] == 0.5
        assert abs(dur["avg"] - 0.3) < 0.001
        assert abs(dur["total"] - 1.5) < 0.001

    def test_p95_requires_20_observations(self, telemetry):
        """P95 calculation should use int(n*0.95) index when n >= 20."""
        # With exactly 20 observations, p95_index = int(20 * 0.95) = 19
        # which is the last element (0-indexed)
        values = list(range(1, 21))  # 1 through 20
        for v in values:
            telemetry.observe("big_set", float(v))
        summary = telemetry.get_summary()
        dur = summary["durations"]["big_set"]
        assert dur["count"] == 20
        # p95_index = int(20 * 0.95) = 19, which is index 19 -> value 20
        assert dur["p95"] == 20.0

    def test_p95_with_fewer_than_20_observations(self, telemetry):
        """With < 20 observations, p95 should use the last element (n-1 index)."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        for v in values:
            telemetry.observe("small_set", v)
        summary = telemetry.get_summary()
        dur = summary["durations"]["small_set"]
        # p95_index = n - 1 = 4, which is value 5.0
        assert dur["p95"] == 5.0


# ---------------------------------------------------------------------------
# Timer context manager
# ---------------------------------------------------------------------------


class TestTimer:
    """Verify the timer context manager records elapsed time."""

    def test_timer_context_manager(self, telemetry):
        """Timer should record elapsed time as a duration observation."""
        with telemetry.timer("operation"):
            time.sleep(0.05)  # 50ms minimum
        summary = telemetry.get_summary()
        dur = summary["durations"]["operation"]
        assert dur["count"] == 1
        assert dur["min"] >= 0.04  # Allow slight timing jitter

    def test_timer_with_labels(self, telemetry):
        """Timer should support labels."""
        with telemetry.timer("api_call", provider="openai"):
            time.sleep(0.01)
        summary = telemetry.get_summary()
        assert "api_call" in summary["durations"]
        # Labels should create a labeled counter entry too
        assert "api_call" in summary["labeled_counters"]


# ---------------------------------------------------------------------------
# Summary structure
# ---------------------------------------------------------------------------


class TestSummary:
    """Verify get_summary() returns the expected structure."""

    def test_summary_structure(self, telemetry):
        """Summary should contain counters, durations, labeled_counters, uptime_seconds."""
        summary = telemetry.get_summary()
        assert "counters" in summary
        assert "durations" in summary
        assert "labeled_counters" in summary
        assert "uptime_seconds" in summary

    def test_empty_summary(self, telemetry):
        """Empty telemetry should return an empty summary with correct structure."""
        summary = telemetry.get_summary()
        assert summary["counters"] == {}
        assert summary["durations"] == {}
        assert summary["labeled_counters"] == {}
        assert summary["uptime_seconds"] >= 0

    def test_uptime_increases(self, telemetry):
        """Uptime should increase over time."""
        s1 = telemetry.get_summary()["uptime_seconds"]
        time.sleep(0.05)
        s2 = telemetry.get_summary()["uptime_seconds"]
        assert s2 > s1


# ---------------------------------------------------------------------------
# Save and reset
# ---------------------------------------------------------------------------


class TestSaveAndReset:
    """Verify save/reset operations."""

    def test_save_creates_file(self, telemetry, tmp_path):
        """save() should create a JSON file under the metrics directory."""
        telemetry.inc("test_counter")
        path = telemetry.save()
        assert path.exists()
        assert path.suffix == ".json"
        assert "metrics" in str(path.parent)

    def test_save_json_valid(self, telemetry, tmp_path):
        """Saved file should be valid JSON with expected fields."""
        telemetry.inc("test_counter", value=42.0)
        telemetry.observe("test_duration", 1.23)
        path = telemetry.save()
        data = json.loads(path.read_text())
        assert "counters" in data
        assert "durations" in data
        assert "saved_at" in data
        assert data["counters"]["test_counter"] == 42.0

    def test_reset_clears_all(self, telemetry):
        """reset() should clear all counters, durations, and labels."""
        telemetry.inc("requests", value=100.0)
        telemetry.observe("latency", 0.5)
        telemetry.inc("calls", provider="test")
        telemetry.reset()
        summary = telemetry.get_summary()
        assert summary["counters"] == {}
        assert summary["durations"] == {}
        assert summary["labeled_counters"] == {}


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """Verify the singleton get_telemetry() function."""

    def test_singleton_get_telemetry(self):
        """get_telemetry() should return the same instance on repeated calls."""
        import loom.telemetry as mod
        original = mod._telemetry
        try:
            mod._telemetry = None  # Force fresh creation
            t1 = get_telemetry()
            t2 = get_telemetry()
            assert t1 is t2
        finally:
            mod._telemetry = original  # Restore


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    """Verify thread-safe counter increments."""

    def test_thread_safety_concurrent_increments(self, telemetry):
        """Concurrent increments from multiple threads should produce correct total."""
        num_threads = 10
        increments_per_thread = 100
        barrier = threading.Barrier(num_threads)

        def worker():
            barrier.wait()
            for _ in range(increments_per_thread):
                telemetry.inc("concurrent_counter")

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = num_threads * increments_per_thread
        assert telemetry.get_counter("concurrent_counter") == expected
