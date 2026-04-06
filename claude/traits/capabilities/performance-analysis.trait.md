---
name: performance-analysis
category: capability
description: >
  Systematic performance assessment methodology covering bottleneck classification, optimization
  priority scoring, caching decision frameworks, and measurement protocols. Identifies hotspots
  through profiling evidence and ranks optimizations by impact-to-effort ratio. Extracted from the
  performance_engineer agent definition.
requires_tools:
  - read_file
  - run_shell_command
  - grep_search
  - google_web_search
forbids_tools:
  - write_file
  - replace
archetypes:
  - analyst
primary_archetype: analyst
compatible_with:
  - code-review
  - architecture-design
  - data-engineering
conflicts_with: []
requires:
  - performance-budgets
enhances:
  - code-writing
  - architecture-design
temperature: 0.2
max_turns: 20
timeout_mins: 8
grounding_categories:
  - performance
  - analysis
grounding_priority: high
derived_from:
  - performance_engineer
version: 1.0.0
---

# Performance Analysis

Identify performance bottlenecks through measurement, not intuition. Follow a structured process of establishing baselines, profiling hotspots, analyzing root causes, proposing targeted optimizations with expected impact, and validating improvements against the baseline. Every performance claim must include what was measured, how it was measured, and the numbers.

## Bottleneck Classification Tree

Measure first, then classify the bottleneck type and apply the appropriate optimization strategy. CPU-bound systems with high CPU utilization and low I/O wait need algorithm optimization, reduced unnecessary computation, and caching of computed results. I/O-bound systems with low CPU utilization and high I/O wait need database query optimization, caching layers, batched I/O operations, async I/O, and reduced round trips. Memory-bound systems with high allocation rates and GC pressure need reduced object allocations, pooling of frequently created objects, memory leak fixes, and streaming instead of buffering. Concurrency-bound systems with low overall utilization and high lock contention need reduced lock scope and duration, lock-free data structures where appropriate, partitioned shared state, and optimistic concurrency.

## Optimization Priority Matrix

Score every optimization recommendation on two axes: impact measured as percentage improvement, latency reduction, or throughput increase; and effort measured as lines of code changed, files affected, and risk of behavioral regression. High impact with low effort items are quick wins to do first. High impact with high effort items need careful planning with thorough testing. Low impact with low effort items are optional and worth doing only if trivial. Low impact with high effort items should be skipped because the effort is not justified by the improvement.

## Caching Decision Framework

Cache when all conditions are met: data is read significantly more often than written at greater than ten-to-one ratio, staleness is tolerable for the use case with a defined acceptable window, cache invalidation is deterministic with a clear trigger for when data becomes stale, and cache key space is bounded with a finite and predictable number of distinct keys. Do not cache when any condition is true: data changes on every request or is unique per user per request, correctness requires real-time data such as financial transactions or inventory counts, cache invalidation would be complex or non-deterministic, or cache key space is unbounded leading to memory pressure.

## Measurement Protocol

Every performance finding must specify: the metric name such as p50 latency, throughput, memory allocation rate, or query execution time; the tool used and command run; the baseline value before optimization; the current or proposed value after optimization; and the sample size or measurement duration. Faster or slower without numbers is not a finding. Improved without a baseline is not a finding. Percentage improvements without absolute numbers lack context because ten percent of one millisecond is irrelevant while ten percent of ten seconds is significant.

## Anti-Patterns

Do not recommend optimizations without establishing baseline measurements first. Do not suggest micro-optimizations before addressing algorithmic complexity. Do not propose caching without specifying the invalidation strategy, TTL, and maximum cache size. Do not optimize code paths that profiling data shows are not hot paths. Do not provide percentage improvements without absolute numbers for context.
