# Changelog

All notable changes to Loom will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Silk.1.2] - 2026-04-07

### Fixed
- Cloud agent pipeline now writes files from code blocks in responses
- LiteLLM routing fixed — Azure DeepSeek-V3.2 and Cohere responding in ~1s
- qwen3 thinking mode disabled — 30-90s savings per LLM call
- Model kept hot in VRAM — eliminates 2-3s reload per call
- Timeouts reduced from 120s to 30-45s for fast failure
- Text-to-tool fallback when local models describe instead of calling tools
- PSKit server.py _parse() now extracts JSON from PS output field
- Memory engine graceful degradation — Neo4j/LiteLLM missing never crashes
- start-swarm.py loads .env dynamically from multiple search paths

### Added
- PSKit MCP extracted as standalone package (github.com/Nickalus12/pskit)
- 38 PSKit tools with structured output and tool annotations
- KAN model trained — 24 features, [24,12,6,1] architecture, 89.7% accuracy
- deploy and optimize plan types routing to devops_engineer and performance_engineer
- pskit doctor, pskit audit CLI commands with Rich streaming output
- CLAUDE.md comprehensive rewrite with full PSKit + Loom tool reference
- PSKit-aware hooks — prompt guards on delete_file, git_push, run_command
- Cloud coder file output format injected into orchestrator prompts

### Performance
- Azure cloud agents: ~1s response (DeepSeek-V3.2, Cohere via LiteLLM)
- Local qwen3:4b: ~1.5s with thinking disabled (was 5-90s)
- Full 5-phase cloud craft: ~15-30s (was 5-10 minutes)

## [1.5.0] - 2026-04-01

### Added

- **`get_skill_content` MCP tool** â€” Reads delegation protocols, templates, and reference documents by identifier via MCP, bypassing workspace sandbox restrictions. Used by the orchestrate command to load non-skill resources (methodology skills are loaded via `activate_skill`).
- **`references/orchestration-steps.md`** â€” Shared numbered-step sequence (40 steps with inline HARD-GATEs) loaded by both Gemini CLI and Claude Code orchestrate commands as the sole procedural authority.
- **`AGENT_CAPABILITIES` tier map** in `lib/core/agent-registry.js` â€” Classifies all 22 agents into `read_only`, `read_shell`, `read_write`, or `full` capability tiers. Exports `getAgentCapability()` and `canCreateFiles()`.
- **`agent_capability_mismatch` validation rule** in `validate_plan` â€” Server-side enforcement that read-only agents cannot be assigned to file-creating phases. Emits error violations for explicit file lists, warnings for creation-signal phase names.
- **Claude Code plugin** â€” Full dual-runtime support. Same 22 agents, 7 methodology skills (plus 12 command entry-point wrappers), 12 commands, lifecycle hooks, and MCP state management now available on Claude Code via the `claude/` subdirectory
- **Claude Code MCP auto-registration** (`claude/.mcp.json`) â€” MCP server discovered automatically when the plugin is loaded
- **MCP tool name mapping** â€” Orchestrator commands include mapping tables translating bare tool names (e.g., `initialize_workspace`) to Claude Code's prefixed names (`mcp__plugin_loom_loom__initialize_workspace`)
- **Agent name mapping** â€” Orchestrator commands include mapping for Claude Code's `loom:` agent prefix (e.g., `loom:coder`, `loom:code-reviewer`)
- **Claude Code hook adapter** (`claude/scripts/hook-adapter.js`) â€” Normalizes Claude Code's PreToolUse/SessionStart/SessionEnd hook contract to Loom's internal format
- **Policy enforcer** (`claude/scripts/policy-enforcer.js`) â€” Blocks destructive shell commands via Claude Code's PreToolUse hook on Bash tool calls
- **Library drift detection** (`scripts/check-claude-lib-drift.sh`) â€” CI script that validates shared `lib/` files haven't diverged between Gemini and Claude runtimes

