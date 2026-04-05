"""Unit tests for individual language parsers."""

import pytest
from loom.parsers.python_parser import PythonParser
from loom.parsers.typescript_parser import TypeScriptParser, TsxParser
from loom.parsers.javascript_parser import JavaScriptParser


# ---------------------------------------------------------------------------
# PythonParser
# ---------------------------------------------------------------------------


class TestPythonParser:
    """Test PythonParser entity extraction from Python source code."""

    @pytest.fixture(autouse=True)
    def parser(self):
        self.parser = PythonParser()

    def test_python_extracts_functions(self, sample_python_code):
        """Should find top-level function definitions."""
        result = self.parser.parse(sample_python_code)
        function_names = [e["name"] for e in result if e["type"] == "Function"]
        assert "standalone_function" in function_names

    def test_python_extracts_classes(self, sample_python_code):
        """Should find class definitions."""
        result = self.parser.parse(sample_python_code)
        class_names = [e["name"] for e in result if e["type"] == "Class"]
        assert "UserService" in class_names

    def test_python_extracts_methods(self, sample_python_code):
        """Should find methods inside class bodies."""
        result = self.parser.parse(sample_python_code)
        function_names = [e["name"] for e in result if e["type"] == "Function"]
        assert "create_user" in function_names
        assert "delete_user" in function_names

    def test_python_extracts_docstrings(self, sample_python_code):
        """Should use the docstring as the entity summary."""
        result = self.parser.parse(sample_python_code)
        standalone = next(e for e in result if e["name"] == "standalone_function")
        assert "standalone top-level function" in standalone["summary"].lower()

    def test_python_no_docstring_fallback(self, sample_python_code):
        """Should use fallback summary when no docstring is present."""
        result = self.parser.parse(sample_python_code)
        no_doc = next(e for e in result if e["name"] == "no_docstring")
        assert no_doc["summary"] == "Python function defined in file"

    def test_python_empty_input(self):
        """Should return empty list for empty string."""
        result = self.parser.parse("")
        assert result == []

    def test_python_extensions(self):
        """Should declare .py as its extension."""
        assert self.parser.extensions == [".py"]


# ---------------------------------------------------------------------------
# TypeScriptParser
# ---------------------------------------------------------------------------


class TestTypeScriptParser:
    """Test TypeScriptParser entity extraction from TypeScript source code."""

    @pytest.fixture(autouse=True)
    def parser(self):
        self.parser = TypeScriptParser()

    def test_ts_extracts_functions(self, sample_ts_code):
        """Should find function_declaration nodes."""
        result = self.parser.parse(sample_ts_code)
        function_names = [e["name"] for e in result if e["type"] == "Function"]
        assert "createService" in function_names

    def test_ts_extracts_classes(self, sample_ts_code):
        """Should find class_declaration nodes."""
        result = self.parser.parse(sample_ts_code)
        class_names = [e["name"] for e in result if e["type"] == "Class"]
        assert "UserController" in class_names

    def test_ts_extracts_interfaces(self, sample_ts_code):
        """Should find interface_declaration nodes."""
        result = self.parser.parse(sample_ts_code)
        interface_names = [e["name"] for e in result if e["type"] == "Interface"]
        assert "ServiceConfig" in interface_names

    def test_ts_extracts_jsdoc(self, sample_ts_code):
        """Should use JSDoc comment as the entity summary."""
        result = self.parser.parse(sample_ts_code)
        config = next(e for e in result if e["name"] == "ServiceConfig")
        assert "configuration options" in config["summary"].lower()

    def test_ts_fallback_summary_when_no_jsdoc(self):
        """Should use fallback summary when no JSDoc is present."""
        code = "function noDoc(): void { }"
        result = self.parser.parse(code)
        assert len(result) == 1
        assert result[0]["summary"] == "TypeScript function defined in file"

    def test_ts_empty_input(self):
        """Should return empty list for empty string."""
        result = self.parser.parse("")
        assert result == []

    def test_ts_extensions(self):
        """Should declare .ts as its extension (TSX is handled by TsxParser)."""
        assert self.parser.extensions == [".ts"]


# ---------------------------------------------------------------------------
# JavaScriptParser
# ---------------------------------------------------------------------------


