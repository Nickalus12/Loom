---
name: agent
description: Run a local Ollama agent to autonomously review, edit, or analyze code with tool-calling, git safety, caching, and Graphiti memory
argument-hint: "<task description>"
allowed-tools: Read, Glob, Grep, Bash(python:*), Bash(uv:*)
---

# Loom Agent

Run a local Ollama agent task. The agent operates entirely on your machine via Ollama, using tool calling to autonomously read, edit, and search code through PowerShell MCP tools.

## Capabilities

- **Dual-model routing**: Fast model (qwen3:4b) for tool calls, smart model (deepseek-coder-v2:16b) for analysis
- **7 tools**: `read_file`, `read_file_lines`, `edit_file`, `write_file`, `search_code`, `find_files`, `run_powershell`
- **Git safety**: Auto-creates `loom/agent-<timestamp>` branch before file writes, shows diff on completion
- **Think-then-act**: Qwen3 models use built-in chain-of-thought; others get a planning turn
- **Retry + caching**: Failed tools retry once; file reads are cached within a task
- **Syntax validation**: Auto-validates `.py` files after writes
- **Session memory**: Stores/retrieves task context via Graphiti knowledge graph

## Workflow

1. Call the `local_agent_task` MCP tool with the user's task description
2. Present the agent's `AgentResult`:
   - `response`: The agent's final analysis or review
   - `files_changed`: List of modified files
   - `git_branch` / `git_diff`: Branch name and diff summary
   - `tool_log`: Detailed log of every tool call made
   - `validation_results`: Syntax check results for written files
   - `tool_calls_made` / `turns_used`: Execution stats

## Usage Examples

```
/loom:agent Review src/loom/server.py for security issues
/loom:agent Add input validation to the execute_powershell function
/loom:agent Refactor kan_engine.py to reduce method complexity
/loom:agent Find all TODO comments and summarize them
```

## Constraints

- All file operations pass through the 3-tier safety pipeline (KAN + blocklist + Gemma review)
- The agent runs up to 15 tool-calling turns by default
- File writes require Ollama running (for Gemma safety review on elevated commands)
- Session memory requires Neo4j running (graceful degradation if unavailable)
- The agent works within the project root only — path safety prevents external access
