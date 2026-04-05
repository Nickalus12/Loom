"""Unit tests for the AgentRegistry and AgentConfig."""

import pytest
from loom.agent_registry import AgentRegistry, AgentConfig, HEAVY_AGENTS, LOCAL_AGENTS


class TestAgentRegistry:
    """Verify AgentRegistry loads and queries agent definitions."""

    @pytest.fixture(autouse=True)
    def registry(self):
        self.reg = AgentRegistry()

    def test_loads_all_agents(self):
        """Should load exactly 24 agents from the agents/ directory."""
        assert len(self.reg) == 24

    def test_list_agents_sorted(self):
        """Should return sorted list of agent names."""
        names = self.reg.list_agents()
        assert names == sorted(names)
        assert "architect" in names
        assert "coder" in names
        assert "tester" in names

    def test_get_existing_agent(self):
        """Should return AgentConfig for a known agent."""
        config = self.reg.get("architect")
        assert isinstance(config, AgentConfig)
        assert config.name == "architect"

    def test_get_missing_agent_raises(self):
        """Should raise KeyError for unknown agent names."""
        with pytest.raises(KeyError, match="nonexistent"):
            self.reg.get("nonexistent")

    def test_contains(self):
        """Should support `in` operator."""
        assert "coder" in self.reg
        assert "nonexistent" not in self.reg

    def test_agent_has_methodology(self):
        """Every agent should have non-empty methodology text."""
        for name in self.reg.list_agents():
            config = self.reg.get(name)
            assert len(config.methodology) > 50, f"{name} has empty/short methodology"

    def test_agent_has_tools(self):
        """Every agent should have at least one tool."""
        for name in self.reg.list_agents():
            config = self.reg.get(name)
            assert len(config.tools) >= 1, f"{name} has no tools"

    def test_agent_temperature_range(self):
        """Temperature should be between 0 and 1."""
        for name in self.reg.list_agents():
            config = self.reg.get(name)
            assert 0.0 <= config.temperature <= 1.0, f"{name} temp={config.temperature}"

    def test_heavy_agents_set(self):
        """All HEAVY_AGENTS should exist and be classified correctly."""
        for name in HEAVY_AGENTS:
            assert name in self.reg, f"HEAVY_AGENTS lists {name} but it's not in registry"
            config = self.reg.get(name)
            assert config.tier == "heavy", f"{name} should be heavy tier"

    def test_tier_classification(self):
        """Agents should be classified into heavy, light, or local tiers."""
        heavy = self.reg.get_by_tier("heavy")
        light = self.reg.get_by_tier("light")
        local = self.reg.get_by_tier("local")
        assert len(heavy) + len(light) + len(local) == 24
        assert len(heavy) == len(HEAVY_AGENTS)
        assert len(local) == len(LOCAL_AGENTS)
        for config in heavy:
            assert config.name in HEAVY_AGENTS
        for config in light:
            assert config.name not in HEAVY_AGENTS
            assert config.name not in LOCAL_AGENTS
        for config in local:
            assert config.name in LOCAL_AGENTS

    def test_get_by_tier_heavy(self):
        """Should return only heavy-tier agents."""
        heavy = self.reg.get_by_tier("heavy")
        assert all(c.tier == "heavy" for c in heavy)

    def test_get_by_tier_light(self):
        """Should return only light-tier agents."""
        light = self.reg.get_by_tier("light")
        assert all(c.tier == "light" for c in light)

    def test_architect_properties(self):
        """Spot-check architect agent properties."""
        arch = self.reg.get("architect")
        assert arch.tier == "heavy"
        assert arch.temperature == 0.3
        assert arch.max_turns == 15
        assert arch.timeout_mins == 5
        assert "read_file" in arch.tools or "read" in arch.tools

    def test_coder_properties(self):
        """Spot-check coder agent properties."""
        coder = self.reg.get("coder")
        assert coder.tier == "heavy"
        assert coder.temperature == 0.2
        assert coder.max_turns == 25

    def test_code_reviewer_is_read_only(self):
        """Code reviewer should not have write tools."""
        cr = self.reg.get("code_reviewer")
        assert cr.tier == "light"
        assert "write_file" not in cr.tools
        assert "write" not in cr.tools
        assert "replace" not in cr.tools
