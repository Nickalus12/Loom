---
title: "Remediate Critical PowerShell MCP Findings Implementation Plan"
design_ref: "docs/maestro/plans/2026-04-05-ps-mcp-remediation-design.md"
created: "2026-04-05T12:00:00.000Z"
status: "approved"
total_phases: 3
estimated_files: 5
task_complexity: "medium"
---

# Remediate Critical PowerShell MCP Findings Implementation Plan

## Plan Overview

- **Total phases**: 3
- **Agents involved**: debugger, coder, tester
- **Estimated effort**: 3 sequential phases

## Dependency Graph

```
Phase 1 (debugger) → Phase 2 (coder) → Phase 3 (tester)
   investigate          remediate          validate
```

## Execution Strategy

| Stage | Phases | Execution | Agent Count | Notes |
|-------|--------|-----------|-------------|-------|
| 1 | Phase 1 | Sequential | 1 | Investigation |
| 2 | Phase 2 | Sequential | 1 | Remediation |
| 3 | Phase 3 | Sequential | 1 | Validation |

## Phase 1: Investigate Critical Findings

### Objective
Reproduce and document root causes for all 3 Critical findings.

### Agent: debugger
### Parallel: No

### Files to Create
- None

### Files to Modify
- None (read-only investigation)

### Implementation Details
- Read `_SESSION_INIT_TEMPLATE` at `repl_manager.py:29-38` — confirm `-ErrorAction SilentlyContinue` swallows module load failures
- Read `_EXEC_WRAPPER_TEMPLATE` at `repl_manager.py:40-49` and `.format()` at line 284 — confirm format string injection vector
- Read `review_powershell_command` at `local_inference.py:250-269` — confirm exception returns `caution` instead of raising
- Read `_execute_inner` at `repl_manager.py:257-277` — trace the fails-open path
- Verify `LoomAgentTools.psm1` exists on disk

### Validation
- Task Report documenting all 3 root causes with file:line references

### Dependencies
- Blocked by: None
- Blocks: Phase 2

---

## Phase 2: Remediate All Critical Findings

### Objective
Fix all 3 Critical findings in source code.

### Agent: coder
### Parallel: No

### Files to Create
- None

### Files to Modify
- `src/loom/powershell_tools/repl_manager.py` — Module load fix (line 37) + format string fix (line 284)
- `src/loom/local_inference.py` — Safety fails-open fix (lines 262-269)

### Implementation Details

**Fix 1 — Module load**: Replace `-ErrorAction SilentlyContinue` with `-ErrorAction Stop` in try/catch block
**Fix 2 — Format string**: Replace `.format()` with `.replace()` to prevent `{}`-based injection
**Fix 3 — Safety fails-open**: Change exception handler to re-raise instead of returning caution

### Validation
- `python -c "import ast; ast.parse(open('src/loom/powershell_tools/repl_manager.py').read())"`
- `python -c "import ast; ast.parse(open('src/loom/local_inference.py').read())"`

### Dependencies
- Blocked by: Phase 1
- Blocks: Phase 3

---

## Phase 3: Validate Fixes with Tests

### Objective
Write targeted tests covering all 3 Critical fixes and run full test suite.

### Agent: tester
### Parallel: No

### Files to Create
- `tests/unit/test_repl_safety.py` — Test suite for the 3 remediations

### Files to Modify
- None

### Implementation Details
- Module load tests: verify template uses -ErrorAction Stop, bad path produces warning
- Format string tests: script with `{marker}` doesn't leak, `{unknown}` doesn't raise KeyError
- Safety review tests: exception re-raises, _execute_inner returns blocked when safety unavailable

### Validation
- `pytest tests/unit/test_repl_safety.py -v`
- `pytest tests/unit/ -v`

### Dependencies
- Blocked by: Phase 2
- Blocks: None

---

## File Inventory

| # | File | Phase | Purpose |
|---|------|-------|---------|
| 1 | `src/loom/powershell_tools/repl_manager.py` | 1, 2 | Module load + format string fix |
| 2 | `src/loom/local_inference.py` | 1, 2 | Safety fails-open fix |
| 3 | `src/loom/server.py` | 1 | Investigate MCP tool interpolation |
| 4 | `src/loom/powershell_tools/LoomAgentTools.psm1` | 1 | Verify module exists |
| 5 | `tests/unit/test_repl_safety.py` | 3 | Test coverage for all 3 fixes |

## Risk Classification

| Phase | Risk | Rationale |
|-------|------|-----------|
| 1 | LOW | Read-only investigation |
| 2 | MEDIUM | Modifying safety pipeline |
| 3 | LOW | New test file only |

## Execution Profile

```
Execution Profile:
- Total phases: 3
- Parallelizable phases: 0 (in 0 batches)
- Sequential-only phases: 3
- Estimated parallel wall time: N/A
- Estimated sequential wall time: ~15 min

Note: Native subagents currently run without user approval gates.
All tool calls are auto-approved without user confirmation.
```