### Changed

- **Orchestrate command restructured to numbered-step backbone** â€” `commands/loom/orchestrate.toml` is now a thin runtime preamble (~28 lines) that loads `orchestration-steps.md`. The previous 347-line inlined protocol with prose instruction sections has been replaced. Same change applied to `claude/commands/orchestrate.md` (~773 lines â†’ ~214 lines).
- **Design-dialogue protocol moved** from inlined in orchestrate command to on-demand loading via `activate_skill` (Gemini) or `Read` tool (Claude).
- **Template and reference loading deferred to consumption points** â€” `design-document`, `implementation-plan`, and `session-state` templates are no longer loaded at classification time; each is loaded at the step where it's consumed (steps 13, 15, 20).
- **`GEMINI.md` inline workflow content removed** â€” Express Workflow, Standard Workflow Phase 1-4, Task Complexity Classification, and Workflow Mode Selection sections replaced by pointer to `orchestration-steps.md`.
- **Express Flow state persistence** â€” Added step 5 (`transition_phase`) between coder delegation and code review to persist file manifests and downstream context before the review runs. Previously, state was only updated after the review.
- **Express Flow delegation enforcement** â€” Added HARD-GATE blocks preventing the orchestrator from editing code directly after code review findings. Fixes must be re-delegated to the implementing agent.
- **Express Flow brief presentation** â€” Split into two explicit sub-steps (2a: output brief as text, 2b: short approval prompt) with HARD-GATE preventing brief content from being stuffed into AskUserQuestion/ask_user
- **`create_session` field name** â€” Express Flow instructions now explicitly require `agent` (singular string) in phase objects, not `agents` (plural array which was silently ignored by the MCP server)
- **Delegation headers** â€” Added `Batch: single` to Express Flow delegation headers to match the delegation skill's required header set
- **Environment variable fallbacks** â€” `lib/config/setting-resolver.js` checks `CLAUDE_PLUGIN_ROOT` as fallback for `LOOM_EXTENSION_PATH`; `lib/core/project-root-resolver.js` checks `CLAUDE_PROJECT_DIR` as fallback for `LOOM_WORKSPACE_PATH`. Harmless no-op under Gemini CLI.

### Security

- **`validateContainment()` in `session-state.js`** â€” Absolute `state_dir` paths must resolve within the project root; rejects paths outside the cwd boundary. Applied to both `resolveStateDirPath` and `ensureWorkspace`.
- **`ensureBaseDir()` in `hook-state.js`** â€” Validates hook state base directory is not a symlink before creating session subdirectories. Temp directory naming changed from predictable `/tmp/loom-hooks` to per-user `loom-hooks-${uid}`.
- **Policy enforcer full-command parsing** â€” `splitCommands()` and `extractSubshells()` in `policy-enforcer.js` decompose commands on `;`, `&&`, `||`, `|`, and `$()` boundaries before checking deny rules against each segment. Prefix matching trims leading whitespace. Error handler changed from fail-open to fail-closed.
- **MCP error message path stripping** â€” Error handler in both MCP bundles replaces absolute filesystem paths with `[path]` before returning to the client. `get-skill-content.js` returns `err.code` instead of `err.message`.
- **`readBoundedStdin()` in hook adapters** â€” 1MB `MAX_STDIN_BYTES` limit applied to all hook entry scripts (7 scripts across both runtimes), `stdin-reader.js`, and `policy-enforcer.js`.
- **`ensureWorkspace` create-then-verify ordering** â€” Directory is created first, then verified via `lstatSync` that it is not a symlink, replacing the previous check-then-create ordering.
- **Explicit file permissions in `atomicWriteSync`** â€” Directories created with mode `0o700`, files with mode `0o600`. Same modes applied in `ensureWorkspace` and `ensureSessionDir`.
- **Session state `.gitignore`** â€” `docs/loom/state/` added to project `.gitignore`. `ensureWorkspace` auto-creates a `.gitignore` inside the state directory excluding `active-session.md` and `archive/`.

