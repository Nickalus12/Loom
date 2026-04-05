import tree_sitter_typescript as tstypescript
from tree_sitter import Language, Parser


_NODE_TYPE_MAP = {
    "function_declaration": "Function",
    "class_declaration": "Class",
    "interface_declaration": "Interface",
    "type_alias_declaration": "TypeAlias",
    "enum_declaration": "Enum",
}


class TypeScriptParser:
    extensions = [".ts"]

    def __init__(self):
        self._ts_language = Language(tstypescript.language_typescript())
        self._tsx_language = Language(tstypescript.language_tsx())
        self._ts_parser = Parser(self._ts_language)
        self._tsx_parser = Parser(self._tsx_language)

    def parse(self, content: str, *, tsx: bool = False) -> list[dict]:
        parser = self._tsx_parser if tsx else self._ts_parser
        tree = parser.parse(bytes(content, "utf8"))
        entities: list[dict] = []
        self._extract_entities(tree.root_node, content, entities)
        return entities

    def _extract_entities(self, node, content: str, entities: list[dict]) -> None:
        for child in node.children:
            # Unwrap export statements to find the declaration inside
            actual = child
            jsdoc_target = child
            if child.type == "export_statement":
                for sub in child.children:
                    if sub.type in _NODE_TYPE_MAP or sub.type == "lexical_declaration":
                        actual = sub
                        break
                else:
                    continue

            # Handle arrow functions: const fn = () => {}
            if actual.type == "lexical_declaration":
                self._extract_arrow_functions(actual, content, entities, jsdoc_target)
                continue

            entity_type = _NODE_TYPE_MAP.get(actual.type)
            if entity_type:
                name_node = actual.child_by_field_name("name")
                if name_node:
                    name = content[name_node.start_byte:name_node.end_byte]
                    jsdoc_src = jsdoc_target if child.type == "export_statement" else actual
                    summary = self._get_jsdoc(jsdoc_src, content) or f"TypeScript {entity_type.lower()} defined in file"
                    entities.append({"type": entity_type, "name": name, "summary": summary})

    def _extract_arrow_functions(self, decl_node, content: str, entities: list[dict], jsdoc_target) -> None:
        """Extract named arrow functions from lexical_declaration nodes."""
        for child in decl_node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")
                if name_node and value_node and value_node.type == "arrow_function":
                    name = content[name_node.start_byte:name_node.end_byte]
                    summary = self._get_jsdoc(jsdoc_target, content) or "TypeScript function defined in file"
                    entities.append({"type": "Function", "name": name, "summary": summary})

    def _get_jsdoc(self, node, content: str) -> str | None:
        prev = node.prev_named_sibling
        if prev and prev.type == "comment":
            text = content[prev.start_byte:prev.end_byte]
            if text.startswith("/**"):
                # Strip the /** ... */ wrapper, then find first content line
                inner = text.removeprefix("/**").removesuffix("*/")
                for line in inner.split("\n"):
                    stripped = line.strip().lstrip("* ").strip()
                    if stripped and not stripped.startswith("@"):
                        return stripped
        return None


class TsxParser:
    """Thin wrapper that delegates to TypeScriptParser with TSX grammar."""
    extensions = [".tsx"]

    def __init__(self, ts_parser: TypeScriptParser):
        self._ts_parser = ts_parser

    def parse(self, content: str) -> list[dict]:
        return self._ts_parser.parse(content, tsx=True)
