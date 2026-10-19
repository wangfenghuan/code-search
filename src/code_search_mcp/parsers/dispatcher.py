import bisect
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from tree_sitter import Node, Parser, QueryCursor

from .common import (
    BaseLanguageParser,
    EXTENSION_LANG_MAP,
    FileImports,
    GO_LANG,
    JAVA_LANG,
    JS_LANG,
    PY_LANG,
    ParsedSymbol,
    RUST_LANG,
    TS_LANG,
    extract_route_from_text,
    get_module_name_from_path,
)
from .go import GoParser
from .java import JavaParser
from .javascript import TSJSParser
from .python import PythonParser
from .rust import RustParser


class TreeSitterParser:
    """工业级 Tree-sitter 多语言代码解析器 (基于多语言独立解析器组合与单例统一调度)"""

    _instance: Optional["TreeSitterParser"] = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

        self._parsers: Dict[str, Parser] = {}
        if PY_LANG:
            self._parsers["python"] = Parser(PY_LANG)
        if JS_LANG:
            self._parsers["javascript"] = Parser(JS_LANG)
        if TS_LANG:
            self._parsers["typescript"] = Parser(TS_LANG)
        if GO_LANG:
            self._parsers["go"] = Parser(GO_LANG)
        if JAVA_LANG:
            self._parsers["java"] = Parser(JAVA_LANG)
        if RUST_LANG:
            self._parsers["rust"] = Parser(RUST_LANG)

        # 实例化各语言独立解析器
        self.py_parser = PythonParser()
        self.tsjs_parser = TSJSParser()
        self.go_parser = GoParser()
        self.java_parser = JavaParser()
        self.rust_parser = RustParser()

        # 语言解析器统一映射表 (纯分发调度体系)
        self._sub_parsers: Dict[str, BaseLanguageParser] = {
            "python": self.py_parser,
            "javascript": self.tsjs_parser,
            "typescript": self.tsjs_parser,
            "go": self.go_parser,
            "java": self.java_parser,
            "rust": self.rust_parser,
        }

        # 兼容性属性桥接 (供外部或历史代码访问底层 Query)
        self._py_class_query = self.py_parser.class_query
        self._py_fn_query = self.py_parser.fn_query
        self._py_calls_query = self.py_parser.calls_query

        self._ts_class_query = self.tsjs_parser.ts_class_query
        self._ts_defs_query = self.tsjs_parser.ts_defs_query
        self._ts_calls_query = self.tsjs_parser.ts_calls_query

        self._js_class_query = self.tsjs_parser.js_class_query
        self._js_defs_query = self.tsjs_parser.js_defs_query
        self._js_calls_query = self.tsjs_parser.js_calls_query

        self._go_types_query = self.go_parser.types_query
        self._go_defs_query = self.go_parser.defs_query
        self._go_calls_query = self.go_parser.calls_query

        self._java_types_query = self.java_parser.types_query
        self._java_defs_query = self.java_parser.defs_query
        self._java_calls_query = self.java_parser.calls_query
        self._java_fields_query = self.java_parser.fields_query

        self._rust_types_query = self.rust_parser.types_query
        self._rust_fn_query = self.rust_parser.fn_query
        self._rust_calls_query = self.rust_parser.calls_query

    def is_supported(self, file_path: Path) -> bool:
        ext = file_path.suffix.lower()
        lang = EXTENSION_LANG_MAP.get(ext)
        return bool(lang and lang in self._parsers)

    def extract_calls_from_code(
        self,
        code: str,
        lang: str = "python",
        imports: Optional[FileImports] = None,
        module_name: str = "",
    ) -> List[str]:
        """按需从单段代码中快速提取所有调用的符号名 (微秒级单片段分析，用于按需 Callee 查询)"""
        if not code or lang not in self._parsers or lang not in self._sub_parsers:
            return []
        sub_parser = self._sub_parsers[lang]
        calls_query = getattr(sub_parser, "calls_query", None) or getattr(sub_parser, "ts_calls_query", None)
        if not calls_query:
            return []
        source_bytes = code.encode("utf-8") if isinstance(code, str) else code
        tree = self._parsers[lang].parse(source_bytes)
        cursor = QueryCursor(calls_query)
        matches = cursor.matches(tree.root_node)
        calls = sub_parser.extract_calls_from_matches(matches, source_bytes, imports, module_name)
        del cursor
        del tree
        return calls

    def parse_code(
        self,
        source_bytes: bytes,
        file_name: str = "demo.py",
        lang: Optional[str] = None,
        include_calls: bool = True,
    ) -> List[ParsedSymbol]:
        """直接解析内存中的源代码字节流 (include_calls=False 时仅提取顶层符号定义，毫秒级轻量跳过调用边遍历)"""
        if not lang:
            ext = Path(file_name).suffix.lower()
            lang = EXTENSION_LANG_MAP.get(ext)
        if not lang or lang not in self._parsers or lang not in self._sub_parsers:
            return []
        if not source_bytes.strip():
            return []

        sub_parser = self._sub_parsers[lang]
        parser = self._parsers[lang]
        tree = parser.parse(source_bytes)
        root = tree.root_node

        line_starts = [0] + [m.end() for m in re.finditer(b"\n", source_bytes)]

        def byte_to_line(b: int) -> int:
            return bisect.bisect_right(line_starts, b)

        module_name = get_module_name_from_path(file_name)
        imports = sub_parser.extract_imports(root, source_bytes) if include_calls else None
        symbols: List[ParsedSymbol] = []

        sub_parser.parse(
            tree,
            source_bytes,
            symbols,
            imports=imports,
            module_name=module_name,
            file_path=file_name,
            byte_to_line=byte_to_line,
            include_calls=include_calls,
            lang=lang,
        )

        del tree
        return symbols

    def parse_file(
        self,
        file_path: Path,
        rel_path: Optional[str] = None,
        include_calls: bool = True,
    ) -> List[ParsedSymbol]:
        """读取文件并解析为符号定义列表 (可指定 include_calls=False，纯符号定义秒级抽取)"""
        ext = file_path.suffix.lower()
        lang = EXTENSION_LANG_MAP.get(ext)
        if not lang or lang not in self._parsers:
            return []

        try:
            source_bytes = file_path.read_bytes()
        except Exception:
            return []

        path_for_module = rel_path if rel_path else file_path.as_posix()
        return self.parse_code(source_bytes, path_for_module, lang, include_calls=include_calls)

    # 纯委托辅助方法 (100% 保持历史方法兼容，同时消除冗余重复逻辑)
    def _extract_imports(self, root: Node, source: bytes, lang: str) -> FileImports:
        sub = self._sub_parsers.get(lang)
        return sub.extract_imports(root, source) if sub else FileImports()

    def _extract_calls(
        self,
        node: Node,
        source: bytes,
        lang: str,
        imports: Optional[FileImports] = None,
        current_module: str = "",
        current_class: str = "",
    ) -> List[str]:
        sub = self._sub_parsers.get(lang)
        if not sub:
            return []
        calls_query = getattr(sub, "calls_query", None) or getattr(sub, "ts_calls_query", None)
        if not calls_query:
            return []
        cursor = QueryCursor(calls_query)
        cursor.set_byte_range(int(node.start_byte), int(node.end_byte))
        matches = cursor.matches(node)
        calls = sub.extract_calls_from_matches(
            matches, source, imports=imports, module_name=current_module, current_class=current_class
        )
        del cursor
        return calls

    def _extract_py_calls(self, *args, **kwargs) -> List[str]:
        return self.py_parser.extract_calls_from_matches(*args, **kwargs)

    def _extract_ts_calls(self, *args, **kwargs) -> List[str]:
        return self.tsjs_parser.extract_calls_from_matches(*args, **kwargs)

    def _extract_go_calls(self, *args, **kwargs) -> List[str]:
        return self.go_parser.extract_calls_from_matches(*args, **kwargs)

    def _extract_java_calls(self, *args, **kwargs) -> List[str]:
        return self.java_parser.extract_calls_from_matches(*args, **kwargs)

    def _extract_rust_calls(self, *args, **kwargs) -> List[str]:
        return self.rust_parser.extract_calls_from_matches(*args, **kwargs)

    def _extract_route_from_text(self, text: str) -> str:
        return extract_route_from_text(text)

    def _parse_python(self, *args, **kwargs):
        return self.py_parser.parse(*args, **kwargs)

    def _parse_ts_js(self, *args, **kwargs):
        return self.tsjs_parser.parse(*args, **kwargs)

    def _parse_go(self, *args, **kwargs):
        return self.go_parser.parse(*args, **kwargs)

    def _parse_java(self, *args, **kwargs):
        return self.java_parser.parse(*args, **kwargs)

    def _parse_rust(self, *args, **kwargs):
        return self.rust_parser.parse(*args, **kwargs)
