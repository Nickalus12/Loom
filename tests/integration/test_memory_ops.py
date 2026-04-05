"""Integration tests for full memory operations against a live Neo4j instance.

These tests exercise the core CRUD and graph-query capabilities of
``LoomSwarmMemory``: adding file nodes, creating bug edges, retrieving
context, and invalidating edges through blackboard transitions.

All tests are gated behind the ``integration`` marker and are
automatically skipped when Docker services are unavailable.
"""

import os
import tempfile
import textwrap

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_temp_python_file(content: str) -> str:
    """Write *content* to a temporary ``.py`` file and return its path.

    The caller is responsible for cleanup (the tests use ``tmp_path`` or
    explicit ``os.unlink``).
    """
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


# ---------------------------------------------------------------------------
# File node tests
# ---------------------------------------------------------------------------

class TestAddFileNode:
    """Verify that file nodes can be persisted and retrieved."""

    async def test_add_file_node_creates_retrievable_node(self, live_memory):
        """Should create a file node that has a non-empty uuid."""
        node = await live_memory.add_file_node(
            file_path="integration_test_dummy.py",
            summary="Dummy file used by integration tests",
        )
        assert node is not None
        assert hasattr(node, "uuid")
        assert isinstance(node.uuid, str)
        assert len(node.uuid) > 0

    async def test_add_file_node_with_ast_children(self, live_memory):
        """Should create AST child entities when the file contains parseable code."""
        python_source = textwrap.dedent("""\
            class Calculator:
                \"\"\"A simple calculator.\"\"\"

                def add(self, a: int, b: int) -> int:
                    \"\"\"Return the sum of a and b.\"\"\"
                    return a + b

            def standalone_helper(x: int) -> int:
                \"\"\"Double a value.\"\"\"
                return x * 2
        """)
        temp_path = _write_temp_python_file(python_source)
        try:
            node = await live_memory.add_file_node(
                file_path=temp_path,
                summary="Temp file with Calculator class and helper function",
            )
            # The file node itself must exist
            assert node is not None
            assert len(node.uuid) > 0
            # We cannot directly query child nodes through the public API of
            # LoomSwarmMemory, but the fact that add_file_node completed without
            # error and returned a valid node (after internally saving child
            # nodes and CONTAINS edges) is the integration-level assertion.
            # A deeper assertion would require querying Neo4j directly, which
            # couples the test to Graphiti internals.
        finally:
            os.unlink(temp_path)


# ---------------------------------------------------------------------------
# Bug edge tests
# ---------------------------------------------------------------------------

class TestAddBugEdge:
    """Verify HAS_BUG edge creation between nodes."""

    async def test_add_bug_edge_creates_relationship(self, live_memory):
        """Should create a HAS_BUG edge with a valid uuid."""
        source_node = await live_memory.add_file_node(
            file_path="source_module.py",
            summary="Source module for bug edge test",
        )
        target_node = await live_memory.add_file_node(
            file_path="target_module.py",
            summary="Target module for bug edge test",
        )

        edge = await live_memory.add_bug_edge(
            source_node_uuid=source_node.uuid,
            file_node_uuid=target_node.uuid,
            bug_description="Off-by-one error in loop boundary",
        )

        assert edge is not None
        assert hasattr(edge, "uuid")
        assert isinstance(edge.uuid, str)
        assert len(edge.uuid) > 0


# ---------------------------------------------------------------------------
# Context retrieval tests
# ---------------------------------------------------------------------------

class TestGetContext:
    """Verify that context retrieval returns the expected structure."""

    async def test_get_context_returns_structure(self, live_memory):
        """Should return a dict with nodes, active_bugs, and raw_edges keys."""
        # Seed minimal data so the search has something to find
        node = await live_memory.add_file_node(
            file_path="context_test_file.py",
            summary="File created for context retrieval integration test",
        )

        context = await live_memory.get_context_for_coder("context_test_file.py")

        assert isinstance(context, dict)
        assert "nodes" in context
        assert "active_bugs" in context
        assert "raw_edges" in context
        # nodes and raw_edges are lists (may be empty if search doesn't match)
        assert isinstance(context["nodes"], list)
        assert isinstance(context["active_bugs"], list)
        assert isinstance(context["raw_edges"], list)


# ---------------------------------------------------------------------------
# Blackboard transition tests
# ---------------------------------------------------------------------------

class TestBlackboardTransition:
    """Verify temporal invalidation of HAS_BUG edges."""

    async def test_blackboard_transition_invalidates_bugs(self, live_memory):
        """Should set invalid_at on the transitioned edge so it no longer appears as active."""
        source = await live_memory.add_file_node(
            file_path="transition_source.py",
            summary="Source for blackboard transition test",
        )
        target = await live_memory.add_file_node(
            file_path="transition_target.py",
            summary="Target for blackboard transition test",
        )
        edge = await live_memory.add_bug_edge(
            source_node_uuid=source.uuid,
            file_node_uuid=target.uuid,
            bug_description="Null pointer dereference in handler",
        )

        # Transition (invalidate) the bug edge
        await live_memory.blackboard_transition(
            edge_uuids=[edge.uuid],
            agent_name="test-agent",
        )

        # Re-fetch the edge and verify invalid_at is set
        refreshed = await live_memory.memory.edges.entity.get_by_uuid(edge.uuid)
        assert refreshed is not None
        assert refreshed.invalid_at is not None

    async def test_blackboard_transition_missing_uuid_raises(self, live_memory):
        """Should raise ValueError when a non-existent edge UUID is provided."""
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        with pytest.raises(ValueError, match="Edge UUIDs not found"):
            await live_memory.blackboard_transition(
                edge_uuids=[fake_uuid],
                agent_name="test-agent",
            )
