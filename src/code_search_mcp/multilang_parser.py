"""多语言代码解析器门面模块 (Multilingual Parser Facade)

为了保持代码库清晰度与高内聚，底层各语言专用解析逻辑已拆分为模块化子系统 `code_search_mcp.parsers`：
- parsers.common: 多语言内置方法表、AST 节点工具、通用数据结构
- parsers.python: Python 专用 AST 解析与调用边提取
- parsers.javascript: TypeScript / JavaScript 专用 AST 解析与调用边提取
- parsers.go: Go 专用 AST 解析与调用边提取
- parsers.java: Java 专用 AST 解析、Spring 路由提取与依赖注入推断
- parsers.dispatcher: TreeSitterParser 单例与统一调度引擎

本模块完整重导出所有公共符号与历史接口，确保向后兼容性 100%。
"""

from code_search_mcp.parsers import (
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
    GoParser,
    JavaParser,
    ParsedSymbol,
    PythonParser,
    RustParser,
    TSJSParser,
    TreeSitterParser,
    extract_route_from_text,
    get_leading_comment,
    get_module_name_from_path,
    get_node_text,
)

__all__ = [
    "TreeSitterParser",
    "BaseLanguageParser",
    "PythonParser",
    "TSJSParser",
    "GoParser",
    "JavaParser",
    "RustParser",
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
