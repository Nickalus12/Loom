---
title: "Loom Python MCP Server Hardening"
created: "2026-04-04T00:00:00Z"
status: "approved"
authors: ["TechLead", "Nickalus Brewer"]
type: "design"
design_depth: "deep"
task_complexity: "medium"
---

# Loom Python MCP Server Hardening Design Document

## Problem Statement

The Loom Python MCP server (`src/loom/`) is a FastMCP-based orchestration engine that coordinates 22 specialized agents through a temporal knowledge graph (Neo4j/Graphiti) and LLM proxy (LiteLLM). While the server initializes and imports succeed, **runtime operations fail** due to Neo4j connection lifecycle bugs (`Driver closed` errors during index creation, authentication rate-limiting from reconnection storms).

Beyond the runtime failures, the codebase has **zero test coverage**, making regression detection impossible. Error handling is minimal — `blackboard_transition` silently skips missing edges, `add_file_node` reads files without encoding guards, and `server.py` resolves `.env` relative to a fragile `../` path. The AST parser only extracts top-level Python entities with placeholder summaries, despite `tree-sitter-typescript` being an unused dependency.

The system cannot be reliably developed, extended, or operated in its current state. This hardening effort addresses the three compounding gaps: **broken runtime behavior**, **absent test infrastructure**, and **accumulated code quality debt**.

## Requirements

### Functional Requirements

1. **REQ-F1: Neo4j Connection Lifecycle** — The memory engine must establish, maintain, and cleanly close Neo4j connections. `build_indices_and_constraints()` must succeed when Neo4j is reachable with valid credentials. Connection errors must raise descriptive exceptions, not silently fail.

2. **REQ-F2: Blackboard Transition Integrity** — `blackboard_transition()` must validate that each edge UUID exists before attempting mutation. Missing UUIDs must raise a clear error (not silently skip). Batch operations should be atomic where the driver supports it.

3. **REQ-F3: Multi-Language AST Parsing** — `ASTParser` must support Python, TypeScript, and JavaScript. It must extract: (a) top-level and nested functions/methods, (b) classes, (c) docstrings/JSDoc as summaries. A pluggable per-language parser design must allow future language additions without modifying core logic.

4. **REQ-F4: File Node Creation with Encoding Safety** — `add_file_node()` must handle non-UTF-8 files gracefully (skip AST parsing, still create the node). File reads must specify `encoding='utf-8'` with `errors='replace'`.

5. **REQ-F5: Robust .env Resolution** — `server.py` must resolve `.env` from the project root using `__file__`-relative pathing or `pathlib`, not `os.getcwd()/../`.

### Non-Functional Requirements

6. **REQ-N1: Unit Test Coverage** — All 4 Python modules must have unit tests with mocked infrastructure. Target: every public method tested, including error paths.

7. **REQ-N2: Integration Test Suite** — Integration tests gated behind `@pytest.mark.integration` that exercise real Neo4j operations (index creation, node/edge CRUD, search, blackboard transition).

8. **REQ-N3: Contract Test Suite** — Function-level tests that validate MCP tool return types, error response shapes, and parameter validation for all 5 exposed tools.

9. **REQ-N4: Test Isolation** — `pytest` with no markers runs only unit tests (fast, no Docker). `pytest -m integration` adds infrastructure tests.

### Constraints

- Must preserve the existing MCP tool API surface (no breaking changes to tool names, parameters, or return types)
- Must keep graphiti-core, litellm, and tree-sitter as the core dependencies
- Docker (Neo4j + LiteLLM) remains the required infrastructure for runtime

## Approach

### Selected Approach: Protocol-Driven Hardening + Parser Plugin System

**Summary**: Define Python `Protocol` types for the key contracts (`MemoryBackend`, `LanguageParser`). Refactor `LoomSwarmMemory` to accept a `Graphiti` instance via constructor injection. Implement a parser registry where each language (Python, TypeScript, JavaScript) is a self-contained parser class conforming to `LanguageParser`. Tests mock at protocol boundaries.

**Pros**:
- Constructor injection makes all components trivially testable
- Parser plugin system scales to new languages without modifying core code
- Protocols serve as living documentation of module contracts
- Aligns with the project's own multi-agent architecture philosophy (composable, pluggable)

**Cons**:
- Moderate refactoring overhead (add protocols.py, refactor __init__ signatures)
- Existing code that instantiates `LoomSwarmMemory` directly must pass the Graphiti client

### Alternatives Considered

