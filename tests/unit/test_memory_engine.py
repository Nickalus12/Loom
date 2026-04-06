"""Unit tests for LoomSwarmMemory with injected mock Graphiti backend."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from loom.memory_engine import LoomSwarmMemory, _validate_file_path


@pytest.fixture
def memory(mock_graphiti):
    """Create a LoomSwarmMemory instance with an injected mock Graphiti client."""
    return LoomSwarmMemory(graphiti=mock_graphiti)


class TestConstructorInjection:
    """Verify constructor injection bypasses env var requirements."""

    def test_constructor_injection(self, mock_graphiti):
        """Should accept a graphiti parameter and use it directly, no env vars needed."""
        mem = LoomSwarmMemory(graphiti=mock_graphiti)
        assert mem.memory is mock_graphiti

    def test_constructor_without_injection_requires_env(self):
        """Should raise ValueError when no graphiti param and env vars are missing."""
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="LITELLM_MASTER_KEY"):
                LoomSwarmMemory()

    def test_constructor_missing_neo4j_password(self):
        """Should raise ValueError when LITELLM_MASTER_KEY is set but NEO4J_PASSWORD is not."""
        env = {"LITELLM_MASTER_KEY": "test-key"}
        with patch.dict("os.environ", env, clear=True):
            with pytest.raises(ValueError, match="NEO4J_PASSWORD"):
                LoomSwarmMemory()


class TestBuildIndicesAndConstraints:
    """Verify build_indices_and_constraints delegates to the backend."""

    @pytest.mark.asyncio
    async def test_build_indices_delegates(self, memory, mock_graphiti):
        """Should call graphiti.build_indices_and_constraints."""
        await memory.build_indices_and_constraints()
        mock_graphiti.build_indices_and_constraints.assert_awaited_once()


class TestClose:
    """Verify close delegates to the backend."""

    @pytest.mark.asyncio
    async def test_close_delegates(self, memory, mock_graphiti):
        """Should call graphiti.close."""
        await memory.close()
        mock_graphiti.close.assert_awaited_once()


class TestGetContextForCoder:
    """Verify get_context_for_coder search and filtering behavior."""

    @pytest.mark.asyncio
    async def test_get_context_for_coder_returns_dict(self, memory, mock_graphiti):
        """Should return a dict with nodes, active_bugs, and raw_edges keys."""
        result = await memory.get_context_for_coder("src/main.py")
        assert isinstance(result, dict)
        assert "nodes" in result
        assert "active_bugs" in result
        assert "raw_edges" in result

    @pytest.mark.asyncio
    async def test_get_context_for_coder_calls_search(self, memory, mock_graphiti):
        """Should call search_ with query containing the target file."""
        await memory.get_context_for_coder("src/main.py")
        mock_graphiti.search_.assert_awaited_once()
        call_kwargs = mock_graphiti.search_.call_args
        assert "src/main.py" in call_kwargs.kwargs.get("query", call_kwargs.args[0] if call_kwargs.args else "")

    @pytest.mark.asyncio
    async def test_get_context_filters_active_bugs(self, memory, mock_graphiti):
        """Should only include edges with name='HAS_BUG' and invalid_at=None in active_bugs."""
        active_bug = MagicMock(name="HAS_BUG", invalid_at=None)
        active_bug.name = "HAS_BUG"
        active_bug.invalid_at = None

        resolved_bug = MagicMock(name="HAS_BUG", invalid_at=datetime(2024, 1, 1, tzinfo=timezone.utc))
        resolved_bug.name = "HAS_BUG"
        resolved_bug.invalid_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        other_edge = MagicMock(name="CONTAINS", invalid_at=None)
        other_edge.name = "CONTAINS"
        other_edge.invalid_at = None

        search_result = MagicMock()
        search_result.nodes = []
        search_result.edges = [active_bug, resolved_bug, other_edge]
        mock_graphiti.search_ = AsyncMock(return_value=search_result)

        result = await memory.get_context_for_coder("target.py")

        assert len(result["active_bugs"]) == 1
        assert result["active_bugs"][0] is active_bug
        assert len(result["raw_edges"]) == 3


def _fake_entity_node(**kwargs):
    """Create a MagicMock that looks like an EntityNode without pydantic validation."""
    node = MagicMock()
    for k, v in kwargs.items():
        setattr(node, k, v)
    node.uuid = kwargs.get("uuid", "fake-node-uuid")
    return node


def _fake_entity_edge(**kwargs):
    """Create a MagicMock that looks like an EntityEdge without pydantic validation."""
    edge = MagicMock()
    for k, v in kwargs.items():
        setattr(edge, k, v)
    edge.uuid = kwargs.get("uuid", "fake-edge-uuid")
    return edge


class TestAddFileNode:
    """Verify add_file_node creates nodes and handles AST parsing."""

    @pytest.mark.asyncio
    @patch("loom.memory_engine.EntityNode", side_effect=_fake_entity_node)
    async def test_add_file_node_creates_node(self, mock_node_cls, memory, mock_graphiti):
        """Should call nodes.entity.save to persist the file node."""
        await memory.add_file_node("/some/file.py", "A test file")
        mock_graphiti.nodes.entity.save.assert_awaited()

    @pytest.mark.asyncio
    @patch("loom.memory_engine.EntityNode", side_effect=_fake_entity_node)
    async def test_add_file_node_nonexistent_file(self, mock_node_cls, memory, mock_graphiti):
        """Should create the node even if the file does not exist on disk (no AST parsing)."""
        node = await memory.add_file_node("/nonexistent/path.py", "Missing file")
        # The node is created via save, but no AST parsing children
        mock_graphiti.nodes.entity.save.assert_awaited_once()
        assert node is not None

    @pytest.mark.asyncio
    @patch("loom.memory_engine.EntityNode", side_effect=_fake_entity_node)
    async def test_add_file_node_returns_node_object(self, mock_node_cls, memory, mock_graphiti):
        """Should return the saved node object."""
        node = await memory.add_file_node("/some/file.py", "A test file")
        assert node is not None
        assert hasattr(node, "name") or hasattr(node, "uuid")

    @pytest.mark.asyncio
    @patch("loom.memory_engine.EntityEdge", side_effect=_fake_entity_edge)
    @patch("loom.memory_engine.EntityNode", side_effect=_fake_entity_node)
    async def test_add_file_node_parses_ast_children(self, mock_node_cls, mock_edge_cls, memory, mock_graphiti, tmp_path):
        """Should create child nodes and CONTAINS edges when file exists and has parseable code."""
        py_file = tmp_path / "example.py"
        py_file.write_text('def greet():\n    """Say hello."""\n    pass\n\nclass Greeter:\n    """A greeter."""\n    pass\n')

        await memory.add_file_node(str(py_file), "Example file with function and class")

        # 1 file node + 1 function + 1 class = 3 node saves
        assert mock_graphiti.nodes.entity.save.await_count == 3
        # 2 CONTAINS edges (file->function, file->class)
        assert mock_graphiti.edges.entity.save.await_count == 2

    @pytest.mark.asyncio
    @patch("loom.memory_engine.EntityNode", side_effect=_fake_entity_node)
    async def test_add_file_node_unsupported_extension_no_ast(self, mock_node_cls, memory, mock_graphiti, tmp_path):
        """Should create node but skip AST parsing for unsupported file types."""
        rb_file = tmp_path / "example.rb"
        rb_file.write_text("puts 'hello'\n")

        await memory.add_file_node(str(rb_file), "Ruby file")

        # Only 1 save (the file node itself, no AST children)
        assert mock_graphiti.nodes.entity.save.await_count == 1
        # No edges created
        mock_graphiti.edges.entity.save.assert_not_awaited()


class TestAddBugEdge:
    """Verify add_bug_edge creates HAS_BUG edges."""

    @pytest.mark.asyncio
    @patch("loom.memory_engine.EntityEdge", side_effect=_fake_entity_edge)
    async def test_add_bug_edge_creates_edge(self, mock_edge_cls, memory, mock_graphiti):
        """Should call edges.entity.save with a HAS_BUG edge."""
        edge = await memory.add_bug_edge("uuid-src", "uuid-file", "Null pointer bug")
        mock_graphiti.edges.entity.save.assert_awaited_once()
        saved_edge = mock_graphiti.edges.entity.save.call_args[0][0]
        assert saved_edge.name == "HAS_BUG"
        assert saved_edge.fact == "Null pointer bug"

    @pytest.mark.asyncio
    @patch("loom.memory_engine.EntityEdge", side_effect=_fake_entity_edge)
    async def test_add_bug_edge_returns_edge_object(self, mock_edge_cls, memory, mock_graphiti):
        """Should return the saved edge object."""
        edge = await memory.add_bug_edge("uuid-src", "uuid-file", "Bug desc")
        assert edge is not None


class TestBlackboardTransition:
    """Verify blackboard_transition invalidates edges atomically."""

    @pytest.mark.asyncio
    async def test_blackboard_transition_success(self, memory, mock_graphiti):
        """Should set invalid_at and save each found edge."""
        edge1 = MagicMock()
        edge1.invalid_at = None
        edge2 = MagicMock()
        edge2.invalid_at = None

        mock_graphiti.edges.entity.get_by_uuid = AsyncMock(
            side_effect=lambda uuid: {"uuid-1": edge1, "uuid-2": edge2}.get(uuid)
        )

        await memory.blackboard_transition(["uuid-1", "uuid-2"], "coder")

        assert edge1.invalid_at is not None
        assert isinstance(edge1.invalid_at, datetime)
        assert edge2.invalid_at is not None
        assert isinstance(edge2.invalid_at, datetime)
        assert mock_graphiti.edges.entity.save.await_count == 2

    @pytest.mark.asyncio
    async def test_blackboard_transition_missing_uuid(self, memory, mock_graphiti):
        """Should raise ValueError when an edge UUID is not found."""
        mock_graphiti.edges.entity.get_by_uuid = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="Edge UUIDs not found"):
            await memory.blackboard_transition(["nonexistent-uuid"], "coder")

    @pytest.mark.asyncio
    async def test_blackboard_transition_all_or_nothing(self, memory, mock_graphiti):
        """Should not mutate any edges if any UUID is missing (all-or-nothing check)."""
        edge1 = MagicMock()
        edge1.invalid_at = None

        mock_graphiti.edges.entity.get_by_uuid = AsyncMock(
            side_effect=lambda uuid: edge1 if uuid == "uuid-1" else None
        )

        with pytest.raises(ValueError):
            await memory.blackboard_transition(["uuid-1", "nonexistent"], "coder")

        # edge1 should NOT have been saved because the validation failed before mutation
        mock_graphiti.edges.entity.save.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_blackboard_transition_empty_list(self, memory, mock_graphiti):
        """Should succeed with no-op when given an empty list."""
        await memory.blackboard_transition([], "coder")
        mock_graphiti.edges.entity.save.assert_not_awaited()


# ---------------------------------------------------------------------------
# Path traversal protection
# ---------------------------------------------------------------------------


class TestPathValidation:
    """Verify _validate_file_path prevents traversal attacks."""

    def test_normal_path_allowed(self):
        """Normal relative paths should pass validation."""
        result = _validate_file_path("src/loom/server.py")
        assert result.name == "server.py"

    def test_absolute_path_allowed(self, tmp_path):
        """Absolute paths within allowed_root should pass."""
        test_file = tmp_path / "test.py"
        test_file.write_text("pass")
        result = _validate_file_path(str(test_file), allowed_root=str(tmp_path))
        assert result == test_file

    def test_traversal_blocked(self):
        """Paths with .. should be rejected."""
        with pytest.raises(ValueError, match="traversal"):
            _validate_file_path("src/../../etc/passwd")

    def test_traversal_outside_root_blocked(self, tmp_path):
        """Paths resolving outside allowed_root should be rejected."""
        with pytest.raises(ValueError, match="outside allowed root"):
            _validate_file_path("/etc/passwd", allowed_root=str(tmp_path))

    def test_no_root_allows_any_absolute(self):
        """Without allowed_root, absolute paths are allowed (traversal still blocked)."""
        result = _validate_file_path("/some/absolute/path.py")
        assert result.name == "path.py"


class TestAddFileNodeSecurity:
    """Verify add_file_node enforces path validation."""

    @pytest.fixture
    def secured_memory(self, mock_graphiti, tmp_path):
        """Memory engine with allowed_root set."""
        return LoomSwarmMemory(graphiti=mock_graphiti, allowed_root=str(tmp_path))

    @pytest.mark.asyncio
    @patch("loom.memory_engine.EntityNode", side_effect=_fake_entity_node)
    async def test_add_file_node_blocks_traversal(self, mock_cls, secured_memory):
        """Should reject file paths with .. traversal."""
        with pytest.raises(ValueError, match="traversal"):
            await secured_memory.add_file_node("../../etc/passwd", "Sensitive file")

    @pytest.mark.asyncio
    @patch("loom.memory_engine.EntityNode", side_effect=_fake_entity_node)
    async def test_add_file_node_blocks_outside_root(self, mock_cls, secured_memory):
        """Should reject absolute paths outside the allowed root."""
        with pytest.raises(ValueError, match="outside allowed root"):
            await secured_memory.add_file_node("/etc/shadow", "System file")

    @pytest.mark.asyncio
    @patch("loom.memory_engine.EntityNode", side_effect=_fake_entity_node)
    async def test_add_file_node_allows_valid_path(self, mock_cls, secured_memory, mock_graphiti, tmp_path):
        """Should accept files within the allowed root."""
        safe_file = tmp_path / "safe.py"
        safe_file.write_text("x = 1")
        node = await secured_memory.add_file_node(str(safe_file), "Safe file")
        assert node is not None


# ===========================================================================
# Expanded Tests: Local Insight Storage
# ===========================================================================


class TestAddLocalInsight:
    """Verify add_local_insight stores episodes with correct metadata."""

    @pytest.mark.asyncio
    async def test_add_local_insight_stores_episode(self, memory, mock_graphiti):
        """Should call Graphiti.add_episode with correct parameters."""
        mock_graphiti.add_episode = AsyncMock()
        await memory.add_local_insight(
            file_path="src/app.py",
            analysis="Found a potential null reference on line 42.",
            confidence="high",
            category="bug",
        )

        mock_graphiti.add_episode.assert_awaited_once()
        call_kwargs = mock_graphiti.add_episode.call_args.kwargs
        assert call_kwargs["name"] == "LocalInsight:src/app.py"
        assert "null reference" in call_kwargs["episode_body"]
        assert call_kwargs["source_description"] == "local_e2b|high|bug"

    @pytest.mark.asyncio
    async def test_add_local_insight_medium_confidence(self, memory, mock_graphiti):
        """Should correctly format source_description for medium confidence."""
        mock_graphiti.add_episode = AsyncMock()
        await memory.add_local_insight(
            file_path="src/utils.py",
            analysis="Style issue found",
            confidence="medium",
            category="pattern",
        )

        call_kwargs = mock_graphiti.add_episode.call_args.kwargs
        assert call_kwargs["source_description"] == "local_e2b|medium|pattern"

    @pytest.mark.asyncio
    async def test_add_local_insight_low_confidence_observation(self, memory, mock_graphiti):
        """Should correctly format source_description for low confidence observation."""
        mock_graphiti.add_episode = AsyncMock()
        await memory.add_local_insight(
            file_path="src/config.py",
            analysis="Code is well structured",
            confidence="low",
            category="observation",
        )

        call_kwargs = mock_graphiti.add_episode.call_args.kwargs
        assert call_kwargs["source_description"] == "local_e2b|low|observation"

    @pytest.mark.asyncio
    async def test_add_local_insight_security_category(self, memory, mock_graphiti):
        """Should correctly store security category insights."""
        mock_graphiti.add_episode = AsyncMock()
        await memory.add_local_insight(
            file_path="src/auth.py",
            analysis="SQL injection vulnerability on line 15",
            confidence="high",
            category="security",
        )

        call_kwargs = mock_graphiti.add_episode.call_args.kwargs
        assert call_kwargs["source_description"] == "local_e2b|high|security"
        assert "SQL injection" in call_kwargs["episode_body"]

    @pytest.mark.asyncio
    async def test_add_local_insight_has_reference_time(self, memory, mock_graphiti):
        """Should include a reference_time in the episode."""
        mock_graphiti.add_episode = AsyncMock()
        await memory.add_local_insight(
            file_path="src/app.py",
            analysis="Analysis text",
            confidence="high",
            category="bug",
        )

        call_kwargs = mock_graphiti.add_episode.call_args.kwargs
        assert "reference_time" in call_kwargs
        assert isinstance(call_kwargs["reference_time"], datetime)

    @pytest.mark.asyncio
    async def test_add_local_insight_uses_group_id(self, mock_graphiti):
        """Should use the memory engine's group_id for the episode."""
        mock_graphiti.add_episode = AsyncMock()
        mem = LoomSwarmMemory(graphiti=mock_graphiti, group_id="custom-group")
        await mem.add_local_insight(
            file_path="test.py",
            analysis="test",
            confidence="high",
            category="bug",
        )

        call_kwargs = mock_graphiti.add_episode.call_args.kwargs
        assert call_kwargs["group_id"] == "custom-group"


