import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from tree_sitter import Language, Node, Parser

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

LANG_BUILTINS: Dict[str, Set[str]] = {
    "python": PYTHON_BUILTINS,
    "javascript": JS_BUILTINS,
    "typescript": JS_BUILTINS,
    "go": GO_BUILTINS,
}

BUILTIN_CALLS: Set[str] = PYTHON_BUILTINS | JS_BUILTINS | GO_BUILTINS


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
class FileImports:
    """单个源文件的依赖导入与实例化拓扑表"""
    # 局部导入的符号名 -> 模块限定名 (如 "AuthService": "auth.AuthService", "hp": "auth.service.hash_password")
    symbols: Dict[str, str] = field(default_factory=dict)
    # 局部导入的模块名/别名 -> 模块路径 (如 "srv": "auth.service", "service": "auth.service")
    modules: Dict[str, str] = field(default_factory=dict)
    # 局部变量实例化推断 (如 "auth_service": "AuthService")
    instances: Dict[str, str] = field(default_factory=dict)


def get_module_name_from_path(file_path: str) -> str:
    """根据文件路径计算标准模块限定前缀 (如 auth/service.py -> auth.service)"""
    p = Path(str(file_path).replace("\\", "/"))
    parts = list(p.parts)
    if not parts:
        return ""
    parts[-1] = p.stem
    clean_parts = []
    for part in parts:
        part = part.rstrip(":\\/ ")
        if not part or part in (".", "..", "src", "app") or part.startswith("."):
            continue
        clean_parts.append(part)
    return ".".join(clean_parts)


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

    def parse_code(self, source_bytes: bytes, file_name: str = "demo.py", lang: Optional[str] = None) -> List[ParsedSymbol]:
        """直接解析内存中的源代码字节流"""
        if not lang:
            ext = Path(file_name).suffix.lower()
            lang = EXTENSION_LANG_MAP.get(ext)
        if not lang or lang not in self._parsers:
            return []
        if not source_bytes.strip():
            return []

        parser = self._parsers[lang]
        tree = parser.parse(source_bytes)
        root = tree.root_node
        symbols: List[ParsedSymbol] = []

        module_name = get_module_name_from_path(file_name)
        imports = self._extract_imports(root, source_bytes, lang)

        if lang == "python":
            self._parse_python(root, source_bytes, symbols, imports=imports, module_name=module_name, file_path=file_name)
        elif lang in ("typescript", "javascript"):
            self._parse_ts_js(root, source_bytes, symbols, imports=imports, module_name=module_name, file_path=file_name)
        elif lang == "go":
            self._parse_go(root, source_bytes, symbols, imports=imports, module_name=module_name, file_path=file_name)

        return symbols

    def parse_file(self, file_path: Path, rel_path: Optional[str] = None) -> List[ParsedSymbol]:
        """读取文件并解析为符号定义列表"""
        ext = file_path.suffix.lower()
        lang = EXTENSION_LANG_MAP.get(ext)
        if not lang or lang not in self._parsers:
            return []

        try:
            source_bytes = file_path.read_bytes()
        except Exception:
            return []

        path_for_module = rel_path if rel_path else file_path.as_posix()
        return self.parse_code(source_bytes, path_for_module, lang)

    def _extract_imports(self, root: Node, source: bytes, lang: str) -> FileImports:
        """从源文件中提取 import / require 及顶级实例化，建立跨文件符号表"""
        file_imports = FileImports()
        if lang == "python":
            for child in root.children:
                if child.type == "import_statement":
                    for sub in child.children:
                        if sub.type == "dotted_name":
                            mod = get_node_text(sub, source).strip()
                            file_imports.modules[mod] = mod
                            if "." in mod:
                                file_imports.modules[mod.split(".")[-1]] = mod
                        elif sub.type == "aliased_import":
                            name_node = sub.child_by_field_name("name")
                            alias_node = sub.child_by_field_name("alias")
                            if name_node and alias_node:
                                real_name = get_node_text(name_node, source).strip()
                                alias = get_node_text(alias_node, source).strip()
                                file_imports.modules[alias] = real_name
                elif child.type == "import_from_statement":
                    mod_name = ""
                    mod_node = child.child_by_field_name("module_name")
                    if mod_node:
                        mod_name = get_node_text(mod_node, source).strip()
                    else:
                        rel_parts = [get_node_text(c, source).strip() for c in child.children if c.type in ("relative_import", "dotted_name")]
                        if rel_parts:
                            mod_name = rel_parts[0]

                    for sub in child.children:
                        if sub.type == "dotted_name" and sub != mod_node:
                            sym = get_node_text(sub, source).strip()
                            file_imports.symbols[sym] = f"{mod_name}.{sym}" if mod_name else sym
                        elif sub.type == "aliased_import":
                            name_node = sub.child_by_field_name("name")
                            alias_node = sub.child_by_field_name("alias")
                            if name_node and alias_node:
                                sym = get_node_text(name_node, source).strip()
                                alias = get_node_text(alias_node, source).strip()
                                file_imports.symbols[alias] = f"{mod_name}.{sym}" if mod_name else sym
                elif child.type == "expression_statement":
                    for sub in child.children:
                        if sub.type == "assignment":
                            left = sub.child_by_field_name("left")
                            right = sub.child_by_field_name("right")
                            if left and right and left.type == "identifier" and right.type == "call":
                                fn = right.child_by_field_name("function")
                                if fn:
                                    var_name = get_node_text(left, source).strip()
                                    cls_name = get_node_text(fn, source).strip()
                                    file_imports.instances[var_name] = cls_name
        elif lang in ("typescript", "javascript"):
            for child in root.children:
                stmt = child
                if child.type == "export_statement":
                    for c in child.children:
                        if c.type in ("import_statement", "lexical_declaration", "variable_declaration"):
                            stmt = c
                            break
                if stmt.type == "import_statement":
                    src_node = stmt.child_by_field_name("source")
                    src_path = get_node_text(src_node, source).strip("\"' ;") if src_node else ""
                    clean_mod = get_module_name_from_path(src_path) or src_path.split("/")[-1]
                    for sub in stmt.children:
                        if sub.type == "import_clause":
                            for item in sub.children:
                                if item.type == "identifier":
                                    alias = get_node_text(item, source).strip()
                                    file_imports.modules[alias] = clean_mod
                                    file_imports.symbols[alias] = clean_mod
                                elif item.type == "named_imports":
                                    for spec in item.children:
                                        if spec.type == "import_specifier":
                                            name_n = spec.child_by_field_name("name")
                                            alias_n = spec.child_by_field_name("alias")
                                            if name_n:
                                                name_str = get_node_text(name_n, source).strip()
                                                alias_str = get_node_text(alias_n, source).strip() if alias_n else name_str
                                                file_imports.symbols[alias_str] = f"{clean_mod}.{name_str}" if clean_mod else name_str
                elif stmt.type in ("lexical_declaration", "variable_declaration"):
                    for decl in stmt.children:
                        if decl.type == "variable_declarator":
                            name_n = decl.child_by_field_name("name")
                            val_n = decl.child_by_field_name("value")
                            if name_n and val_n and name_n.type == "identifier":
                                v_name = get_node_text(name_n, source).strip()
                                if val_n.type == "new_expression":
                                    c_node = val_n.child_by_field_name("constructor")
                                    if c_node:
                                        c_name = get_node_text(c_node, source).strip()
                                        file_imports.instances[v_name] = c_name
                                elif val_n.type == "call_expression":
                                    fn = val_n.child_by_field_name("function")
                                    if fn and get_node_text(fn, source).strip() == "require":
                                        args = val_n.child_by_field_name("arguments")
                                        if args and args.children:
                                            arg_text = get_node_text(args.children[1] if len(args.children) > 1 else args.children[0], source).strip("\"' ")
                                            mod_n = get_module_name_from_path(arg_text) or arg_text.split("/")[-1]
                                            file_imports.modules[v_name] = mod_n
        elif lang == "go":
            for child in root.children:
                if child.type == "import_declaration":
                    for spec in child.children:
                        if spec.type == "import_spec":
                            p_node = spec.child_by_field_name("path")
                            n_node = spec.child_by_field_name("name")
                            if p_node:
                                p_str = get_node_text(p_node, source).strip("\"' ")
                                default_name = p_str.split("/")[-1]
                                alias = get_node_text(n_node, source).strip() if n_node else default_name
                                file_imports.modules[alias] = p_str
                        elif spec.type == "import_spec_list":
                            for s in spec.children:
                                if s.type == "import_spec":
                                    p_node = s.child_by_field_name("path")
                                    n_node = s.child_by_field_name("name")
                                    if p_node:
                                        p_str = get_node_text(p_node, source).strip("\"' ")
                                        default_name = p_str.split("/")[-1]
                                        alias = get_node_text(n_node, source).strip() if n_node else default_name
                                        file_imports.modules[alias] = p_str

        return file_imports

    def _extract_calls(
        self,
        node: Node,
        source: bytes,
        lang: str,
        imports: Optional[FileImports] = None,
        current_module: str = "",
        current_class: str = "",
    ) -> List[str]:
        """提取 AST 节点内部调用的所有函数或方法名，并结合符号表生成限定目标"""
        calls: List[str] = []
        seen = set()

        def walk(curr: Node):
            # 避开嵌套的类定义，避免干扰
            if curr != node and curr.type in ("class_definition", "class_declaration"):
                return

            call_names = []
            if lang == "python" and curr.type == "call":
                fn_node = curr.child_by_field_name("function")
                if fn_node:
                    if fn_node.type == "identifier":
                        bare = get_node_text(fn_node, source).strip()
                        call_names.append(bare)
                        if imports and bare in imports.symbols:
                            call_names.append(imports.symbols[bare])
                        elif current_module:
                            call_names.append(f"{current_module}.{bare}")
                    elif fn_node.type == "attribute":
                        attr_node = fn_node.child_by_field_name("attribute")
                        obj_node = fn_node.child_by_field_name("object")
                        if attr_node:
                            attr_name = get_node_text(attr_node, source).strip()
                            call_names.append(attr_name)
                            if obj_node:
                                obj_name = get_node_text(obj_node, source).strip()
                                if obj_name in ("self", "cls"):
                                    if current_class:
                                        call_names.append(f"{current_class}.{attr_name}")
                                        if current_module:
                                            call_names.append(f"{current_module}.{current_class}.{attr_name}")
                                elif imports and obj_name in imports.instances:
                                    inst_cls = imports.instances[obj_name]
                                    if inst_cls in imports.symbols:
                                        call_names.append(f"{imports.symbols[inst_cls]}.{attr_name}")
                                    elif current_module:
                                        call_names.append(f"{current_module}.{inst_cls}.{attr_name}")
                                    else:
                                        call_names.append(f"{inst_cls}.{attr_name}")
                                elif imports and obj_name in imports.modules:
                                    mod = imports.modules[obj_name]
                                    call_names.append(f"{mod}.{attr_name}")
                                elif imports and obj_name in imports.symbols:
                                    sym = imports.symbols[obj_name]
                                    call_names.append(f"{sym}.{attr_name}")
                                else:
                                    call_names.append(f"{obj_name}.{attr_name}")
            elif lang in ("typescript", "javascript") and curr.type == "call_expression":
                fn_node = curr.child_by_field_name("function")
                if fn_node:
                    if fn_node.type == "identifier":
                        bare = get_node_text(fn_node, source).strip()
                        call_names.append(bare)
                        if imports and bare in imports.symbols:
                            call_names.append(imports.symbols[bare])
                        elif current_module:
                            call_names.append(f"{current_module}.{bare}")
                    elif fn_node.type == "member_expression":
                        # 过滤 console.log / console.error 等调用
                        obj_node = fn_node.child_by_field_name("object")
                        prop_node = fn_node.child_by_field_name("property")
                        if obj_node and prop_node:
                            obj_text = get_node_text(obj_node, source).strip()
                            prop_text = get_node_text(prop_node, source).strip()
                            if obj_text != "console":
                                call_names.append(prop_text)
                                if obj_text == "this":
                                    if current_class:
                                        call_names.append(f"{current_class}.{prop_text}")
                                        if current_module:
                                            call_names.append(f"{current_module}.{current_class}.{prop_text}")
                                elif imports and obj_text in imports.instances:
                                    inst_cls = imports.instances[obj_text]
                                    if inst_cls in imports.symbols:
                                        call_names.append(f"{imports.symbols[inst_cls]}.{prop_text}")
                                    else:
                                        call_names.append(f"{inst_cls}.{prop_text}")
                                elif imports and obj_text in imports.modules:
                                    mod = imports.modules[obj_text]
                                    call_names.append(f"{mod}.{prop_text}")
                                else:
                                    call_names.append(f"{obj_text}.{prop_text}")
            elif lang == "go" and curr.type == "call_expression":
                fn_node = curr.child_by_field_name("function")
                if fn_node:
                    if fn_node.type == "identifier":
                        bare = get_node_text(fn_node, source).strip()
                        call_names.append(bare)
                        if current_module:
                            call_names.append(f"{current_module}.{bare}")
                    elif fn_node.type == "selector_expression":
                        field_node = fn_node.child_by_field_name("field")
                        operand_node = fn_node.child_by_field_name("operand")
                        if field_node:
                            field_name = get_node_text(field_node, source).strip()
                            call_names.append(field_name)
                            if operand_node:
                                operand_name = get_node_text(operand_node, source).strip()
                                call_names.append(f"{operand_name}.{field_name}")

            lang_builtins = LANG_BUILTINS.get(lang, BUILTIN_CALLS)
            for name in call_names:
                if name and name not in lang_builtins and name not in seen:
                    seen.add(name)
                    calls.append(name)

            for child in curr.children:
                walk(child)

        walk(node)
        return calls

    def _parse_python(
        self,
        root: Node,
        source: bytes,
        symbols: List[ParsedSymbol],
        imports: Optional[FileImports] = None,
        module_name: str = "",
        file_path: str = "",
    ):
        def extract_item(node: Node):
            target = node
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
                cls_qname = f"{module_name}.{cls_name}" if module_name else cls_name
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
                        calls=[],
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=cls_qname,
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
                            m_calls = self._extract_calls(
                                m_target,
                                source,
                                "python",
                                imports=imports,
                                current_module=module_name,
                                current_class=cls_name,
                            )
                            method_name = f"{cls_name}.{fn_name}" if cls_name else fn_name
                            m_qname = f"{module_name}.{method_name}" if module_name else method_name
                            symbols.append(
                                ParsedSymbol(
                                    name=method_name,
                                    symbol_type="method",
                                    start_line=item.start_point.row + 1,
                                    end_line=item.end_point.row + 1,
                                    code=get_node_text(item, source),
                                    docstring=fn_doc,
                                    route_info=route,
                                    signature=sig,
                                    calls=m_calls,
                                    file_path=file_path,
                                    module_name=module_name,
                                    qualified_name=m_qname,
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
                fn_calls = self._extract_calls(
                    target,
                    source,
                    "python",
                    imports=imports,
                    current_module=module_name,
                    current_class="",
                )
                fn_qname = f"{module_name}.{fn_name}" if module_name else fn_name
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
                        calls=fn_calls,
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=fn_qname,
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

    def _parse_ts_js(
        self,
        root: Node,
        source: bytes,
        symbols: List[ParsedSymbol],
        imports: Optional[FileImports] = None,
        module_name: str = "",
        file_path: str = "",
    ):
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
                cls_qname = f"{module_name}.{cls_name}" if module_name else cls_name
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
                        calls=[],
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=cls_qname,
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
                                m_calls = self._extract_calls(
                                    item,
                                    source,
                                    "typescript",
                                    imports=imports,
                                    current_module=module_name,
                                    current_class=cls_name,
                                )
                                full_method = f"{cls_name}.{m_name}" if cls_name else m_name
                                m_qname = f"{module_name}.{full_method}" if module_name else full_method
                                symbols.append(
                                    ParsedSymbol(
                                        name=full_method,
                                        symbol_type="method",
                                        start_line=item.start_point.row + 1,
                                        end_line=item.end_point.row + 1,
                                        code=get_node_text(item, source),
                                        docstring=m_doc,
                                        route_info=m_route,
                                        signature=sig,
                                        calls=m_calls,
                                        file_path=file_path,
                                        module_name=module_name,
                                        qualified_name=m_qname,
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
                    fn_calls = self._extract_calls(
                        target,
                        source,
                        "typescript",
                        imports=imports,
                        current_module=module_name,
                        current_class="",
                    )
                    fn_qname = f"{module_name}.{fn_name}" if module_name else fn_name
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
                            calls=fn_calls,
                            file_path=file_path,
                            module_name=module_name,
                            qualified_name=fn_qname,
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
                                fn_calls = self._extract_calls(
                                    target,
                                    source,
                                    "typescript",
                                    imports=imports,
                                    current_module=module_name,
                                    current_class="",
                                )
                                v_qname = f"{module_name}.{v_name}" if module_name else v_name
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
                                        calls=fn_calls,
                                        file_path=file_path,
                                        module_name=module_name,
                                        qualified_name=v_qname,
                                    )
                                )

        for child in root.children:
            handle_node(child)

    def _parse_go(
        self,
        root: Node,
        source: bytes,
        symbols: List[ParsedSymbol],
        imports: Optional[FileImports] = None,
        module_name: str = "",
        file_path: str = "",
    ):
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
                        struct_qname = f"{module_name}.{type_name}" if module_name else type_name
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
                                calls=[],
                                file_path=file_path,
                                module_name=module_name,
                                qualified_name=struct_qname,
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
                fn_calls = self._extract_calls(
                    child,
                    source,
                    "go",
                    imports=imports,
                    current_module=module_name,
                    current_class="",
                )
                fn_qname = f"{module_name}.{fn_name}" if module_name else fn_name
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
                        calls=fn_calls,
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=fn_qname,
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
                fn_calls = self._extract_calls(
                    child,
                    source,
                    "go",
                    imports=imports,
                    current_module=module_name,
                    current_class=recv_clean,
                )
                method_qname = f"{module_name}.{full_name}" if module_name else full_name
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
                        calls=fn_calls,
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=method_qname,
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
