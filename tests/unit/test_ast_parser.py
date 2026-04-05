"""Unit tests for ASTParser registry-based dispatch."""

import pytest
from loom.ast_parser import ASTParser
from loom.parsers import PARSER_REGISTRY


class TestASTParserRegistryDispatch:
    """Verify that ASTParser dispatches to the correct language parser based on file extension."""

    @pytest.fixture(autouse=True)
    def parser(self):
        self.parser = ASTParser()

    def test_parse_file_python_dispatch(self, sample_python_code):
        """Should return entities when parsing a .py file."""
        result = self.parser.parse_file("example.py", sample_python_code)
        assert isinstance(result, list)
        assert len(result) > 0
        names = [e["name"] for e in result]
        assert "UserService" in names
        assert "standalone_function" in names

    def test_parse_file_typescript_dispatch(self, sample_ts_code):
        """Should return entities when parsing a .ts file."""
        result = self.parser.parse_file("example.ts", sample_ts_code)
        assert isinstance(result, list)
        assert len(result) > 0
        names = [e["name"] for e in result]
        assert "createService" in names
        assert "UserController" in names

    def test_parse_file_javascript_dispatch(self, sample_js_code):
        """Should return entities when parsing a .js file."""
        result = self.parser.parse_file("example.js", sample_js_code)
        assert isinstance(result, list)
        assert len(result) > 0
        names = [e["name"] for e in result]
        assert "add" in names
        assert "EventEmitter" in names

    def test_parse_file_unknown_extension(self):
        """Should return empty list when file extension is not in registry."""
        result = self.parser.parse_file("example.rb", "class Foo; end")
        assert result == []

    def test_parse_python_file_backward_compat(self, sample_python_code):
        """Should still work via the legacy parse_python_file method."""
        result = self.parser.parse_python_file(sample_python_code)
        assert isinstance(result, list)
        assert len(result) > 0
        names = [e["name"] for e in result]
        assert "UserService" in names

    def test_registry_has_all_extensions(self):
        """Should have registry entries for .py, .ts, .tsx, .js, .jsx, .mjs."""
        expected_extensions = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs"}
        assert expected_extensions.issubset(set(self.parser.registry.keys()))


class TestASTParserEdgeCases:
    """Edge cases for ASTParser behavior."""

    @pytest.fixture(autouse=True)
    def parser(self):
        self.parser = ASTParser()

    def test_parse_file_empty_content(self):
        """Should return empty list when parsing empty content."""
        result = self.parser.parse_file("empty.py", "")
        assert result == []

    def test_parse_file_no_extension(self):
        """Should return empty list when file has no extension."""
        result = self.parser.parse_file("Makefile", "all: build")
        assert result == []

    def test_registry_is_independent_copy(self):
        """Should use its own copy of the registry, not the module-level dict."""
        original_len = len(self.parser.registry)
        self.parser.registry[".fake"] = None
        # A new parser should not see the mutation
        parser2 = ASTParser()
        assert ".fake" not in parser2.registry
        assert len(parser2.registry) == original_len