### Fixed

- **Skill files now accessible in all modes** (normal, Plan Mode, auto-edit) via `get_skill_content` MCP tool â€” replaces broken `read_file` â†’ `run_shell_command cat` fallback chain that failed due to workspace sandbox + Plan Mode policy restrictions.
- **Agent dispatch enforcement** â€” Delegation rules now require calling agents by registered tool name, preventing fallback to the built-in `generalist` tool which ignores agent frontmatter (methodology, temperature, tool restrictions, turn limits).
- **Express workflow `transition_phase` enforcement** â€” HARD-GATE ensures session state records all delivered files after agent execution.

## [1.4.0] - 2026-03-19

### Added

- **10 new specialist agents** â€” `seo_specialist`, `copywriter`, `content_strategist`, `ux_designer`, `accessibility_specialist`, `product_manager`, `analytics_engineer`, `i18n_specialist`, `design_system_engineer`, `compliance_reviewer`; roster expanded from 12 to 22
- **MCP server** (`mcp/loom-server.js`) â€” Bundled Model Context Protocol server registered via `mcpServers` in `gemini-extension.json` with 9 tools at launch: `initialize_workspace`, `assess_task_complexity`, `validate_plan`, `create_session`, `get_session_status`, `update_session`, `transition_phase`, `archive_session`, `resolve_settings` (10th tool `get_skill_content` added in v1.5.0)
- **Express workflow** â€” Streamlined inline flow for `simple` tasks: 1-2 clarifying questions, combined design+plan structured brief, single-agent delegation, code review, and archival without skill activations or execution-mode gating
- **Task complexity classification** â€” Three-tier system (`simple`, `medium`, `complex`) gating workflow mode selection (Express vs Standard), design depth defaults, domain analysis breadth, question coverage, and phase count limits
- **8-domain analysis** â€” Pre-planning domain sweep across Engineering, Product, Design, Content, SEO, Compliance, Internationalization, and Analytics; scaled by task complexity to identify specialist involvement
- **Design depth gate** â€” Three-tier depth selector (`Quick`, `Standard`, `Deep`) in design-dialogue controlling reasoning richness: assumption surfacing, decision matrices, rationale annotations, and requirement traceability; orthogonal to task complexity
- **3 standalone commands** â€” `/loom:a11y-audit` (WCAG compliance), `/loom:compliance-check` (GDPR/CCPA/regulatory), `/loom:seo-audit` (technical SEO assessment)
- **Policy engine rules** (`policies/loom.toml`) â€” Extension-tier deny/ask guardrails: blocks `rm -rf`, `git reset --hard`, `git clean`, and heredoc shell writes; prompts on `tee` and shell redirection operators
- **Hook adapter layer** (`hooks/hook-adapter.js`) â€” Normalizes Gemini stdin JSON to internal context contract and formats responses for stdout, decoupling hook I/O from business logic
- **Runtime-agnostic hook logic** â€” Extracted core hook behavior into `lib/hooks/` modules (`before-agent-logic.js`, `after-agent-logic.js`, `session-start-logic.js`, `session-end-logic.js`) separate from I/O handling
- **`scripts/read-setting.js`** â€” CLI utility to resolve a single Loom setting using script-accurate precedence
- **Architecture reference** (`references/architecture.md`) â€” Compact reference for agent roster, state contract, session lifecycle, execution modes, and delegation contract; read by commands at startup
- **`ARCHITECTURE.md`** and **`OVERVIEW.md`** â€” Top-level project documentation for architecture deep-dive and quick-start overview
- **Context budget guidance** â€” GEMINI.md section on minimizing skill activations, leveraging delegation for context relief, and preferring compact MCP responses over full state reads
- **`codebase_investigator` integration** â€” Design-dialogue and implementation-planning skills call the built-in investigator for repo grounding before proposing approaches or decomposing phases
- **Design document enrichments** â€” Decision matrix template (Standard/Deep), rationale annotations, per-decision alternatives (Deep), requirement traceability tags (Deep), `design_depth` and `task_complexity` frontmatter fields, numbered requirement IDs (`REQ-N`)
- **Session state fields** â€” `workflow_mode`, `execution_backend`, `current_batch`, and `task_complexity` added to session state template

