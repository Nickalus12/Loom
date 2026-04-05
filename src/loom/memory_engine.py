import os
import sys
from datetime import datetime, timezone
from graphiti_core import Graphiti
from graphiti_core.llm_client import LLMConfig
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient
from graphiti_core.embedder import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.cross_encoder.openai_reranker_client import OpenAIRerankerClient
from graphiti_core.nodes import EntityNode
from graphiti_core.edges import EntityEdge

from loom.ast_parser import ASTParser

class LoomSwarmMemory:
    def __init__(self):
        litellm_key = os.getenv("LITELLM_MASTER_KEY")
        neo4j_password = os.getenv("NEO4J_PASSWORD")
        
        if not litellm_key:
            raise ValueError("LITELLM_MASTER_KEY environment variable is missing")
        if not neo4j_password:
            raise ValueError("NEO4J_PASSWORD environment variable is missing")

        # 1. Initialize LLM Config and Client
        llm_config = LLMConfig(
            base_url="http://localhost:4000/v1",
            api_key=litellm_key,
            model=os.getenv("LOOM_HEAVY_MODEL", "heavy/*")
        )
        self.llm_client = OpenAIGenericClient(config=llm_config)
        
        # 2. Initialize Embedder Config and Client
        embedder_config = OpenAIEmbedderConfig(
            base_url="http://localhost:4000/v1",
            api_key=litellm_key,
            model="gemini-embedding-2-preview",
            embedding_dim=1536  # Upgraded to recommended dimensionality for multimodal embeddings
        )
        self.embedder = OpenAIEmbedder(config=embedder_config)

        # 3. Initialize Reranker
        self.reranker = OpenAIRerankerClient(client=self.llm_client, config=llm_config)

        # 4. Initialize Graphiti with Neo4j, LLM Client, Embedder, and Reranker
        # Do NOT pass model to Graphiti.
        self.memory = Graphiti(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=neo4j_password,
            llm_client=self.llm_client,
            embedder=self.embedder,
            cross_encoder=self.reranker
        )
        
        # 5. Initialize AST Parser
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
        
        # Perform search using search_
        results = await self.memory.search_(
            query=search_query,
            limit=15
        )
        
        # Filter for active bugs (where invalid_at is None and name is HAS_BUG)
        active_bugs = [
            edge for edge in results.edges 
            if edge.name == "HAS_BUG" and edge.invalid_at is None
        ]
        
        return {
            "nodes": results.nodes,
            "active_bugs": active_bugs,
            "raw_edges": results.edges
        }

    async def blackboard_transition(self, edge_uuids: list[str], agent_name: str):
        """
        Implements Step 3 of the Blackboard SOP.
        The Coder fixes the bug and invalidates the old 'HAS_BUG' edges temporally.
        """
        for edge_uuid in edge_uuids:
            edge = await self.memory.edges.entity.get_by_uuid(edge_uuid)
            if edge:
                edge.invalid_at = datetime.now(timezone.utc)
                # We can also add attributes if needed, but the prompt only specified invalid_at
                await self.memory.edges.entity.save(edge)
        
        print(f"[Loom Memory] Temporal state updated. {len(edge_uuids)} bugs resolved by {agent_name}.", file=sys.stderr)

    async def add_file_node(self, file_path: str, summary: str):
        """
        Adds a file node and its AST children (functions/classes) to the memory graph.
        """
        # 1. Create the File node
        file_node = EntityNode(name=file_path, summary=summary, labels=["File"])
        file_node = await self.memory.nodes.entity.save(file_node)
        
        # 2. If it's a Python file, parse the AST
        if file_path.endswith(".py") and os.path.exists(file_path):
            with open(file_path, "r") as f:
                content = f.read()
                
            entities = self.ast_parser.parse_python_file(content)
            
            for ent in entities:
                # Create Child Node (Function/Class)
                child_node = EntityNode(name=ent["name"], summary=ent["summary"], labels=[ent["type"]])
                child_node = await self.memory.nodes.entity.save(child_node)
                
                # Link to File Node
                contains_edge = EntityEdge(
                    source_node_uuid=file_node.uuid,
                    target_node_uuid=child_node.uuid,
                    name="CONTAINS",
                    fact=f"File {file_path} contains {ent['type']} {ent['name']}"
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
            fact=bug_description
        )
        return await self.memory.edges.entity.save(edge)
