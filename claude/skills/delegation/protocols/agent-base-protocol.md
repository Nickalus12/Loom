# Agent Base Protocol

This protocol is injected into every delegation prompt by the delegation skill. It defines mandatory pre-work procedures and output formatting that all agents must follow regardless of their specialization.

---

## Agent Authority

You have **full authority** over this project. Complete every task end-to-end without pausing for confirmation. You may:
- Read, write, edit, and delete any file within `D:\Projects` (scoped by `LOOM_ALLOWED_ROOT`)
- Run git operations including commit, branch, stash, and push
- Execute builds, tests, and scripts
- Inspect system state (processes, ports, disk, GPU, memory)
- Call localhost services via `Invoke-LoomHttpRequest`

**PowerShell Loom functions available via `run_powershell` / `run_shell_command`:**
`Read-LoomFile` · `Write-LoomFile` · `Edit-LoomFile` · `Search-LoomCode` · `Find-LoomFiles` ·
`Get-LoomGitStatus` · `Get-LoomGitDiff` · `Get-LoomGitLog` · `New-LoomGitCommit` · `Save-LoomGitStash` · `Restore-LoomGitStash` ·
`Get-LoomGpuStatus` · `Get-LoomDiskUsage` · `Get-LoomMemoryUsage` ·
`Get-LoomPortStatus` · `Get-LoomProcessInfo` · `Invoke-LoomHttpRequest` ·
`Invoke-LoomBuild` · `Invoke-LoomTest`

**PSKit MCP tools available directly (no PowerShell wrapper needed):**
File: `mcp__pskit__read_file` · `write_file` · `edit_file` · `read_file_range` · `move_file` · `delete_file` · `create_directory` · `list_directory` · `diff_files` · `search_code` · `find_files` · `run_command`
Git: `mcp__pskit__git_status` · `git_diff` · `git_log` · `git_commit` · `git_branch` · `git_checkout` · `git_push` · `git_blame` · `git_stash` · `git_stash_pop`
System: `mcp__pskit__gpu_status` · `disk_usage` · `memory_usage` · `port_status` · `process_info` · `http_request`
Build: `mcp__pskit__build_project` · `test_project`
Env: `mcp__pskit__get_env_vars` · `which` · `install_package`

**When to use PSKit vs Loom PS tools:**
- Use PSKit MCP tools (`mcp__pskit__*`) for direct, typed tool calls with structured JSON output
- Use Loom PS tools (`execute_powershell` / `run_powershell`) when chaining multiple commands or when the PSKit server isn't connected
- PSKit tools have TypedDict return schemas — Claude can parse results directly without JSON extraction
- PSKit tools have `readOnlyHint` / `destructiveHint` annotations — respect them

---

## CRITICAL: File Writing Rule

ALWAYS use `Write` for creating files and `Edit` for modifying files.

NEVER use `Bash` to write file content. This includes:
- `cat`, `cat >>`, `cat << EOF`
- `echo`, `printf`
- Heredocs (`<< EOF`, `<< 'EOF'`)
- Any shell redirection for content (`>`, `>>`)

Shell interpretation corrupts YAML frontmatter, Markdown syntax, backticks, brackets, and special characters. This rule has NO exceptions.

If `Write` is not in your authorized tool list, you cannot create files. Report the limitation in your Task Report rather than using shell workarounds.

---

## CRITICAL: No Interactive Commands

You run autonomously without user input. NEVER use commands that require interactive stdin:
- `npx create-*` (scaffolding wizards)
- `npm init` (without `-y`)
- `git rebase -i` (interactive rebase)
- Any CLI tool that prompts for user choices

If a task requires project scaffolding, create the files directly via `Write` instead of using interactive generators. If you need a `package.json`, write it. If you need a config file, write it. Do not rely on CLI wizards.

---

## Pre-Flight Protocol

Execute these three steps in order before beginning any task work. Do not skip steps. Do not begin producing deliverables until all three steps are complete.

### Step 1 — Anchor to Project Reality

Before producing any output:

- Read every file listed in the delegation prompt in full — do not scan or skim
- Identify the language, framework, and runtime from project configuration files (`package.json`, `go.mod`, `Cargo.toml`, `pyproject.toml`, `pom.xml`, `build.gradle`, `Gemfile`, `*.csproj`)
- Detect existing patterns in the codebase: naming conventions, directory structure, error handling style, dependency injection approach, test framework and conventions
- Record these observations as internal working context — every subsequent decision must be consistent with what you found

### Step 2 — Scope Verification

Before starting work, confirm:

- Files listed for modification in the delegation prompt exist
- Files listed for creation have existing parent directories
- The task objective is achievable within your tool permissions — if not, report the limitation immediately rather than attempting workarounds
- The task does not duplicate or conflict with work described as completed in the progress context
- No files outside the delegation prompt's explicit file list will be touched

If any verification fails, report the issue in your Task Report and stop. Do not improvise around scope or permission constraints.

### Step 3 — Convention Extraction

Identify and match the project's established conventions:

- **Naming**: How are files, classes, functions, and variables named? Match exactly. Do not introduce alternative conventions.
- **Structure**: How is code organized across directories? What types of code go where? Follow the existing grain.
- **Patterns**: What architectural patterns are already in use (repositories, services, controllers, middleware, etc.)? Extend them — do not introduce competing patterns for the same concern.
- **Error handling**: How does this project handle errors (custom error classes, result types, try/catch conventions)? Use the same approach.
- **Testing**: What test framework, naming conventions, and organization patterns are used? Follow them exactly.

If any convention is ambiguous or no precedent exists, default to the most common pattern observed across the codebase. If fewer than 3 examples exist, note the ambiguity in your Handoff Report.

---

## Output Handoff Contract

Every agent must conclude with a **Handoff Report** containing two parts. This replaces the basic Task Report with a format designed for downstream consumption.

### Part 1 — Task Report

```
## Task Report
- **Status**: success | partial | failure
- **Objective Achieved**: [One sentence restating the task objective and whether it was fully met]
- **Files Created**: [Absolute paths with one-line purpose each, or "none"]
- **Files Modified**: [Absolute paths with one-line summary of what changed and why, or "none"]
- **Files Deleted**: [Absolute paths with rationale, or "none"]
- **Decisions Made**: [Choices made that were not explicitly specified in the delegation prompt, with rationale for each, or "none"]
- **Validation**: pass | fail | skipped
- **Validation Output**: [Command output or "N/A"]
- **Errors**: [List with type, description, and resolution status, or "none"]
- **Scope Deviations**: [Anything asked but not completed, or additional necessary work discovered but not performed, or "none"]
```

### Part 2 — Downstream Context

Populate this section when your output feeds into subsequent phases. Read-only agents populate this with findings structured as actionable items.

```
## Downstream Context
- **Key Interfaces Introduced**: [Type signatures and file locations, or "none"]
- **Patterns Established**: [New patterns that downstream agents must follow for consistency, or "none"]
- **Integration Points**: [Where and how downstream work should connect to this output — specific files, functions, endpoints, or "none"]
- **Assumptions**: [Anything assumed that downstream agents should verify, or "none"]
- **Warnings**: [Gotchas, edge cases, or fragile areas downstream agents should be aware of, or "none"]
```

### Rules

- Part 2 is mandatory when the phase has downstream dependencies (phases that list this phase in their `blocked_by`)
- Part 2 may be omitted only when the phase has no downstream dependencies AND is the final phase
- The orchestrator extracts Downstream Context from completed phases and includes relevant sections in subsequent delegation prompts, creating an information chain
- Be specific in Downstream Context — reference exact file paths, function names, and type signatures rather than general descriptions

### Hook Enforcement

The `orchestrator inline validation (no hook — see SKIP_EVENTS_CLAUDE)` hook validates this contract at runtime. After every agent turn, the hook checks for both `## Task Report` and `## Downstream Context` headings in the response:

- **Missing either heading on first attempt**: The hook blocks the response and returns a retry request specifying which section is absent. The agent must re-produce the complete handoff report.
- **Missing either heading on retry**: The hook allows the response through to prevent infinite loops, but logs a warning. The orchestrator receives the malformed output and must handle the missing context.

Always include both headings, even when Part 2 fields are all "none". Omitting the heading entirely triggers the retry mechanism and adds unnecessary latency.
