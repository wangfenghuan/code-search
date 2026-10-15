import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tree_sitter import Language, Node, Parser

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
}


@dataclass
class ParsedSymbol:
    name: str
    symbol_type: str  # class, method, function, struct, interface
    start_line: int
    end_line: int
    code: str
    docstring: Optional[str]
    route_info: str
    signature: str


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


class TreeSitterParser:
    """工业级 Tree-sitter 多语言代码解析器"""

    def __init__(self):
        self._parsers: Dict[str, Parser] = {}
        if PY_LANG:
            self._parsers["python"] = Parser(PY_LANG)
        if JS_LANG:
            self._parsers["javascript"] = Parser(JS_LANG)
        if TS_LANG:
            self._parsers["typescript"] = Parser(TS_LANG)
        if GO_LANG:
            self._parsers["go"] = Parser(GO_LANG)

    def is_supported(self, file_path: Path) -> bool:
        ext = file_path.suffix.lower()
        lang = EXTENSION_LANG_MAP.get(ext)
        return lang in self._parsers

    def parse_file(self, file_path: Path) -> List[ParsedSymbol]:
        ext = file_path.suffix.lower()
        lang = EXTENSION_LANG_MAP.get(ext)
        if not lang or lang not in self._parsers:
            return []

        try:
            source_bytes = file_path.read_bytes()
        except Exception:
            return []

        if not source_bytes.strip():
            return []

        parser = self._parsers[lang]
        tree = parser.parse(source_bytes)
        root = tree.root_node

        symbols: List[ParsedSymbol] = []

        if lang == "python":
            self._parse_python(root, source_bytes, symbols)
        elif lang in ("typescript", "javascript"):
            self._parse_ts_js(root, source_bytes, symbols)
        elif lang == "go":
            self._parse_go(root, source_bytes, symbols)

        return symbols

    def _parse_python(self, root: Node, source: bytes, symbols: List[ParsedSymbol]):
        def extract_item(node: Node):
            target = node
            doc_context = ""
            if node.type == "decorated_definition":
                for c in node.children:
                    if c.type in ("class_definition", "function_definition"):
                        target = c
                        break

            if target.type == "class_definition":
                cls_name = ""
                for n in target.children:
                    if n.type == "identifier":
                        cls_name = get_node_text(n, source)
                        break

                doc = self._get_python_docstring(target, source) or get_leading_comment(node, source)
                symbols.append(
                    ParsedSymbol(
                        name=cls_name or "[AnonymousClass]",
                        symbol_type="class",
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        code=get_node_text(node, source),
                        docstring=doc,
                        route_info="",
                        signature="",
                    )
                )

                # 提取方法
                body = target.child_by_field_name("body")
                if body:
                    for item in body.children:
                        m_target = item
                        if item.type == "decorated_definition":
                            for c in item.children:
                                if c.type == "function_definition":
                                    m_target = c
                                    break
                        if m_target.type == "function_definition":
                            fn_name = ""
                            sig = ""
                            for n in m_target.children:
                                if n.type == "identifier":
                                    fn_name = get_node_text(n, source)
                                elif n.type == "parameters":
                                    sig = get_node_text(n, source)

                            fn_doc = self._get_python_docstring(m_target, source) or get_leading_comment(item, source)
                            route = self._extract_route_from_text(get_node_text(item, source))
                            symbols.append(
                                ParsedSymbol(
                                    name=f"{cls_name}.{fn_name}" if cls_name else fn_name,
                                    symbol_type="method",
                                    start_line=item.start_point.row + 1,
                                    end_line=item.end_point.row + 1,
                                    code=get_node_text(item, source),
                                    docstring=fn_doc,
                                    route_info=route,
                                    signature=sig,
                                )
                            )

            elif target.type == "function_definition":
                fn_name = ""
                sig = ""
                for n in target.children:
                    if n.type == "identifier":
                        fn_name = get_node_text(n, source)
                    elif n.type == "parameters":
                        sig = get_node_text(n, source)

                doc = self._get_python_docstring(target, source) or get_leading_comment(node, source)
                route = self._extract_route_from_text(get_node_text(node, source))
                symbols.append(
                    ParsedSymbol(
                        name=fn_name,
                        symbol_type="function",
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        code=get_node_text(node, source),
                        docstring=doc,
                        route_info=route,
                        signature=sig,
                    )
                )

        for child in root.children:
            extract_item(child)

    def _get_python_docstring(self, node: Node, source: bytes) -> str:
        body = node.child_by_field_name("body")
        if body and body.children:
            first_stmt = body.children[0]
            if first_stmt.type == "expression_statement":
                for sub in first_stmt.children:
                    if sub.type == "string":
                        txt = get_node_text(sub, source)
                        return txt.strip("\"' \n\r")
        return ""

    def _parse_ts_js(self, root: Node, source: bytes, symbols: List[ParsedSymbol]):
        def handle_node(node: Node):
            # 处理 export 包装
            target = node
            if node.type == "export_statement":
                for c in node.children:
                    if c.type in ("class_declaration", "function_declaration", "lexical_declaration"):
                        target = c
                        break

            if target.type == "class_declaration":
                cls_name = ""
                for n in target.children:
                    if n.type in ("identifier", "type_identifier"):
                        cls_name = get_node_text(n, source)
                        break

                doc = get_leading_comment(node, source)
                symbols.append(
                    ParsedSymbol(
                        name=cls_name or "[AnonymousClass]",
                        symbol_type="class",
                        start_line=node.start_point.row + 1,
                        end_line=node.end_point.row + 1,
                        code=get_node_text(node, source),
                        docstring=doc,
                        route_info="",
                        signature="",
                    )
                )

                # 提取方法
                body = target.child_by_field_name("body")
                if body:
                    for item in body.children:
                        if item.type in ("method_definition", "public_field_definition"):
                            m_name = ""
                            sig = ""
                            for n in item.children:
                                if n.type == "property_identifier":
                                    m_name = get_node_text(n, source)
                                elif n.type == "formal_parameters":
                                    sig = get_node_text(n, source)
                            if m_name:
                                m_doc = get_leading_comment(item, source)
                                m_route = self._extract_route_from_text(get_node_text(item, source))
                                symbols.append(
                                    ParsedSymbol(
                                        name=f"{cls_name}.{m_name}" if cls_name else m_name,
                                        symbol_type="method",
                                        start_line=item.start_point.row + 1,
                                        end_line=item.end_point.row + 1,
                                        code=get_node_text(item, source),
                                        docstring=m_doc,
                                        route_info=m_route,
                                        signature=sig,
                                    )
                                )

            elif target.type == "function_declaration":
                fn_name = ""
                sig = ""
                for n in target.children:
                    if n.type == "identifier":
                        fn_name = get_node_text(n, source)
                    elif n.type == "formal_parameters":
                        sig = get_node_text(n, source)
                if fn_name:
                    doc = get_leading_comment(node, source)
                    route = self._extract_route_from_text(get_node_text(node, source))
                    symbols.append(
                        ParsedSymbol(
                            name=fn_name,
                            symbol_type="function",
                            start_line=node.start_point.row + 1,
                            end_line=node.end_point.row + 1,
                            code=get_node_text(node, source),
                            docstring=doc,
                            route_info=route,
                            signature=sig,
                        )
                    )

            elif target.type == "lexical_declaration":
                # const login = async (req, res) => { ... }
                code_text = get_node_text(target, source)
                if "=>" in code_text or "function" in code_text:
                    for decl in target.children:
                        if decl.type == "variable_declarator":
                            v_name = ""
                            for n in decl.children:
                                if n.type == "identifier":
                                    v_name = get_node_text(n, source)
                                    break
                            if v_name:
                                doc = get_leading_comment(node, source)
                                route = self._extract_route_from_text(code_text)
                                symbols.append(
                                    ParsedSymbol(
                                        name=v_name,
                                        symbol_type="function",
                                        start_line=node.start_point.row + 1,
                                        end_line=node.end_point.row + 1,
                                        code=get_node_text(node, source),
                                        docstring=doc,
                                        route_info=route,
                                        signature="()",
                                    )
                                )

        for child in root.children:
            handle_node(child)

    def _parse_go(self, root: Node, source: bytes, symbols: List[ParsedSymbol]):
        for child in root.children:
            if child.type == "type_declaration":
                for spec in child.children:
                    if spec.type == "type_spec":
                        type_name = ""
                        for n in spec.children:
                            if n.type == "type_identifier":
                                type_name = get_node_text(n, source)
                                break
                        doc = get_leading_comment(child, source)
                        symbols.append(
                            ParsedSymbol(
                                name=type_name or "[Struct]",
                                symbol_type="struct",
                                start_line=child.start_point.row + 1,
                                end_line=child.end_point.row + 1,
                                code=get_node_text(child, source),
                                docstring=doc,
                                route_info="",
                                signature="",
                            )
                        )

            elif child.type == "function_declaration":
                fn_name = ""
                sig = ""
                for n in child.children:
                    if n.type == "identifier":
                        fn_name = get_node_text(n, source)
                    elif n.type == "parameter_list":
                        sig = get_node_text(n, source)

                doc = get_leading_comment(child, source)
                route = self._extract_route_from_text(get_node_text(child, source))
                symbols.append(
                    ParsedSymbol(
                        name=fn_name,
                        symbol_type="function",
                        start_line=child.start_point.row + 1,
                        end_line=child.end_point.row + 1,
                        code=get_node_text(child, source),
                        docstring=doc,
                        route_info=route,
                        signature=sig,
                    )
                )

            elif child.type == "method_declaration":
                recv_node = child.child_by_field_name("receiver")
                name_node = child.child_by_field_name("name")
                params_node = child.child_by_field_name("parameters")

                recv_raw = get_node_text(recv_node, source) if recv_node else ""
                fn_name = get_node_text(name_node, source) if name_node else ""
                sig = get_node_text(params_node, source) if params_node else "()"

                recv_clean = re.sub(r"[\*\(\)\s]", "", recv_raw.split()[-1]) if recv_raw else ""
                full_name = f"{recv_clean}.{fn_name}" if recv_clean else fn_name
                doc = get_leading_comment(child, source)
                route = self._extract_route_from_text(get_node_text(child, source))
                symbols.append(
                    ParsedSymbol(
                        name=full_name,
                        symbol_type="method",
                        start_line=child.start_point.row + 1,
                        end_line=child.end_point.row + 1,
                        code=get_node_text(child, source),
                        docstring=doc,
                        route_info=route,
                        signature=sig,
                    )
                )

    def _extract_route_from_text(self, text: str) -> str:
        """从装饰器、注释或路由代码中提取 API 路由"""
        # Python / NestJS: @router.post("/login"), @Post('/auth')
        m = re.search(r"@(?:router|app|\w+)?\.?(get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", text, re.I)
        if m:
            return f"HTTP {m.group(1).upper()} {m.group(2)}"

        # Express / Go Gin: router.POST("/login", ...), app.get('/api/users')
        m2 = re.search(r"\.(GET|POST|PUT|DELETE|PATCH|get|post|put|delete|patch)\s*\(\s*['\"]([^'\"]+)['\"]", text)
        if m2:
            return f"HTTP {m2.group(1).upper()} {m2.group(2)}"

        return ""
