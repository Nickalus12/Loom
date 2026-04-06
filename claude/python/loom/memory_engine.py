import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum file size to read for AST parsing (10 MB)
_MAX_FILE_SIZE = 10 * 1024 * 1024


def _validate_file_path(file_path: str, allowed_root: str | None = None) -> Path:
    """Validate and resolve a file path, preventing path traversal attacks.

    Raises ValueError if the path contains traversal sequences or escapes
    the allowed root directory.
    """
    resolved = Path(file_path).resolve()

    # Block obvious traversal patterns in the original input
    if ".." in Path(file_path).parts:
        raise ValueError(f"Path traversal detected in file_path: {file_path}")

    # If an allowed root is configured, enforce containment
    if allowed_root is not None:
        root = Path(allowed_root).resolve()
        if not str(resolved).startswith(str(root)):
            raise ValueError(
                f"file_path '{file_path}' resolves outside allowed root '{root}'"
            )

    return resolved
from graphiti_core import Graphiti
from graphiti_core.llm_client import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.nodes import EntityNode, EpisodeType
from graphiti_core.edges import EntityEdge
from graphiti_core.errors import EdgeNotFoundError
from graphiti_core.search.search_config import SearchConfig

from loom.ast_parser import ASTParser

class LoomSwarmMemory:
    def __init__(self, graphiti: "Graphiti | None" = None, group_id: str = "default", allowed_root: str | None = None):
        self.group_id = group_id
        self.allowed_root = allowed_root
        if graphiti is not None:
            self.memory = graphiti
        else:
            litellm_key = os.getenv("LITELLM_MASTER_KEY")
            neo4j_password = os.getenv("NEO4J_PASSWORD")

            if not litellm_key:
                raise ValueError("LITELLM_MASTER_KEY environment variable is missing")
            if not neo4j_password:
                raise ValueError("NEO4J_PASSWORD environment variable is missing")

            llm_config = LLMConfig(
                base_url="http://localhost:4000/v1",
                api_key=litellm_key,
                model=os.getenv("LOOM_HEAVY_MODEL", "heavy/*")
            )
            self.llm_client = OpenAIGenericClient(config=llm_config)

            embedder_config = OpenAIEmbedderConfig(
                base_url="http://localhost:4000/v1",
                api_key=litellm_key,
                embedding_model="gemini-embedding-2-preview",
                embedding_dim=768
            )
            self.embedder = OpenAIEmbedder(config=embedder_config)

            self.reranker = OpenAIRerankerClient(client=self.llm_client, config=llm_config)

            self.memory = Graphiti(
                uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
                user=os.getenv("NEO4J_USER", "neo4j"),
                password=neo4j_password,
                llm_client=self.llm_client,
                embedder=self.embedder,
                cross_encoder=self.reranker
            )

        self.ast_parser = ASTParser()

    async def build_indices_and_constraints(self):
        """
        Ensures indices and constraints are created in Neo4j.
        """
        await self.memory.build_indices_and_constraints()

    async def close(self):
        """
        Closes the underlying Neo4j driver.
        """
        await self.memory.close()

    async def get_context_for_coder(self, target_file: str) -> dict:
        """
        Executes a search centered on the target file
        to retrieve temporal context before the Coder acts.
        """
        search_query = f"Retrieve architectural context, dependencies, and active bugs for {target_file}"
        
        results = await self.memory.search_(
            query=search_query,
            config=SearchConfig(limit=15),
        )
        
        # Filter for active bugs (where invalid_at is None and name is HAS_BUG)
        active_bugs = [
            edge for edge in results.edges
            if edge.name == "HAS_BUG" and edge.invalid_at is None
        ]

        local_insights = []
        for episode in results.episodes:
            sd = getattr(episode, "source_description", None) or ""
            if sd.startswith("local_e2b|"):
                parts = sd.split("|")
                local_insights.append({
                    "fact": getattr(episode, "content", str(episode)),
                    "confidence": parts[1] if len(parts) > 1 else "unknown",
                    "category": parts[2] if len(parts) > 2 else "unknown",
                })

        return {
            "nodes": results.nodes,
            "active_bugs": active_bugs,
            "raw_edges": results.edges,
            "local_insights": local_insights,
        }

    async def blackboard_transition(self, edge_uuids: list[str], agent_name: str):
        """
        Implements Step 3 of the Blackboard SOP.
        The Coder fixes the bug and invalidates the old 'HAS_BUG' edges temporally.

        All edge UUIDs are validated before any mutation begins. If any UUID is
        missing, a ValueError is raised and no edges are modified. However, the
        save phase is not transactional — if a save fails partway through, earlier
        edges may already be persisted as invalidated. This is acceptable because
        re-invalidating an already-invalidated edge is idempotent.
        """
        edges = []
        missing = []
        for uuid in edge_uuids:
            try:
                edge = await self.memory.edges.entity.get_by_uuid(uuid)
            except EdgeNotFoundError:
                edge = None
            if edge is None:
                missing.append(uuid)
            else:
                edges.append(edge)
        if missing:
            raise ValueError(f"Edge UUIDs not found: {missing}")
        for edge in edges:
            edge.invalid_at = datetime.now(timezone.utc)
            await self.memory.edges.entity.save(edge)
        logger.info("Temporal state updated. %d bugs resolved by %s.", len(edges), agent_name)

    async def add_file_node(self, file_path: str, summary: str):
        """
        Adds a file node and its AST children (functions/classes) to the memory graph.

        Validates file_path against traversal attacks and optionally enforces
        that it resides within allowed_root. Skips AST parsing for files
        larger than 10 MB or that don't exist on disk.
        """
        resolved = _validate_file_path(file_path, self.allowed_root)

        file_node = EntityNode(name=file_path, summary=summary, labels=["File"], group_id=self.group_id)
        file_node = await self.memory.nodes.entity.save(file_node)

        if resolved.is_file():
            file_size = resolved.stat().st_size
            if file_size > _MAX_FILE_SIZE:
                logger.warning("Skipping AST parsing for %s (%d bytes > %d limit)", file_path, file_size, _MAX_FILE_SIZE)
                return file_node

            with open(resolved, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()

            entities = self.ast_parser.parse_file(file_path, content)

            for ent in entities:
                child_node = EntityNode(name=ent["name"], summary=ent["summary"], labels=[ent["type"]], group_id=self.group_id)
                child_node = await self.memory.nodes.entity.save(child_node)

                contains_edge = EntityEdge(
                    source_node_uuid=file_node.uuid,
                    target_node_uuid=child_node.uuid,
                    name="CONTAINS",
                    fact=f"File {file_path} contains {ent['type']} {ent['name']}",
                    group_id=self.group_id,
                    created_at=datetime.now(timezone.utc),
                )
                await self.memory.edges.entity.save(contains_edge)

        return file_node

    async def add_bug_edge(self, source_node_uuid: str, file_node_uuid: str, bug_description: str):
        """
        Adds a HAS_BUG edge between a source node and a file node.
        """
        edge = EntityEdge(
            source_node_uuid=source_node_uuid,
            target_node_uuid=file_node_uuid,
            name="HAS_BUG",
            fact=bug_description,
            group_id=self.group_id,
            created_at=datetime.now(timezone.utc),
        )
        return await self.memory.edges.entity.save(edge)

    async def add_local_insight(
        self,
        file_path: str,
        analysis: str,
        confidence: str,
        category: str,
    ) -> None:
        """
        Writes a local model analysis insight as a Graphiti episode.

        Args:
            file_path: Path of the analyzed file.
            analysis: The analysis text from the local model.
            confidence: Confidence level (high/medium/low).
            category: Analysis type (bug/security/pattern/observation).
        """
        await self.memory.add_episode(
            name=f"LocalInsight:{file_path}",
            episode_body=analysis,
            source=EpisodeType.text,
            reference_time=datetime.now(timezone.utc),
            source_description=f"local_e2b|{confidence}|{category}",
            group_id=self.group_id,
        )