### Changed

- **`src/lib/` flattened to `lib/`** â€” All shared modules relocated from `src/lib/` to `lib/`; scripts, hooks, and internal imports updated to new paths
- **Default state directory** â€” `LOOM_STATE_DIR` default changed from `.gemini` to `docs/loom`; updated in `gemini-extension.json`, GEMINI.md, session-state module, and all command/skill references
- **Hook architecture** â€” Hooks (`before-agent.js`, `after-agent.js`, `session-start.js`, `session-end.js`) refactored from `defineHook`/`hook-facade` pattern to direct stdin/stdout with `hook-adapter.js` normalization and separated logic modules
- **Agent registry** â€” `KNOWN_AGENTS` array updated from 12 to 22 entries; `detectAgentFromPrompt` now checks agent header (`agent: <name>`) before env var and prompt pattern matching
- **Orchestrate command** â€” Expanded from 14-line protocol summary to full orchestrator template with hard gates, first-turn contract, required question order, design/plan approval gates, execution mode gate, delegation requirements, Express workflow routing, and recovery rules
- **Execute command** â€” Added inline Loom Execute section with workspace initialization, execution-mode gate resolution, and parallel/sequential dispatch constraints
- **Resume command** â€” Added Express resume detection (`workflow_mode: "express"`), anti-delegation guards for token/status queries, and inline Loom Resume section with constraint rules
- **Archive command** â€” Rewritten to use `get_session_status` and `archive_session` MCP tools instead of direct file manipulation
- **Status and resume commands** â€” Added anti-delegation guards preventing token/accounting questions from being routed to `cli_help` or research agents
- **All standalone audit commands** (`debug`, `perf-check`, `security-audit`, `review`) â€” Added delegation skill activation for protocol injection
- **Delegation skill** â€” Protocol injection paths updated to `${extensionPath}/skills/delegation/protocols/`; added missing context fallback and downstream consumer declaration patterns
- **Design-dialogue skill** â€” Added Standard-workflow-only gate, Express bypass, repository grounding protocol with `codebase_investigator`, depth gate with first-turn contract, and complexity-aware section/question scaling
- **Implementation-planning skill** â€” Added Standard-workflow-only gate, codebase grounding protocol, `task_complexity` propagation from design document to plan frontmatter
- **Session-management skill** â€” Added MCP-first state access protocol (preferred > fallback > legacy), Express workflow session creation, and `workflow_mode` awareness
- **Execution skill** â€” Added Standard-workflow-only scope note and Express bypass
- **GEMINI.md orchestrator context** â€” Expanded with workflow routing, complexity classification, Express workflow definition, domain analysis matrix, context budget section, MCP tool preference for state operations, `codebase_investigator` guidance, and 22-agent roster
- **Package identity** â€” Renamed from `gemini-loom` to `@loom-orchestrator/gemini-extension`; added `files` manifest for publishable assets
- **License** â€” Changed from MIT to Apache-2.0
- **`env-file-parser`** â€” Added multi-line quoted value support for values spanning multiple lines within double quotes
- **`session-state` module** â€” Added `resolveStateDirPath` helper; `ensureWorkspace` accepts absolute `stateDir` paths; removed `parallel` subdirectory from workspace scaffold
- **`atomic-write`** â€” Added monotonic counter to temp file names to prevent PID-only collisions
- **`project-root-resolver`** â€” Added `LOOM_WORKSPACE_PATH` env var check before git fallback
- **`hook-state`** â€” Added `LOOM_HOOKS_DIR` env var override for hook state base directory
- **`setting-resolver`** â€” Removed `os.homedir()` fallback for extension path; requires `LOOM_EXTENSION_PATH` env var when resolving extension `.env`
- **`refactor` agent** â€” Added `run_shell_command` to tool set
- **Implementation plan template** â€” Updated parallel dispatch note from `--approval-mode=yolo` reference to native subagent framing; added `task_complexity` frontmatter
- **`USAGE.md`** and **`README.md`** â€” Rewrites reflecting 22-agent roster, Express workflow, MCP tools, policy engine, and updated configuration

