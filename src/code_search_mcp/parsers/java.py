import bisect
import re
from typing import Any, Callable, List, Optional

from tree_sitter import Node, Query, QueryCursor

from .common import (
    BaseLanguageParser,
    FileImports,
    JAVA_BUILTINS,
    JAVA_LANG,
    ParsedSymbol,
    extract_route_from_text,
    get_leading_comment,
    get_node_text,
)


class JavaParser(BaseLanguageParser):
    """Java 语言专属解析器、Spring 路由提取与依赖注入推断器"""

    def __init__(self):
        self.types_query = Query(
            JAVA_LANG,
            """
            (class_declaration name: (identifier) @cls.name) @cls.def
            (record_declaration name: (identifier) @rec.name) @rec.def
            (interface_declaration name: (identifier) @iface.name) @iface.def
            (enum_declaration name: (identifier) @enum.name) @enum.def
            (annotation_type_declaration name: (identifier) @anno.name) @anno.def
            """,
        ) if JAVA_LANG else None
        self.defs_query = Query(
            JAVA_LANG,
            """
            (method_declaration name: (identifier) @method.name) @method.def
            (constructor_declaration name: (identifier) @ctor.name) @ctor.def
            """,
        ) if JAVA_LANG else None
        self.calls_query = Query(
            JAVA_LANG,
            """
            (method_invocation object: (_) @call.obj name: (identifier) @call.name) @call.root
            (method_invocation !object name: (identifier) @call.name) @call.root
            (object_creation_expression type: (_) @call.type) @call.root
            """,
        ) if JAVA_LANG else None
        self.fields_query = Query(
            JAVA_LANG,
            """
            (field_declaration type: (_) @field.type (variable_declarator name: (identifier) @field.name))
            """,
        ) if JAVA_LANG else None

    def extract_imports(self, root: Node, source: bytes, **kwargs) -> FileImports:
        file_imports = FileImports()
        for child in root.children:
            if child.type == "package_declaration":
                for sub in child.children:
                    if sub.type in ("scoped_identifier", "identifier"):
                        pkg_name = get_node_text(sub, source).strip()
                        file_imports.modules[pkg_name] = pkg_name
            elif child.type == "import_declaration":
                is_static = any(sub.type == "static" for sub in child.children)
                is_wildcard = any(sub.type == "asterisk" for sub in child.children)
                for sub in child.children:
                    if sub.type in ("scoped_identifier", "identifier"):
                        imp_path = get_node_text(sub, source).strip()
                        if is_wildcard:
                            file_imports.modules[imp_path] = imp_path
                            tail = imp_path.split(".")[-1]
                            file_imports.modules[tail] = imp_path
                        elif is_static:
                            sym_name = imp_path.split(".")[-1]
                            file_imports.symbols[sym_name] = imp_path
                        else:
                            cls_name = imp_path.split(".")[-1]
                            file_imports.symbols[cls_name] = imp_path
                            file_imports.modules[cls_name] = imp_path

        # 提取字段声明用于依赖注入实例化推断 (如 private UserService userService;)
        if self.fields_query:
            cursor_f = QueryCursor(self.fields_query)
            for pat, cap in cursor_f.matches(root):
                fn = get_node_text(cap["field.name"][0], source).strip()
                ft = get_node_text(cap["field.type"][0], source).strip()
                clean_ft = re.sub(r"<.*>|\[.*\]", "", ft).strip()
                if fn and clean_ft:
                    file_imports.instances[fn] = clean_ft
            del cursor_f

        return file_imports

    def extract_calls_from_matches(
        self,
        matches: Any,
        source: bytes,
        imports: Optional[FileImports],
        module_name: str,
        current_class: str = "",
        **kwargs,
    ) -> List[str]:
        calls = []
        seen = set()
        for pat, cap in matches:
            call_names = []
            if "call.name" in cap:
                bare_name = get_node_text(cap["call.name"][0], source).strip()
                call_names.append(bare_name)
                if "call.obj" in cap:
                    obj_text = get_node_text(cap["call.obj"][0], source).strip()
                    if obj_text in ("this", "super"):
                        if current_class:
                            call_names.append(f"{current_class}.{bare_name}")
                            if module_name:
                                call_names.append(f"{module_name}.{current_class}.{bare_name}")
                    elif imports and obj_text in imports.instances:
                        inst_cls = imports.instances[obj_text]
                        call_names.append(f"{inst_cls}.{bare_name}")
                        if inst_cls in imports.symbols:
                            call_names.append(f"{imports.symbols[inst_cls]}.{bare_name}")
                        elif module_name:
                            call_names.append(f"{module_name}.{inst_cls}.{bare_name}")
                    elif imports and obj_text in imports.symbols:
                        sym = imports.symbols[obj_text]
                        call_names.append(f"{sym}.{bare_name}")
                    elif imports and obj_text in imports.modules:
                        mod = imports.modules[obj_text]
                        call_names.append(f"{mod}.{bare_name}")
                    else:
                        call_names.append(f"{obj_text}.{bare_name}")
                else:
                    if current_class:
                        call_names.append(f"{current_class}.{bare_name}")
                    if imports and bare_name in imports.symbols:
                        call_names.append(imports.symbols[bare_name])
                    elif module_name:
                        call_names.append(f"{module_name}.{bare_name}")
            elif "call.type" in cap:
                raw_type = get_node_text(cap["call.type"][0], source).strip()
                clean_type = re.sub(r"<.*>|\[.*\]", "", raw_type).strip()
                if clean_type:
                    call_names.append(clean_type)
                    if imports and clean_type in imports.symbols:
                        call_names.append(imports.symbols[clean_type])
                    elif module_name:
                        call_names.append(f"{module_name}.{clean_type}")

            for name in call_names:
                if name and name not in JAVA_BUILTINS and name not in seen:
                    seen.add(name)
                    calls.append(name)
        return calls

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
        if byte_to_line is None:
            line_starts = [0] + [m.end() for m in re.finditer(b"\n", source)]
            byte_to_line = lambda b: bisect.bisect_right(line_starts, b)

        root = tree.root_node if hasattr(tree, "root_node") else tree

        # 检查是否有显式 package 声明
        pkg_name = ""
        for child in root.children:
            if child.type == "package_declaration":
                for sub in child.children:
                    if sub.type in ("scoped_identifier", "identifier"):
                        pkg_name = get_node_text(sub, source).strip()
                        break
                break
        effective_pkg = pkg_name or module_name

        classes = []

        # 1. 查询类、记录、接口、枚举定义
        if self.types_query:
            cursor_types = QueryCursor(self.types_query)
            for pat, cap in cursor_types.matches(root):
                def_node = (
                    cap.get("cls.def")
                    or cap.get("rec.def")
                    or cap.get("iface.def")
                    or cap.get("enum.def")
                    or cap.get("anno.def")
                )[0]
                name_node = (
                    cap.get("cls.name")
                    or cap.get("rec.name")
                    or cap.get("iface.name")
                    or cap.get("enum.name")
                    or cap.get("anno.name")
                )
                name = get_node_text(name_node[0], source).strip() if name_node else "[Anonymous]"

                s_byte = int(def_node.start_byte)
                e_byte = int(def_node.end_byte)
                s_line = byte_to_line(s_byte)
                e_line = byte_to_line(e_byte)
                code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")
                doc = get_leading_comment(def_node, source)

                # 识别类级别的路由前缀 (如 @RequestMapping("/api/v1"))
                class_route_prefix = ""
                m_cls_req = re.search(
                    r"@RequestMapping\s*\(\s*(?:(?:value|path)\s*=\s*)?['\"]([^'\"]+)['\"]",
                    code_text[: min(len(code_text), 300)],
                    re.I,
                )
                if m_cls_req:
                    class_route_prefix = m_cls_req.group(1).strip()

                sym_type = "class"
                if "rec.def" in cap:
                    sym_type = "record"
                elif "iface.def" in cap:
                    sym_type = "interface"
                elif "enum.def" in cap:
                    sym_type = "enum"
                elif "anno.def" in cap:
                    sym_type = "annotation"

                cls_qname = f"{effective_pkg}.{name}" if effective_pkg else name
                classes.append({
                    "name": name,
                    "start": s_byte,
                    "end": e_byte,
                    "route_prefix": class_route_prefix,
                })
                symbols.append(
                    ParsedSymbol(
                        name=name,
                        symbol_type=sym_type,
                        start_line=s_line,
                        end_line=e_line,
                        code=code_text,
                        docstring=doc,
                        route_info=f"PATH {class_route_prefix}" if class_route_prefix else "",
                        signature="",
                        calls=[],
                        file_path=file_path,
                        module_name=effective_pkg,
                        qualified_name=cls_qname,
                    )
                )
            del cursor_types

        # 2. 查询方法与构造器定义
        if self.defs_query:
            cursor_defs = QueryCursor(self.defs_query)
            all_file_calls = []
            call_starts = []
            if include_calls and self.calls_query:
                cursor_calls = QueryCursor(self.calls_query)
                for pat, cap in cursor_calls.matches(root):
                    if "call.root" in cap:
                        sb = int(cap["call.root"][0].start_byte)
                        all_file_calls.append((sb, pat, cap))
                del cursor_calls
                if all_file_calls:
                    all_file_calls.sort(key=lambda x: x[0])
                call_starts = [x[0] for x in all_file_calls]

            cls_starts = [c["start"] for c in classes]

            for pat, cap in cursor_defs.matches(root):
                is_ctor = "ctor.def" in cap
                def_node = cap["ctor.def"][0] if is_ctor else cap["method.def"][0]
                name_node = cap["ctor.name"][0] if is_ctor else cap["method.name"][0]
                m_name = get_node_text(name_node, source).strip()

                s_byte = int(def_node.start_byte)
                e_byte = int(def_node.end_byte)
                s_line = byte_to_line(s_byte)
                e_line = byte_to_line(e_byte)
                code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")
                doc = get_leading_comment(def_node, source)

                # 所属类二分检索
                parent_cls = None
                cls_route_prefix = ""
                hi = bisect.bisect_right(cls_starts, s_byte)
                best_span = None
                for c in classes[:hi]:
                    if c["end"] >= e_byte:
                        span = c["end"] - c["start"]
                        if best_span is None or span < best_span:
                            best_span = span
                            parent_cls = c["name"]
                            cls_route_prefix = c["route_prefix"]

                full_name = f"{parent_cls}.{m_name}" if parent_cls else m_name
                sym_type = "constructor" if is_ctor else "method"

                # 路由提取并与类前缀拼接
                method_route = extract_route_from_text(code_text)
                if method_route and cls_route_prefix:
                    m_rt = re.match(r"^(HTTP\s+[A-Z]+\s+)(.*)$", method_route)
                    if m_rt:
                        verb = m_rt.group(1)
                        sub_path = m_rt.group(2)
                        p_prefix = "/" + cls_route_prefix.strip("/")
                        p_sub = "/" + sub_path.strip("/") if sub_path else ""
                        method_route = f"{verb}{p_prefix}{p_sub}"

                # 签名提取 (参数列表或方法声明头部)
                params_node = def_node.child_by_field_name("parameters")
                sig = get_node_text(params_node, source) if params_node else "()"

                # 二分区间提取调用
                if include_calls and all_file_calls:
                    idx_left = bisect.bisect_left(call_starts, s_byte)
                    idx_right = bisect.bisect_right(call_starts, e_byte)
                    call_matches = [(item[1], item[2]) for item in all_file_calls[idx_left:idx_right]]
                    fn_calls = self.extract_calls_from_matches(call_matches, source, imports, effective_pkg, parent_cls or "")
                else:
                    fn_calls = []

                qname = f"{effective_pkg}.{full_name}" if effective_pkg else full_name
                symbols.append(
                    ParsedSymbol(
                        name=full_name,
                        symbol_type=sym_type,
                        start_line=s_line,
                        end_line=e_line,
                        code=code_text,
                        docstring=doc,
                        route_info=method_route,
                        signature=sig,
                        calls=fn_calls,
                        file_path=file_path,
                        module_name=effective_pkg,
                        qualified_name=qname,
                    )
                )

            del cursor_defs
