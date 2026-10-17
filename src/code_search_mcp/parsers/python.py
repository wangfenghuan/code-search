import bisect
import re
from typing import Any, Callable, List, Optional

from tree_sitter import Node, Query, QueryCursor

from .common import (
    BaseLanguageParser,
    FileImports,
    ParsedSymbol,
    PY_LANG,
    PYTHON_BUILTINS,
    extract_route_from_text,
    get_leading_comment,
    get_node_text,
)


class PythonParser(BaseLanguageParser):
    """Python 语言专属解析器与调用关系提取器"""

    def __init__(self):
        self.class_query = Query(PY_LANG, "(class_definition name: (identifier) @cls.name) @cls.def") if PY_LANG else None
        self.fn_query = Query(PY_LANG, "(function_definition name: (identifier) @fn.name) @fn.def") if PY_LANG else None
        self.calls_query = Query(
            PY_LANG,
            """
            (call function: (identifier) @call.ident) @call.root
            (call function: (attribute object: (_) @call.obj attribute: (identifier) @call.attr)) @call.root
            (call function: (subscript value: (_) @call.sub_val subscript: (_) @call.sub_key)) @call.root
            (call function: (call function: (identifier) @call.chained_fn arguments: (argument_list) @call.chained_args)) @call.root
            """,
        ) if PY_LANG else None

    def extract_imports(self, root: Node, source: bytes, **kwargs) -> FileImports:
        file_imports = FileImports()
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
                    rel_parts = [
                        get_node_text(c, source).strip()
                        for c in child.children
                        if c.type in ("relative_import", "dotted_name")
                    ]
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
        classes = []

        # 1. 声明式查询类定义
        if self.class_query:
            cursor_cls = QueryCursor(self.class_query)
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

        # 2. 声明式查询函数/方法定义 (当 include_calls=False 时跳过 AST 调用边遍历)
        if self.fn_query:
            cursor_fn = QueryCursor(self.fn_query)
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
                route = extract_route_from_text(code_text)

                # 检查是否为嵌套在其他函数内部的局部闭包函数 (Inner / Closure function)
                curr = def_node.parent
                is_inner_fn = False
                enclosing_fn = None
                while curr and curr.type != "class_definition":
                    if curr.type in ("function_definition", "async_function_definition"):
                        is_inner_fn = True
                        n_node = curr.child_by_field_name("name")
                        if n_node:
                            enclosing_fn = get_node_text(n_node, source).strip()
                        break
                    curr = curr.parent

                # 所属类判定：二分查找 O(log K) 替代全量 O(K) 线性扫描
                parent_cls = None
                hi = bisect.bisect_right(cls_starts, s_byte)
                best_span = None
                for c in classes[:hi]:
                    if c["end"] >= e_byte:
                        span = c["end"] - c["start"]
                        if best_span is None or span < best_span:
                            best_span = span
                            parent_cls = c["name"]

                if is_inner_fn:
                    prefix = f"{parent_cls}.{enclosing_fn}" if parent_cls and enclosing_fn else (enclosing_fn or parent_cls or "")
                    full_name = f"{prefix}.<closure>.{fn_name}" if prefix else f"<closure>.{fn_name}"
                    sym_type = "closure"
                else:
                    full_name = f"{parent_cls}.{fn_name}" if parent_cls else fn_name
                    sym_type = "method" if parent_cls else "function"

                # 签名提取
                params_node = def_node.child_by_field_name("parameters")
                sig = get_node_text(params_node, source) if params_node else "()"

                # 二分区间查询调用 (仅当 include_calls=True 时执行)
                if include_calls and all_file_calls:
                    idx_left = bisect.bisect_left(call_starts, int(def_node.start_byte))
                    idx_right = bisect.bisect_right(call_starts, int(def_node.end_byte))
                    call_matches = [(item[1], item[2]) for item in all_file_calls[idx_left:idx_right]]
                    fn_calls = self.extract_calls_from_matches(call_matches, source, imports, module_name, parent_cls or "")
                else:
                    fn_calls = []

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

            del cursor_fn
