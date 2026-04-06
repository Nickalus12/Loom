---
title: "Loom Python MCP Server Hardening Implementation Plan"
design_ref: "docs/maestro/plans/2026-04-04-loom-python-hardening-design.md"
created: "2026-04-04T00:00:00Z"
status: "draft"
total_phases: 4
estimated_files: 19
task_complexity: "medium"
---

# Loom Python MCP Server Hardening Implementation Plan

## Plan Overview

- **Total phases**: 4
- **Agents involved**: `coder` (Phases 1-2), `tester` (Phases 3-4)
- **Estimated effort**: Foundation + parser refactor, core hardening across 3 modules, full test pyramid (unit + contract + integration)

## Dependency Graph

```
Phase 1: Foundation & Parser Plugin System
    |
Phase 2: Core Module Hardening
    |          \
Phase 3:        Phase 4:
Unit &          Integration
Contract Tests  Tests
(parallel)      (parallel)
```

## Execution Strategy

| Stage | Phases | Execution | Agent Count | Notes |
|-------|--------|-----------|-------------|-------|
| 1     | Phase 1 | Sequential | 1 (coder) | Protocols, parser plugins, test infra |
| 2     | Phase 2 | Sequential | 1 (coder) | memory_engine, orchestrator, server fixes |
| 3     | Phases 3, 4 | Parallel | 2 (tester × 2) | Unit/contract tests + integration tests |

---

## Phase 1: Foundation & Parser Plugin System

### Objective
Establish protocol contracts, refactor the AST parser into a plugin-based registry, implement Python/TypeScript/JavaScript parsers, and set up pytest infrastructure.

### Agent: coder
### Parallel: No

### Files to Create

- `src/loom/protocols.py` — Protocol definitions for `LanguageParser` and `MemoryBackend`. `LanguageParser` has `extensions: list[str]` and `parse(content: str) -> list[dict]`. `MemoryBackend` wraps the async Graphiti operations.
- `src/loom/parsers/__init__.py` — Package init that exports all parser classes and a `PARSER_REGISTRY: dict[str, LanguageParser]` built by scanning this package.
- `src/loom/parsers/python_parser.py` — `PythonParser` implementing `LanguageParser`. Uses `tree_sitter_python`. Extracts top-level and nested functions/methods, classes, and docstrings as summaries. `extensions = [".py"]`.
- `src/loom/parsers/typescript_parser.py` — `TypeScriptParser` implementing `LanguageParser`. Uses `tree_sitter_typescript`. Extracts functions, classes, interfaces, type aliases, and JSDoc comments. `extensions = [".ts", ".tsx"]`.
- `src/loom/parsers/javascript_parser.py` — `JavaScriptParser` implementing `LanguageParser`. Uses `tree_sitter_javascript`. Extracts functions, classes, and JSDoc comments. `extensions = [".js", ".jsx", ".mjs"]`.
- `tests/__init__.py` — Empty package init.
- `tests/conftest.py` — Shared pytest fixtures: `mock_graphiti` (AsyncMock of Graphiti), `mock_memory_engine` (LoomSwarmMemory with injected mock), `sample_python_code` / `sample_ts_code` / `sample_js_code` (known-good snippets for parser tests). Custom markers: `integration` registered in pyproject.toml.

### Files to Modify

- `src/loom/ast_parser.py` — Replace monolithic class with registry-based dispatch. `ASTParser.__init__` builds `{extension: parser}` from `parsers` package. New method: `parse_file(file_path: str, content: str) -> list[dict]` dispatches by extension. Keep `parse_python_file` as deprecated backward-compatible wrapper.
- `pyproject.toml` — Add `tree-sitter-javascript>=0.23.0` to dependencies. Add `[tool.pytest.ini_options]` section with `markers = ["integration: requires Docker services"]`, `asyncio_mode = "auto"`. Add `pytest`, `pytest-asyncio` to optional `[project.optional-dependencies.test]`.

### Implementation Details