### Removed

- **`src/lib/` directory** â€” All modules relocated to `lib/`; removed `src/lib/config/dispatch-config-resolver.js`, `src/lib/core/integer-parser.js`, `src/lib/dispatch/concurrency-limiter.js`, `src/lib/dispatch/process-runner.js`, `src/lib/hooks/hook-facade.js`, `src/lib/hooks/hook-response.js`
- **`scripts/parallel-dispatch.js`** â€” Script-based parallel dispatch replaced by native subagent calls in v1.3.0; module fully removed
- **`scripts/sync-version.js`** â€” Version sync script between `package.json` and `gemini-extension.json`; replaced by `files` manifest in `package.json`
- **Entire test suite** â€” Removed `tests/` directory: 19 unit tests, 8 integration tests, test runner (`run-all.js`), and helpers; tests were coupled to removed `src/lib/` modules and dispatch infrastructure
- **CI workflow** â€” Removed `.github/workflows/ci.yml` (cross-platform test matrix on `ubuntu-latest` and `windows-latest`)
- **Architecture docs directory** â€” Removed `docs/architecture/` (5 files: `agent-system.md`, `comprehensive-map.md`, `skills-and-commands.md`, `state-management-and-scripts.md`, `system-overview.md`); replaced by `ARCHITECTURE.md`, `OVERVIEW.md`, and `references/architecture.md`

## [1.3.0] - 2026-03-07

### Added

- **Plan-based execution mode recommendation** â€” When `LOOM_EXECUTION_MODE=ask` (default), the orchestrator analyzes the implementation plan's dependency graph and presents a data-driven parallel vs sequential recommendation via `ask_user`
- **Execution mode gate enforcement** â€” `<HARD-GATE>` language in the execution skill ensures the mode prompt cannot be skipped; safety fallback stops delegation if `execution_mode` is missing from session state
- **Mandatory gate references across all entry points** â€” `orchestrate`, `execute`, and `resume` command prompts all enforce the execution mode gate before any delegation proceeds

### Changed

- **Native-only parallel execution** â€” Replaced script-based parallel dispatch (`parallel-dispatch.js`, `process-runner.js`, `concurrency-limiter.js`) with Gemini CLI's native subagent scheduler; parallel batches are now contiguous agent tool calls in a single turn
- **Simplified extension settings** â€” Removed script-dispatch-only settings (`LOOM_DEFAULT_MODEL`, `LOOM_WRITER_MODEL`, `LOOM_DEFAULT_TEMPERATURE`, `LOOM_MAX_TURNS`, `LOOM_AGENT_TIMEOUT`, `LOOM_STAGGER_DELAY`, `LOOM_GEMINI_EXTRA_ARGS`); native tuning uses agent frontmatter and Gemini CLI `agents.overrides`
- **`LOOM_MAX_CONCURRENT` redefined** â€” Now controls native parallel batch chunk size (how many subagent calls per turn) instead of subprocess concurrency limit
- **Execution skill rewrite** â€” Structured 5-step mode gate protocol with plan analysis, `ask_user` call format, and recommendation logic covering all parallelization percentages
- **GEMINI.md orchestrator context** â€” Updated Phase 3 description and Execution Mode Protocol section to reference the execution skill as the authoritative gate source