# ===========================================================================
# Expanded Tests: Context Extraction Detail
# ===========================================================================


class TestContextExtractionDetail:
    """Verify detailed aspects of get_context_for_coder."""

    @pytest.mark.asyncio
    async def test_get_context_extracts_local_insights(self, memory, mock_graphiti):
        """Should extract local insights from episodes with local_e2b source_description."""
        episode = MagicMock()
        episode.source_description = "local_e2b|high|bug"
        episode.content = "Found null reference"

        search_result = MagicMock()
        search_result.nodes = []
        search_result.edges = []
        search_result.episodes = [episode]
        mock_graphiti.search_ = AsyncMock(return_value=search_result)

        result = await memory.get_context_for_coder("src/app.py")

        assert len(result["local_insights"]) == 1
        assert result["local_insights"][0]["confidence"] == "high"
        assert result["local_insights"][0]["category"] == "bug"

    @pytest.mark.asyncio
    async def test_get_context_ignores_non_local_episodes(self, memory, mock_graphiti):
        """Should not include episodes without local_e2b prefix in local_insights."""
        episode = MagicMock()
        episode.source_description = "cloud_analysis"
        episode.content = "Cloud review"

        search_result = MagicMock()
        search_result.nodes = []
        search_result.edges = []
        search_result.episodes = [episode]
        mock_graphiti.search_ = AsyncMock(return_value=search_result)

        result = await memory.get_context_for_coder("src/app.py")

        assert len(result["local_insights"]) == 0

    @pytest.mark.asyncio
    async def test_get_context_handles_missing_source_description(self, memory, mock_graphiti):
        """Should handle episodes with no source_description attribute."""
        episode = MagicMock(spec=[])
        episode.source_description = None

        search_result = MagicMock()
        search_result.nodes = []
        search_result.edges = []
        search_result.episodes = [episode]
        mock_graphiti.search_ = AsyncMock(return_value=search_result)

        result = await memory.get_context_for_coder("src/app.py")

        # Should not crash — empty source_description means no local insight
        assert len(result["local_insights"]) == 0

    @pytest.mark.asyncio
    async def test_get_context_empty_results(self, memory, mock_graphiti):
        """Should return empty collections when search returns nothing."""
        search_result = MagicMock()
        search_result.nodes = []
        search_result.edges = []
        search_result.episodes = []
        mock_graphiti.search_ = AsyncMock(return_value=search_result)

        result = await memory.get_context_for_coder("nonexistent.py")

        assert result["nodes"] == []
        assert result["active_bugs"] == []
        assert result["raw_edges"] == []
        assert result["local_insights"] == []


# ===========================================================================
# Expanded Tests: Edge Cases
# ===========================================================================


class TestMemoryEdgeCases:
    """Verify behavior with unusual inputs and configurations."""

    def test_group_id_default(self, memory):
        """Should default group_id to 'default'."""
        assert memory.group_id == "default"

    def test_group_id_custom(self, mock_graphiti):
        """Should accept custom group_id."""
        mem = LoomSwarmMemory(graphiti=mock_graphiti, group_id="my-project")
        assert mem.group_id == "my-project"

    def test_allowed_root_stored(self, mock_graphiti, tmp_path):
        """Should store allowed_root when provided."""
        mem = LoomSwarmMemory(graphiti=mock_graphiti, allowed_root=str(tmp_path))
        assert mem.allowed_root == str(tmp_path)

    def test_allowed_root_none_by_default(self, memory):
        """Should default allowed_root to None."""
        assert memory.allowed_root is None