```python
# protocols.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class LanguageParser(Protocol):
    extensions: list[str]
    def parse(self, content: str) -> list[dict]: ...

# parsers/__init__.py
from loom.parsers.python_parser import PythonParser
from loom.parsers.typescript_parser import TypeScriptParser
from loom.parsers.javascript_parser import JavaScriptParser

_ALL_PARSERS = [PythonParser(), TypeScriptParser(), JavaScriptParser()]
PARSER_REGISTRY: dict[str, LanguageParser] = {}
for p in _ALL_PARSERS:
    for ext in p.extensions:
        PARSER_REGISTRY[ext] = p

# ast_parser.py (refactored)
from loom.parsers import PARSER_REGISTRY

class ASTParser:
    def __init__(self):
        self.registry = dict(PARSER_REGISTRY)

    def parse_file(self, file_path: str, content: str) -> list[dict]:
        ext = os.path.splitext(file_path)[1]
        parser = self.registry.get(ext)
        if parser is None:
            return []
        return parser.parse(content)

    def parse_python_file(self, content: str) -> list[dict]:
        """Deprecated: use parse_file() instead."""
        py_parser = self.registry.get(".py")
        return py_parser.parse(content) if py_parser else []
```

Each language parser extracts:
- **Functions**: top-level `function_definition` + class method `function_definition` nodes
- **Classes**: `class_definition` nodes
- **Docstrings**: First `expression_statement > string` child of function/class bodies (Python), or preceding `comment` nodes matching JSDoc pattern `/** ... */` (TS/JS)
- **Summary**: Docstring/JSDoc first line, or `"<Type> <name> defined in file"` fallback

### Validation

- `uv run python -c "from loom.protocols import LanguageParser, MemoryBackend; print('OK')"`
- `uv run python -c "from loom.parsers import PARSER_REGISTRY; print(list(PARSER_REGISTRY.keys()))"`
- `uv run python -c "from loom.ast_parser import ASTParser; p = ASTParser(); print(p.parse_file('test.py', 'def foo(): pass'))"`
- `uv run python -c "from loom.ast_parser import ASTParser; p = ASTParser(); print(p.parse_file('test.ts', 'function foo(): void {}'))"`

### Dependencies

- Blocked by: None
- Blocks: Phase 2, Phase 3, Phase 4

---

## Phase 2: Core Module Hardening

### Objective
Fix runtime failures in memory_engine.py (constructor injection, connection lifecycle, blackboard integrity), server.py (.env resolution), and orchestrator.py (model string, error handling).

### Agent: coder
### Parallel: No

### Files to Modify

- `src/loom/memory_engine.py` —
  1. **Constructor injection**: `__init__` accepts optional `graphiti: Graphiti | None = None`. If None, creates from env vars (current behavior). If provided, uses it directly.
  2. **Encoding safety**: `add_file_node()` opens files with `encoding='utf-8', errors='replace'`.
  3. **Blackboard integrity**: `blackboard_transition()` fetches all edges first, raises `ValueError` listing missing UUIDs before mutating any.
  4. **Use new parser**: Replace `self.ast_parser = ASTParser()` usage. Call `self.ast_parser.parse_file(file_path, content)` instead of `self.ast_parser.parse_python_file(content)`. This enables multi-language AST support for all file types with registered parsers.
  5. **Connection lifecycle**: Ensure Graphiti connection is established before operations and properly closed.

- `src/loom/orchestrator.py` —
  1. **Model string**: Change `f"openai/{tier}/*"` to a configurable model mapping or validated format.
  2. **Error handling**: Wrap `acompletion` calls with proper exception handling, log failures with agent name and tier.
  3. **Timeout**: Add configurable timeout for LLM calls.

- `src/loom/server.py` —
  1. **`.env` resolution**: Replace `os.path.join(os.getcwd(), "..", ".env")` with `pathlib.Path(__file__).resolve().parents[2] / '.env'`.
  2. **Error responses**: Improve error messages in tool functions to include context (which tool, what input caused the failure).
  3. **Graceful init**: Wrap `LoomSwarmMemory()` initialization in a try/except so the server can start even if env vars are missing (tools return error messages instead of crashing the server).

### Implementation Details

