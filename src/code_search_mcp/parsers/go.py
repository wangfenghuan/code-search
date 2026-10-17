import bisect
import re
from typing import Any, Callable, List, Optional

from tree_sitter import Node, Query, QueryCursor

from .common import (
    BaseLanguageParser,
    FileImports,
    GO_BUILTINS,
    GO_LANG,
    ParsedSymbol,
    extract_route_from_text,
    get_leading_comment,
    get_node_text,
)


class GoParser(BaseLanguageParser):
    """Go 语言专属解析器与调用关系提取器"""

    def __init__(self):
        self.types_query = Query(
            GO_LANG,
            """
            (type_spec name: (type_identifier) @type.name type: (struct_type)) @struct.def
            (type_spec name: (type_identifier) @type.name type: (interface_type)) @iface.def
            """,
        ) if GO_LANG else None
        self.defs_query = Query(
            GO_LANG,
            """
            (function_declaration name: (identifier) @fn.name) @fn.def
            (method_declaration receiver: (parameter_list) @method.recv name: (field_identifier) @method.name) @method.def
            """,
        ) if GO_LANG else None
        self.calls_query = Query(
            GO_LANG,
            """
            (call_expression function: (identifier) @call.ident) @call.root
            (call_expression function: (selector_expression operand: (_) @call.operand field: (field_identifier) @call.field)) @call.root
            (call_expression function: (index_expression operand: (_) @call.operand index: (_) @call.idx)) @call.root
            """,
        ) if GO_LANG else None

    def extract_imports(self, root: Node, source: bytes, **kwargs) -> FileImports:
        file_imports = FileImports()
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

        if self.types_query:
            cursor_types = QueryCursor(self.types_query)
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
                    route = extract_route_from_text(code_text)

                    params_node = node.child_by_field_name("parameters")
                    sig = get_node_text(params_node, source) if params_node else "()"

                    if include_calls and all_file_calls:
                        idx_left = bisect.bisect_left(call_starts, s_byte)
                        idx_right = bisect.bisect_right(call_starts, e_byte)
                        call_matches = [(item[1], item[2]) for item in all_file_calls[idx_left:idx_right]]
                        fn_calls = self.extract_calls_from_matches(call_matches, source, imports, module_name)
                    else:
                        fn_calls = []

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
                    route = extract_route_from_text(code_text)
                    params_node = node.child_by_field_name("parameters") or node.child_by_field_name("parameter_list")
                    sig = get_node_text(params_node, source) if params_node else "()"

                    if include_calls and all_file_calls:
                        idx_left = bisect.bisect_left(call_starts, s_byte)
                        idx_right = bisect.bisect_right(call_starts, e_byte)
                        call_matches = [(item[1], item[2]) for item in all_file_calls[idx_left:idx_right]]
                        fn_calls = self.extract_calls_from_matches(call_matches, source, imports, module_name)
                    else:
                        fn_calls = []

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
