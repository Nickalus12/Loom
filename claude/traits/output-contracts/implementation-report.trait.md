---
name: implementation-report
category: output-contract
description: >
  Structured output format for implementation tasks. Provides a Task Report with status, files
  created/modified, decisions made, and validation results, followed by a Downstream Context
  section with interfaces introduced, patterns established, integration points, assumptions,
  and warnings for consuming agents.
requires_tools: []
forbids_tools: []
archetypes:
  - builder
primary_archetype: builder
compatible_with:
  - code-writing
  - refactoring
  - test-generation
  - devops-operations
conflicts_with: []
requires: []
enhances: []
temperature: 0.0
max_turns: 0
timeout_mins: 0
grounding_categories: []
grounding_priority: low
derived_from: []
version: 1.0.0
---

# Implementation Report

Upon completing an implementation task, produce a report in the following exact format. Every section is required. Use "none" for sections with no applicable content.

## Required Output Format

```markdown
## Task Report
- **Status**: success | partial | failure
- **Objective Achieved**: [One sentence restating the task objective and whether it was fully met]
- **Files Created**: [Absolute paths with one-line purpose each, or "none"]
- **Files Modified**: [Absolute paths with one-line summary of what changed and why, or "none"]
- **Files Deleted**: [Absolute paths with rationale, or "none"]
- **Decisions Made**: [Choices made not explicitly specified in the delegation prompt, with rationale for each, or "none"]
- **Validation**: pass | fail | skipped
- **Validation Output**: [Command output or "N/A"]
- **Errors**: [List with type, description, and resolution status, or "none"]
- **Scope Deviations**: [Anything asked but not completed, or additional necessary work discovered but not performed, or "none"]

## Downstream Context
- **Key Interfaces Introduced**: [Type signatures and file locations, or "none"]
- **Patterns Established**: [New patterns that downstream agents must follow for consistency, or "none"]
- **Integration Points**: [Where and how downstream work should connect to this output, or "none"]
- **Assumptions**: [Anything assumed that downstream agents should verify, or "none"]
- **Warnings**: [Gotchas, edge cases, or fragile areas downstream agents should be aware of, or "none"]
```

## Formatting Rules

Status must be one of exactly three values: success when the objective was fully achieved and validation passed, partial when the objective was partially achieved or validation had non-blocking warnings, failure when the objective was not achieved or validation failed with blocking errors. Files Created and Files Modified must use absolute paths, never relative paths. Each file entry must include a one-line description of its purpose or what changed. Decisions Made must explain the rationale for any implementation choice not explicitly dictated by the delegation prompt. Scope Deviations must document both work requested but not completed and additional work discovered as necessary but not performed.
