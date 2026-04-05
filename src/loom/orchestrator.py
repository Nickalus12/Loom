import asyncio
import os
from litellm import acompletion
from loom.memory_engine import LoomSwarmMemory

class LoomOrchestrator:
    def __init__(self, memory_engine: LoomSwarmMemory):
        self.proxy_base = "http://localhost:4000/v1"
        self.memory = memory_engine

    async def dispatch_agent(self, agent_name: str, tier: str, system_prompt: str, task: str):
        """
        Dispatches an agent through the LiteLLM proxy using the designated tier (heavy/light).
        The proxy handles Azure Foundry 429 fallbacks to Ollama automatically.
        """
        model_string = f"openai/{tier}/*"
        
        print(f"[Swarm] Dispatching {agent_name} to {tier} tier...")
        
        response = await acompletion(
            model=model_string,
            api_base=self.proxy_base,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task}
            ],
            temperature=0.2
        )
        return response.choices[0].message.content

    async def execute_swarm(self, prompt: str):
        print(f"\n--- INITIALIZING LOOM SWARM V3 ---")
        print(f"Task: {prompt}")
        
        # Step 1: Architect (Heavy) - Create initial graph nodes
        # In V3, this will trigger AST parsing if files are referenced
        architect_prompt = "You are the Architect. Use MCP tools to analyze the project structure and create nodes for relevant files and features."
        arch_plan = await self.dispatch_agent("architect", "heavy", architect_prompt, prompt)
        
        # Phase 2: Parallel Audits (Simulated batch for V3 demo)
        print("--- LAUNCHING PARALLEL AUDITS ---")
        audit_tasks = [
            self.dispatch_agent("security_engineer", "heavy", "Identify security vulnerabilities and record them in memory.", arch_plan),
            self.dispatch_agent("qa_tester", "light", "Identify logic flaws and record them in memory.", arch_plan)
        ]
        await asyncio.gather(*audit_tasks)
        
        # Phase 3: Coder (Heavy) - Resolve issues
        print("--- LAUNCHING CODER (EVOLVE PHASE) ---")
        coder_prompt = "You are the Coder. Query memory to see active bugs, fix them, and transition the blackboard."
        await self.dispatch_agent("coder", "heavy", coder_prompt, f"Implement fixes for: {prompt}")
        
        print("\n--- SWARM EXECUTION COMPLETE ---")