#### Approach A: Targeted Fix & Bolt-On Tests

- **Description**: Fix each bug in-place with minimal structural changes. Add test files per module that mock dependencies using `unittest.mock.patch`.
- **Pros**: Fastest to implement, lowest regression risk
- **Cons**: Mocking becomes verbose, AST parser grows monolithic, no clean injection points
- **Rejected Because**: Testability and extensibility are primary goals; bolt-on mocking via `patch` is fragile and fights the architecture rather than improving it.

*(Full service-layer abstraction between MCP tools and engine classes was also considered — rejected because it adds unnecessary indirection when the MCP tools are already thin wrappers.)*

### Decision Matrix

| Criterion | Weight | A: Targeted Fix | B: Protocol + Plugin |
|-----------|--------|-----------------|---------------------|
| Testability | 35% | 3: Mocking requires patching internals | 5: Clean injection, protocol-based mocks |
| Implementation speed | 25% | 5: Minimal changes | 3: Moderate refactor needed |
| Extensibility (REQ-F3) | 25% | 2: Monolithic parser grows unwieldy | 5: Plugin registry scales cleanly |
| Risk of regressions | 15% | 5: Minimal structural change | 3: Refactored signatures could break callers |
| **Weighted Total** | | **3.60** | **4.20** |

## Architecture

### Component Diagram

```
src/loom/
├── __init__.py
├── protocols.py          [NEW] Protocol definitions
├── server.py             [MOD] Fix .env resolution, improve error returns
├── orchestrator.py       [MOD] Fix model string, add error handling
├── memory_engine.py      [MOD] Constructor injection, connection lifecycle, error handling
├── ast_parser.py         [MOD] Plugin registry + multi-language support
└── parsers/              [NEW] Language-specific parser plugins
    ├── __init__.py
    ├── python_parser.py
    ├── typescript_parser.py
    └── javascript_parser.py

tests/
├── __init__.py
├── conftest.py           [NEW] Shared fixtures, markers, mock factories
├── unit/
│   ├── test_server.py
│   ├── test_orchestrator.py
│   ├── test_memory_engine.py
│   ├── test_ast_parser.py
│   └── test_parsers.py
├── integration/
│   ├── test_neo4j_lifecycle.py
│   └── test_memory_ops.py
└── contract/
    └── test_mcp_tools.py
```

### Key Interfaces

```python
# protocols.py
from typing import Protocol, runtime_checkable

@runtime_checkable
class LanguageParser(Protocol):
    """Contract for language-specific AST parsers."""
    extensions: list[str]  # e.g., [".py"]
    def parse(self, content: str) -> list[dict]: ...

@runtime_checkable
class MemoryBackend(Protocol):
    """Contract for the knowledge graph backend."""
    async def build_indices_and_constraints(self) -> None: ...
    async def search_(self, query: str, limit: int) -> object: ...
    async def close(self) -> None: ...
```

### Data Flow

1. `server.py` resolves `.env` via `pathlib.Path(__file__).resolve().parents[2] / '.env'` — *Traces To: REQ-F5*
2. `LoomSwarmMemory.__init__` accepts optional `graphiti: Graphiti | None`. If `None`, creates from env vars. If provided, uses injected instance. — *Traces To: REQ-F1*
3. `ASTParser.__init__` auto-discovers parsers from `src/loom/parsers/` and builds `{extension: parser}` registry. `add_file_node()` dispatches by extension. — *Traces To: REQ-F3*
4. `blackboard_transition()` validates all edge UUIDs exist before mutating any. Raises `ValueError` on missing UUIDs. — *Traces To: REQ-F2*

## Risk Assessment

| Risk | Severity | Likelihood | Mitigation | Traces To |
|------|----------|------------|------------|-----------|
| Graphiti API breaking changes | HIGH | LOW | Pin `graphiti-core>=0.28.2,<0.29`. Integration tests catch API drift. | REQ-F1 |
| Tree-sitter grammar incompatibilities | MEDIUM | MEDIUM | Pin grammar versions. Parser unit tests assert expected entity counts on known-good snippets. | REQ-F3 |
| Refactoring introduces regressions | MEDIUM | MEDIUM | Tests before refactor. Optional params with backward-compatible defaults. | REQ-N1 |
| Integration test flakiness | LOW | HIGH | Health-check wait in conftest. Integration marker skips by default. | REQ-N2 |
| MCP tool contract drift | LOW | LOW | Contract tests as living spec. Tool changes require contract test update first. | REQ-N3 |