class TestJavaScriptParser:
    """Test JavaScriptParser entity extraction from JavaScript source code."""

    @pytest.fixture(autouse=True)
    def parser(self):
        self.parser = JavaScriptParser()

    def test_js_extracts_functions(self, sample_js_code):
        """Should find function declarations."""
        result = self.parser.parse(sample_js_code)
        function_names = [e["name"] for e in result if e["type"] == "Function"]
        assert "add" in function_names
        assert "noDoc" in function_names

    def test_js_extracts_classes(self, sample_js_code):
        """Should find class declarations."""
        result = self.parser.parse(sample_js_code)
        class_names = [e["name"] for e in result if e["type"] == "Class"]
        assert "EventEmitter" in class_names

    def test_js_extracts_jsdoc(self, sample_js_code):
        """Should use JSDoc comment as the entity summary."""
        result = self.parser.parse(sample_js_code)
        add_fn = next(e for e in result if e["name"] == "add")
        assert "sum" in add_fn["summary"].lower()

    def test_js_fallback_summary_when_no_jsdoc(self, sample_js_code):
        """Should use fallback summary when no JSDoc is present."""
        result = self.parser.parse(sample_js_code)
        no_doc = next(e for e in result if e["name"] == "noDoc")
        assert no_doc["summary"] == "JavaScript function defined in file"

    def test_js_empty_input(self):
        """Should return empty list for empty string."""
        result = self.parser.parse("")
        assert result == []

    def test_js_extensions(self):
        """Should declare .js, .jsx, .mjs as its extensions."""
        assert self.parser.extensions == [".js", ".jsx", ".mjs"]


# ---------------------------------------------------------------------------
# TypeScript — Arrow Functions & Exports
# ---------------------------------------------------------------------------


class TestTypeScriptArrowFunctions:
    """Test TypeScriptParser extraction of arrow functions and exports."""

    @pytest.fixture(autouse=True)
    def parser(self):
        self.parser = TypeScriptParser()

    def test_ts_arrow_function(self):
        """Should extract named arrow functions from const declarations."""
        code = "const add = (a: number, b: number): number => a + b;"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "add" in names
        assert result[0]["type"] == "Function"

    def test_ts_async_arrow_function(self):
        """Should extract async arrow functions."""
        code = "const fetchData = async (url: string): Promise<Response> => fetch(url);"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "fetchData" in names

    def test_ts_arrow_function_with_jsdoc(self):
        """Should capture JSDoc for arrow functions."""
        code = '/** Doubles a number. */\nconst double = (x: number) => x * 2;'
        result = self.parser.parse(code)
        assert len(result) == 1
        assert "Doubles a number" in result[0]["summary"]

    def test_ts_export_function(self):
        """Should extract exported function declarations."""
        code = "export function compute(): number { return 42; }"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "compute" in names

    def test_ts_export_class(self):
        """Should extract exported class declarations."""
        code = "export class AppService { }"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "AppService" in names

    def test_ts_export_interface(self):
        """Should extract exported interface declarations."""
        code = "export interface Config { port: number; }"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "Config" in names

    def test_ts_export_arrow_function(self):
        """Should extract exported arrow functions."""
        code = "export const handler = (req: Request) => req;"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "handler" in names

    def test_ts_type_alias(self):
        """Should extract type alias declarations."""
        code = "type UserId = string;"
        result = self.parser.parse(code)
        assert len(result) == 1
        assert result[0]["type"] == "TypeAlias"
        assert result[0]["name"] == "UserId"

    def test_ts_export_type_alias(self):
        """Should extract exported type alias declarations."""
        code = "export type Config = { host: string; port: number; };"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "Config" in names

    def test_ts_const_without_arrow_ignored(self):
        """Should NOT extract const declarations that aren't arrow functions."""
        code = "const PORT = 3000;\nconst NAME = 'app';"
        result = self.parser.parse(code)
        assert result == []


# ---------------------------------------------------------------------------
# JavaScript — Arrow Functions & Exports
# ---------------------------------------------------------------------------


class TestJavaScriptArrowFunctions:
    """Test JavaScriptParser extraction of arrow functions and exports."""

    @pytest.fixture(autouse=True)
    def parser(self):
        self.parser = JavaScriptParser()

    def test_js_arrow_function(self):
        """Should extract named arrow functions from const declarations."""
        code = "const add = (a, b) => a + b;"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "add" in names
        assert result[0]["type"] == "Function"

    def test_js_async_arrow_function(self):
        """Should extract async arrow functions."""
        code = "const fetchData = async (url) => fetch(url);"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "fetchData" in names

    def test_js_arrow_function_with_jsdoc(self):
        """Should capture JSDoc for arrow functions."""
        code = '/** Doubles a number. */\nconst double = (x) => x * 2;'
        result = self.parser.parse(code)
        assert len(result) == 1
        assert "Doubles a number" in result[0]["summary"]

    def test_js_export_function(self):
        """Should extract exported function declarations."""
        code = "export function serve() { }"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "serve" in names

    def test_js_export_class(self):
        """Should extract exported class declarations."""
        code = "export class Router { }"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "Router" in names

    def test_js_export_arrow_function(self):
        """Should extract exported arrow functions."""
        code = "export const handler = (req) => req;"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "handler" in names

    def test_js_export_default_function(self):
        """Should extract export default function."""
        code = "export default function main() { }"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "main" in names

    def test_js_const_without_arrow_ignored(self):
        """Should NOT extract const declarations that aren't arrow functions."""
        code = "const PORT = 3000;"
        result = self.parser.parse(code)
        assert result == []


# ---------------------------------------------------------------------------
# TsxParser
# ---------------------------------------------------------------------------


