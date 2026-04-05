import asyncio
import os
import sys
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from pydantic import Field

# Load environment variables from the project root
load_dotenv(dotenv_path=os.path.join(os.getcwd(), "..", ".env"))

# Import our modular logic
from loom.memory_engine import LoomSwarmMemory
from loom.orchestrator import LoomOrchestrator

# Initialize the FastMCP Server
mcp = FastMCP(
    "Loom Enterprise Swarm",
    dependencies=["mcp", "litellm", "graphiti-core", "python-dotenv", "tree-sitter", "tree-sitter-python"]
)

# Initialize engines
memory_engine = LoomSwarmMemory()
swarm_orchestrator = LoomOrchestrator(memory_engine)

@mcp.tool()
async def orchestrate_swarm(task: str = Field(description="The complex engineering task to execute via the 22-agent swarm.")) -> str:
    """
    Triggers the high-level Loom orchestration workflow. 
    Use this to start a multi-agent reasoning session for features, bugs, or refactors.
    """
    try:
        await memory_engine.build_indices_and_constraints()
        await swarm_orchestrator.execute_swarm(task)
        return "Swarm orchestration completed successfully."
    except Exception as e:
        return f"Orchestration failed: {str(e)}"

@mcp.tool()
async def get_context_for_coder(target_file: str = Field(description="The file path to retrieve context and bugs for.")) -> dict:
    """
    Retrieves temporal context, dependencies, and active bugs for a specific file.
    Mandatory for the Coder agent before starting any work.
    """
    return await memory_engine.get_context_for_coder(target_file)

@mcp.tool()
async def add_file_node(file_path: str, summary: str) -> str:
    """
    Creates a node in Graphiti for a file. 
    In V3, this automatically triggers AST parsing to identify functions and classes.
    """
    node = await memory_engine.add_file_node(file_path, summary)
    return f"File node created: {node.uuid}"

@mcp.tool()
async def add_bug_edge(source_uuid: str, file_uuid: str, description: str) -> str:
    """Records a HAS_BUG relationship in the temporal knowledge graph."""
    edge = await memory_engine.add_bug_edge(source_uuid, file_uuid, description)
    return f"Bug recorded: {edge.uuid}"

@mcp.tool()
async def blackboard_transition(edge_uuids: list[str], agent_name: str) -> str:
    """Invalidates bug edges after a fix, preserving historical state."""
    await memory_engine.blackboard_transition(edge_uuids, agent_name)
    return "Blackboard state transitioned."

if __name__ == "__main__":
    # Start the MCP server using stdio transport
    mcp.run()
