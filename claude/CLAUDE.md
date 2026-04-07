# Loom Orchestration Platform

You have access to **Loom** (multi-agent orchestration) and **PSKit** (PowerShell MCP tools) — two complementary systems that give you full autonomous engineering capability.

## Quick Reference — Which Tool When

| Need | Use |
|------|-----|
| Complex multi-phase work (design + audit + implement + review) | `/loom:craft` |
| Quick single-agent task (read, edit, search, run) | `/loom:agent` |
| Code review on specific files or staged changes | `/loom:review` |
| Root cause debugging investigation | `/loom:debug` |
| Security vulnerability assessment | `/loom:security-audit` |
| Read/write/edit a file with line numbers | `mcp__pskit__read_file`, `mcp__pskit__write_file`, `mcp__pskit__edit_file` |
| Search across codebase (ripgrep-powered) | `mcp__pskit__search_code` |
| Git operations (status, diff, log, commit, push, blame) | `mcp__pskit__git_*` |
| System info (disk, memory, GPU, ports, processes) | `mcp__pskit__disk_usage`, `mcp__pskit__memory_usage`, etc. |
| Run build or tests with structured results | `mcp__pskit__build_project`, `mcp__pskit__test_project` |
| Arbitrary PowerShell (safety-gated) | `mcp__pskit__run_command` |
| Check what services are running | `mcp__pskit__port_status` |
| HTTP call to localhost/private network | `mcp__pskit__http_request` |

---

## PSKit MCP Tools (33 tools)

PSKit is a standalone MCP server providing direct PowerShell tool access with a 5-tier neural safety pipeline. Every command is scored by a KAN neural network before execution.

### File Tools
| Tool | What it does | Key params |
|------|-------------|------------|
| `read_file` | Read file with 1-based line numbers | `path`, `max_lines=0` |
| `read_file_range` | Read specific line range (efficient for large files) | `path`, `start_line`, `end_line` |
| `write_file` | Write/create file, auto-creates parent dirs | `path`, `content` |
| `edit_file` | Surgical find-and-replace | `path`, `old_text`, `new_text`, `regex=false`, `replace_all=false` |
| `move_file` | Move or rename file/directory | `source`, `destination` |
| `delete_file` | Delete file or directory (DESTRUCTIVE) | `path`, `recurse=false` |
| `create_directory` | Create directory with parents | `path` |
| `list_directory` | List directory contents with metadata | `path`, `recurse=false` |
| `diff_files` | Unified diff between two files | `path1`, `path2` |
| `search_code` | Ripgrep-powered regex search with context | `pattern`, `path`, `include`, `max_results`, `context` |
| `find_files` | Glob file discovery | `pattern`, `path`, `max_results` |
| `run_command` | Arbitrary PowerShell (fully safety-gated) | `script` |

### Git Tools
| Tool | What it does |
|------|-------------|
| `git_status` | Branch, ahead/behind, changed files with status codes |
| `git_diff` | Unified diff (staged or unstaged, scoped to file) |
| `git_log` | Commit history with path/since/until/author filters |
| `git_commit` | Stage all + commit |
| `git_branch` | Create new branch |
| `git_checkout` | Switch to existing branch/ref |
| `git_push` | Push to remote (DESTRUCTIVE) |
| `git_blame` | Who changed each line |
| `git_stash` / `git_stash_pop` | Save/restore working tree |

### System & Network Tools
| Tool | What it does |
|------|-------------|
| `gpu_status` | NVIDIA GPU name, VRAM, utilization, temperature |
| `disk_usage` | Drive free/used/total GB |
| `memory_usage` | System RAM breakdown |
| `port_status` | TCP listeners + owning PIDs |
| `process_info` | Top processes by CPU (filter by name/PID) |
| `http_request` | HTTP to localhost/private IPs only |

### Build & Test Tools
| Tool | Returns |
|------|---------|
| `build_project` | `{ success, exit_code, stdout, stderr, duration_ms }` |
| `test_project` | `{ success, exit_code, passed, failed, skipped, stdout, stderr, duration_ms }` |

### Environment Tools
| Tool | What it does |
|------|-------------|
| `get_env_vars` | List env vars (filterable) |
| `which` | Check if binary exists + version |
| `install_package` | Install via pip/npm/cargo/winget |

