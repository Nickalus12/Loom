"""PowerShell MCP Benchmark — comprehensive round-trip timing across all command types.

Usage:
    python -X utf8 scripts/bench_ps.py [--verbose] [--quick]

Sections:
  1. Cold start          — PS startup + named-pipe init
  2. Read commands        — echo, read_file, search, find, git ops
  3. Write commands       — file write (small/large/json/append/multi)
  4. Write pipeline       — write then read-back verification
  5. Large output         — big file read, deep dir listing, large git log
  6. Safety pipeline      — safe / readonly / cached / blocked variants
  7. Batch execution      — N commands as 1 round-trip
  8. Sequential baseline  — same N commands one-at-a-time
  9. Concurrent sessions  — parallel asyncio.gather across 3 sessions
 10. Throughput           — rapid-fire commands/sec burst

Outputs:
- Live progress to stdout with timestamps
- JSON results to docs/loom/metrics/bench_ps_<timestamp>.json
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, stdev

# ── Logging ──────────────────────────────────────────────────────────────────

def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(asctime)s.%(msecs)03d [%(levelname)-5s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("bench").setLevel(logging.INFO)

log = logging.getLogger("bench")

# ── Helpers ───────────────────────────────────────────────────────────────────

def sep(title: str = "") -> None:
    if title:
        pad = max(0, 60 - len(title) - 4)
        print(f"\n== {title} {'='*pad}")
    else:
        print("=" * 64)

def row(label: str, times_ms: list[int], extra: str = "") -> None:
    if not times_ms:
        print(f"  {label:<40}  NO DATA")
        return
    avg = int(mean(times_ms))
    med = int(median(times_ms))
    mn  = min(times_ms)
    mx  = max(times_ms)
    sd  = int(stdev(times_ms)) if len(times_ms) > 1 else 0
    tag = f"  avg={avg:>4}ms  med={med:>4}ms  min={mn:>4}ms  max={mx:>4}ms  sd={sd:>3}ms"
    print(f"  {label:<40}{tag}  {extra}")

async def timed(coro) -> tuple[int, object]:
    t = time.monotonic()
    result = await coro
    return int((time.monotonic() - t) * 1000), result

def _safety_stats(results_list: list[dict]) -> tuple[int, int, int]:
    """Return (safety_avg_ms, kan_avg_ms, cache_hits) from a list of execute results."""
    safety = [r.get("safety_timing", {}).get("total_safety_ms", 0) for r in results_list]
    kan    = [r.get("safety_timing", {}).get("kan_ms", 0) for r in results_list]
    hits   = sum(1 for r in results_list if r.get("safety_timing", {}).get("total_safety_ms", -1) == 0)
    return int(mean(safety)) if safety else 0, int(mean(kan)) if kan else 0, hits

# ── Command sets ──────────────────────────────────────────────────────────────

BATCH_COMMANDS = [
    "Read-LoomFile 'src/loom/local_agent.py'",
    "Read-LoomFile 'src/loom/runtime.py'",
    "Search-LoomCode 'def ' -Path 'src' -Include '*.py'",
    "Find-LoomFiles '*.py' -Path 'src'",
    "Get-LoomGitStatus",
]

READ_COMMANDS = {
    "echo":          "Write-Host benchmark-ping",
    "read_small":    "Read-LoomFile 'src/loom/runtime.py'",
    "read_medium":   "Read-LoomFile 'src/loom/powershell_tools/repl_manager.py'",
    "search_code":   "Search-LoomCode 'def ' -Path 'src' -Include '*.py'",
    "find_files":    "Find-LoomFiles '*.py' -Path 'src'",
    "git_status":    "Get-LoomGitStatus",
    "git_log_5":     "Get-LoomGitLog -Limit 5",
    "git_log_20":    "Get-LoomGitLog -Limit 20",
}

WRITE_COMMANDS = {
    "write_small":   "Write-LoomFile 'docs/loom/bench_scratch/small.txt' 'hello benchmark'",
    "write_4kb":     "Write-LoomFile 'docs/loom/bench_scratch/large.txt' ([string]::new('x', 4096))",
    "write_64kb":    "Write-LoomFile 'docs/loom/bench_scratch/xlarge.txt' ([string]::new('x', 65536))",
    "write_json":    (
        "Write-LoomFile 'docs/loom/bench_scratch/data.json' "
        "(@{ts=(Get-Date -Format o);run=1;v='bench'} | ConvertTo-Json -Compress)"
    ),
    "write_append":  (
        "$f='docs/loom/bench_scratch/append.log'; "
        "Add-Content -Path $f -Value \"$(Get-Date -Format o) bench\" -Encoding UTF8; "
        "@{success=$true;path=$f} | ConvertTo-Json -Compress"
    ),
    "multi_write":   (
        "1..3 | ForEach-Object { "
        "  Write-LoomFile \"docs/loom/bench_scratch/multi_$_.txt\" \"content $_\" "
        "} | Out-Null; Write-Host 'done'"
    ),
}

LARGE_OUTPUT_COMMANDS = {
    "read_large_file": "Read-LoomFile 'src/loom/powershell_tools/repl_manager.py'",
    "dir_src":         "Get-ChildItem 'src' -Recurse -File | Select-Object FullName,Length | ConvertTo-Json -Compress",
    "git_log_50":      "Get-LoomGitLog -Limit 50",
    "search_broad":    "Search-LoomCode '' -Path '.' -Include '*.py'",
}

# Commands that should be BLOCKED by the safety pipeline
SAFETY_BLOCKED_COMMANDS = {
    "rm_rf":           "Remove-Item -Recurse -Force 'C:/Windows'",
    "format_disk":     "Format-Volume -DriveLetter C -Force",
}

WARMUP_REPEATS = 1
BENCH_REPEATS  = 5
THROUGHPUT_BURST = 20   # commands in the throughput burst test


# ── Core timing helper ────────────────────────────────────────────────────────

async def _bench_cmd(
    mgr, name: str, cmd: str, session: str, n: int, warmup: int = 1
) -> dict:
    """Run a command n times (after warmup), collect timing + safety stats."""
    for _ in range(warmup):
        await mgr.execute(cmd, session_id=session)

    times: list[int] = []
    ps_times: list[int] = []
    raw_results: list[dict] = []

    for run in range(n):
        ms, r = await timed(mgr.execute(cmd, session_id=session))
        times.append(ms)
        raw_results.append(r)
        if r.get("ps_exec_ms") is not None:
            ps_times.append(r["ps_exec_ms"])
        log.debug(
            "  %s run %d: %dms  ps=%s  success=%s  err=%r",
            name, run+1, ms, r.get("ps_exec_ms"), r.get("success"), r.get("errors", "")[:60],
        )

    safety_avg, kan_avg, cache_hits = _safety_stats(raw_results)
    return {
        "times_ms": times,
        "avg_ms": int(mean(times)),
        "med_ms": int(median(times)),
        "min_ms": min(times),
        "max_ms": max(times),
        "ps_exec_avg_ms": int(mean(ps_times)) if ps_times else None,
        "safety_avg_ms": safety_avg,
        "kan_avg_ms": kan_avg,
        "cache_hits": cache_hits,
        "n": n,
    }


# ── Benchmark ─────────────────────────────────────────────────────────────────

async def run_benchmark(project_root: Path, quick: bool = False) -> dict:
    from loom.powershell_tools.repl_manager import PowerShellREPLManager

    N = 3 if quick else BENCH_REPEATS
    mgr = PowerShellREPLManager(project_root=project_root)
    results: dict = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "project_root": str(project_root),
        "protocol": "unknown",
        "quick_mode": quick,
        "cold_start_ms": None,
        "read": {},
        "write": {},
        "write_pipeline": {},
        "large_output": {},
        "safety": {},
        "batch": {},
        "sequential_baseline": {},
        "concurrent": {},
        "throughput": {},
        "batch_speedup": None,
    }

    # ── 1. Cold start ────────────────────────────────────────────────────────
    sep("1 · Session cold start")
    cold_ms, r = await timed(mgr.execute("Write-Host coldstart", session_id="bench"))
    proto = r.get("protocol", "unknown")
    results["cold_start_ms"] = cold_ms
    results["protocol"] = proto
    st = r.get("safety_timing", {})
    log.info(
        "Cold start: %dms  protocol=%s  kan=%sms  success=%s",
        cold_ms, proto, st.get("kan_ms", "?"), r.get("success"),
    )
    print(f"  Cold start: {cold_ms}ms  protocol={proto}")
    if proto == "stdin/stdout":
        log.warning("  !! Named pipe FALLBACK active — pipe init failed")
    else:
        print("  Named pipe session active")

    # Ensure scratch dir
    await mgr.execute(
        "New-Item -ItemType Directory -Force -Path 'docs/loom/bench_scratch' | Out-Null",
        session_id="bench",
    )

    # ── 2. Read commands ─────────────────────────────────────────────────────
    sep("2 · Read commands (%d runs, safety=readonly path)" % N)
    for name, cmd in READ_COMMANDS.items():
        data = await _bench_cmd(mgr, name, cmd, "bench", N)
        results["read"][name] = data
        ps_note = f"  ps={data['ps_exec_avg_ms']:>4}ms" if data["ps_exec_avg_ms"] is not None else ""
        safety_note = f"  safety={data['safety_avg_ms']:>2}ms  cache={data['cache_hits']}/{N}"
        row(name, data["times_ms"], ps_note + safety_note)

    # ── 3. Write commands ────────────────────────────────────────────────────
    sep("3 · Write commands (%d runs, safety=KAN pipeline)" % N)
    for name, cmd in WRITE_COMMANDS.items():
        data = await _bench_cmd(mgr, name, cmd, "bench", N, warmup=0)
        results["write"][name] = data
        ps_note = f"  ps={data['ps_exec_avg_ms']:>4}ms" if data["ps_exec_avg_ms"] is not None else ""
        safety_note = f"  safety={data['safety_avg_ms']:>2}ms  kan={data['kan_avg_ms']:>2}ms  cache={data['cache_hits']}/{N}"
        row(name, data["times_ms"], ps_note + safety_note)

    # ── 4. Write pipeline (write → read-back → overwrite) ───────────────────
    sep("4 · Write pipeline — write, read-back, verify (%d cycles)" % N)
    pipeline_times: list[int] = []
    pipeline_verify_ok = 0
    payload = "bench-payload-verify-12345"
    for run in range(N):
        t_start = time.monotonic()
        # Write
        wr = await mgr.execute(
            f"Write-LoomFile 'docs/loom/bench_scratch/pipeline.txt' '{payload}'",
            session_id="bench",
        )
        # Verify with a direct PS comparison — avoids nested JSON parsing
        vr = await mgr.execute(
            f"if ((Get-Content 'docs/loom/bench_scratch/pipeline.txt' -Raw).Trim() -eq '{payload}') {{ 'MATCH' }} else {{ 'NOMATCH' }}",
            session_id="bench",
        )
        cycle_ms = int((time.monotonic() - t_start) * 1000)
        pipeline_times.append(cycle_ms)
        ok = "MATCH" in vr.get("output", "") and wr.get("success", False)
        if ok:
            pipeline_verify_ok += 1
        log.debug("  Pipeline run %d: %dms  write=%s  verify_out=%r  ok=%s",
                  run+1, cycle_ms, wr.get("success"), vr.get("output","")[:40], ok)

    results["write_pipeline"] = {
        "times_ms": pipeline_times,
        "avg_ms": int(mean(pipeline_times)),
        "verify_pass": pipeline_verify_ok,
        "verify_total": N,
    }
    row(
        f"write+read cycle",
        pipeline_times,
        f"  verify={pipeline_verify_ok}/{N}",
    )

    # ── 5. Large output ──────────────────────────────────────────────────────
    sep("5 · Large output commands (%d runs)" % N)
    for name, cmd in LARGE_OUTPUT_COMMANDS.items():
        data = await _bench_cmd(mgr, name, cmd, "bench", N)
        results["large_output"][name] = data
        ps_note = f"  ps={data['ps_exec_avg_ms']:>4}ms" if data["ps_exec_avg_ms"] is not None else ""
        row(name, data["times_ms"], ps_note)

    # ── 6. Safety pipeline variants ──────────────────────────────────────────
    sep("6 · Safety pipeline — safe / readonly / cached / blocked")

    # 6a. Blocked commands (should be rejected instantly, no PS execution)
    print("  Blocked commands (expect success=False):")
    for name, cmd in SAFETY_BLOCKED_COMMANDS.items():
        times_b: list[int] = []
        for _ in range(3):
            ms, r = await timed(mgr.execute(cmd, session_id="bench"))
            times_b.append(ms)
            log.debug("  blocked %s: %dms  success=%s  err=%r",
                      name, ms, r.get("success"), (r.get("error") or r.get("errors", ""))[:80])
        results["safety"][f"blocked_{name}"] = {
            "times_ms": times_b,
            "avg_ms": int(mean(times_b)),
            "was_blocked": True,
        }
        row(f"  blocked/{name}", times_b, "  (should be rejected)")

    # 6b. Cache warm-up vs cold: same command 10 times, show first vs rest
    print("  Cache: cold hit (run 1) vs warm (runs 2-10):")
    cache_cmd = "Search-LoomCode 'class ' -Path 'src' -Include '*.py'"
    cache_times: list[int] = []
    cache_safety: list[int] = []
    for i in range(10):
        ms, r = await timed(mgr.execute(cache_cmd, session_id="bench"))
        cache_times.append(ms)
        cache_safety.append(r.get("safety_timing", {}).get("total_safety_ms", 0))
    cold_t = cache_times[0]
    warm_avg = int(mean(cache_times[1:]))
    cold_s = cache_safety[0]
    warm_s_avg = int(mean(cache_safety[1:]))
    results["safety"]["cache_comparison"] = {
        "cold_ms": cold_t, "warm_avg_ms": warm_avg,
        "cold_safety_ms": cold_s, "warm_safety_avg_ms": warm_s_avg,
        "speedup": round(cold_t / warm_avg, 2) if warm_avg else 1.0,
    }
    print(f"    cold={cold_t}ms (safety={cold_s}ms)  warm_avg={warm_avg}ms (safety={warm_s_avg}ms)  speedup={round(cold_t/warm_avg,2) if warm_avg else 1}x")

    # ── 7. Batch execution ───────────────────────────────────────────────────
    sep("7 · Batch (%d commands, 1 round-trip, %d runs)" % (len(BATCH_COMMANDS), N))
    batch_times: list[int] = []
    for run in range(N):
        ms, batch_res = await timed(mgr.execute_batch(BATCH_COMMANDS, session_id="bench"))
        batch_times.append(ms)
        log.debug("  Batch run %d: %dms", run+1, ms)
        if run == 0:
            for i, br in enumerate(batch_res):
                log.debug("    [%d] success=%s ps_exec=%s err=%r",
                          i+1, br.get("success"), br.get("execution_time_ms"), br.get("errors","")[:60])

    results["batch"] = {
        "num_commands": len(BATCH_COMMANDS),
        "times_ms": batch_times,
        "avg_ms": int(mean(batch_times)),
        "avg_per_cmd_ms": int(mean(batch_times) / len(BATCH_COMMANDS)),
    }
    row(f"batch/{len(BATCH_COMMANDS)} cmds", batch_times,
        f"  {int(mean(batch_times) / len(BATCH_COMMANDS))}ms/cmd")

    # ── 8. Sequential baseline ───────────────────────────────────────────────
    sep("8 · Sequential baseline (same %d commands, %d runs)" % (len(BATCH_COMMANDS), N))
    seq_times: list[int] = []
    for run in range(N):
        t0 = time.monotonic()
        for cmd in BATCH_COMMANDS:
            await mgr.execute(cmd, session_id="seq")
        seq_ms = int((time.monotonic() - t0) * 1000)
        seq_times.append(seq_ms)
        log.debug("  Sequential run %d: %dms", run+1, seq_ms)

    speedup = mean(seq_times) / mean(batch_times) if batch_times else 1.0
    results["sequential_baseline"] = {
        "num_commands": len(BATCH_COMMANDS),
        "times_ms": seq_times,
        "avg_ms": int(mean(seq_times)),
        "avg_per_cmd_ms": int(mean(seq_times) / len(BATCH_COMMANDS)),
    }
    results["batch_speedup"] = round(speedup, 2)
    row(f"sequential/{len(BATCH_COMMANDS)} cmds", seq_times,
        f"  {int(mean(seq_times) / len(BATCH_COMMANDS))}ms/cmd")

    # ── 9. Concurrent sessions ───────────────────────────────────────────────
    sep("9 · Concurrent sessions (3 parallel sessions, %d runs)" % N)
    CONCURRENT_CMD = "Search-LoomCode 'def ' -Path 'src' -Include '*.py'"
    concurrent_wall_times: list[int] = []
    sequential_equiv: list[int] = []

    for run in range(N):
        t0 = time.monotonic()
        results_c = await asyncio.gather(
            mgr.execute(CONCURRENT_CMD, session_id="c1"),
            mgr.execute(CONCURRENT_CMD, session_id="c2"),
            mgr.execute(CONCURRENT_CMD, session_id="c3"),
        )
        wall_ms = int((time.monotonic() - t0) * 1000)
        concurrent_wall_times.append(wall_ms)
        per_cmd = [r.get("execution_time_ms", 0) for r in results_c]
        sequential_equiv.append(sum(per_cmd))
        log.debug("  Concurrent run %d: wall=%dms  per_cmd=%s", run+1, wall_ms, per_cmd)

    concur_avg = int(mean(concurrent_wall_times))
    seq_equiv_avg = int(mean(sequential_equiv))
    concur_speedup = round(seq_equiv_avg / concur_avg, 2) if concur_avg else 1.0
    results["concurrent"] = {
        "sessions": 3,
        "wall_times_ms": concurrent_wall_times,
        "wall_avg_ms": concur_avg,
        "sequential_equiv_avg_ms": seq_equiv_avg,
        "parallelism_speedup": concur_speedup,
    }
    row("3 concurrent sessions (wall)", concurrent_wall_times,
        f"  seq_equiv_avg={seq_equiv_avg}ms  parallelism={concur_speedup}x")

    # ── 10. Throughput burst ─────────────────────────────────────────────────
    sep("10 · Throughput burst (%d rapid-fire echo commands)" % THROUGHPUT_BURST)
    burst_cmd = "Write-Host ping"
    # Warmup
    for _ in range(3):
        await mgr.execute(burst_cmd, session_id="bench")

    t_burst = time.monotonic()
    for _ in range(THROUGHPUT_BURST):
        await mgr.execute(burst_cmd, session_id="bench")
    burst_elapsed = time.monotonic() - t_burst
    burst_cps = round(THROUGHPUT_BURST / burst_elapsed, 1)
    burst_avg_ms = round(burst_elapsed / THROUGHPUT_BURST * 1000, 1)

    results["throughput"] = {
        "commands": THROUGHPUT_BURST,
        "elapsed_ms": int(burst_elapsed * 1000),
        "commands_per_second": burst_cps,
        "avg_ms_per_command": burst_avg_ms,
    }
    print(f"  {THROUGHPUT_BURST} echo commands in {int(burst_elapsed*1000)}ms  "
          f"= {burst_cps} cmd/s  ({burst_avg_ms}ms each)")

    await mgr.close_all_sessions()

    # ── Summary ───────────────────────────────────────────────────────────────
    sep("Summary")
    print(f"  Protocol              : {results['protocol']}")
    print(f"  Cold start            : {results['cold_start_ms']}ms")
    if results["read"]:
        read_avgs = [v["avg_ms"] for v in results["read"].values()]
        print(f"  Read cmd avg          : {int(mean(read_avgs))}ms  (range {min(read_avgs)}-{max(read_avgs)}ms)")
    if results["write"]:
        write_avgs = [v["avg_ms"] for v in results["write"].values()]
        write_safety = [v["safety_avg_ms"] for v in results["write"].values()]
        print(f"  Write cmd avg         : {int(mean(write_avgs))}ms  (safety overhead: {int(mean(write_safety))}ms)")
    if results["write_pipeline"]:
        wp = results["write_pipeline"]
        print(f"  Write+read pipeline   : {wp['avg_ms']}ms avg  verify={wp['verify_pass']}/{wp['verify_total']}")
    if results["large_output"]:
        lo_avgs = [v["avg_ms"] for v in results["large_output"].values()]
        print(f"  Large output avg      : {int(mean(lo_avgs))}ms  (range {min(lo_avgs)}-{max(lo_avgs)}ms)")
    if results["safety"].get("cache_comparison"):
        cc = results["safety"]["cache_comparison"]
        print(f"  Safety cache speedup  : {cc['speedup']}x  (cold={cc['cold_ms']}ms  warm={cc['warm_avg_ms']}ms)")
    print(f"  Batch avg             : {results['batch']['avg_ms']}ms  ({results['batch']['avg_per_cmd_ms']}ms/cmd)")
    print(f"  Sequential avg        : {results['sequential_baseline']['avg_ms']}ms  ({results['sequential_baseline']['avg_per_cmd_ms']}ms/cmd)")
    print(f"  Batch speedup         : {results['batch_speedup']}x  (saved {results['sequential_baseline']['avg_ms']-results['batch']['avg_ms']}ms avg)")
    if results["concurrent"]:
        cc = results["concurrent"]
        print(f"  Concurrent speedup    : {cc['parallelism_speedup']}x  (3 sessions, wall={cc['wall_avg_ms']}ms vs seq_equiv={cc['sequential_equiv_avg_ms']}ms)")
    if results["throughput"]:
        tp = results["throughput"]
        print(f"  Throughput            : {tp['commands_per_second']} cmd/s  ({tp['avg_ms_per_command']}ms/cmd)")
    sep()

    results["finished_at"] = datetime.now(timezone.utc).isoformat()
    return results


async def main() -> None:
    parser = argparse.ArgumentParser(description="PowerShell MCP benchmark")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show DEBUG-level logging")
    parser.add_argument("--quick", "-q", action="store_true",
                        help="3 repeats instead of 5 (faster run)")
    args = parser.parse_args()

    setup_logging(args.verbose)

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root / "src"))

    log.info("PowerShell MCP Benchmark — project_root=%s  quick=%s", project_root, args.quick)

    try:
        results = await run_benchmark(project_root, quick=args.quick)
    except KeyboardInterrupt:
        log.warning("Benchmark interrupted by user")
        return

    metrics_dir = project_root / "docs" / "loom" / "metrics"
    metrics_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_path = metrics_dir / f"bench_ps_{ts}.json"
    out_path.write_text(json.dumps(results, indent=2))
    log.info("Results saved → %s", out_path)
    print(f"\nResults saved → {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
