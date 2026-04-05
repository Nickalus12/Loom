"""Integration-specific fixtures requiring Docker services (Neo4j, LiteLLM)."""

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Load project .env so integration tests can find NEO4J_PASSWORD, LITELLM_MASTER_KEY, etc.
_project_root = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=_project_root / ".env")


@pytest.fixture
async def live_memory():
    """Create LoomSwarmMemory connected to real Neo4j.

    Skips the test when Docker services are not available, detected via
    missing environment variables or failed connectivity.
    """
    neo4j_pass = os.getenv("NEO4J_PASSWORD")
    if not neo4j_pass:
        pytest.skip("NEO4J_PASSWORD not set - Docker services required")

    litellm_key = os.getenv("LITELLM_MASTER_KEY")
    if not litellm_key:
        pytest.skip("LITELLM_MASTER_KEY not set - Docker services required")

    from loom.memory_engine import LoomSwarmMemory

    try:
        mem = LoomSwarmMemory()
        await mem.build_indices_and_constraints()
        # Smoke-test the embedding endpoint — node.save() requires it
        from graphiti_core.nodes import EntityNode
        probe = EntityNode(name="__probe__", summary="connectivity check", labels=[], group_id="default")
        await mem.memory.nodes.entity.save(probe)
    except Exception as e:
        pytest.skip(f"Docker services not fully reachable: {e}")

    try:
        yield mem
    finally:
        await mem.close()
