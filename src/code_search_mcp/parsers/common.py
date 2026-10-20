import bisect
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from tree_sitter import Language, Node, Parser, Query, QueryCursor

# 多语言内置函数与标准库高频方法过滤表（按语言精准隔离，消除跨语言误伤）
PYTHON_BUILTINS: Set[str] = {
    "print", "len", "range", "str", "int", "float", "bool", "dict", "list", "set", "tuple",
    "isinstance", "type", "issubclass", "super", "open", "sum", "min", "max", "any", "all",
    "map", "filter", "zip", "enumerate", "sorted", "reversed", "hasattr", "getattr", "setattr",
    "delattr", "id", "hash", "iter", "next", "repr", "round", "abs", "divmod", "pow",
    "bin", "oct", "hex", "chr", "ord", "input", "format", "vars", "dir", "callable",
    "classmethod", "staticmethod", "property",
    "append", "extend", "insert", "remove", "pop", "clear", "index", "count", "sort", "reverse",
    "copy", "keys", "values", "items", "get", "update", "split", "join", "strip", "lstrip",
    "rstrip", "replace", "lower", "upper", "startswith", "endswith", "find", "encode", "decode",
    "Exception", "ValueError", "TypeError", "KeyError", "IndexError", "AttributeError",
    "RuntimeError", "StopIteration", "IOError", "OSError", "ImportError", "NotImplementedError",
}

JS_BUILTINS: Set[str] = {
    "require", "typeof", "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "setImmediate", "clearImmediate", "fetch", "parseInt", "parseFloat", "isNaN", "isFinite",
    "encodeURI", "decodeURI", "encodeURIComponent", "decodeURIComponent", "eval", "super",
    "String", "Number", "Boolean", "Array", "Object", "Function", "Symbol", "BigInt",
    "Math", "Date", "RegExp", "Map", "Set", "WeakMap", "WeakSet", "Promise", "Proxy", "Reflect",
    "JSON", "Error", "TypeError", "RangeError", "SyntaxError", "ReferenceError",
    "push", "pop", "shift", "unshift", "splice", "slice", "concat", "join", "indexOf",
    "lastIndexOf", "includes", "forEach", "map", "filter", "reduce", "reduceRight",
    "some", "every", "find", "findIndex", "fill", "sort", "reverse", "flat", "flatMap",
    "toString", "valueOf", "trim", "split", "replace", "substring", "toLowerCase", "toUpperCase",
    "log", "warn", "error", "info", "debug", "trace",
}

GO_BUILTINS: Set[str] = {
    "make", "new", "len", "cap", "append", "copy", "delete", "close", "panic", "recover",
    "print", "println", "complex", "real", "imag", "clear", "min", "max",
    "Error", "String",
}

JAVA_BUILTINS: Set[str] = {
    "equals", "hashCode", "toString", "getClass", "notify", "notifyAll", "wait", "clone", "finalize",
    "add", "get", "set", "remove", "size", "clear", "isEmpty", "contains", "containsKey", "containsValue",
    "put", "putIfAbsent", "keySet", "values", "entrySet", "iterator", "stream", "parallelStream",
    "forEach", "map", "filter", "collect", "flatMap", "reduce", "findFirst", "findAny", "count",
    "anyMatch", "allMatch", "noneMatch", "sorted", "distinct", "limit", "skip", "toList", "toSet",
    "valueOf", "parseInt", "parseLong", "parseDouble", "parseFloat", "booleanValue", "intValue", "longValue",
    "length", "charAt", "substring", "indexOf", "lastIndexOf", "startsWith", "endsWith", "replace",
    "replaceAll", "trim", "strip", "toLowerCase", "toUpperCase", "split", "join", "format", "matches",
    "print", "println", "printf", "currentTimeMillis", "nanoTime", "arraycopy", "exit", "gc",
    "start", "run", "sleep", "join", "interrupt", "isAlive", "append", "close", "flush", "read", "write",
    "builder", "build",
    "String", "Integer", "Long", "Double", "Float", "Boolean", "Byte", "Short", "Character",
    "Object", "Class", "System", "Math", "Arrays", "Collections", "Objects", "Optional",
    "List", "ArrayList", "LinkedList", "Set", "HashSet", "TreeSet", "Map", "HashMap", "TreeMap",
    "Exception", "RuntimeException", "IllegalArgumentException", "NullPointerException",
    "IllegalStateException", "IndexOutOfBoundsException", "UnsupportedOperationException",
}

