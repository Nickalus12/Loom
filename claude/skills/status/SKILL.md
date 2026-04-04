---
name: status
description: Summarize the active Loom session without mutating state
---


# Loom Status

## MCP Tool Name Mapping

Loom MCP tools are registered with a namespace prefix in Claude Code. When instructions reference bare tool names, use the prefixed version:

| Referenced as | Actual tool name |
|--------------|-----------------|
| `get_session_status` | `mcp__plugin_loom_loom__get_session_status` |
| `resolve_settings` | `mcp__plugin_loom_loom__resolve_settings` |

When instructions say "If `X` appears in your available tools, call it", search your available tools for the prefixed version.

Read `${CLAUDE_PLUGIN_ROOT}/references/architecture.md`.

## Workflow

1. Resolve `docs/loom` from `LOOM_STATE_DIR`.
2. Call `mcp__plugin_loom_loom__get_session_status` to read the active session. If unavailable, read `node ${CLAUDE_PLUGIN_ROOT}/scripts/read-active-session.js` output or inspect `docs/loom/state/active-session.md` directly via `Read`.
3. Report current session status, phase progress, file manifests, validation state, and unresolved errors.

## Constraints

- This is read-only. Do not mutate state, archive sessions, or continue execution.
- If no active session exists, say so plainly.
