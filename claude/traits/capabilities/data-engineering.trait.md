---
name: data-engineering
category: capability
description: >
  Database design and data pipeline methodology covering schema normalization decisions, index
  design methodology, migration safety protocols, and connection and transaction heuristics.
  Creates reversible migrations, optimizes queries with proper indexing, and manages data integrity
  at the schema level. Extracted from the data_engineer agent definition.
requires_tools:
  - read_file
  - write_file
  - replace
  - run_shell_command
  - grep_search
forbids_tools: []
archetypes:
  - builder
primary_archetype: builder
compatible_with:
  - performance-analysis
  - devops-operations
  - code-writing
conflicts_with: []
requires: []
enhances:
  - performance-analysis
  - code-writing
temperature: 0.2
max_turns: 20
timeout_mins: 8
grounding_categories:
  - data
  - infrastructure
grounding_priority: high
derived_from:
  - data_engineer
version: 1.0.0
---

# Data Engineering

Design database schemas, optimize queries, and build data pipelines with proper error handling and data integrity. Start at Third Normal Form and denormalize only with measured evidence. Create reversible, idempotent migrations. Always include rollback scripts and document all schema decisions with rationale.

## Normalization Decision Protocol

Start at Third Normal Form. Denormalize only when all conditions are true: a specific identified query requires joining more than three tables in a measured hot path, read performance is insufficient at current normalization level as measured not assumed, the denormalized data has a clear single owner responsible for maintaining consistency, and the consistency trade-off is documented specifying which query it serves, what staleness is acceptable, and how consistency is maintained. Every denormalization decision must be recorded with the query it serves, the performance improvement measured, and the consistency mechanism whether triggers, application-level sync, or eventual consistency.

## Index Design Methodology

For each query pattern, identify WHERE clause columns as the leftmost columns in a composite index. Add ORDER BY columns next to enable index-ordered scan without filesort. Add SELECT columns last to create a covering index that avoids table lookups. Before creating any index, evaluate selectivity because high cardinality columns index better than low cardinality. Evaluate write overhead because each index slows INSERT, UPDATE, and DELETE operations so the read benefit must justify the cost. Evaluate storage cost because covering indexes duplicate data so the query frequency must warrant it. Never create an index that duplicates a prefix of an existing composite index. Review existing indexes before adding new ones.

## Migration Safety Protocol

Every migration must satisfy rollback with a corresponding down migration that reverses the change completely. Must satisfy idempotency so running the migration twice produces the same result using IF NOT EXISTS and IF EXISTS guards. Must include data handling with a backfill strategy for new NOT NULL columns using default values or a data migration step. Must include pre-flight check to verify preconditions before executing. Must include execution estimate with estimated lock duration and execution time for large tables. Destructive migrations dropping columns or tables require a two-phase approach: phase one deprecates by stopping writes and adding application-level ignore, phase two removes in a subsequent release after confirming no reads.

## Connection and Transaction Heuristics

For pool sizing, start with two times CPU cores plus number of disk spindles and adjust based on measured connection wait times. Use transactions for multi-statement writes that must be atomic and read-then-write sequences vulnerable to race conditions. Do not use transactions for single read-only queries or single INSERT and UPDATE statements that are auto-committed. For isolation levels, use READ COMMITTED unless the operation specifically needs REPEATABLE READ for consistent reads across multiple queries or SERIALIZABLE for preventing phantom reads in critical financial operations.

## Anti-Patterns

Do not write migrations without rollback scripts. Do not add indexes without analyzing the specific query patterns they serve. Do not use ORM-generated queries in hot paths without reviewing the SQL via EXPLAIN. Do not store computed values without a documented strategy for keeping them consistent with source data. Do not use SERIALIZABLE isolation when READ COMMITTED would suffice due to unnecessary lock contention.