JDK_PACKAGE_PREFIXES = (
    "java.", "javax.", "sun.", "jdk.", "com.sun.",
    "org.w3c.", "org.xml.", "org.slf4j.", "org.apache.commons.",
)

RUST_BUILTINS: Set[str] = {
    "println", "print", "eprintln", "eprint", "format", "panic", "vec", "assert",
    "assert_eq", "assert_ne", "dbg", "todo", "unimplemented", "unreachable",
    "clone", "to_string", "as_str", "as_bytes", "len", "is_empty", "unwrap",
    "expect", "unwrap_or", "unwrap_or_else", "unwrap_or_default", "map",
    "and_then", "or_else", "ok", "err", "is_ok", "is_err", "push", "pop",
    "insert", "remove", "get", "get_mut", "iter", "into_iter", "collect",
    "Some", "None", "Ok", "Err", "Box", "Rc", "Arc", "RefCell", "Mutex",
    "String", "Vec", "Option", "Result", "Default", "default", "new",
}

LANG_BUILTINS: Dict[str, Set[str]] = {
    "python": PYTHON_BUILTINS,
    "javascript": JS_BUILTINS,
    "typescript": JS_BUILTINS,
    "go": GO_BUILTINS,
    "java": JAVA_BUILTINS,
    "rust": RUST_BUILTINS,
}

BUILTIN_CALLS: Set[str] = PYTHON_BUILTINS | JS_BUILTINS | GO_BUILTINS | JAVA_BUILTINS | RUST_BUILTINS


# 导入语言包
try:
    import tree_sitter_python as tspy
    PY_LANG = Language(tspy.language())
except Exception:
    PY_LANG = None

try:
    import tree_sitter_javascript as tsjs
    JS_LANG = Language(tsjs.language())
except Exception:
    JS_LANG = None

try:
    import tree_sitter_typescript as tsts
    TS_LANG = Language(tsts.language_typescript())
    TSX_LANG = Language(tsts.language_tsx())
except Exception:
    TS_LANG = None
    TSX_LANG = None

try:
    import tree_sitter_go as tsgo
    GO_LANG = Language(tsgo.language())
except Exception:
    GO_LANG = None

try:
    import tree_sitter_java as tsjava
    JAVA_LANG = Language(tsjava.language())
except Exception:
    JAVA_LANG = None

try:
    import tree_sitter_rust as tsrust
    RUST_LANG = Language(tsrust.language())
except Exception:
    RUST_LANG = None


# 扩展名到语言的映射
EXTENSION_LANG_MAP: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".vue": "vue",
}


@dataclass
class FileImports:
    """单个源文件的依赖导入与实例化拓扑表"""
    # 局部导入的符号名 -> 模块限定名 (如 "AuthService": "auth.AuthService", "hp": "auth.service.hash_password")
    symbols: Dict[str, str] = field(default_factory=dict)
    # 局部导入的模块名/别名 -> 模块路径 (如 "srv": "auth.service", "service": "auth.service")
    modules: Dict[str, str] = field(default_factory=dict)
    # 局部变量实例化推断 (如 "auth_service": "AuthService")
    instances: Dict[str, str] = field(default_factory=dict)


@dataclass
class ParsedSymbol:
    name: str
    symbol_type: str  # class, method, function, struct, interface, record, enum, constructor, closure
    start_line: int
    end_line: int
    code: str
    docstring: Optional[str]
    route_info: str
    signature: str
    calls: List[str] = field(default_factory=list)
    file_path: str = ""
    module_name: str = ""
    qualified_name: str = ""


def get_node_text(node: Node, source_bytes: bytes) -> str:
    """提取节点的源码文本"""
    return source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")


