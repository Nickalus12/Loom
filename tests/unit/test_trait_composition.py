"""Unit tests for Dynamic Agent Fabric trait composition validation.

Tests the composition rules that govern which traits can be combined with which
archetypes. Reads trait files directly from disk using PyYAML and reimplements
the core validation logic in Python to verify conflict detection, auto-add of
required traits, tool resolution, and archetype compatibility warnings.

This approach avoids a subprocess dependency on Node.js + js-yaml and tests
the trait data (the source of truth) directly.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TRAITS_DIR = PROJECT_ROOT / "traits"


# ---------------------------------------------------------------------------
# Pure-Python reimplementation of the composition validator
# ---------------------------------------------------------------------------


def _parse_frontmatter(filepath: Path) -> dict | None:
    """Parse YAML frontmatter from a trait/archetype file."""
    content = filepath.read_text(encoding="utf-8")
    if not content.startswith("---"):
        return None
    end = content.index("---", 3)
    return yaml.safe_load(content[3:end].strip())


def _load_archetype(name: str) -> dict | None:
    fp = TRAITS_DIR / "archetypes" / f"{name}.archetype.md"
    if not fp.exists():
        return None
    return _parse_frontmatter(fp)


def _load_trait(name: str) -> dict | None:
    for subdir in ("capabilities", "constraints", "output-contracts"):
        fp = TRAITS_DIR / subdir / f"{name}.trait.md"
        if fp.exists():
            return _parse_frontmatter(fp)
    return None


def validate_composition(archetype_name: str, trait_names: list[str]) -> dict[str, Any]:
    """Python reimplementation of handleValidateTraitComposition.

    Returns a dict matching the JS handler's output shape:
        {valid, errors, warnings, auto_added_traits, resolved_tools}
    """
    errors: list[str] = []
    warnings: list[str] = []
    auto_added: list[str] = []

    archetype_meta = _load_archetype(archetype_name)
    if archetype_meta is None:
        return {
            "valid": False,
            "errors": [f"Archetype not found: {archetype_name}"],
            "warnings": [],
            "auto_added_traits": [],
            "resolved_tools": [],
        }

    all_trait_names = set(trait_names)
    trait_metas: list[dict[str, Any]] = []

    for name in trait_names:
        meta = _load_trait(name)
        if meta is None:
            errors.append(f"Trait not found: {name}")
            continue
        if meta.get("archetypes") and archetype_name not in meta["archetypes"]:
            warnings.append(
                f'Trait "{name}" not designed for archetype "{archetype_name}"'
            )
        trait_metas.append({"name": name, "meta": meta})

    # Check conflicts
    for entry in trait_metas:
        for conflict in entry["meta"].get("conflicts_with") or []:
            if conflict in all_trait_names:
                errors.append(
                    f'Conflict: "{entry["name"]}" conflicts with "{conflict}"'
                )

    # Auto-add required traits
    snapshot = list(trait_metas)
    for entry in snapshot:
        for req in entry["meta"].get("requires") or []:
            if req not in all_trait_names:
                req_meta = _load_trait(req)
                if req_meta:
                    all_trait_names.add(req)
                    auto_added.append(req)
                    trait_metas.append({"name": req, "meta": req_meta})
                else:
                    warnings.append(f'Required trait "{req}" not found')

    # Resolve tools
    archetype_allowed = set(archetype_meta.get("allowed_tools") or [])
    archetype_forbidden = set(archetype_meta.get("forbidden_tools") or [])
    resolved_tools = set(archetype_allowed)

    for entry in trait_metas:
        meta = entry["meta"]
        for tool in meta.get("requires_tools") or []:
            if tool in archetype_forbidden:
                errors.append(
                    f'Tool conflict: trait requires "{tool}" but archetype forbids it'
                )
            else:
                resolved_tools.add(tool)
        for tool in meta.get("forbids_tools") or []:
            resolved_tools.discard(tool)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "auto_added_traits": auto_added,
        "resolved_tools": sorted(resolved_tools),
    }


# ---------------------------------------------------------------------------
# Valid compositions
# ---------------------------------------------------------------------------


class TestValidCompositions:
    """Verify that known-good trait combinations pass validation."""

    def test_valid_builder_code_writing(self):
        """builder + [code-writing] should pass validation."""
        result = validate_composition("builder", ["code-writing"])
        assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"

    def test_valid_analyst_code_review(self):
        """analyst + [code-review] should pass validation."""
        result = validate_composition("analyst", ["code-review"])
        assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"

    def test_empty_traits_valid(self):
        """builder + [] (no traits, just archetype) should pass validation."""
        result = validate_composition("builder", [])
        assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"

    def test_multiple_compatible_traits(self):
        """builder + [code-writing, test-generation, debugging] should pass."""
        result = validate_composition("builder", ["code-writing", "test-generation", "debugging"])
        assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"

    def test_analyst_security_analysis(self):
        """analyst + [security-analysis] should pass validation."""
        result = validate_composition("analyst", ["security-analysis"])
        assert result["valid"] is True, f"Expected valid, got errors: {result['errors']}"


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------


class TestConflictDetection:
    """Verify that conflicting trait combinations are rejected."""

    def test_conflict_detected_code_writing_and_review(self):
        """builder + [code-writing, code-review] should fail due to conflicts."""
        result = validate_composition("builder", ["code-writing", "code-review"])
        assert result["valid"] is False, "Expected invalid due to code-writing vs code-review conflict"
        assert any("Conflict" in e for e in result["errors"]), (
            f"Expected conflict error, got: {result['errors']}"
        )

    def test_conflict_is_bidirectional(self):
        """Conflict should be detected regardless of trait order."""
        result = validate_composition("builder", ["code-review", "code-writing"])
        assert result["valid"] is False, "Expected conflict in reverse order too"


# ---------------------------------------------------------------------------
# Auto-add of required traits
# ---------------------------------------------------------------------------


class TestAutoAddRequiredTraits:
    """Verify that required traits are automatically added to the composition."""

    def test_auto_add_solid_principles(self):
        """builder + [code-writing] should auto-add solid-principles."""
        result = validate_composition("builder", ["code-writing"])
        assert "solid-principles" in result["auto_added_traits"], (
            f"Expected solid-principles to be auto-added, got: {result['auto_added_traits']}"
        )

    def test_auto_add_owasp_security(self):
        """analyst + [security-analysis] should auto-add owasp-security."""
        result = validate_composition("analyst", ["security-analysis"])
        assert "owasp-security" in result["auto_added_traits"], (
            f"Expected owasp-security to be auto-added, got: {result['auto_added_traits']}"
        )

    def test_auto_add_wcag(self):
        """analyst + [accessibility-analysis] should auto-add wcag-accessibility."""
        result = validate_composition("analyst", ["accessibility-analysis"])
        assert "wcag-accessibility" in result["auto_added_traits"], (
            f"Expected wcag-accessibility to be auto-added, got: {result['auto_added_traits']}"
        )

    def test_no_auto_add_when_already_included(self):
        """builder + [code-writing, solid-principles] should NOT auto-add solid-principles."""
        result = validate_composition("builder", ["code-writing", "solid-principles"])
        assert "solid-principles" not in result["auto_added_traits"], (
            f"solid-principles should not be auto-added when explicitly included, got: {result['auto_added_traits']}"
        )


# ---------------------------------------------------------------------------
# Tool resolution
# ---------------------------------------------------------------------------


class TestToolResolution:
    """Verify resolved tool lists combine archetype and trait requirements correctly."""

    def test_resolved_tools_include_trait_requirements(self):
        """builder + [code-writing] resolved tools should include write_file."""
        result = validate_composition("builder", ["code-writing"])
        assert "write_file" in result["resolved_tools"], (
            f"Expected write_file in resolved tools, got: {result['resolved_tools']}"
        )

    def test_resolved_tools_exclude_forbidden(self):
        """analyst resolved tools should NOT include write_file."""
        result = validate_composition("analyst", [])
        assert "write_file" not in result["resolved_tools"], (
            f"write_file should be excluded from analyst tools, got: {result['resolved_tools']}"
        )

    def test_tool_conflict_analyst_write_file(self):
        """analyst + [code-writing] should detect tool conflict (write_file forbidden)."""
        result = validate_composition("analyst", ["code-writing"])
        assert result["valid"] is False, "Expected invalid due to tool conflict"
        assert any("Tool conflict" in e for e in result["errors"]), (
            f"Expected tool conflict error, got: {result['errors']}"
        )

    def test_resolved_tools_include_archetype_base_tools(self):
        """builder + [] should still have base tools like read_file."""
        result = validate_composition("builder", [])
        assert "read_file" in result["resolved_tools"], (
            f"Expected read_file in builder base tools, got: {result['resolved_tools']}"
        )

    def test_code_review_forbids_tools_removed_from_resolved(self):
        """analyst + [code-review] should not include write_file, replace, run_shell_command."""
        result = validate_composition("analyst", ["code-review"])
        for tool in ("write_file", "replace", "run_shell_command"):
            assert tool not in result["resolved_tools"], (
                f"{tool} should not be in resolved tools for analyst + code-review"
            )


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    """Verify proper error handling for invalid inputs."""

    def test_unknown_trait_error(self):
        """builder + [nonexistent-trait] should produce an error."""
        result = validate_composition("builder", ["nonexistent-trait"])
        assert any("not found" in e.lower() for e in result["errors"]), (
            f"Expected 'not found' error, got: {result['errors']}"
        )

    def test_unknown_archetype_error(self):
        """[invalidarch] should produce an error."""
        result = validate_composition("invalidarch", [])
        assert result["valid"] is False, "Expected invalid for unknown archetype"
        assert any("not found" in e.lower() for e in result["errors"]), (
            f"Expected 'not found' error for unknown archetype, got: {result['errors']}"
        )


# ---------------------------------------------------------------------------
# Warnings
# ---------------------------------------------------------------------------


class TestArchetypeWarnings:
    """Verify warnings when traits are used outside their designed archetype."""

    def test_archetype_warning_mismatch(self):
        """analyst + [test-generation] should produce a warning (designed for builder)."""
        result = validate_composition("analyst", ["test-generation"])
        assert any("not designed for" in w.lower() for w in result["warnings"]), (
            f"Expected archetype mismatch warning, got: {result['warnings']}"
        )

    def test_no_warning_for_matching_archetype(self):
        """builder + [code-writing] should produce no archetype mismatch warnings."""
        result = validate_composition("builder", ["code-writing"])
        mismatch = [w for w in result["warnings"] if "not designed for" in w.lower()]
        assert len(mismatch) == 0, (
            f"Expected no mismatch warnings for matching archetype, got: {mismatch}"
        )


# ---------------------------------------------------------------------------
# Constraint trait properties
# ---------------------------------------------------------------------------


class TestConstraintTraitProperties:
    """Verify constraint traits have expected structural properties."""

    def test_constraint_has_no_tool_requirements(self):
        """All constraint traits should have empty requires_tools."""
        constraints_dir = TRAITS_DIR / "constraints"
        for f in sorted(constraints_dir.iterdir()):
            if f.name.endswith(".trait.md"):
                meta = _parse_frontmatter(f)
                assert meta is not None, f"Cannot parse {f.name}"
                requires_tools = meta.get("requires_tools", [])
                assert requires_tools == [] or requires_tools is None, (
                    f"Constraint {meta['name']} should have empty requires_tools, got: {requires_tools}"
                )
