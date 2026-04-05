import tree_sitter_python as tspython
from tree_sitter import Language, Parser

class ASTParser:
    def __init__(self):
        # Load Python language grammar
        self.PY_LANGUAGE = Language(tspython.language())
        self.parser = Parser(self.PY_LANGUAGE)

    def parse_python_file(self, content: str):
        """
        Parses Python content and extracts top-level classes and functions.
        """
        tree = self.parser.parse(bytes(content, "utf8"))
        root_node = tree.root_node
        
        entities = []
        
        # Traverse top-level nodes
        for child in root_node.children:
            if child.type == 'function_definition':
                name_node = child.child_by_field_name('name')
                if name_node:
                    entities.append({
                        "type": "Function",
                        "name": content[name_node.start_byte:name_node.end_byte],
                        "summary": f"Python function defined in file"
                    })
            elif child.type == 'class_definition':
                name_node = child.child_by_field_name('name')
                if name_node:
                    entities.append({
                        "type": "Class",
                        "name": content[name_node.start_byte:name_node.end_byte],
                        "summary": f"Python class defined in file"
                    })
                    
        return entities
