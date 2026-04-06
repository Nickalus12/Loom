---
title: "Local Gemma 4 E2B Integration Implementation Plan"
design_ref: "docs/maestro/plans/2026-04-05-local-gemma4-integration-design.md"
created: "2026-04-05T00:00:00.000Z"
status: "approved"
total_phases: 8
estimated_files: 10
task_complexity: "complex"
---

# Local Gemma 4 E2B Integration Implementation Plan

## Plan Overview

- **Total phases**: 8
- **Agents involved**: coder, technical-writer, tester, code-reviewer
- **Estimated effort**: Core module + server integration + memory enhancement + config + tests + review

## Dependency Graph

```
Phase 1 (depth 0)
    |
    ├── Phase 2 ─┐
    ├── Phase 3  ├── depth 1 (parallel batch)
    ├── Phase 4  │
    ├── Phase 5  │
    └── Phase 6 ─┘
           |
       Phase 7 (depth 2)
           |
       Phase 8 (depth 3)
```

## Execution Strategy

| Stage | Phases | Execution | Agent Count | Notes |
|-------|--------|-----------|-------------|-------|
| 1 | Phase 1 | Sequential | 1 (coder) | Foundation |
| 2 | Phases 2-6 | Parallel | 4 (coder x3, technical-writer x1) | Non-overlapping files |
| 3 | Phase 7 | Sequential | 1 (tester) | Depends on phases 2, 3 |
| 4 | Phase 8 | Sequential | 1 (code-reviewer) | Final review gate |

## Phase 1: LocalInferenceEngine Core Module

### Objective
Create the core LocalInferenceEngine class managing Ollama connectivity, background worker, on-demand handlers, and confidence tagging.

### Agent: coder
### Parallel: No

### Files to Create
- `src/loom/local_inference.py` — LocalInferenceEngine with Ollama client, background worker, on-demand methods, confidence tagger, system prompts, env var configuration

### Implementation Details

**Ollama Client**: `openai.AsyncOpenAI(base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") + "/v1", api_key="ollama")`

**Background Worker**: asyncio.Task with `_worker_loop()` polling `git diff --name-only` every LOOM_BACKGROUND_INTERVAL seconds. Track `_last_seen_commit`. Skip files >50KB. Write findings via `memory.add_local_insight()`.

**Confidence Tagger**: Keyword heuristic — hedging → low, conditional → medium, direct → high.

**Graceful Degradation**: try/except on all Ollama calls. Exponential backoff for background worker (30s→300s max).

**Env vars**: OLLAMA_BASE_URL, LOOM_LOCAL_ANALYSIS_MODEL, LOOM_LOCAL_CREATIVE_MODEL, LOOM_BACKGROUND_INTERVAL

### Validation
- `python -c "from loom.local_inference import LocalInferenceEngine"`

### Dependencies
- Blocked by: None
- Blocks: 2, 3, 4, 5, 6

---

## Phase 2: MCP Server Integration

### Objective
Wire 4 new MCP tools into server.py with lazy initialization.

### Agent: coder
### Parallel: Yes

### Files to Modify
- `src/loom/server.py` — Add `_local_engine` global, `_get_local_engine()` lazy init, 4 @mcp.tool() functions: local_brainstorm, local_review, local_debug, local_status. Auto-start background worker on first call.

### Validation
- `python -c "from loom.server import mcp"`

### Dependencies
- Blocked by: 1
- Blocks: 7

---

## Phase 3: Memory Engine Enhancement

### Objective
Add local insight episode writing and enhance get_context_for_coder to surface local insights.

### Agent: coder
### Parallel: Yes

### Files to Modify
- `src/loom/memory_engine.py` — Add `add_local_insight()` method using `self.memory.add_episode()`. Enhance `get_context_for_coder()` to include `local_insights` key filtering by `source_description` prefix `local_e2b|`.

### Validation
- `python -c "from loom.memory_engine import LoomSwarmMemory"`

### Dependencies
- Blocked by: 1
- Blocks: 7

---

## Phase 4: LiteLLM Local Tier Config

