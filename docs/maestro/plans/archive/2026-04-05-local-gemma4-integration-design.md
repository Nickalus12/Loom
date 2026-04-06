---
title: "Local Gemma 4 E2B Integration"
created: "2026-04-05T00:00:00.000Z"
status: "approved"
authors: ["TechLead", "User"]
type: "design"
design_depth: "standard"
task_complexity: "complex"
---

# Local Gemma 4 E2B Integration Design Document

## Problem Statement

Loom's current architecture routes all agent inference through cloud APIs (Gemini, Azure) via LiteLLM proxy. This creates three gaps:

1. **Latency bottleneck for lightweight tasks**: Quick brainstorming, initial code review, and debug triage all pay full cloud API round-trip latency (500ms-2s+), even when the task only needs a fast, approximate answer.

2. **No continuous codebase awareness**: The system only analyzes code when explicitly invoked. There is no background process that continuously monitors file changes, mines patterns, or proactively identifies bugs — insights only enter the knowledge graph through manual `add_file_node` calls.

3. **Underutilized local GPU**: The user's RTX 3080 (10GB VRAM) sits idle during development while all inference routes to cloud. Open-source models like Gemma 4 E2B can run locally at near-zero marginal cost, providing fast feedback loops that complement cloud model reasoning.

**Goal**: Integrate 2x Gemma 4 E2B models running locally via Ollama as always-on sidecar assistants that provide (a) continuous background code analysis feeding insights into the Graphiti knowledge graph, and (b) on-demand fast inference tools callable by cloud agents and the user.

## Requirements

### Functional Requirements

1. **REQ-F1**: Loom MCP server exposes `local_brainstorm(task: str, context: str)` tool that returns creative approaches/ideas from a local E2B model within 3 seconds
2. **REQ-F2**: Loom MCP server exposes `local_review(code: str, file_path: str)` tool that returns quick code review findings with confidence tags
3. **REQ-F3**: Loom MCP server exposes `local_debug(error: str, context: str)` tool that analyzes errors/stack traces and suggests probable causes
4. **REQ-F4**: Background worker monitors git-tracked file changes, runs modified files through local E2B analysis, and writes findings as Graphiti episodes with confidence metadata
5. **REQ-F5**: `get_context_for_coder` returns local model insights alongside existing graph context
6. **REQ-F6**: LiteLLM config gains a `local/*` tier routing to Ollama
7. **REQ-F7**: Agent registry gains local-tier agent definitions with Ollama-optimized system prompts

### Non-Functional Requirements

1. **REQ-N1**: On-demand tools respond in <3 seconds (local GPU inference)
2. **REQ-N2**: Background worker uses <2GB additional VRAM beyond the 2x E2B baseline (~8GB)
3. **REQ-N3**: Background analysis does not block MCP tool responsiveness (async, non-blocking)
4. **REQ-N4**: Local model outputs include confidence tags (high/medium/low) before entering Graphiti
5. **REQ-N5**: System degrades gracefully if Ollama is unavailable

### Constraints

- RTX 3080 with 10GB VRAM — 2x E2B Q4 models (~8GB)
- Ollama as local runtime (day-one Gemma 4 support)
- Must not break existing `heavy/*` and `light/*` tier routing
- Same-process deployment (background worker inside MCP server)
- Python 3.12+ (existing constraint)

## Approach

### Selected Approach: Integrated Local Inference Layer

A new `src/loom/local_inference.py` module provides a `LocalInferenceEngine` class that manages:
- **Ollama client** via `AsyncOpenAI(base_url='http://localhost:11434/v1')` — *reuses the same OpenAI-compatible pattern as the orchestrator's LiteLLM client*
- **Background worker** as an `asyncio.Task` started on first MCP tool invocation (lazy init) — *prevents startup failures when Ollama isn't running*
- **On-demand handlers** as async methods called by new MCP tool functions in `server.py`
- **Confidence tagger** that parses model outputs and assigns high/medium/low confidence

### Alternatives Considered

#### Agent-Centric Local Models
- **Description**: Model local Gemma as agents in the registry, dispatch via existing orchestrator
- **Pros**: Uniform agent treatment, leverages existing dispatch
- **Cons**: Phase model doesn't suit always-on background monitoring
- **Rejected Because**: The agent/phase model assumes discrete task execution, not continuous background monitoring

#### Event-Driven Microservice
- **Description**: Separate process with filesystem event watching
- **Pros**: Maximum isolation, independently restartable
- **Cons**: Contradicts same-process preference, adds IPC complexity
- **Rejected Because**: User explicitly chose same-process deployment for simplicity

### Decision Matrix

