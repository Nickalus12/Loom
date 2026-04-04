---
name: archive
description: Archive the active Loom session while preserving the shared state layout
---


# Loom Archive

Read `${CLAUDE_PLUGIN_ROOT}/references/architecture.md` and `${CLAUDE_PLUGIN_ROOT}/templates/session-state.md`.

## Workflow

1. Resolve `docs/loom` from `LOOM_STATE_DIR`.
2. Verify that an active session exists.
3. Move the active session file into `docs/loom/state/archive/`.
4. Move the associated design and implementation plan files into `docs/loom/plans/archive/`.
5. Verify that no active-session file remains and report the archived paths.

## Constraints

- Do not delete plan or session history.
- Preserve the existing archive directory structure.
