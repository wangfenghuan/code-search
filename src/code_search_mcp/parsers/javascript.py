import bisect
import re
from typing import Any, Callable, List, Optional

from tree_sitter import Node, Query, QueryCursor

from .common import (
    BaseLanguageParser,
    FileImports,
    JS_BUILTINS,
    JS_LANG,
    ParsedSymbol,
    TS_LANG,
    extract_route_from_text,
    get_leading_comment,
    get_module_name_from_path,
    get_node_text,
)


class TSJSParser(BaseLanguageParser):
    """TypeScript 与 JavaScript 语言专属解析器与调用关系提取器"""

    def __init__(self):
        self.ts_class_query = Query(TS_LANG, "(class_declaration name: (type_identifier) @cls.name) @cls.def") if TS_LANG else None
        self.ts_defs_query = Query(
            TS_LANG,
            """
            (function_declaration name: (identifier) @fn.name) @fn.def
            (method_definition name: (property_identifier) @method.name) @method.def
            (public_field_definition name: (property_identifier) @field.name) @field.def
            (lexical_declaration (variable_declarator name: (identifier) @var.name value: [(arrow_function) (function_expression)])) @var.def
            (variable_declaration (variable_declarator name: (identifier) @var.name value: [(arrow_function) (function_expression)])) @var.def
            """,
        ) if TS_LANG else None
        self.ts_calls_query = Query(
            TS_LANG,
            """
            (call_expression function: (identifier) @call.ident) @call.root
            (call_expression function: (member_expression object: (_) @call.obj property: (property_identifier) @call.prop)) @call.root
            (call_expression function: (subscript_expression object: (_) @call.obj index: (_) @call.idx)) @call.root
            """,
        ) if TS_LANG else None

        self.js_class_query = Query(JS_LANG, "(class_declaration name: (identifier) @cls.name) @cls.def") if JS_LANG else None
        self.js_defs_query = Query(
            JS_LANG,
            """
            (function_declaration name: (identifier) @fn.name) @fn.def
            (method_definition name: (property_identifier) @method.name) @method.def
            (lexical_declaration (variable_declarator name: (identifier) @var.name value: [(arrow_function) (function_expression)])) @var.def
            (variable_declaration (variable_declarator name: (identifier) @var.name value: [(arrow_function) (function_expression)])) @var.def
            """,
        ) if JS_LANG else None
        self.js_calls_query = Query(
            JS_LANG,
            """
            (call_expression function: (identifier) @call.ident) @call.root
            (call_expression function: (member_expression object: (_) @call.obj property: (property_identifier) @call.prop)) @call.root
            (call_expression function: (subscript_expression object: (_) @call.obj index: (_) @call.idx)) @call.root
            """,
        ) if JS_LANG else None

    def extract_imports(self, root: Node, source: bytes, **kwargs) -> FileImports:
        file_imports = FileImports()
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
                                        arg_text = get_node_text(
                                            args.children[1] if len(args.children) > 1 else args.children[0],
                                            source,
                                        ).strip("\"' ")
                                        mod_n = get_module_name_from_path(arg_text) or arg_text.split("/")[-1]
                                        file_imports.modules[v_name] = mod_n
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
        lang: str = "typescript",
        **kwargs,
    ) -> None:
        if byte_to_line is None:
            line_starts = [0] + [m.end() for m in re.finditer(b"\n", source)]
            byte_to_line = lambda b: bisect.bisect_right(line_starts, b)

        root = tree.root_node if hasattr(tree, "root_node") else tree
        classes = []

        is_js = (lang == "javascript")
        class_query = self.js_class_query if is_js else self.ts_class_query
        defs_query = self.js_defs_query if is_js else self.ts_defs_query
        calls_query = self.js_calls_query if is_js else self.ts_calls_query

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

        if defs_query:
            cursor_defs = QueryCursor(defs_query)
            all_file_calls = []
            call_starts = []
            if include_calls and calls_query:
                cursor_calls = QueryCursor(calls_query)
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
                route = extract_route_from_text(code_text)

                # 二分区间查询调用 (仅当 include_calls=True 时执行)
                if include_calls and all_file_calls:
                    idx_left = bisect.bisect_left(call_starts, int(item_node.start_byte))
                    idx_right = bisect.bisect_right(call_starts, int(item_node.end_byte))
                    call_matches = [(item[1], item[2]) for item in all_file_calls[idx_left:idx_right]]
                    fn_calls = self.extract_calls_from_matches(call_matches, source, imports, module_name, parent_cls or "")
                else:
                    fn_calls = []

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