| Criterion | Weight | Integrated Layer | Agent-Centric | Event-Driven |
|-----------|--------|-----------------|---------------|--------------|
| Integration simplicity | 30% | 5: Single module | 3: Phase mismatch | 2: Separate process |
| Background fidelity | 25% | 4: Async loop | 2: Forced phases | 5: Dedicated watcher |
| Deployment simplicity | 20% | 5: One process | 4: Same process | 2: Multi-process |
| User preference | 15% | 5: Matches all | 3: Partial fit | 2: Contradicts |
| Extensibility | 10% | 4: Easy to add | 5: Agent pattern | 3: Service interface |
| **Weighted Total** | | **4.6** | **3.1** | **2.9** |

## Architecture

### Component Diagram

```
┌───────────────────────────────────────────────────┐
���              Loom MCP Server (server.py)           │
│                                                   │
│  ┌─────────────────────┬─────────────────────┐   │
│  │  Existing MCP Tools │  New Local Tools     │   │
│  │  orchestrate_swarm  │  local_brainstorm    │   │
│  │  get_context_for_   │  local_review        │   │
│  │  add_file_node      │  local_debug         │   │
│  │  add_bug_edge       │  local_status        │   │
│  └─────────────────────┴─────────────────────┘   │
│           │                     │                  │
│  ��────────▼─────────────────────▼────────────┐   │
│  │       LocalInferenceEngine                 │   │
│  │  ┌──────────────┐  ┌�����───────────────┐    │   │
│  │  │ Background   │  │ On-Demand       │    │   │
│  │  │ Worker       │  │ Handler         │    │   │
│  │  └──────────────┘  └─────────────────┘    │   │
│  │  ┌─────────────────────────────────────┐  │   │
│  │  │  Ollama Client (AsyncOpenAI)        │  │   │
│  │  │  models: gemma4-e2b:q4 x2           │  │   │
│  │  └─────────────────────────────────────┘  │   │
���  └────────────────────────────────────────────┘   │
│           │                                        │
│  ┌────────▼───────────────────────────────────┐   │
│  │  LoomSwarmMemory (Graphiti / Neo4j)        │   │
│  │  + LOCAL_INSIGHT episodes (new)            │   │
│  └────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────┘
         │                          │
    ┌────▼────┐              ┌─────▼──────┐
    │  Neo4j  │              │   Ollama   │
    └─────────┘              └────────────┘
```

### Data Flow

**Background Analysis Flow:**
1. Worker polls `git diff --name-only` every 30s
2. Changed files sent to E2B with analysis system prompt
3. Response parsed by ConfidenceTagger → high/medium/low
4. Results written as Graphiti episodes with metadata

**On-Demand Flow:**
1. Cloud agent calls `local_brainstorm/review/debug` MCP tool
2. Handler sends to E2B via AsyncOpenAI
3. Response returned directly to caller

**Enriched Context Flow:**
1. Cloud agent calls `get_context_for_coder(file)`
2. Memory engine returns nodes + edges + LOCAL_INSIGHT episodes

### Key Interfaces

```python
class LocalInferenceEngine:
    async def start_background_worker(self) -> None
    async def stop_background_worker(self) -> None
    async def brainstorm(self, task: str, context: str = "") -> str
    async def review(self, code: str, file_path: str) -> dict
    async def debug_assist(self, error: str, context: str = "") -> str
    async def get_status(self) -> dict
```

## Agent Team

| Phase | Agent(s) | Parallel | Deliverables |
|-------|----------|----------|--------------|
| 1 | coder | No | `src/loom/local_inference.py` |
| 2 | coder | Yes | `server.py` — 4 new MCP tools |
| 3 | coder | Yes | `memory_engine.py` — local insight support |
| 4 | coder | Yes | `litellm_config.yaml` — local/* tier |
| 5 | coder | Yes | Agent definitions + registry update |
| 6 | technical-writer | Yes | docker-compose + .env.example |
| 7 | tester | No | Test suite |
| 8 | code-reviewer | No | Final review |

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation |
|------|----------|------------|------------|
| Ollama unavailable at runtime | MEDIUM | MEDIUM | Graceful degradation (REQ-N5) |
| VRAM exhaustion | HIGH | LOW | Q4 quantization, OLLAMA_MAX_LOADED_MODELS=2 |
| Background worker interference | MEDIUM | LOW | Async priority, yield during tool calls |
| Low-quality insights | MEDIUM | MEDIUM | Confidence tagging, temporal invalidation |
| Git diff polling gaps | LOW | LOW | Configurable interval, next-cycle catch-up |
| Model availability in Ollama | HIGH | LOW | Day-one support confirmed, configurable model name |

## Success Criteria

1. `local_brainstorm` returns within 3 seconds
2. `local_review` identifies basic code issues with confidence tags
3. `local_debug` provides relevant diagnostic suggestions
4. `local_status` reports model and worker state
5. Background worker writes LOCAL_INSIGHT episodes within 60s of file change
6. `get_context_for_coder` includes local insights
7. LiteLLM `local/*` tier routes to Ollama
8. Graceful degradation when Ollama unavailable
9. VRAM stays under 10GB
10. Unit tests pass
