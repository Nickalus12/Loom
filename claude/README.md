# Loom Plugin for Claude Code

[![Silk 1.0](https://img.shields.io/badge/Silk-1.0-C9A96E?style=for-the-badge&labelColor=2D1B0E)](https://github.com/Nickalus12/Loom)
[![License](https://img.shields.io/badge/license-Apache_2.0-blue?style=flat-square)](LICENSE)

Multi-agent orchestration with Dynamic Agent Fabric, local Ollama agents, 3-tier safety, and knowledge graph memory.

## Quick Install

```bash
# Option A: Clone just the plugin directory
git clone --depth 1 https://github.com/Nickalus12/Loom.git /tmp/loom-temp
cp -r /tmp/loom-temp/claude ~/.claude/plugins/loom
rm -rf /tmp/loom-temp

# Launch with Loom
claude --plugin-dir ~/.claude/plugins/loom
```

```bash
# Option B: Clone full repo and point at it
git clone https://github.com/Nickalus12/Loom.git ~/loom
claude --plugin-dir ~/loom/claude
```

## Make It Permanent

Add to `~/.claude/settings.json`:
```json
{
  "plugins": ["~/.claude/plugins/loom"]
}
```

Then just run `claude` — Loom loads automatically.

## Prerequisites

| Requirement | Install | What It Enables |
|-------------|---------|----------------|
| **Python 3.12+** | System | Python MCP server (42 tools) |
| **pip deps** | `pip install graphiti-core litellm mcp python-dotenv rich` | Full functionality |
| **Ollama** | [ollama.com](https://ollama.com) | Local agent |
| **qwen3:4b** | `ollama pull qwen3:4b` | Tool-calling model |
| **Node.js 18+** | System | Session management MCP |

Optional: Neo4j (memory), NIA_API_KEY (codebase grounding), GEMINI_API_KEY (cloud routing)

## Commands

| Command | Purpose |
|---------|---------|
| `/loom:craft` | Multi-agent pipeline (architect + audit + code + review) |
| `/loom:agent` | Local Ollama agent with tool-calling |
| `/loom:review` | Code review |
| `/loom:debug` | Root cause investigation |
| `/loom:security-audit` | Security scan |
| `/loom:perf-check` | Performance analysis |
| `/loom:a11y-audit` | Accessibility audit |
| `/loom:compliance-check` | Regulatory review |
| `/loom:status` | Session status |
| `/loom:resume` | Resume session |
| `/loom:execute` | Execute plan |
| `/loom:archive` | Archive session |

## What's Included

```
claude/
  .claude-plugin/plugin.json    Manifest
  .mcp.json                     3 MCP servers
  CLAUDE.md                     System context
  mcp/loom-server.js            Node.js MCP server
  python/loom/                   Python MCP server (42 tools)
  skills/ (21)                   Orchestration skills
  agents/ (22)                   Agent definitions
  traits/ (36)                   Composable DAF traits
  hooks/ (6)                     Lifecycle hooks
  scripts/                       Hook executors
  lib/                           Shared libraries
```

## License

Apache-2.0 | [Nickalus Brewer](https://github.com/Nickalus12)