### Removed

- **Script-based dispatch backend** â€” Removed `scripts/parallel-dispatch.js`, `src/lib/dispatch/process-runner.js`, `src/lib/dispatch/concurrency-limiter.js`, `src/lib/config/dispatch-config-resolver.js`, and all associated tests
- **Dispatch-only extension settings** â€” Removed 7 settings from `gemini-extension.json` that only applied to the script dispatch backend

## [1.2.1] - 2026-02-19

### Added

- **Expanded test coverage** â€” Added 91 unit tests and migrated integration tests to Node.js to validate hooks, dispatch, state handling, config resolution, and timeout behavior
- **Cross-platform PR CI matrix** â€” Added GitHub Actions workflow (`.github/workflows/ci.yml`) running `node tests/run-all.js` on both `ubuntu-latest` and `windows-latest`

### Changed

- **Cross-platform runtime migration** â€” Replaced bash/Python hook and script execution paths with Node.js entry points for Windows PowerShell compatibility
- **Layered module architecture** â€” Reorganized shared runtime into focused modules under `src/lib/core`, `src/lib/config`, `src/lib/hooks`, `src/lib/state`, and `src/lib/dispatch`
- **Hook lifecycle and context output** â€” Registered SessionStart/SessionEnd hooks and standardized hook response context metadata (`hookEventName` + `additionalContext`) via shared hook helpers
- **Dispatch and settings behavior** â€” Moved operational logs to stderr, standardized env resolution/parsing, strengthened integer/path validation, and enforced canonical snake_case agent naming with hyphen alias normalization
- **Windows shell behavior** â€” Made shell mode opt-in to avoid `cmd.exe` argument mangling in Windows terminal flows
- **Documentation alignment** â€” Updated project documentation to align with current codebase behavior, naming conventions, and workflows

### Fixed

- **Windows stability fixes** â€” Resolved Windows-specific dispatch/session regressions and aligned integration harness behavior with `windows-latest` runner semantics
- **AfterAgent stale-state handling** â€” Cleared active-agent state on deny responses to prevent sticky handoff validation across unrelated turns
- **Process safety hardening** â€” Added PID guards, timeout validation, descriptor cleanup safeguards, and safer stale hook-state handling

### Removed

- **Legacy shell runtime paths** â€” Removed `.sh` hooks/scripts and bash/Python runtime dependencies in favor of Node.js equivalents

## [1.2.0] - 2026-02-19

### Added

