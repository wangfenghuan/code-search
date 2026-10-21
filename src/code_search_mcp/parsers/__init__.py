"""Multilingual AST Parsers Subsystem

Provides modular, high-performance AST parsing for code-search-graph:
- common: Base data structures (ParsedSymbol, FileImports), builtin filtering, and AST utilities
- python: Python AST parser, closure and dynamic attribute call extraction
- javascript: TypeScript / JavaScript parser and call graph edge extraction
- vue: Vue Single File Component (.vue SFC) template & script parser
- go: Go struct and method parser
- java: Java Spring Boot route mapping and class parser
- rust: Rust trait, struct, and impl block parser
- dispatcher: TreeSitterParser unified routing facade and singleton engine
"""

from .common import (
    BUILTIN_CALLS,
    EXTENSION_LANG_MAP,
    GO_BUILTINS,
    GO_LANG,
    JAVA_BUILTINS,
    JAVA_LANG,
    JS_BUILTINS,
    JS_LANG,
    LANG_BUILTINS,
    PY_LANG,
    PYTHON_BUILTINS,
    RUST_BUILTINS,
    RUST_LANG,
    TS_LANG,
    TSX_LANG,
    BaseLanguageParser,
    FileImports,
    ParsedSymbol,
    extract_route_from_text,
    get_leading_comment,
    get_module_name_from_path,
    get_node_text,
)
from .dispatcher import TreeSitterParser
from .go import GoParser
from .java import JavaParser
from .javascript import TSJSParser
from .python import PythonParser
from .rust import RustParser
from .vue import VueParser

__all__ = [
    "TreeSitterParser",
    "BaseLanguageParser",
    "PythonParser",
    "TSJSParser",
    "GoParser",
    "JavaParser",
    "RustParser",
    "VueParser",
    "ParsedSymbol",
    "FileImports",
    "EXTENSION_LANG_MAP",
    "LANG_BUILTINS",
    "BUILTIN_CALLS",
    "PYTHON_BUILTINS",
    "JS_BUILTINS",
    "GO_BUILTINS",
    "JAVA_BUILTINS",
    "RUST_BUILTINS",
    "PY_LANG",
    "JS_LANG",
    "TS_LANG",
    "TSX_LANG",
    "GO_LANG",
    "JAVA_LANG",
    "RUST_LANG",
    "get_node_text",
    "get_leading_comment",
    "get_module_name_from_path",
    "extract_route_from_text",
]
