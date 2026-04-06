"""Unit tests for the Dynamic Agent Fabric trait index.

Validates actual trait files on disk: YAML frontmatter structure, required fields,
correct counts, cross-references, and conflict/requires integrity.
"""

import os
from pathlib import Path

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TRAITS_DIR = Path(__file__).resolve().parents[2] / "traits"
CATEGORIES = {
    "archetypes": ".archetype.md",
    "capabilities": ".trait.md",
    "constraints": ".trait.md",
    "output-contracts": ".trait.md",
}


def _parse_frontmatter(filepath: Path) -> dict | None:
    """Parse YAML frontmatter from a trait file."""
    content = filepath.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None
    end = content.index("---", 3)
    yaml_block = content[3:end].strip()
    return yaml.safe_load(yaml_block)


def _collect_traits(category: str, extension: str) -> list[tuple[str, dict]]:
    """Return list of (filename, frontmatter_dict) for a trait category."""
    folder = TRAITS_DIR / category
    if not folder.exists():
        return []
    results = []
    for f in sorted(folder.iterdir()):
        if f.name.endswith(extension):
            meta = _parse_frontmatter(f)
            if meta is not None:
                results.append((f.name, meta))
    return results


def _all_traits() -> list[tuple[str, str, dict]]:
    """Return (category, filename, meta) for every trait across all categories."""
    all_items = []
    for category, ext in CATEGORIES.items():
        for filename, meta in _collect_traits(category, ext):
            all_items.append((category, filename, meta))
    return all_items


ALL_TRAITS = _all_traits()
ARCHETYPES = _collect_traits("archetypes", ".archetype.md")
CAPABILITIES = _collect_traits("capabilities", ".trait.md")
CONSTRAINTS = _collect_traits("constraints", ".trait.md")
OUTPUT_CONTRACTS = _collect_traits("output-contracts", ".trait.md")


# ---------------------------------------------------------------------------
# Frontmatter validity
# ---------------------------------------------------------------------------


class TestArchetypeFrontmatter:
    """Verify all archetype files have valid YAML frontmatter with required fields."""

    @pytest.mark.parametrize("filename,meta", ARCHETYPES, ids=[a[0] for a in ARCHETYPES])
    def test_archetype_has_valid_frontmatter(self, filename, meta):
        assert meta is not None, f"{filename} has no parseable frontmatter"
        assert "name" in meta, f"{filename} missing 'name'"
        assert "description" in meta, f"{filename} missing 'description'"
        assert "allowed_tools" in meta, f"{filename} missing 'allowed_tools'"
        assert "forbidden_tools" in meta or "forbids_tools" in meta or isinstance(meta.get("allowed_tools"), list), (
            f"{filename} missing tool configuration"
        )


class TestCapabilityFrontmatter:
    """Verify all capability trait files have valid YAML frontmatter."""

    @pytest.mark.parametrize("filename,meta", CAPABILITIES, ids=[c[0] for c in CAPABILITIES])
    def test_capability_has_valid_frontmatter(self, filename, meta):
        assert meta is not None, f"{filename} has no parseable frontmatter"
        assert "name" in meta, f"{filename} missing 'name'"
        assert "category" in meta, f"{filename} missing 'category'"
        assert meta["category"] == "capability", f"{filename} category should be 'capability', got '{meta['category']}'"
        assert "description" in meta, f"{filename} missing 'description'"


class TestConstraintFrontmatter:
    """Verify all constraint trait files have valid YAML frontmatter."""

    @pytest.mark.parametrize("filename,meta", CONSTRAINTS, ids=[c[0] for c in CONSTRAINTS])
    def test_constraint_has_valid_frontmatter(self, filename, meta):
        assert meta is not None, f"{filename} has no parseable frontmatter"
        assert "name" in meta, f"{filename} missing 'name'"
        assert "category" in meta, f"{filename} missing 'category'"
        assert meta["category"] == "constraint", f"{filename} category should be 'constraint', got '{meta['category']}'"
        assert "description" in meta, f"{filename} missing 'description'"


class TestOutputContractFrontmatter:
    """Verify all output-contract trait files have valid YAML frontmatter."""

    @pytest.mark.parametrize("filename,meta", OUTPUT_CONTRACTS, ids=[o[0] for o in OUTPUT_CONTRACTS])
    def test_output_contract_has_valid_frontmatter(self, filename, meta):
        assert meta is not None, f"{filename} has no parseable frontmatter"
        assert "name" in meta, f"{filename} missing 'name'"
        assert "category" in meta, f"{filename} missing 'category'"
        assert meta["category"] == "output-contract", (
            f"{filename} category should be 'output-contract', got '{meta['category']}'"
        )
        assert "description" in meta, f"{filename} missing 'description'"


