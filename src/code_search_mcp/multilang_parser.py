import bisect
import re
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

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
    """工业级 Tree-sitter 多语言代码解析器 (基于 Tree-sitter Query S-expression 与微秒级线段树映射)"""

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

        # 预编译查询 (Tree-sitter Query S-expressions)
        self._py_class_query = Query(PY_LANG, "(class_definition name: (identifier) @cls.name) @cls.def") if PY_LANG else None
        self._py_fn_query = Query(PY_LANG, "(function_definition name: (identifier) @fn.name) @fn.def") if PY_LANG else None
        self._py_calls_query = Query(PY_LANG, """
        (call function: (identifier) @call.ident) @call.root
        (call function: (attribute object: (_) @call.obj attribute: (identifier) @call.attr)) @call.root
        (call function: (subscript value: (_) @call.sub_val subscript: (_) @call.sub_key)) @call.root
        (call function: (call function: (identifier) @call.chained_fn arguments: (argument_list) @call.chained_args)) @call.root
        """) if PY_LANG else None

        self._ts_class_query = Query(TS_LANG, "(class_declaration name: (type_identifier) @cls.name) @cls.def") if TS_LANG else None
        self._ts_defs_query = Query(TS_LANG, """
        (function_declaration name: (identifier) @fn.name) @fn.def
        (method_definition name: (property_identifier) @method.name) @method.def
        (public_field_definition name: (property_identifier) @field.name) @field.def
        (lexical_declaration (variable_declarator name: (identifier) @var.name value: [(arrow_function) (function_expression)])) @var.def
        (variable_declaration (variable_declarator name: (identifier) @var.name value: [(arrow_function) (function_expression)])) @var.def
        """) if TS_LANG else None
        self._ts_calls_query = Query(TS_LANG, """
        (call_expression function: (identifier) @call.ident) @call.root
        (call_expression function: (member_expression object: (_) @call.obj property: (property_identifier) @call.prop)) @call.root
        (call_expression function: (subscript_expression object: (_) @call.obj index: (_) @call.idx)) @call.root
        """) if TS_LANG else None

        self._js_class_query = Query(JS_LANG, "(class_declaration name: (identifier) @cls.name) @cls.def") if JS_LANG else None
        self._js_defs_query = Query(JS_LANG, """
        (function_declaration name: (identifier) @fn.name) @fn.def
        (method_definition name: (property_identifier) @method.name) @method.def
        (lexical_declaration (variable_declarator name: (identifier) @var.name value: [(arrow_function) (function_expression)])) @var.def
        (variable_declaration (variable_declarator name: (identifier) @var.name value: [(arrow_function) (function_expression)])) @var.def
        """) if JS_LANG else None
        self._js_calls_query = Query(JS_LANG, """
        (call_expression function: (identifier) @call.ident) @call.root
        (call_expression function: (member_expression object: (_) @call.obj property: (property_identifier) @call.prop)) @call.root
        (call_expression function: (subscript_expression object: (_) @call.obj index: (_) @call.idx)) @call.root
        """) if JS_LANG else None

        self._go_types_query = Query(GO_LANG, """
        (type_spec name: (type_identifier) @type.name type: (struct_type)) @struct.def
        (type_spec name: (type_identifier) @type.name type: (interface_type)) @iface.def
        """) if GO_LANG else None
        self._go_defs_query = Query(GO_LANG, """
        (function_declaration name: (identifier) @fn.name) @fn.def
        (method_declaration receiver: (parameter_list) @method.recv name: (field_identifier) @method.name) @method.def
        """) if GO_LANG else None
        self._go_calls_query = Query(GO_LANG, """
        (call_expression function: (identifier) @call.ident) @call.root
        (call_expression function: (selector_expression operand: (_) @call.operand field: (field_identifier) @call.field)) @call.root
        (call_expression function: (index_expression operand: (_) @call.operand index: (_) @call.idx)) @call.root
        """) if GO_LANG else None

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

        line_starts = [0] + [m.end() for m in re.finditer(b"\\n", source_bytes)]

        def byte_to_line(b: int) -> int:
            return bisect.bisect_right(line_starts, b)

        module_name = get_module_name_from_path(file_name)
        imports = self._extract_imports(root, source_bytes, lang)
        symbols: List[ParsedSymbol] = []

        if lang == "python":
            self._parse_python(tree, source_bytes, symbols, imports=imports, module_name=module_name, file_path=file_name, byte_to_line=byte_to_line)
        elif lang in ("typescript", "javascript"):
            self._parse_ts_js(tree, source_bytes, symbols, imports=imports, module_name=module_name, file_path=file_name, byte_to_line=byte_to_line, lang=lang)
        elif lang == "go":
            self._parse_go(tree, source_bytes, symbols, imports=imports, module_name=module_name, file_path=file_name, byte_to_line=byte_to_line)

        del tree
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

    def _extract_py_calls(self, matches, source: bytes, imports: Optional[FileImports], module_name: str, current_class: str) -> List[str]:
        calls = []
        seen = set()
        for pat, cap in matches:
            call_names = []
            if "call.ident" in cap:
                bare = get_node_text(cap["call.ident"][0], source).strip()
                if bare == "getattr" and "call.root" in cap:
                    args_node = cap["call.root"][0].child_by_field_name("arguments")
                    if args_node:
                        pos_args = [c for c in args_node.children if c.type not in ("(", ")", ",")]
                        if len(pos_args) >= 2:
                            obj_text = get_node_text(pos_args[0], source).strip()
                            attr_node = pos_args[1]
                            if attr_node.type == "string":
                                attr_name = get_node_text(attr_node, source).strip().strip("'\"")
                                call_names.append(attr_name)
                                call_names.append(f"dynamic:getattr({obj_text},{attr_name})")
                                if obj_text in ("self", "cls") and current_class:
                                    call_names.append(f"{current_class}.{attr_name}")
                                    if module_name:
                                        call_names.append(f"{module_name}.{current_class}.{attr_name}")
                                elif imports and obj_text in imports.instances:
                                    inst_cls = imports.instances[obj_text]
                                    if inst_cls in imports.symbols:
                                        call_names.append(f"{imports.symbols[inst_cls]}.{attr_name}")
                                    else:
                                        call_names.append(f"{inst_cls}.{attr_name}")
                                else:
                                    call_names.append(f"{obj_text}.{attr_name}")
                            else:
                                dyn_name = get_node_text(attr_node, source).strip()
                                call_names.append(f"<dynamic:{dyn_name}>")
                                call_names.append(f"dynamic:getattr({obj_text},{dyn_name})")
                else:
                    call_names.append(bare)
                    if imports and bare in imports.symbols:
                        call_names.append(imports.symbols[bare])
                    elif module_name:
                        call_names.append(f"{module_name}.{bare}")
            elif "call.attr" in cap:
                attr_name = get_node_text(cap["call.attr"][0], source).strip()
                call_names.append(attr_name)
                if "call.obj" in cap:
                    obj_name = get_node_text(cap["call.obj"][0], source).strip()
                    if obj_name in ("self", "cls"):
                        if current_class:
                            call_names.append(f"{current_class}.{attr_name}")
                            if module_name:
                                call_names.append(f"{module_name}.{current_class}.{attr_name}")
                    elif imports and obj_name in imports.instances:
                        inst_cls = imports.instances[obj_name]
                        if inst_cls in imports.symbols:
                            call_names.append(f"{imports.symbols[inst_cls]}.{attr_name}")
                        elif module_name:
                            call_names.append(f"{module_name}.{inst_cls}.{attr_name}")
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
            elif "call.sub_val" in cap and "call.sub_key" in cap:
                val_text = get_node_text(cap["call.sub_val"][0], source).strip()
                sub_node = cap["call.sub_key"][0]
                if sub_node.type == "string":
                    key_name = get_node_text(sub_node, source).strip().strip("'\"")
                    call_names.append(key_name)
                    call_names.append(f"{val_text}.{key_name}")
                    call_names.append(f"dynamic:subscript({val_text},{key_name})")
                else:
                    dyn_key = get_node_text(sub_node, source).strip()
                    call_names.append(f"<dynamic:{dyn_key}>")
                    call_names.append(f"dynamic:subscript({val_text},{dyn_key})")

            for name in call_names:
                if name and name not in PYTHON_BUILTINS and name not in seen:
                    seen.add(name)
                    calls.append(name)
        return calls

    def _extract_ts_calls(self, matches, source: bytes, imports: Optional[FileImports], module_name: str, current_class: str) -> List[str]:
        calls = []
        seen = set()
        for pat, cap in matches:
            call_names = []
            if "call.ident" in cap:
                bare = get_node_text(cap["call.ident"][0], source).strip()
                call_names.append(bare)
                if imports and bare in imports.symbols:
                    call_names.append(imports.symbols[bare])
                elif module_name:
                    call_names.append(f"{module_name}.{bare}")
            elif "call.prop" in cap and "call.obj" in cap:
                obj_text = get_node_text(cap["call.obj"][0], source).strip()
                prop_text = get_node_text(cap["call.prop"][0], source).strip()
                if obj_text != "console":
                    call_names.append(prop_text)
                    if obj_text == "this":
                        if current_class:
                            call_names.append(f"{current_class}.{prop_text}")
                            if module_name:
                                call_names.append(f"{module_name}.{current_class}.{prop_text}")
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
            elif "call.idx" in cap and "call.obj" in cap:
                obj_text = get_node_text(cap["call.obj"][0], source).strip()
                idx_node = cap["call.idx"][0]
                if idx_node.type == "string":
                    prop_text = get_node_text(idx_node, source).strip().strip("'\"`")
                    call_names.append(prop_text)
                    call_names.append(f"dynamic:subscript({obj_text},{prop_text})")
                    if obj_text == "this" and current_class:
                        call_names.append(f"{current_class}.{prop_text}")
                        if module_name:
                            call_names.append(f"{module_name}.{current_class}.{prop_text}")
                    elif imports and obj_text in imports.instances:
                        inst_cls = imports.instances[obj_text]
                        if inst_cls in imports.symbols:
                            call_names.append(f"{imports.symbols[inst_cls]}.{prop_text}")
                        else:
                            call_names.append(f"{inst_cls}.{prop_text}")
                    else:
                        call_names.append(f"{obj_text}.{prop_text}")
                else:
                    dyn_var = get_node_text(idx_node, source).strip()
                    call_names.append(f"<dynamic:{dyn_var}>")
                    call_names.append(f"dynamic:subscript({obj_text},{dyn_var})")

            for name in call_names:
                if name and name not in JS_BUILTINS and name not in seen:
                    seen.add(name)
                    calls.append(name)
        return calls

    def _extract_go_calls(self, matches, source: bytes, imports: Optional[FileImports], module_name: str) -> List[str]:
        calls = []
        seen = set()
        for pat, cap in matches:
            call_names = []
            if "call.ident" in cap:
                bare = get_node_text(cap["call.ident"][0], source).strip()
                call_names.append(bare)
                if module_name:
                    call_names.append(f"{module_name}.{bare}")
            elif "call.field" in cap and "call.operand" in cap:
                field_name = get_node_text(cap["call.field"][0], source).strip()
                operand_name = get_node_text(cap["call.operand"][0], source).strip()
                call_names.append(field_name)
                call_names.append(f"{operand_name}.{field_name}")
            elif "call.idx" in cap and "call.operand" in cap:
                op_name = get_node_text(cap["call.operand"][0], source).strip()
                idx_name = get_node_text(cap["call.idx"][0], source).strip().strip("`\"")
                call_names.append(idx_name)
                call_names.append(f"{op_name}.{idx_name}")
                call_names.append(f"dynamic:index({op_name},{idx_name})")

            for name in call_names:
                if name and name not in GO_BUILTINS and name not in seen:
                    seen.add(name)
                    calls.append(name)
        return calls

    def _extract_calls(
        self,
        node: Node,
        source: bytes,
        lang: str,
        imports: Optional[FileImports] = None,
        current_module: str = "",
        current_class: str = "",
    ) -> List[str]:
        """向后兼容的调用提取接口 (内部转调高效 Query Cursor)"""
        query_map = {
            "python": self._py_calls_query,
            "typescript": self._ts_calls_query,
            "javascript": self._ts_calls_query,
            "go": self._go_calls_query,
        }
        query = query_map.get(lang)
        if not query:
            return []
        cursor = QueryCursor(query)
        cursor.set_byte_range(int(node.start_byte), int(node.end_byte))
        matches = cursor.matches(node)
        if lang == "python":
            calls = self._extract_py_calls(matches, source, imports, current_module, current_class)
        elif lang in ("typescript", "javascript"):
            calls = self._extract_ts_calls(matches, source, imports, current_module, current_class)
        elif lang == "go":
            calls = self._extract_go_calls(matches, source, imports, current_module)
        else:
            calls = []
        del cursor
        return calls

    def _parse_python(
        self,
        tree: Any,
        source: bytes,
        symbols: List[ParsedSymbol],
        imports: Optional[FileImports] = None,
        module_name: str = "",
        file_path: str = "",
        byte_to_line=None,
    ):
        if byte_to_line is None:
            line_starts = [0] + [m.end() for m in re.finditer(b"\n", source)]
            byte_to_line = lambda b: bisect.bisect_right(line_starts, b)

        root = tree.root_node if hasattr(tree, "root_node") else tree
        classes = []

        # 1. 声明式查询类定义
        if self._py_class_query:
            cursor_cls = QueryCursor(self._py_class_query)
            for pat, cap in cursor_cls.matches(root):
                def_node = cap["cls.def"][0]
                outer_node = def_node.parent if def_node.parent and def_node.parent.type == "decorated_definition" else def_node
                name = get_node_text(cap["cls.name"][0], source).strip()
                s_byte = int(outer_node.start_byte)
                e_byte = int(outer_node.end_byte)
                s_line = byte_to_line(s_byte)
                e_line = byte_to_line(e_byte)
                code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")
                doc = get_leading_comment(outer_node, source)
                cls_qname = f"{module_name}.{name}" if module_name else name
                classes.append({
                    "name": name,
                    "start": s_byte,
                    "end": e_byte,
                })
                symbols.append(
                    ParsedSymbol(
                        name=name or "[AnonymousClass]",
                        symbol_type="class",
                        start_line=s_line,
                        end_line=e_line,
                        code=code_text,
                        docstring=doc,
                        route_info="",
                        signature="",
                        calls=[],
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=cls_qname,
                    )
                )
            del cursor_cls

        # 2. 声明式查询函数/方法定义与单遍二分调用匹配 (Single-Pass Call Site Extraction)
        if self._py_fn_query and self._py_calls_query:
            cursor_fn = QueryCursor(self._py_fn_query)
            cursor_calls = QueryCursor(self._py_calls_query)

            all_file_calls = []
            for pat, cap in cursor_calls.matches(root):
                if "call.root" in cap:
                    sb = int(cap["call.root"][0].start_byte)
                    all_file_calls.append((sb, pat, cap))
            del cursor_calls
            if all_file_calls:
                all_file_calls.sort(key=lambda x: x[0])
            call_starts = [x[0] for x in all_file_calls]
            cls_starts = [c["start"] for c in classes]

            for pat, cap in cursor_fn.matches(root):
                def_node = cap["fn.def"][0]
                outer_node = def_node.parent if def_node.parent and def_node.parent.type == "decorated_definition" else def_node
                fn_name = get_node_text(cap["fn.name"][0], source).strip()
                s_byte = int(outer_node.start_byte)
                e_byte = int(outer_node.end_byte)
                s_line = byte_to_line(s_byte)
                e_line = byte_to_line(e_byte)
                code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")
                doc = get_leading_comment(outer_node, source)
                route = self._extract_route_from_text(code_text)

                # 所属类判定：二分查找 O(log K) 替代全量 O(K) 线性扫描
                # classes 在进入本循环前已按 start_byte 升序排列（由 tree-sitter 查询顺序保证）
                parent_cls = None
                # 用 bisect 找出所有 start <= s_byte 的类（候选集），再过滤 end >= e_byte
                hi = bisect.bisect_right(cls_starts, s_byte)
                best_span = None
                for c in classes[:hi]:
                    if c["end"] >= e_byte:
                        span = c["end"] - c["start"]
                        if best_span is None or span < best_span:
                            best_span = span
                            parent_cls = c["name"]

                # 签名提取
                params_node = def_node.child_by_field_name("parameters")
                sig = get_node_text(params_node, source) if params_node else "()"

                # 二分区间查询调用 (O(log K) 极速匹配)
                idx_left = bisect.bisect_left(call_starts, int(def_node.start_byte))
                idx_right = bisect.bisect_right(call_starts, int(def_node.end_byte))
                call_matches = [(item[1], item[2]) for item in all_file_calls[idx_left:idx_right]]
                fn_calls = self._extract_py_calls(call_matches, source, imports, module_name, parent_cls or "")

                full_name = f"{parent_cls}.{fn_name}" if parent_cls else fn_name
                qname = f"{module_name}.{full_name}" if module_name else full_name
                symbols.append(
                    ParsedSymbol(
                        name=full_name,
                        symbol_type="method" if parent_cls else "function",
                        start_line=s_line,
                        end_line=e_line,
                        code=code_text,
                        docstring=doc,
                        route_info=route,
                        signature=sig,
                        calls=fn_calls,
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=qname,
                    )
                )

            del cursor_fn

    def _parse_ts_js(
        self,
        tree: Any,
        source: bytes,
        symbols: List[ParsedSymbol],
        imports: Optional[FileImports] = None,
        module_name: str = "",
        file_path: str = "",
        byte_to_line=None,
        lang: str = "typescript",
    ):
        if byte_to_line is None:
            line_starts = [0] + [m.end() for m in re.finditer(b"\n", source)]
            byte_to_line = lambda b: bisect.bisect_right(line_starts, b)

        root = tree.root_node if hasattr(tree, "root_node") else tree
        classes = []

        is_js = (lang == "javascript")
        class_query = self._js_class_query if is_js else self._ts_class_query
        defs_query = self._js_defs_query if is_js else self._ts_defs_query
        calls_query = self._js_calls_query if is_js else self._ts_calls_query

        if class_query:
            cursor_cls = QueryCursor(class_query)
            for pat, cap in cursor_cls.matches(root):
                def_node = cap["cls.def"][0]
                outer_node = def_node.parent if def_node.parent and def_node.parent.type == "export_statement" else def_node
                name = get_node_text(cap["cls.name"][0], source).strip()
                s_byte = int(outer_node.start_byte)
                e_byte = int(outer_node.end_byte)
                s_line = byte_to_line(s_byte)
                e_line = byte_to_line(e_byte)
                code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")
                doc = get_leading_comment(outer_node, source)
                cls_qname = f"{module_name}.{name}" if module_name else name
                classes.append({"name": name, "start": s_byte, "end": e_byte})
                symbols.append(
                    ParsedSymbol(
                        name=name or "[AnonymousClass]",
                        symbol_type="class",
                        start_line=s_line,
                        end_line=e_line,
                        code=code_text,
                        docstring=doc,
                        route_info="",
                        signature="",
                        calls=[],
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=cls_qname,
                    )
                )
            del cursor_cls

        if defs_query and calls_query:
            cursor_defs = QueryCursor(defs_query)
            cursor_calls = QueryCursor(calls_query)

            all_file_calls = []
            for pat, cap in cursor_calls.matches(root):
                if "call.root" in cap:
                    sb = int(cap["call.root"][0].start_byte)
                    all_file_calls.append((sb, pat, cap))
            del cursor_calls
            if all_file_calls:
                all_file_calls.sort(key=lambda x: x[0])
            call_starts = [x[0] for x in all_file_calls]

            for pat, cap in cursor_defs.matches(root):
                item_node = None
                name = ""
                sym_type = "function"
                sig = "()"

                if "fn.def" in cap and "fn.name" in cap:
                    item_node = cap["fn.def"][0]
                    name = get_node_text(cap["fn.name"][0], source).strip()
                    params = item_node.child_by_field_name("parameters") or item_node.child_by_field_name("formal_parameters")
                    sig = get_node_text(params, source) if params else "()"
                elif "method.def" in cap and "method.name" in cap:
                    item_node = cap["method.def"][0]
                    name = get_node_text(cap["method.name"][0], source).strip()
                    sym_type = "method"
                    params = item_node.child_by_field_name("parameters") or item_node.child_by_field_name("formal_parameters")
                    sig = get_node_text(params, source) if params else "()"
                elif "field.def" in cap and "field.name" in cap:
                    item_node = cap["field.def"][0]
                    name = get_node_text(cap["field.name"][0], source).strip()
                    sym_type = "method"
                    sig = ""
                elif "var.def" in cap and "var.name" in cap:
                    item_node = cap["var.def"][0]
                    name = get_node_text(cap["var.name"][0], source).strip()
                    sym_type = "function"
                    sig = "()"

                if not item_node or not name:
                    continue

                outer_node = item_node.parent if item_node.parent and item_node.parent.type == "export_statement" else item_node
                s_byte = int(outer_node.start_byte)
                e_byte = int(outer_node.end_byte)
                s_line = byte_to_line(s_byte)
                e_line = byte_to_line(e_byte)
                code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")

                parent_cls = None
                enclosing = [c for c in classes if c["start"] <= s_byte and e_byte <= c["end"]]
                if enclosing:
                    enclosing.sort(key=lambda c: c["end"] - c["start"])
                    parent_cls = enclosing[0]["name"]
                    sym_type = "method"

                doc = get_leading_comment(outer_node, source)
                route = self._extract_route_from_text(code_text)

                # 二分区间查询调用 (O(log K) 极速匹配)
                idx_left = bisect.bisect_left(call_starts, int(item_node.start_byte))
                idx_right = bisect.bisect_right(call_starts, int(item_node.end_byte))
                call_matches = [(item[1], item[2]) for item in all_file_calls[idx_left:idx_right]]
                fn_calls = self._extract_ts_calls(call_matches, source, imports, module_name, parent_cls or "")

                full_name = f"{parent_cls}.{name}" if parent_cls else name
                qname = f"{module_name}.{full_name}" if module_name else full_name
                symbols.append(
                    ParsedSymbol(
                        name=full_name,
                        symbol_type=sym_type,
                        start_line=s_line,
                        end_line=e_line,
                        code=code_text,
                        docstring=doc,
                        route_info=route,
                        signature=sig,
                        calls=fn_calls,
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=qname,
                    )
                )

            del cursor_defs

    def _parse_go(
        self,
        tree: Any,
        source: bytes,
        symbols: List[ParsedSymbol],
        imports: Optional[FileImports] = None,
        module_name: str = "",
        file_path: str = "",
        byte_to_line=None,
    ):
        if byte_to_line is None:
            line_starts = [0] + [m.end() for m in re.finditer(b"\n", source)]
            byte_to_line = lambda b: bisect.bisect_right(line_starts, b)

        root = tree.root_node if hasattr(tree, "root_node") else tree

        if self._go_types_query:
            cursor_types = QueryCursor(self._go_types_query)
            for pat, cap in cursor_types.matches(root):
                node = cap.get("struct.def", cap.get("iface.def"))[0]
                outer_node = node.parent if node.parent and node.parent.type == "type_declaration" else node
                name = get_node_text(cap["type.name"][0], source).strip()
                s_byte = int(outer_node.start_byte)
                e_byte = int(outer_node.end_byte)
                s_line = byte_to_line(s_byte)
                e_line = byte_to_line(e_byte)
                code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")
                doc = get_leading_comment(outer_node, source)
                qname = f"{module_name}.{name}" if module_name else name
                symbols.append(
                    ParsedSymbol(
                        name=name or "[Struct]",
                        symbol_type="struct",
                        start_line=s_line,
                        end_line=e_line,
                        code=code_text,
                        docstring=doc,
                        route_info="",
                        signature="",
                        calls=[],
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=qname,
                    )
                )
            del cursor_types

        if self._go_defs_query and self._go_calls_query:
            cursor_defs = QueryCursor(self._go_defs_query)
            cursor_calls = QueryCursor(self._go_calls_query)

            all_file_calls = []
            for pat, cap in cursor_calls.matches(root):
                if "call.root" in cap:
                    sb = int(cap["call.root"][0].start_byte)
                    all_file_calls.append((sb, pat, cap))
            del cursor_calls
            if all_file_calls:
                all_file_calls.sort(key=lambda x: x[0])
            call_starts = [x[0] for x in all_file_calls]

            for pat, cap in cursor_defs.matches(root):
                if "method.def" in cap:
                    node = cap["method.def"][0]
                    m_name = get_node_text(cap["method.name"][0], source).strip()
                    recv_text = get_node_text(cap["method.recv"][0], source).strip("() ")
                    recv_clean = re.sub(r"[\*\(\)\s]", "", recv_text.split()[-1]) if recv_text else ""
                    full_name = f"{recv_clean}.{m_name}" if recv_clean else m_name
                    s_byte = int(node.start_byte)
                    e_byte = int(node.end_byte)
                    s_line = byte_to_line(s_byte)
                    e_line = byte_to_line(e_byte)
                    code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")
                    doc = get_leading_comment(node, source)
                    route = self._extract_route_from_text(code_text)

                    params_node = node.child_by_field_name("parameters")
                    sig = get_node_text(params_node, source) if params_node else "()"

                    idx_left = bisect.bisect_left(call_starts, s_byte)
                    idx_right = bisect.bisect_right(call_starts, e_byte)
                    call_matches = [(item[1], item[2]) for item in all_file_calls[idx_left:idx_right]]
                    fn_calls = self._extract_go_calls(call_matches, source, imports, module_name)

                    qname = f"{module_name}.{full_name}" if module_name else full_name
                    symbols.append(
                        ParsedSymbol(
                            name=full_name,
                            symbol_type="method",
                            start_line=s_line,
                            end_line=e_line,
                            code=code_text,
                            docstring=doc,
                            route_info=route,
                            signature=sig,
                            calls=fn_calls,
                            file_path=file_path,
                            module_name=module_name,
                            qualified_name=qname,
                        )
                    )
                elif "fn.def" in cap:
                    node = cap["fn.def"][0]
                    fn_name = get_node_text(cap["fn.name"][0], source).strip()
                    s_byte = int(node.start_byte)
                    e_byte = int(node.end_byte)
                    s_line = byte_to_line(s_byte)
                    e_line = byte_to_line(e_byte)
                    code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")
                    doc = get_leading_comment(node, source)
                    route = self._extract_route_from_text(code_text)
                    params_node = node.child_by_field_name("parameters") or node.child_by_field_name("parameter_list")
                    sig = get_node_text(params_node, source) if params_node else "()"

                    idx_left = bisect.bisect_left(call_starts, s_byte)
                    idx_right = bisect.bisect_right(call_starts, e_byte)
                    call_matches = [(item[1], item[2]) for item in all_file_calls[idx_left:idx_right]]
                    fn_calls = self._extract_go_calls(call_matches, source, imports, module_name)

                    qname = f"{module_name}.{fn_name}" if module_name else fn_name
                    symbols.append(
                        ParsedSymbol(
                            name=fn_name,
                            symbol_type="function",
                            start_line=s_line,
                            end_line=e_line,
                            code=code_text,
                            docstring=doc,
                            route_info=route,
                            signature=sig,
                            calls=fn_calls,
                            file_path=file_path,
                            module_name=module_name,
                            qualified_name=qname,
                        )
                    )

            del cursor_defs

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