def get_leading_comment(node: Node, source_bytes: bytes) -> str:
    """提取节点上方的紧随注释作为文档说明"""
    prev = node.prev_sibling
    comments = []
    while prev and prev.type in ("comment", "line_comment", "block_comment"):
        text = get_node_text(prev, source_bytes).strip()
        # 清理常见注释符号 // 或 # 或 /* */
        clean = re.sub(r"^(//|#|/\*+|\*+/?)", "", text).strip()
        if clean:
            comments.insert(0, clean)
        prev = prev.prev_sibling
    return " ".join(comments)


def get_module_name_from_path(file_path: str) -> str:
    """根据文件路径计算标准模块限定前缀 (如 auth/service.py -> auth.service, src/main/java/com/demo/User.java -> com.demo.User)"""
    p = Path(str(file_path).replace("\\", "/"))
    parts = list(p.parts)
    if not parts:
        return ""
    parts[-1] = p.stem
    if "java" in parts:
        idx = parts.index("java")
        parts = parts[idx + 1 :]
    clean_parts = []
    for part in parts:
        part = part.rstrip(":\\/ ")
        if not part or part in (".", "..", "src", "main", "test", "app") or part.startswith("."):
            continue
        clean_parts.append(part)
    return ".".join(clean_parts)


def extract_route_from_text(text: str) -> str:
    """从装饰器、注释或路由代码中提取 API 路由"""
    # Java Spring Boot: @GetMapping("/users"), @PostMapping(path = "/users"), @RequestMapping(value = "/users", method = RequestMethod.POST)
    m_spring = re.search(r"@(Get|Post|Put|Delete|Patch)Mapping\s*\(\s*(?:(?:value|path)\s*=\s*)?['\"]([^'\"]+)['\"]", text, re.I)
    if m_spring:
        return f"HTTP {m_spring.group(1).upper()} {m_spring.group(2)}"

    m_req = re.search(r"@RequestMapping\s*\(\s*(?:(?:value|path)\s*=\s*)?['\"]([^'\"]+)['\"](?:.*method\s*=\s*(?:RequestMethod\.)?([A-Z]+))?", text, re.I)
    if m_req:
        method = m_req.group(2).upper() if m_req.group(2) else "GET"
        return f"HTTP {method} {m_req.group(1)}"

    # Rust Actix-web / Rocket: #[get("/orders")], #[post("/orders")]
    m_rust = re.search(r"#\[(get|post|put|delete|patch|options|head)\s*\(\s*['\"]([^'\"]+)['\"]", text, re.I)
    if m_rust:
        return f"HTTP {m_rust.group(1).upper()} {m_rust.group(2)}"

    # Python / NestJS: @router.post("/login"), @Post('/auth')
    m = re.search(r"@(?:router|app|\w+)?\.?(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", text, re.I)
    if m:
        return f"HTTP {m.group(1).upper()} {m.group(2)}"

    # Express / Go Gin: router.POST("/login", ...), app.get('/api/users')
    m2 = re.search(r"\.(GET|POST|PUT|DELETE|PATCH|get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", text)
    if m2:
        return f"HTTP {m2.group(1).upper()} {m2.group(2)}"

    return ""


class BaseLanguageParser(ABC):
    """多语言解析器抽象基类"""

    @abstractmethod
    def parse(
        self,
        tree: Any,
        source: bytes,
        symbols: List[ParsedSymbol],
        imports: Optional[FileImports] = None,
        module_name: str = "",
        file_path: str = "",
        byte_to_line: Optional[Callable[[int], int]] = None,
        include_calls: bool = False,
        **kwargs,
    ) -> None:
        """从语法树中提取符号定义列表"""
        pass

    @abstractmethod
    def extract_imports(self, root: Node, source: bytes, **kwargs) -> FileImports:
        """从语法树中提取导入与实例化表"""
        pass

    @abstractmethod
    def extract_calls_from_matches(
        self,
        matches: Any,
        source: bytes,
        imports: Optional[FileImports],
        module_name: str,
        current_class: str = "",
        **kwargs,
    ) -> List[str]:
        """从匹配结果中提取调用的符号"""
        pass
