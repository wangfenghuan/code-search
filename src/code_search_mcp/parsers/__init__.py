"""多语言 AST 解析器子系统 (Multilingual AST Parsers Subsystem)

该子系统为 code-search-mcp 提供模块化、高性能且隔离良好的代码解析能力：
- common: 通用数据结构 (ParsedSymbol, FileImports)、语言内置方法过滤表与 AST 基础工具
- python: Python 语言专属解析器、闭包与 getattr 动态调用提取
- javascript: TypeScript / JavaScript 语言专属解析器与调用边提取
- go: Go 语言专属解析器、结构体与多返回值方法提取
- java: Java 语言专属解析器、Spring Boot 路由合并与依赖注入推断
- dispatcher: TreeSitterParser 统一分发门面与单例引擎
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
