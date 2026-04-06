---
title: "Remediate Critical PowerShell MCP Findings"
created: "2026-04-05T12:00:00.000Z"
status: "approved"
authors: ["TechLead", "User"]
type: "design"
design_depth: "quick"
task_complexity: "medium"
---

# Remediate Critical PowerShell MCP Findings Design Document

## Problem Statement

The Loom V4 PowerShell MCP REPL (built 2026-04-05, session `2026-04-05-powershell-mcp-repl`) shipped with 5 Critical + 6 Major code review findings that were never remediated. Three Critical findings are high-impact security and functionality bugs:

1. **Module load silently fails** (`repl_manager.py:37`): `-ErrorAction SilentlyContinue` swallows Import-Module failures, making all 15 Loom-prefixed cmdlets non-functional
2. **Format string injection** (`repl_manager.py:284`): `_EXEC_WRAPPER_TEMPLATE.format()` allows `{marker}` leakage and `{unknown}` KeyError DoS
3. **Safety review fails open** (`local_inference.py:264`): Exception returns `caution` instead of raising, bypassing repl_manager's block-on-failure logic

## Approach

### Selected Approach

**Three-phase agent pipeline: investigate → remediate → validate**

A debugger agent investigates all 3 findings using PowerShell MCP tools and native tools, a coder agent remediates all 3 issues, and a tester agent writes and runs tests. This tests the Maestro multi-agent delegation pipeline end-to-end while fixing real bugs.

### Alternatives Considered

#### Single-Agent Remediation
- **Description**: Have a single coder agent do all investigation, fixing, and testing
- **Pros**: Simpler delegation, fewer handoff risks
- **Cons**: Doesn't test multi-agent pipeline coordination
- **Rejected Because**: The user's goal is explicitly to test the pipeline and map how agents work

## Agent Team

| Phase | Agent(s) | Parallel | Deliverables |
|-------|----------|----------|--------------|
| 1 | debugger | No | Root cause report for 3 Critical findings |
| 2 | coder | No | Fixed source files (repl_manager.py, local_inference.py) |
| 3 | tester | No | Test suite covering all 3 fixes |

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| PowerShell MCP tools inaccessible to subagents | MEDIUM | MEDIUM | Agents fall back to native Read/Bash tools |
| Safety review fix breaks existing tests | LOW | LOW | Tester phase validates full test suite |
| Format string fix changes REPL behavior | LOW | LOW | Marker protocol is internal; fix is isolated |

## Success Criteria

1. All 3 Critical findings are fixed in source code
2. New test suite covers all 3 fixes and passes
3. Existing unit test suite passes without regressions
4. Agent pipeline delegation works end-to-end (debugger → coder → tester)
