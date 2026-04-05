import os

from loom.parsers import PARSER_REGISTRY


class ASTParser:
    def __init__(self):
        self.registry = dict(PARSER_REGISTRY)

    def parse_file(self, file_path: str, content: str) -> list[dict]:
        ext = os.path.splitext(file_path)[1]
        parser = self.registry.get(ext)
        if parser is None:
            return []
        return parser.parse(content)

    def parse_python_file(self, content: str) -> list[dict]:
        parser = self.registry.get(".py")
        if parser is None:
            return []
        return parser.parse(content)
