"""Integration tests for Neo4j connection lifecycle.

These tests verify that LoomSwarmMemory can connect to, operate on,
and cleanly disconnect from a real Neo4j instance.  All tests are
gated behind the ``integration`` marker and are automatically skipped
when Docker services are unavailable (see ``live_memory`` fixture).
"""

import os

import pytest

pytestmark = pytest.mark.integration


class TestBuildIndices:
    """Verify that Neo4j index/constraint creation completes without error."""

    async def test_build_indices_succeeds(self, live_memory):
        """Should complete build_indices_and_constraints without raising on a fresh Neo4j."""
        # The live_memory fixture already calls build_indices_and_constraints once
        # during setup.  Calling it a second time verifies idempotency and that the
        # first call left the driver in a usable state.
        await live_memory.build_indices_and_constraints()

    async def test_sequential_operations_survive(self, live_memory):
        """Should survive multiple sequential build_indices calls without a 'Driver closed' error."""
        for _ in range(3):
            await live_memory.build_indices_and_constraints()


class TestCloseAndReopen:
    """Verify graceful teardown and reconnection."""

    async def test_close_and_reopen(self):
        """Should be able to close a connection and create a new LoomSwarmMemory afterwards."""
        neo4j_pass = os.getenv("NEO4J_PASSWORD")
        if not neo4j_pass:
            pytest.skip("NEO4J_PASSWORD not set - Docker services required")

        litellm_key = os.getenv("LITELLM_MASTER_KEY")
        if not litellm_key:
            pytest.skip("LITELLM_MASTER_KEY not set - Docker services required")

        from loom.memory_engine import LoomSwarmMemory

        # First connection
        mem1 = LoomSwarmMemory()
        await mem1.build_indices_and_constraints()
        await mem1.close()

        # Second connection after explicit close
        mem2 = LoomSwarmMemory()
        try:
            await mem2.build_indices_and_constraints()
        finally:
            await mem2.close()
