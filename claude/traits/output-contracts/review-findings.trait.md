---
name: review-findings
category: output-contract
description: >
  Structured output format for code review and analysis tasks. Produces findings sorted by
  severity with file:line references, evidence, and suggested fixes, followed by summary
  statistics and positive observations.
requires_tools: []
forbids_tools: []
archetypes:
  - analyst
primary_archetype: analyst
compatible_with:
  - code-review
  - security-analysis
  - performance-analysis
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

# Review Findings

Upon completing a review or analysis task, produce findings in the following exact format. Findings are sorted by severity descending. Every finding must reference a specific file and line.

## Required Output Format

```markdown
## Review Summary
- **Scope**: [Files and directories reviewed]
- **Review Type**: [code-review | security-analysis | performance-analysis]
- **Total Findings**: [Count by severity: N critical, N major, N minor, N suggestions]

## Findings

### Critical

#### [C1] [Short title]
- **File**: `path/to/file.ext:line`
- **Description**: [What the issue is and why it is critical]
- **Evidence**: [Code snippet or trace demonstrating the issue]
- **Suggested Fix**: [Specific actionable fix with code example]

### Major

#### [M1] [Short title]
- **File**: `path/to/file.ext:line`
- **Description**: [What the issue is and its impact under realistic conditions]
- **Evidence**: [Code snippet or trace demonstrating the issue]
- **Suggested Fix**: [Specific actionable fix]

### Minor

#### [m1] [Short title]
- **File**: `path/to/file.ext:line`
- **Description**: [What the issue is and its maintenance impact]
- **Suggested Fix**: [Specific actionable fix]

### Suggestions

#### [S1] [Short title]
- **File**: `path/to/file.ext:line`
- **Description**: [Subjective improvement and its benefit]

## Positive Observations
- [Well-implemented patterns worth preserving]

## Statistics
- **Files Reviewed**: [Count]
- **Lines Analyzed**: [Approximate count]
- **Issues by Severity**: Critical: N | Major: N | Minor: N | Suggestions: N
```

## Formatting Rules

Findings within each severity section are numbered sequentially with a prefix: C for critical, M for major, m for minor, S for suggestion. Every finding must include a file path with line number. Critical and Major findings require an Evidence section with the actual code or execution trace that demonstrates the issue. Every finding at Critical or Major severity must include a Suggested Fix with a concrete, actionable code change. Omit severity sections that have zero findings rather than showing an empty section. The Positive Observations section is required and must contain at least one observation; if nothing stands out, acknowledge the general code quality level.