- **Hooks-based lifecycle middleware** â€” BeforeAgent and AfterAgent hooks with shared shell library (`hooks/lib/common.sh`), `safe_main` wrapper for guaranteed JSON output, and advisory error handling
- **Agent tracking** â€” BeforeAgent/AfterAgent hooks track active agent identity via `/tmp/loom-hooks/<session-id>/active-agent`; lazy state creation on first write, stale-pruned during BeforeAgent
- **Handoff report validation** â€” AfterAgent hook validates delegated agent output includes `Task Report` and `Downstream Context`; skips TechLead and non-delegation turns; requests one retry on malformed output
- **Active session gating** â€” `has_active_loom_session` helper allows hooks to skip initialization when no Loom session exists in the workspace
- **Final code review quality gate** â€” Phase 4 completion requires a `code_reviewer` pass on non-documentation file changes before archival; blocks on unresolved Critical/Major findings with remediation loop
- **14 extension settings** â€” All `LOOM_*` env vars declared in `gemini-extension.json`: `DEFAULT_MODEL`, `WRITER_MODEL`, `DEFAULT_TEMPERATURE`, `MAX_TURNS`, `AGENT_TIMEOUT`, `DISABLED_AGENTS`, `MAX_RETRIES`, `AUTO_ARCHIVE`, `VALIDATION_STRICTNESS`, `STATE_DIR`, `MAX_CONCURRENT`, `STAGGER_DELAY`, `GEMINI_EXTRA_ARGS`, `EXECUTION_MODE`
- **`LOOM_WRITER_MODEL`** (restored) â€” Per-agent model override for technical_writer in parallel dispatch
- **`LOOM_GEMINI_EXTRA_ARGS`** â€” Space-separated Gemini CLI flags forwarded to each parallel dispatch process
- **`LOOM_STATE_DIR`** (restored) â€” Configurable state directory with `extensionPath` resolution and env/workspace/extension/default precedence
- **`read-active-session.sh`** â€” Script to resolve the active session file path respecting `LOOM_STATE_DIR`
- **macOS timeout fallback** â€” Cancel-file-based watchdog with SIGTERM/SIGKILL for systems without GNU `timeout`
- **Shell helper library** (`hooks/lib/common.sh`) â€” `read_stdin`, `json_get`, `json_get_bool`, `respond_allow`, `respond_block`, `log_hook`, `validate_session_id`, `resolve_active_session_path`, `has_active_loom_session`, `prune_stale_hook_state`
- **Built-in tools expanded** â€” `read_many_files`, `write_todos`, `ask_user`, and web tools added across agents
- **`activate_skill` guidance** â€” Agents and skills document how to activate skills with user consent behavior
- `enter_plan_mode`/`exit_plan_mode` for read-only Phase 1-2 with fallback when Plan Mode unavailable
- `save_memory` for cross-session knowledge persistence at Phase 4
- `{{args}}` parameter forwarding in status and resume commands
- **Integration test suite** â€” `tests/run-all.sh` covering all hooks, parallel dispatch (args forwarding, config fallback, exit-code propagation), and active-session resolution (8 test files)
- **`CLAUDE.md`** â€” Project-level contributor instructions

### Changed

- **Lazy hook lifecycle** â€” SessionStart and SessionEnd removed from `hooks.json` registration; hook state created lazily by BeforeAgent and stale-pruned inline (2-hour threshold)
- All 12 agents: `model` field omitted (inherits main session model), canonical `grep_search` tool name, unified Handoff Report output contract
- `parallel-dispatch.sh`: sets `LOOM_CURRENT_AGENT` per spawned process, forwards `LOOM_GEMINI_EXTRA_ARGS`, warns on deprecated `--allowed-tools` flag
- Commands moved from `commands/loom.*.toml` to `commands/loom/*.toml` (directory-based namespace)
- Protocols moved from `protocols/` to `skills/delegation/protocols/` (co-located with delegation skill)
- `delegation` skill: prompt-based enforcement documented as defense-in-depth (native frontmatter is primary gate)
- `code-review` skill: updated for orchestration quality gates (post-phase checks and final completion gate); includes current file contents when diff unavailable
- `execution` skill: documents hook lifecycle, adds final code review gate section, includes review status in completion summary
- `session-management` skill: documents lazy hook state lifecycle with BeforeAgent creation and stale pruning
- `design-dialogue` skill: adds Plan Mode handling
- `session-start.sh`: checks for active Loom session before initializing state
- `session-end.sh`: simplified to minimal cleanup without logging
- Architecture docs rewritten for accuracy against Gemini CLI specification
- Deprecated `--yolo` and `-p` flags replaced with `--approval-mode=yolo` and positional args in dispatch
- Session state template: added `task` field, reconciled `execution_mode`

### Fixed

- Hook advisory behavior: `safe_main` wrapper guarantees JSON output on all code paths; errors emit `{}` instead of crashing
- Hook matchers removed (were too restrictive for SessionStart/SessionEnd)
- AfterAgent validates on retry without re-issuing denial
- `ask_user` parameter schema corrected in design-dialogue skill
- Plan Mode write paths corrected (`exit_plan_mode` path)
- Delegation paths corrected in skills to use `activate_skill` resources
- State template synced with runtime expectations
- `read_file` ignore enforcement and state access asymmetry clarified in skills
- Agent roster corrections: `run_shell_command` removed from refactor, `get_internal_docs` removed from devops_engineer and technical_writer
- macOS timeout support in parallel dispatch

