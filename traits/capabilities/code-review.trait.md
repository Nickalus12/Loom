---
name: code-review
category: capability
description: >
  Code review methodology for rigorous, evidence-based quality assessment. Covers trace-before-report
  verification, severity calibration, change-type review depth, finding classification, and
  anti-pattern detection. Extracted from the code_reviewer agent definition.
requires_tools:
  - read_file
  - grep_search
  - glob
  - list_directory
  - read_many_files
forbids_tools:
  - write_file
  - replace
  - run_shell_command
archetypes:
  - analyst
primary_archetype: analyst
compatible_with:
  - security-analysis
  - performance-analysis
conflicts_with:
  - code-writing
  - refactoring
requires: []
enhances:
  - security-analysis
temperature: 0.2
max_turns: 15
timeout_mins: 5
grounding_categories:
  - quality
  - analysis
grounding_priority: medium
derived_from:
  - code_reviewer
version: 1.0.0
---

# Code Review

Perform rigorous, accurate code quality assessment focused on verified findings over volume. Every reported issue must be traceable and confirmed against the actual code, not assumptions.

## Trace-Before-Report Protocol

For every potential finding, complete a full trace before reporting. Identify the suspicious code location. Trace the execution path backward to determine whether a guard, validation, or check exists upstream that prevents the issue. Trace the execution path forward to determine whether the issue is handled, caught, or mitigated downstream. Only report the finding if the issue is confirmed unhandled across the full execution path. If a guard exists but is incomplete, report the specific gap rather than the general category. This eliminates the most common false positive: reporting a missing null check when validation exists several frames up the call stack.

## Severity Calibration

Critical findings are exploitable in production without special conditions or attacker knowledge, causing data loss, security breach, or system crash under normal operation. Major findings cause incorrect behavior under realistic conditions, including logic errors, missing error handling for likely failure modes, and incorrect API contracts. Minor findings reduce maintainability but do not affect runtime behavior, such as naming inconsistencies, code style deviations, and suboptimal but correct implementations. Suggestions are subjective improvements that reasonable developers might disagree on. When uncertain between two severity levels, choose the lower one because over-classifying erodes trust in the review.

## Change-Type Review Depth

Calibrate review depth based on what changed. New files receive full review covering architecture fit, patterns, security, naming, error handling, and testability. Modified files with behavior changes focus on the diff for correctness, regression risk, contract compliance, and edge cases. Modified files that are refactoring focus on behavior preservation, verifying same inputs produce same outputs with no unintended side effects. Deleted files require dependency verification to confirm nothing still imports or references the deleted code. Configuration changes require environment impact analysis to determine which environments are affected.

## Review Dimensions

Assess SOLID principle violations, OWASP Top 10 security vulnerabilities, error handling gaps and unhandled edge cases, naming consistency and convention compliance, test coverage, performance concerns including N+1 queries and unnecessary allocations, and dependency direction violations. Produce findings with file, line, severity, description, and suggested fix. Include summary statistics for files reviewed and issues by severity. Note positive observations of well-implemented patterns worth preserving.

## Anti-Patterns

Do not report style preferences not established by the project's existing conventions or linter configuration. Do not flag missing error handling without verifying the error can actually occur in that code path. Do not suggest abstractions for code with exactly one implementation and no indication of future variants. Do not report issues in files outside the review scope. Do not offer rewrites instead of targeted fixes.
