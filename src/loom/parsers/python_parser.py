import tree_sitter_python as tspython
from tree_sitter import Language, Parser


class PythonParser:
    extensions = [".py"]

    def __init__(self):
        self._language = Language(tspython.language())
        self._parser = Parser(self._language)

    def parse(self, content: str) -> list[dict]:
        tree = self._parser.parse(bytes(content, "utf8"))
        entities: list[dict] = []
        self._extract_entities(tree.root_node, content, entities)
        return entities

    def _extract_entities(self, node, content: str, entities: list[dict]) -> None:
        for child in node.children:
            if child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                if name_node:
                    name = content[name_node.start_byte:name_node.end_byte]
                    summary = self._get_docstring(child, content) or "Python function defined in file"
                    entities.append({"type": "Function", "name": name, "summary": summary})
            elif child.type == "class_definition":
                name_node = child.child_by_field_name("name")
                if name_node:
                    name = content[name_node.start_byte:name_node.end_byte]
                    summary = self._get_docstring(child, content) or "Python class defined in file"
                    entities.append({"type": "Class", "name": name, "summary": summary})
                    body = child.child_by_field_name("body")
                    if body:
                        self._extract_methods(body, content, entities)

    def _extract_methods(self, body_node, content: str, entities: list[dict]) -> None:
        for child in body_node.children:
            if child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                if name_node:
                    name = content[name_node.start_byte:name_node.end_byte]
                    summary = self._get_docstring(child, content) or "Python function defined in file"
                    entities.append({"type": "Function", "name": name, "summary": summary})

    def _get_docstring(self, node, content: str) -> str | None:
        body = node.child_by_field_name("body")
        if body and body.children:
            first_stmt = body.children[0]
            if first_stmt.type == "expression_statement" and first_stmt.children:
                string_node = first_stmt.children[0]
                if string_node.type == "string":
                    text = content[string_node.start_byte:string_node.end_byte]
                    # Strip triple or single quotes properly
                    for quote in ('"""', "'''", '"', "'"):
                        if text.startswith(quote) and text.endswith(quote):
                            text = text[len(quote):-len(quote)]
                            break
                    first_line = text.split("\n")[0].strip()
                    return first_line if first_line else None
        return None
