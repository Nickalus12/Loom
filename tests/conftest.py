"""Shared pytest fixtures for Loom test suite."""

import pytest
from unittest.mock import AsyncMock, MagicMock, PropertyMock


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "integration: requires Docker services (Neo4j, LiteLLM)"
    )


# ---------------------------------------------------------------------------
# Mock Graphiti fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_graphiti():
    """AsyncMock of the Graphiti client with mocked node/edge operations."""
    graphiti = AsyncMock()

    # Mock nodes.entity
    nodes_entity = AsyncMock()
    nodes_entity.save = AsyncMock(side_effect=lambda node: node)
    nodes_entity.get_by_uuid = AsyncMock(return_value=None)

    nodes = MagicMock()
    nodes.entity = nodes_entity
    graphiti.nodes = nodes

    # Mock edges.entity
    edges_entity = AsyncMock()
    edges_entity.save = AsyncMock(side_effect=lambda edge: edge)
    edges_entity.get_by_uuid = AsyncMock(return_value=None)

    edges = MagicMock()
    edges.entity = edges_entity
    graphiti.edges = edges

    # Mock search_
    search_result = MagicMock()
    search_result.nodes = []
    search_result.edges = []
    graphiti.search_ = AsyncMock(return_value=search_result)

    # Mock build_indices_and_constraints
    graphiti.build_indices_and_constraints = AsyncMock()

    # Mock close
    graphiti.close = AsyncMock()

    return graphiti


# ---------------------------------------------------------------------------
# Sample code fixtures for parser tests
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_python_code():
    return '''
class UserService:
    """Manages user CRUD operations."""

    def create_user(self, name: str) -> dict:
        """Create a new user with the given name."""
        return {"name": name}

    def delete_user(self, user_id: int) -> bool:
        """Delete a user by ID."""
        return True


def standalone_function(x: int) -> int:
    """A standalone top-level function."""
    return x * 2


def no_docstring():
    pass
'''


@pytest.fixture
def sample_ts_code():
    return '''
/** Configuration options for the service. */
interface ServiceConfig {
    host: string;
    port: number;
}

/** User data transfer object. */
type UserDTO = {
    id: string;
    name: string;
};

/** Creates a new service instance. */
function createService(config: ServiceConfig): void {
    console.log(config);
}

class UserController {
    private service: ServiceConfig;

    constructor(service: ServiceConfig) {
        this.service = service;
    }

    getUser(id: string): UserDTO {
        return { id, name: "test" };
    }
}
'''


@pytest.fixture
def sample_js_code():
    return '''
/** Calculates the sum of two numbers. */
function add(a, b) {
    return a + b;
}

class EventEmitter {
    constructor() {
        this.listeners = {};
    }

    on(event, callback) {
        this.listeners[event] = callback;
    }
}

function noDoc() {
    return true;
}
'''