class TestTsxParser:
    """Test TsxParser handles JSX syntax in TypeScript files."""

    @pytest.fixture(autouse=True)
    def parser(self):
        ts = TypeScriptParser()
        self.parser = TsxParser(ts)

    def test_tsx_extensions(self):
        """Should declare .tsx as its extension."""
        assert self.parser.extensions == [".tsx"]

    def test_tsx_parses_jsx_syntax(self):
        """Should parse functions that return JSX elements."""
        code = "function Button(): JSX.Element { return <button>Click</button>; }"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "Button" in names

    def test_tsx_arrow_component(self):
        """Should extract arrow function components with JSX."""
        code = "const App = () => <div>Hello</div>;"
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "App" in names

    def test_tsx_with_interfaces(self):
        """Should extract interfaces alongside JSX components."""
        code = "interface Props { name: string; }\nfunction Greeting(props: Props) { return <h1>{props.name}</h1>; }"
        result = self.parser.parse(code)
        types = {e["name"]: e["type"] for e in result}
        assert types.get("Props") == "Interface"
        assert types.get("Greeting") == "Function"


# ---------------------------------------------------------------------------
# TypeScript — Enum Support
# ---------------------------------------------------------------------------


class TestTypeScriptEnums:
    """Test TypeScriptParser extraction of enum declarations."""

    @pytest.fixture(autouse=True)
    def parser(self):
        self.parser = TypeScriptParser()

    def test_ts_extracts_enum(self):
        """Should extract enum declarations."""
        code = "enum Status { Active, Inactive, Pending }"
        result = self.parser.parse(code)
        assert len(result) == 1
        assert result[0]["type"] == "Enum"
        assert result[0]["name"] == "Status"

    def test_ts_export_enum(self):
        """Should extract exported enum declarations."""
        code = 'export enum Role { Admin = "admin", User = "user" }'
        result = self.parser.parse(code)
        names = [e["name"] for e in result]
        assert "Role" in names

    def test_ts_enum_with_jsdoc(self):
        """Should capture JSDoc for enums."""
        code = '/** HTTP status codes. */\nenum HttpStatus { OK = 200, NotFound = 404 }'
        result = self.parser.parse(code)
        assert "HTTP status codes" in result[0]["summary"]


# ---------------------------------------------------------------------------
# Parser Resilience — All Languages
# ---------------------------------------------------------------------------


class TestParserResilience:
    """Ensure parsers never crash on malformed, unusual, or edge-case inputs."""

    @pytest.fixture(autouse=True)
    def parsers(self):
        self.py = PythonParser()
        self.ts = TypeScriptParser()
        self.js = JavaScriptParser()

    def test_syntax_error_python(self):
        """Should return partial results or empty list, never crash."""
        code = "def broken(\n    class {"
        result = self.py.parse(code)
        assert isinstance(result, list)

    def test_syntax_error_typescript(self):
        """Should not crash on malformed TypeScript."""
        code = "function { broken syntax }"
        result = self.ts.parse(code)
        assert isinstance(result, list)

    def test_syntax_error_javascript(self):
        """Should not crash on malformed JavaScript."""
        code = "const = ; class {"
        result = self.js.parse(code)
        assert isinstance(result, list)

    def test_unicode_identifiers_python(self):
        """Should handle unicode function/class names."""
        code = 'def grüße():\n    """Greetings."""\n    pass'
        result = self.py.parse(code)
        assert isinstance(result, list)

    def test_unicode_identifiers_typescript(self):
        """Should handle unicode in TypeScript."""
        code = 'function 挨拶(): void {}'
        result = self.ts.parse(code)
        assert isinstance(result, list)

    def test_comment_only_python(self):
        """Should return empty for comment-only Python files."""
        code = "# This is just a comment\n# Another comment"
        result = self.py.parse(code)
        assert result == []

    def test_comment_only_javascript(self):
        """Should return empty for comment-only JS files."""
        code = "// just a comment\n/* block comment */"
        result = self.js.parse(code)
        assert result == []

    def test_very_long_single_line(self):
        """Should handle a very long line without hanging."""
        code = "function f() { " + "x = x + 1; " * 1000 + "}"
        result = self.js.parse(code)
        assert isinstance(result, list)

    def test_deeply_nested_python(self):
        """Should handle deeply nested structures."""
        code = "class A:\n" + "".join(f"{'    ' * (i+1)}class C{i}:\n" for i in range(10))
        result = self.py.parse(code)
        assert isinstance(result, list)
        assert any(e["name"] == "A" for e in result)

    def test_null_bytes(self):
        """Should handle content with null bytes without crashing."""
        code = "function foo() {}\x00\x00class Bar {}"
        result = self.js.parse(code)
        assert isinstance(result, list)

    def test_only_whitespace(self):
        """Should return empty for whitespace-only input."""
        for parser in (self.py, self.ts, self.js):
            result = parser.parse("   \n\n\t\t  \n")
            assert result == []