```python
# memory_engine.py __init__ change
class LoomSwarmMemory:
    def __init__(self, graphiti: Graphiti | None = None):
        if graphiti is not None:
            self.memory = graphiti
            self.ast_parser = ASTParser()
            return
        # ... existing env var initialization ...

# memory_engine.py blackboard_transition change
async def blackboard_transition(self, edge_uuids: list[str], agent_name: str):
    edges = []
    missing = []
    for uuid in edge_uuids:
        edge = await self.memory.edges.entity.get_by_uuid(uuid)
        if edge is None:
            missing.append(uuid)
        else:
            edges.append(edge)
    if missing:
        raise ValueError(f"Edge UUIDs not found: {missing}")
    for edge in edges:
        edge.invalid_at = datetime.now(timezone.utc)
        await self.memory.edges.entity.save(edge)

# server.py .env fix
from pathlib import Path
_project_root = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_project_root / '.env')
```

### Validation

- `uv run python -c "from loom.server import mcp; print('Server init OK')"`
- `uv run python -c "from loom.memory_engine import LoomSwarmMemory; m = LoomSwarmMemory(graphiti=object()); print('Injection OK')"`
- `uv run python -c "from loom.orchestrator import LoomOrchestrator; print('Orchestrator OK')"`

### Dependencies

- Blocked by: Phase 1
- Blocks: Phase 3, Phase 4

---

## Phase 3: Unit & Contract Tests

### Objective
Implement unit tests for all 4 modules (mocked infrastructure) and contract tests for all 5 MCP tools. Every public method tested including error paths.

### Agent: tester
### Parallel: Yes (with Phase 4)

### Files to Create

- `tests/unit/__init__.py` — Empty package init.
- `tests/unit/test_ast_parser.py` — Tests for `ASTParser`: registry construction, `parse_file` dispatch by extension, unknown extension returns empty, backward-compat `parse_python_file`.
- `tests/unit/test_parsers.py` — Tests for each language parser: Python (functions, classes, nested methods, docstrings), TypeScript (functions, classes, interfaces, JSDoc), JavaScript (functions, classes, JSDoc). Each with known-good snippets asserting entity count and summary content.
- `tests/unit/test_memory_engine.py` — Tests for `LoomSwarmMemory` with injected mock Graphiti: `build_indices_and_constraints` delegates to graphiti, `get_context_for_coder` filters active bugs, `add_file_node` creates node + AST children, `add_file_node` with non-UTF-8 file, `blackboard_transition` validates UUIDs and raises on missing, `blackboard_transition` sets `invalid_at`.
- `tests/unit/test_orchestrator.py` — Tests for `LoomOrchestrator` with mocked `acompletion`: `dispatch_agent` sends correct model/messages, `execute_swarm` runs all phases in order, error handling on LLM failure.
- `tests/unit/test_server.py` — Tests for server module: `.env` path resolution uses `__file__`, `orchestrate_swarm` returns success/failure strings, `get_context_for_coder` returns correct dict shape, `add_file_node` returns UUID string, `add_bug_edge` returns UUID string, `blackboard_transition` returns confirmation string.
- `tests/contract/__init__.py` — Empty package init.
- `tests/contract/test_mcp_tools.py` — Contract tests for all 5 MCP tools: validate return types (str for orchestrate_swarm/add_file_node/add_bug_edge/blackboard_transition, dict for get_context_for_coder), validate error response shapes, validate parameter types match Field definitions.

### Validation

- `uv run pytest tests/unit/ -v` — all unit tests pass
- `uv run pytest tests/contract/ -v` — all contract tests pass
- `uv run pytest tests/unit/ tests/contract/ --tb=short` — full fast suite passes

### Dependencies

- Blocked by: Phase 2
- Blocks: None

---

## Phase 4: Integration Tests

### Objective
Implement integration tests that exercise real Neo4j operations, gated behind `@pytest.mark.integration`.

### Agent: tester
### Parallel: Yes (with Phase 3)

### Files to Create

- `tests/integration/__init__.py` — Empty package init.
- `tests/integration/test_neo4j_lifecycle.py` — Integration tests for Neo4j connection: `build_indices_and_constraints` creates expected indices, connection survives multiple sequential operations, connection cleanup on `close()`. Uses real Neo4j via Docker. Skip if Neo4j unreachable.
- `tests/integration/test_memory_ops.py` — Integration tests for full memory operations: `add_file_node` creates retrievable node with AST children, `add_bug_edge` creates retrievable HAS_BUG edge, `get_context_for_coder` returns nodes and active bugs, `blackboard_transition` sets `invalid_at` and bug no longer appears in active query.

