import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

HEAVY_AGENTS = frozenset({
    "architect",
    "coder",
    "debugger",
    "refactor",
    "security_engineer",
    "api_designer",
})

LOCAL_AGENTS = frozenset({
    "local_analyst",
    "local_creative",
})

_DEFAULT_AGENTS_DIR = Path(__file__).resolve().parents[2] / "agents"


@dataclass(frozen=True, slots=True)
class AgentConfig:
    name: str
    description: str
    tools: list[str]
    temperature: float
    max_turns: int
    timeout_mins: int
    tier: str
    methodology: str


def _parse_agent_file(path: Path) -> AgentConfig | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Unable to read agent file %s: %s", path, exc)
        return None

    parts = raw.split("---", 2)
    if len(parts) < 3:
        logger.warning("Agent file %s has invalid frontmatter (missing --- delimiters)", path)
        return None

    try:
        meta = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        logger.warning("Agent file %s has malformed YAML frontmatter: %s", path, exc)
        return None

    if not isinstance(meta, dict):
        logger.warning("Agent file %s frontmatter is not a mapping", path)
        return None

    name = meta.get("name", path.stem)

    if name in LOCAL_AGENTS:
        default_tier = "local"
    elif name in HEAVY_AGENTS:
        default_tier = "heavy"
    else:
        default_tier = "light"
    tier = default_tier

    return AgentConfig(
        name=name,
        description=meta.get("description", ""),
        tools=meta.get("tools", []),
        temperature=float(meta.get("temperature", 0.2)),
        max_turns=int(meta.get("max_turns", 20)),
        timeout_mins=int(meta.get("timeout_mins", 8)),
        tier=tier,
        methodology=parts[2].strip(),
    )


class AgentRegistry:
    """Loads and manages agent definitions from Markdown files with YAML frontmatter."""

    def __init__(self, agents_dir: str | Path | None = None):
        self._agents: dict[str, AgentConfig] = {}
        directory = Path(agents_dir) if agents_dir is not None else _DEFAULT_AGENTS_DIR

        if not directory.is_dir():
            logger.warning("Agents directory does not exist: %s", directory)
            return

        for md_path in sorted(directory.glob("*.md")):
            config = _parse_agent_file(md_path)
            if config is not None:
                self._agents[config.name] = config

        logger.info("AgentRegistry loaded %d agents from %s", len(self._agents), directory)

    def get(self, name: str) -> AgentConfig:
        try:
            return self._agents[name]
        except KeyError:
            available = ", ".join(sorted(self._agents))
            raise KeyError(
                f"Agent '{name}' not found. Available agents: {available}"
            ) from None

    def list_agents(self) -> list[str]:
        return sorted(self._agents)

    def get_by_tier(self, tier: str) -> list[AgentConfig]:
        return [agent for agent in self._agents.values() if agent.tier == tier]

    def __len__(self) -> int:
        return len(self._agents)

    def __contains__(self, name: object) -> bool:
        return name in self._agents

    def __repr__(self) -> str:
        return f"AgentRegistry(agents={len(self._agents)})"
