---
name: performance-budgets
category: constraint
description: >
  Performance budget constraint defining Core Web Vitals targets, bundle size limits, time-to-interactive
  thresholds, memory budgets, API latency SLAs, and database query limits. Applied to any capability
  that produces or reviews code with measurable performance impact.
requires_tools: []
forbids_tools: []
archetypes:
  - builder
  - analyst
  - architect
  - investigator
primary_archetype: builder
compatible_with:
  - performance-analysis
  - code-writing
  - devops-operations
conflicts_with: []
requires: []
enhances:
  - performance-analysis
temperature: 0.2
max_turns: 0
timeout_mins: 0
grounding_categories: []
grounding_priority: low
derived_from: []
version: 1.0.0
---

# Performance Budgets

All code must respect quantitative performance budgets. Performance regressions are treated as defects, not tradeoffs to be discussed.

## Core Web Vitals Targets

LCP under 2.5s, FID under 100ms, INP under 200ms, CLS under 0.1, FCP under 1.8s, TTFB under 800ms -- all at 75th percentile. Target device profile: mid-range mobile on 4G with 150ms RTT.

## Bundle Size Limits

Initial JavaScript bundle must not exceed 200KB compressed. Per-route lazy chunks must not exceed 50KB compressed. CSS must not exceed 75KB compressed. Above-fold images must be under 100KB each using WebP/AVIF for photos and SVG for icons. Third-party scripts count toward the total. Evaluate every new dependency for size impact before inclusion.

## API Latency and Throughput SLAs

User-facing endpoints must respond within 200ms at p95. Background endpoints within 5s at p95. Batch endpoints within 30s at p95. WebSocket handling within 50ms. Apply timeouts to all external calls with circuit breakers for cascading failure prevention.

## Database Query Limits

Individual queries must complete within 100ms at p95. Maximum 10 queries per request. Eliminate N+1 patterns using eager loading, batch fetching, or dataloaders. Queries against tables over 100K rows must use indexed columns in WHERE and JOIN clauses. Full table scans are prohibited in production paths.

## Memory and Resource Budgets

Server request handlers must not exceed 50MB heap per request. Long-running processes must demonstrate stable memory with no unbounded growth. Client applications must stay under 100MB heap. Close all connections, handles, and sockets explicitly. Stream payloads over 1MB instead of buffering.