### Usage Rules
- **Always** `read_file` before `edit_file` — verify `old_text` exists exactly
- **Always** `search_code` before reading files blindly — locate what you need first
- **Always** `build_project` then `test_project` before `git_commit`
- Use `git_stash` before risky edits, `git_stash_pop` to restore
- Use `port_status("11434")` to verify Ollama before calling it
- If `edit_file` returns `replacements_made=0`, re-read the file — spacing/indentation didn't match

---

## Loom Swarm Tools (orchestration + local inference)

### Orchestration
| Tool | What it does |
|------|-------------|
| `craft` | Full pipeline: Architect → Security + Quality → Coder → Review |
| `execute_plan` | Execute a pre-built SwarmPlan |
| `local_agent_task` | Autonomous Ollama agent with 7 tools + 19 PS functions |

### Local AI Inference (Ollama)
| Tool | What it does |
|------|-------------|
| `local_brainstorm` | Creative ideation via Gemma |
| `local_review` | Code review via Gemma |
| `local_debug` | Debug analysis via Gemma |
| `local_status` | Model availability + worker state |

### KAN Neural Safety
| Tool | What it does |
|------|-------------|
| `kan_score_command` | Score a PS command's risk (0.0 safe → 1.0 dangerous) |
| `kan_status_ps` | KAN model status and training info |
| `kan_train_ps` | Retrain from accumulated history |
| `kan_learn_history_ps` | Train from Graphiti command history |

### Memory (Neo4j/Graphiti)
| Tool | What it does |
|------|-------------|
| `get_context_for_coder` | Retrieve relevant memory for a task |
| `add_file_node` | Add file to knowledge graph |
| `add_bug_edge` | Record a bug finding |
| `blackboard_transition` | Advance session state |

---

## Architecture

### Model Routing (3 tiers)
- **Heavy**: Azure AI Foundry / Gemini — complex reasoning, architecture
- **Light**: Gemini / Ollama — utility tasks, reviews, audits
- **Local**: Ollama (qwen3:4b tool-calling, deepseek-coder-v2:16b analysis, gemma4:e2b safety)

### Safety Pipeline (5 tiers)
All PowerShell commands pass through:
1. **Result cache** — 30s TTL, SHA-256 keyed (instant replay for reads)
2. **KAN neural scoring** — 24 features, trained model, <1ms
3. **Dangerous command blocklist** — hard-block destructive ops only
4. **Path safety** — enforces `LOOM_ALLOWED_ROOT=D:\Projects`
5. **Gemma LLM review** — elevated commands only, **fails open** if Ollama offline

### Session Pool
3 pre-warmed named-pipe PowerShell sessions (~5ms round-trip). Read-only commands use result cache. Parallel batch execution for multiple reads.

---

## 24 Cloud Agents Available

| Agent | Tier | Use For |
|-------|------|---------|
| `architect` | Heavy | System design, technology selection |
| `coder` | Heavy | Feature implementation (writes files in cloud mode) |
| `debugger` | Heavy | Root cause analysis |
| `refactor` | Heavy | Code restructuring |
| `security_engineer` | Heavy | Vulnerability assessment, OWASP |
| `api_designer` | Heavy | REST/GraphQL contracts |
| `code_reviewer` | Light | PR review, bug detection |
| `tester` | Light | Unit/integration tests, TDD |
| `technical_writer` | Light | Docs, READMEs, ADRs |
| `devops_engineer` | Light | CI/CD, Docker, Terraform |
| `performance_engineer` | Light | Profiling, bottlenecks |
| `data_engineer` | Light | Schema design, query optimization |
| `ux_designer` | Light | User flows, wireframes |
| `product_manager` | Light | PRDs, user stories |
| + 10 more specialists | Light | SEO, a11y, i18n, compliance, analytics, etc. |

---

## Conventions
- Agent names use kebab-case in Claude Code (e.g., `loom:coder`, `loom:code-reviewer`)
- Session state in `docs/loom/state/`, plans in `docs/loom/plans/`
- All file writes go through `Write`/`Edit` tools or PSKit — never shell redirection
- The coder agent in cloud mode outputs code blocks with `### \`path\`` headers — Loom writes them automatically
