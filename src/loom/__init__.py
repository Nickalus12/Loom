"""Loom — Multi-agent swarm orchestrator for Claude Code and Gemini CLI."""

from loom.memory_engine import LoomSwarmMemory
from loom.orchestrator import LoomOrchestrator, Phase, SwarmPlan
from loom.ast_parser import ASTParser
from loom.local_inference import LocalInferenceEngine
from loom.protocols import LanguageParser, MemoryBackend
from loom.powershell_tools import PowerShellKANEngine, PowerShellREPLManager
from loom.runtime import RuntimeCapabilities, get_runtime

__all__ = [
    "LoomSwarmMemory",
    "LoomOrchestrator",
    "Phase",
    "SwarmPlan",
    "ASTParser",
    "LocalInferenceEngine",
    "LanguageParser",
    "MemoryBackend",
    "PowerShellKANEngine",
    "PowerShellREPLManager",
    "RuntimeCapabilities",
    "get_runtime",
]
