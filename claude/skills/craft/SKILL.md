---
name: craft
description: Craft a multi-agent solution using Loom's orchestration pipeline — architect, audit, implement, and review
argument-hint: "<task description>"
allowed-tools: Read, Glob, Grep, Bash(python:*), Bash(uv:*), Agent
---

# Loom Craft

Craft a solution using Loom's multi-agent pipeline. This is the primary orchestration command — use it for complex tasks that benefit from multiple specialist agents working together.

## Pipeline

```
Architect → Security + Quality (parallel) → Coder → Code Review
```

1. **Architect** analyzes the task, identifies key files, proposes an approach
2. **Security Engineer** + **Tester** audit the design in parallel
3. **Coder** implements via LocalAgent (tool-calling, git safety, caching, Graphiti memory)
4. **Code Reviewer** validates the output with severity-classified findings

## Modes

- **Cloud** (default): Agents dispatch through LiteLLM proxy using cloud models
- **Local**: Agents dispatch through LocalAgent using Ollama models with tool-calling
  Configure via `LOOM_CRAFT_MODE=local`

## Workflow

1. Call the `craft` MCP tool with the user's task and optional `mode` parameter
2. Present phase outcomes as they complete
3. On completion, show:
   - Files created and modified
   - Code review findings (Critical/Major/Minor/Suggestion)
   - Git branch name (if local mode created one)

## When to Use

| Task | Command |
|------|---------|
| Complex multi-phase work | `/loom:craft` |
| Quick single-agent task | `/loom:agent` |
| Code review only | `/loom:review` |
| Debug investigation | `/loom:debug` |
| Security audit | `/loom:security-audit` |

## Examples

```
/loom:craft Add rate limiting to the API endpoints
/loom:craft Refactor the authentication module for testability
/loom:craft Build a new CLI command for database migrations
```
