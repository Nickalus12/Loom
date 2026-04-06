---
name: debug-report
category: output-contract
description: >
  Structured output format for debugging and root cause analysis tasks. Covers symptom description,
  root cause analysis with execution trace, evidence chain, recommended fix, and regression
  prevention measures.
requires_tools: []
forbids_tools: []
archetypes:
  - builder
  - investigator
primary_archetype: investigator
compatible_with:
  - debugging
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

# Debug Report

Upon completing a debugging or root cause analysis task, produce a report in the following exact format. Every section is required.

## Required Output Format

```markdown
## Symptom Description
- **Reported Behavior**: [What was observed: error message, incorrect output, crash, performance degradation]
- **Expected Behavior**: [What should have happened]
- **Reproduction Steps**: [Numbered steps to reproduce the issue, or "intermittent - see conditions below"]
- **Environment**: [OS, runtime version, configuration, or deployment environment where the issue occurs]
- **First Observed**: [Date, commit, or deployment where the issue first appeared, if known]

## Root Cause Analysis

### Root Cause
[One to three sentences identifying the specific code defect, configuration error, or environmental condition causing the symptom]

### Location
- **File**: `path/to/file.ext:line`
- **Function/Method**: [Name of the function or method containing the defect]
- **Introduced In**: [Commit hash or PR reference if identified, or "unknown"]

### Execution Trace
1. [Entry point: how the defective code path is reached]
2. [Intermediate step: relevant state or transformation]
3. [Failure point: where the defect manifests with specific variable state or condition]
4. [Propagation: how the failure surfaces as the reported symptom]

## Evidence

### Confirming Evidence
1. [Evidence that supports the identified root cause]
2. [Evidence that supports the identified root cause]
3. [Evidence that supports the identified root cause]

### Ruled Out Hypotheses
| Hypothesis | Contradicting Evidence |
|-----------|----------------------|
| [Alternative cause considered] | [Evidence that eliminated this hypothesis] |

## Recommended Fix

### Code Change
```[language]
// Before
[Code showing the defective implementation]

// After
[Code showing the corrected implementation]
```

### Rationale
[Why this fix addresses the root cause without introducing side effects]

### Affected Areas
- [Other code paths, tests, or configurations that may need updates due to this fix]

## Regression Prevention
- **Test Case**: [Description of a test that would catch this defect: input, expected output, assertion]
- **Monitoring**: [Metric, log query, or alert that would detect recurrence in production]
- **Process**: [Development practice change that would prevent similar defects, or "none - isolated incident"]
```

## Formatting Rules

The Execution Trace must show the complete path from entry point to symptom, not just the failure point in isolation. Confirming Evidence must contain at least three items. The Ruled Out Hypotheses table must contain at least one alternative that was investigated and eliminated. The Recommended Fix must show both before and after code. The Regression Prevention section must include at least a test case description that would detect the defect.