### Objective
Add local/* model tier to LiteLLM routing to Ollama.

### Agent: coder
### Parallel: Yes

### Files to Modify
- `litellm_config.yaml` — Add `local/*` model entry with `ollama/gemma4-e2b` and `api_base: http://localhost:11434`

### Validation
- YAML syntax valid, existing tiers unchanged

### Dependencies
- Blocked by: 1
- Blocks: 7

---

## Phase 5: Local Agent Definitions

### Objective
Create local-tier agent definitions and update registry.

### Agent: coder
### Parallel: Yes

### Files to Create
- `agents/local_analyst.md` — tier: local, temperature: 0.2, max_turns: 5
- `agents/local_creative.md` — tier: local, temperature: 0.7, max_turns: 5

### Files to Modify
- `src/loom/agent_registry.py` — Add LOCAL_AGENTS frozenset, handle "local" tier

### Validation
- Agent files parse via AgentRegistry, list_agents() includes new agents

### Dependencies
- Blocked by: 1
- Blocks: 7

---

## Phase 6: Deployment Config & Docs

### Objective
Update deployment configuration for Docker and native Ollama.

### Agent: technical-writer
### Parallel: Yes

### Files to Modify
- `docker-compose.yml` — Add Ollama service with NVIDIA GPU runtime
- `.env.example` — Add OLLAMA_BASE_URL, LOOM_LOCAL_ANALYSIS_MODEL, LOOM_LOCAL_CREATIVE_MODEL, LOOM_BACKGROUND_INTERVAL

### Validation
- `docker-compose config` passes

### Dependencies
- Blocked by: 1
- Blocks: 7

---

## Phase 7: Test Suite

### Objective
Create comprehensive tests for LocalInferenceEngine with mocked Ollama.

### Agent: tester
### Parallel: No

### Files to Create
- `tests/test_local_inference.py` — Tests: brainstorm response, review findings+confidence, debug suggestions, confidence tagger (high/medium/low), graceful degradation, worker lifecycle, poll changes, get_status

### Validation
- `python -m pytest tests/test_local_inference.py -v`

### Dependencies
- Blocked by: 2, 3
- Blocks: 8

---

## Phase 8: Final Code Review

### Objective
Review all changes for correctness, security, and consistency.

### Agent: code-reviewer
### Parallel: No

### Validation
- No Critical or Major findings

### Dependencies
- Blocked by: 7
- Blocks: None

---

## File Inventory

| # | File | Phase | Purpose |
|---|------|-------|---------|
| 1 | `src/loom/local_inference.py` | 1 | Core LocalInferenceEngine |
| 2 | `src/loom/server.py` | 2 | 4 new MCP tools |
| 3 | `src/loom/memory_engine.py` | 3 | Local insight support |
| 4 | `litellm_config.yaml` | 4 | local/* tier |
| 5 | `agents/local_analyst.md` | 5 | Analysis agent def |
| 6 | `agents/local_creative.md` | 5 | Creative agent def |
| 7 | `src/loom/agent_registry.py` | 5 | Local tier support |
| 8 | `docker-compose.yml` | 6 | Ollama service |
| 9 | `.env.example` | 6 | New env vars |
| 10 | `tests/test_local_inference.py` | 7 | Test suite |

## Risk Classification

| Phase | Risk | Rationale |
|-------|------|-----------|
| 1 | MEDIUM | Core module with async worker |
| 2 | LOW | Follows established pattern |
| 3 | LOW | Additive changes |
| 4 | LOW | Config only |
| 5 | LOW | Follows existing format |
| 6 | LOW | Docs and config |
| 7 | LOW | Test only |
| 8 | LOW | Read-only review |

## Execution Profile

```
Execution Profile:
- Total phases: 8
- Parallelizable phases: 5 (in 1 batch)
- Sequential-only phases: 3
- Estimated parallel wall time: ~15 minutes (4 batches)
- Estimated sequential wall time: ~35 minutes (8 serial phases)

Note: Native parallel execution currently runs agents in autonomous mode.
All tool calls are auto-approved without user confirmation.
```
