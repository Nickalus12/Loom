from loom.parsers.python_parser import PythonParser
from loom.parsers.typescript_parser import TypeScriptParser, TsxParser
from loom.parsers.javascript_parser import JavaScriptParser
from loom.protocols import LanguageParser

_ts_parser = TypeScriptParser()
_ALL_PARSERS = [PythonParser(), _ts_parser, TsxParser(_ts_parser), JavaScriptParser()]
PARSER_REGISTRY: dict[str, LanguageParser] = {}
for _p in _ALL_PARSERS:
    for _ext in _p.extensions:
        PARSER_REGISTRY[_ext] = _p