### Removed

- `before-tool.sh`, `before-tool-selection.sh`, `after-tool.sh` hooks â€” native frontmatter `tools:` handles tool enforcement
- `BeforeModel` hook â€” Gemini CLI discards model field from hook output
- `permissions.json` and `generate-permissions.sh` â€” redundant with native frontmatter enforcement
- `validate-agent-permissions.sh` â€” validated against the removed permissions manifest
- `display_name` field from all agent frontmatter (undocumented by Gemini CLI)
- `excludeTools` patterns â€” non-functional; use Policy Engine instead
- `hookEventName` from hook output (not consumed by Gemini CLI)

## [1.1.1] - 2026-02-15

### Fixed

- Removed extension settings prompts from install â€” Gemini CLI doesn't support default values, so users were forced through 13 prompts on install. All settings now use orchestrator defaults and are configurable via environment variables.

### Changed

- README configuration section renamed from "Extension Settings" to "Environment Variables" with all 13 parameters documented

## [1.1.0] - 2026-02-15

### Added

- Extension settings with 13 configurable parameters via environment variables
- Loom branded dark theme with warm gold accents
- Shell-based parallel dispatch for concurrent subagent execution (`scripts/parallel-dispatch.sh`)
- Agent base protocol with pre-flight procedures and structured output formatting
- Settings references in delegation, execution, session-management, and validation skills
- TechLead orchestrator startup checks with settings resolution
- Filesystem safety protocol for delegated agents (`protocols/filesystem-safety-protocol.md`)
- Workspace bootstrap script for directory safety (`scripts/ensure-workspace.sh`)
- State file I/O scripts for atomic reads and writes (`scripts/read-state.sh`, `scripts/write-state.sh`)
- Agent name validation against `agents/` directory in parallel dispatch (`scripts/validate-agent-permissions.sh`)
- Concurrency cap (`max_concurrent`) and stagger delay (`stagger_delay_seconds`) settings for parallel dispatch
- Execution mode selection (`execution_mode`) in extension settings and session state template
- Workspace readiness startup check in orchestrator
- File-writing enforcement rules across agent base protocol, delegation prompts, and filesystem safety protocol
- Project root auto-injection into all parallel dispatch prompts
- Execution mode gate and state file access protocol in execution skill
- Execution profile requirement in implementation planning skill

### Fixed

- Hardened `parallel-dispatch.sh` against shell injection and edge cases
- Hardened scripts and commands against injection and path traversal attacks
- Stagger delay default changed from 0 to 5 seconds
- File writing rules enforced via `write_file` tool-only policy across all delegation prompts

### Changed

- Execution mode upgraded from sequential-only to PARALLEL (shell-based) as default strategy
- Delegation skill updated with agent name rules and absolute path safety net
- Filesystem safety protocol injected into all delegation prompts
- Session-management `mkdir` steps annotated as defense-in-depth fallbacks

## [1.0.0] - 2026-02-09

### Added

- TechLead orchestrator with 12 specialized subagents
- Guided design dialogue with structured requirements gathering
- Automated implementation planning with phase dependencies and parallelization
- Parallel execution of independent phases via subagent invocation
- Session persistence with YAML+Markdown state tracking
- Least-privilege security model per agent
- Standalone commands: `loom.orchestrate`, `loom.resume`, `loom.execute`
- Standalone commands: `loom.review`, `loom.debug`, `loom.security-audit`, `loom.perf-check`
- Session management: `loom.status`, `loom.archive`
- Design document, implementation plan, and session state templates
- Skill modules: code-review, delegation, design-dialogue, execution, implementation-planning, session-management, validation