### Implementation Details

```python
# tests/integration/conftest.py or tests/conftest.py addition
import pytest
import asyncio

@pytest.fixture
async def live_memory():
    """Create LoomSwarmMemory connected to real Neo4j (Docker)."""
    import os
    if not os.getenv("NEO4J_PASSWORD"):
        pytest.skip("NEO4J_PASSWORD not set — Docker services required")
    from loom.memory_engine import LoomSwarmMemory
    mem = LoomSwarmMemory()
    await mem.build_indices_and_constraints()
    yield mem
    await mem.close()
```

### Validation

- `uv run pytest tests/integration/ -v -m integration` — passes when Docker services are running
- `uv run pytest` — integration tests are skipped (not selected by default)

### Dependencies

- Blocked by: Phase 2
- Blocks: None

---

## File Inventory

| # | File | Phase | Purpose |
|---|------|-------|---------|
| 1 | `src/loom/protocols.py` | 1 | Protocol definitions (LanguageParser, MemoryBackend) |
| 2 | `src/loom/parsers/__init__.py` | 1 | Parser package with PARSER_REGISTRY |
| 3 | `src/loom/parsers/python_parser.py` | 1 | Python AST parser (functions, classes, docstrings) |
| 4 | `src/loom/parsers/typescript_parser.py` | 1 | TypeScript AST parser (functions, classes, interfaces, JSDoc) |
| 5 | `src/loom/parsers/javascript_parser.py` | 1 | JavaScript AST parser (functions, classes, JSDoc) |
| 6 | `src/loom/ast_parser.py` | 1 | Refactored to registry-based dispatch |
| 7 | `pyproject.toml` | 1 | Add tree-sitter-javascript, pytest deps, markers |
| 8 | `tests/__init__.py` | 1 | Test package init |
| 9 | `tests/conftest.py` | 1 | Shared fixtures, markers, mock factories |
| 10 | `src/loom/memory_engine.py` | 2 | Constructor injection, encoding, blackboard integrity |
| 11 | `src/loom/orchestrator.py` | 2 | Model string fix, error handling, timeout |
| 12 | `src/loom/server.py` | 2 | .env resolution, error responses, graceful init |
| 13 | `tests/unit/__init__.py` | 3 | Unit test package init |
| 14 | `tests/unit/test_ast_parser.py` | 3 | ASTParser unit tests |
| 15 | `tests/unit/test_parsers.py` | 3 | Language parser unit tests |
| 16 | `tests/unit/test_memory_engine.py` | 3 | Memory engine unit tests |
| 17 | `tests/unit/test_orchestrator.py` | 3 | Orchestrator unit tests |
| 18 | `tests/unit/test_server.py` | 3 | Server unit tests |
| 19 | `tests/contract/__init__.py` | 3 | Contract test package init |
| 20 | `tests/contract/test_mcp_tools.py` | 3 | MCP tool contract tests |
| 21 | `tests/integration/__init__.py` | 4 | Integration test package init |
| 22 | `tests/integration/test_neo4j_lifecycle.py` | 4 | Neo4j connection integration tests |
| 23 | `tests/integration/test_memory_ops.py` | 4 | Memory operation integration tests |

## Risk Classification

| Phase | Risk | Rationale |
|-------|------|-----------|
| 1 | MEDIUM | New parser plugins for TS/JS require correct tree-sitter node type mapping. Mitigated by known-good test snippets. |
| 2 | MEDIUM | Refactoring __init__ signatures and .env resolution could break existing callers. Mitigated by backward-compatible defaults. |
| 3 | LOW | Unit/contract tests are additive — no existing code changes. |
| 4 | LOW | Integration tests are additive. Flakiness risk mitigated by skip-when-unavailable. |

## Execution Profile

```
Execution Profile:
- Total phases: 4
- Parallelizable phases: 2 (in 1 batch)
- Sequential-only phases: 2
- Estimated parallel wall time: 3 agent dispatches (Phases 1, 2, then 3+4 parallel)
- Estimated sequential wall time: 4 agent dispatches

Note: Native subagents currently run without user approval gates.
All tool calls are auto-approved without user confirmation.
```