# ---------------------------------------------------------------------------
# Exact counts
# ---------------------------------------------------------------------------


class TestTraitCounts:
    """Verify exact trait counts per category to detect accidental additions or deletions."""

    def test_archetype_count(self):
        assert len(ARCHETYPES) == 4, (
            f"Expected 4 archetypes, found {len(ARCHETYPES)}: {[a[0] for a in ARCHETYPES]}"
        )

    def test_trait_count_capabilities(self):
        assert len(CAPABILITIES) == 21, (
            f"Expected 21 capability traits, found {len(CAPABILITIES)}: {[c[0] for c in CAPABILITIES]}"
        )

    def test_trait_count_constraints(self):
        assert len(CONSTRAINTS) == 6, (
            f"Expected 6 constraint traits, found {len(CONSTRAINTS)}: {[c[0] for c in CONSTRAINTS]}"
        )

    def test_trait_count_output_contracts(self):
        assert len(OUTPUT_CONTRACTS) == 5, (
            f"Expected 5 output contracts, found {len(OUTPUT_CONTRACTS)}: {[o[0] for o in OUTPUT_CONTRACTS]}"
        )


# ---------------------------------------------------------------------------
# Required fields across all traits
# ---------------------------------------------------------------------------


class TestRequiredFields:
    """Verify all traits have mandatory fields regardless of category."""

    @pytest.mark.parametrize(
        "category,filename,meta",
        ALL_TRAITS,
        ids=[f"{t[0]}/{t[1]}" for t in ALL_TRAITS],
    )
    def test_all_traits_have_name_field(self, category, filename, meta):
        assert "name" in meta, f"{category}/{filename} missing 'name' field"

    @pytest.mark.parametrize(
        "category,filename,meta",
        [t for t in ALL_TRAITS if t[0] != "archetypes"],
        ids=[f"{t[0]}/{t[1]}" for t in ALL_TRAITS if t[0] != "archetypes"],
    )
    def test_all_non_archetype_traits_have_category_field(self, category, filename, meta):
        assert "category" in meta, f"{category}/{filename} missing 'category' field"

    @pytest.mark.parametrize(
        "category,filename,meta",
        ALL_TRAITS,
        ids=[f"{t[0]}/{t[1]}" for t in ALL_TRAITS],
    )
    def test_all_traits_have_description_field(self, category, filename, meta):
        assert "description" in meta, f"{category}/{filename} missing 'description' field"
        assert len(str(meta["description"]).strip()) > 0, f"{category}/{filename} has empty description"

    @pytest.mark.parametrize(
        "filename,meta",
        CAPABILITIES,
        ids=[c[0] for c in CAPABILITIES],
    )
    def test_all_capability_traits_have_requires_tools(self, filename, meta):
        assert "requires_tools" in meta, f"{filename} missing 'requires_tools' field"

    @pytest.mark.parametrize(
        "filename,meta",
        CAPABILITIES,
        ids=[c[0] for c in CAPABILITIES],
    )
    def test_all_capability_traits_have_archetypes(self, filename, meta):
        assert "archetypes" in meta, f"{filename} missing 'archetypes' field"
        assert isinstance(meta["archetypes"], list), f"{filename} 'archetypes' should be a list"
        assert len(meta["archetypes"]) > 0, f"{filename} 'archetypes' should not be empty"


# ---------------------------------------------------------------------------
# Uniqueness and cross-references
# ---------------------------------------------------------------------------


class TestTraitIntegrity:
    """Verify cross-referential integrity of the trait system."""

    def test_no_duplicate_trait_names(self):
        """No two traits should share the same name across all categories."""
        names = [meta["name"] for _, _, meta in ALL_TRAITS]
        seen = set()
        duplicates = []
        for name in names:
            if name in seen:
                duplicates.append(name)
            seen.add(name)
        assert not duplicates, f"Duplicate trait names found: {duplicates}"

    def test_builder_archetype_has_write_file(self):
        """Builder archetype must allow write_file."""
        builder = next((meta for fname, meta in ARCHETYPES if meta["name"] == "builder"), None)
        assert builder is not None, "builder archetype not found"
        assert "write_file" in builder.get("allowed_tools", []), "builder should allow write_file"

    def test_analyst_archetype_forbids_write_file(self):
        """Analyst archetype must forbid write_file."""
        analyst = next((meta for fname, meta in ARCHETYPES if meta["name"] == "analyst"), None)
        assert analyst is not None, "analyst archetype not found"
        assert "write_file" in analyst.get("forbidden_tools", []), "analyst should forbid write_file"

    def test_code_writing_conflicts_with_code_review(self):
        """code-writing trait must list code-review in conflicts_with."""
        cw = next((meta for fname, meta in CAPABILITIES if meta["name"] == "code-writing"), None)
        assert cw is not None, "code-writing capability not found"
        assert "code-review" in cw.get("conflicts_with", []), "code-writing should conflict with code-review"

    def test_code_review_conflicts_with_code_writing(self):
        """code-review trait must list code-writing in conflicts_with."""
        cr = next((meta for fname, meta in CAPABILITIES if meta["name"] == "code-review"), None)
        assert cr is not None, "code-review capability not found"
        assert "code-writing" in cr.get("conflicts_with", []), "code-review should conflict with code-writing"

    def test_code_writing_requires_solid_principles(self):
        """code-writing trait must require solid-principles constraint."""
        cw = next((meta for fname, meta in CAPABILITIES if meta["name"] == "code-writing"), None)
        assert cw is not None, "code-writing capability not found"
        assert "solid-principles" in cw.get("requires", []), "code-writing should require solid-principles"

    def test_security_analysis_requires_owasp_security(self):
        """security-analysis trait must require owasp-security constraint."""
        sa = next((meta for fname, meta in CAPABILITIES if meta["name"] == "security-analysis"), None)
        assert sa is not None, "security-analysis capability not found"
        assert "owasp-security" in sa.get("requires", []), "security-analysis should require owasp-security"

    def test_accessibility_analysis_requires_wcag(self):
        """accessibility-analysis trait must require wcag-accessibility constraint."""
        aa = next((meta for fname, meta in CAPABILITIES if meta["name"] == "accessibility-analysis"), None)
        assert aa is not None, "accessibility-analysis capability not found"
        assert "wcag-accessibility" in aa.get("requires", []), "accessibility-analysis should require wcag-accessibility"

    def test_all_required_traits_exist(self):
        """For every trait's requires[], verify the referenced trait exists."""
        all_names = {meta["name"] for _, _, meta in ALL_TRAITS}
        missing = []
        for category, filename, meta in ALL_TRAITS:
            for req in meta.get("requires", []) or []:
                if req not in all_names:
                    missing.append(f"{category}/{filename} requires '{req}' which does not exist")
        assert not missing, "Missing required traits:\n" + "\n".join(missing)

    def test_all_compatible_with_references_exist(self):
        """For every trait's compatible_with[], verify the referenced trait exists."""
        all_names = {meta["name"] for _, _, meta in ALL_TRAITS}
        missing = []
        for category, filename, meta in ALL_TRAITS:
            for compat in meta.get("compatible_with", []) or []:
                if compat not in all_names:
                    missing.append(f"{category}/{filename} lists compatible_with '{compat}' which does not exist")
        assert not missing, "Missing compatible_with references:\n" + "\n".join(missing)

    def test_all_conflicts_with_references_exist(self):
        """For every trait's conflicts_with[], verify the referenced trait exists."""
        all_names = {meta["name"] for _, _, meta in ALL_TRAITS}
        missing = []
        for category, filename, meta in ALL_TRAITS:
            for conflict in meta.get("conflicts_with", []) or []:
                if conflict not in all_names:
                    missing.append(f"{category}/{filename} lists conflicts_with '{conflict}' which does not exist")
        assert not missing, "Missing conflicts_with references:\n" + "\n".join(missing)

    def test_all_archetype_references_valid(self):
        """For every capability/constraint, verify referenced archetypes exist."""
        archetype_names = {meta["name"] for _, meta in ARCHETYPES}
        invalid = []
        for category, filename, meta in ALL_TRAITS:
            if category == "archetypes":
                continue
            for arch in meta.get("archetypes", []) or []:
                if arch not in archetype_names:
                    invalid.append(f"{category}/{filename} references archetype '{arch}' which does not exist")
        assert not invalid, "Invalid archetype references:\n" + "\n".join(invalid)
