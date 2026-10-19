import bisect
import re
from typing import Any, Callable, List, Optional

from tree_sitter import Node, Query, QueryCursor

from .common import (
    BaseLanguageParser,
    FileImports,
    ParsedSymbol,
    RUST_BUILTINS,
    RUST_LANG,
    extract_route_from_text,
    get_leading_comment,
    get_node_text,
)


class RustParser(BaseLanguageParser):
    """Rust 语言专属解析器、宏路由提取与类型/调用图推断器"""

    def __init__(self):
        self.types_query = Query(
            RUST_LANG,
            """
            (struct_item name: (type_identifier) @struct.name) @struct.def
            (enum_item name: (type_identifier) @enum.name) @enum.def
            (trait_item name: (type_identifier) @trait.name) @trait.def
            (union_item name: (type_identifier) @union.name) @union.def
            (type_item name: (type_identifier) @alias.name) @alias.def
            """,
        ) if RUST_LANG else None

        self.fn_query = Query(
            RUST_LANG,
            """
            (function_item name: (identifier) @fn.name) @fn.def
            """,
        ) if RUST_LANG else None

        self.calls_query = Query(
            RUST_LANG,
            """
            (call_expression function: (identifier) @call.name) @call.root
            (call_expression function: (field_expression value: (_) @call.obj field: (field_identifier) @call.name)) @call.root
            (call_expression function: (scoped_identifier path: (_) @call.path name: (identifier) @call.name)) @call.root
            (macro_invocation macro: (identifier) @call.name) @call.root
            (macro_invocation macro: (scoped_identifier path: (_) @call.path name: (identifier) @call.name)) @call.root
            """,
        ) if RUST_LANG else None

    def _get_impl_parent_info(self, node: Node, source: bytes) -> tuple:
        curr = node.parent
        while curr:
            if curr.type == "impl_item":
                type_node = curr.child_by_field_name("type")
                trait_node = curr.child_by_field_name("trait")
                impl_type = get_node_text(type_node, source).strip() if type_node else ""
                impl_type = re.sub(r"<.*>", "", impl_type).strip()
                impl_trait = get_node_text(trait_node, source).strip() if trait_node else ""
                impl_trait = re.sub(r"<.*>", "", impl_trait).strip()
                return impl_type, impl_trait
            curr = curr.parent
        return "", ""

    def extract_imports(self, root: Node, source: bytes, **kwargs) -> FileImports:
        file_imports = FileImports()
        for child in root.children:
            if child.type == "use_declaration":
                text = get_node_text(child, source).strip()
                text = re.sub(r"^pub\s+", "", text)
                text = re.sub(r"^use\s+", "", text).rstrip(";").strip()
                if "::{" in text:
                    prefix, group = text.split("::{", 1)
                    items = [it.strip() for it in group.rstrip("}").split(",") if it.strip()]
                    for item in items:
                        if " as " in item:
                            orig, alias = item.split(" as ", 1)
                            file_imports.symbols[alias.strip()] = f"{prefix}::{orig.strip()}"
                        else:
                            file_imports.symbols[item] = f"{prefix}::{item}"
                    file_imports.modules[prefix] = prefix
                elif " as " in text:
                    orig, alias = text.split(" as ", 1)
                    file_imports.symbols[alias.strip()] = orig.strip()
                elif text.endswith("::*"):
                    mod_path = text[:-3]
                    file_imports.modules[mod_path] = mod_path
                else:
                    sym_name = text.split("::")[-1]
                    file_imports.symbols[sym_name] = text
                    mod_prefix = "::".join(text.split("::")[:-1])
                    if mod_prefix:
                        file_imports.modules[mod_prefix] = mod_prefix
        return file_imports

    def extract_calls_from_matches(
        self,
        matches: Any,
        source: bytes,
        imports: Optional[FileImports] = None,
        module_name: str = "",
        current_class: str = "",
        **kwargs,
    ) -> List[str]:
        calls = []
        seen = set()
        for pat, cap in matches:
            call_names = []
            if "call.name" in cap:
                bare_name = get_node_text(cap["call.name"][0], source).strip()
                if not bare_name or bare_name in RUST_BUILTINS:
                    continue
                call_names.append(bare_name)
                if "call.obj" in cap:
                    obj_text = get_node_text(cap["call.obj"][0], source).strip()
                    if obj_text in ("self", "&self", "&mut self"):
                        if current_class:
                            call_names.append(f"{current_class}.{bare_name}")
                            call_names.append(f"{current_class}::{bare_name}")
                    elif imports and obj_text in imports.symbols:
                        call_names.append(f"{imports.symbols[obj_text]}.{bare_name}")
                    else:
                        pass
                elif "call.path" in cap:
                    path_text = get_node_text(cap["call.path"][0], source).strip()
                    clean_path = re.sub(r"<.*>", "", path_text).strip()
                    call_names.append(f"{clean_path}::{bare_name}")
                    call_names.append(f"{clean_path}.{bare_name}")
                    if imports and clean_path in imports.symbols:
                        full_prefix = imports.symbols[clean_path]
                        call_names.append(f"{full_prefix}::{bare_name}")
                else:
                    if imports and bare_name in imports.symbols:
                        call_names.append(imports.symbols[bare_name])
                    elif module_name:
                        call_names.append(f"{module_name}.{bare_name}")

            for name in call_names:
                if (
                    name
                    and name not in RUST_BUILTINS
                    and name not in seen
                    and not name.startswith("std::")
                ):
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
                for k, nodes in cap.items():
                    if k.endswith(".name"):
                        kind = k.split(".")[0]
                        name = get_node_text(nodes[0], source).strip()
                        def_key = f"{kind}.def"
                        node = cap.get(def_key, nodes)[0]
                        s_byte = int(node.start_byte)
                        e_byte = int(node.end_byte)
                        code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")
                        doc = get_leading_comment(node, source)
                        type_str = (
                            "struct"
                            if kind in ("struct", "union")
                            else (
                                "enum"
                                if kind == "enum"
                                else ("interface" if kind == "trait" else "type_alias")
                            )
                        )
                        qname = f"{module_name}.{name}" if module_name else name
                        symbols.append(
                            ParsedSymbol(
                                name=name,
                                symbol_type=type_str,
                                start_line=byte_to_line(s_byte),
                                end_line=byte_to_line(e_byte),
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

        if self.fn_query:
            cursor_defs = QueryCursor(self.fn_query)
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
                node = cap["fn.def"][0]
                fn_name = get_node_text(cap["fn.name"][0], source).strip()
                impl_type, impl_trait = self._get_impl_parent_info(node, source)

                if impl_type:
                    full_name = f"{impl_type}.{fn_name}"
                    sym_type = "method"
                else:
                    full_name = fn_name
                    sym_type = "function"

                s_byte = int(node.start_byte)
                e_byte = int(node.end_byte)
                s_line = byte_to_line(s_byte)
                e_line = byte_to_line(e_byte)
                code_text = source[s_byte:e_byte].decode("utf-8", errors="replace")
                doc = get_leading_comment(node, source)

                # 检查属性 (如 #[get("/api/v1/orders")])
                route_text = ""
                prev = node.prev_sibling
                while prev and prev.type == "attribute_item":
                    attr_str = get_node_text(prev, source).strip()
                    r = extract_route_from_text(attr_str)
                    if r:
                        route_text = r
                        break
                    prev = prev.prev_sibling
                if not route_text:
                    route_text = extract_route_from_text(code_text)

                calls = []
                if include_calls and all_file_calls:
                    idx_start = bisect.bisect_left(call_starts, s_byte)
                    node_matches = []
                    for idx in range(idx_start, len(all_file_calls)):
                        c_sb, c_pat, c_cap = all_file_calls[idx]
                        if c_sb >= e_byte:
                            break
                        node_matches.append((c_pat, c_cap))
                    if node_matches:
                        calls = self.extract_calls_from_matches(
                            node_matches,
                            source,
                            imports=imports,
                            module_name=module_name,
                            current_class=impl_type,
                        )

                qname = f"{module_name}.{full_name}" if module_name else full_name
                symbols.append(
                    ParsedSymbol(
                        name=full_name,
                        symbol_type=sym_type,
                        start_line=s_line,
                        end_line=e_line,
                        code=code_text,
                        docstring=doc,
                        route_info=route_text,
                        signature="",
                        calls=calls,
                        file_path=file_path,
                        module_name=module_name,
                        qualified_name=qname,
                    )
                )
            del cursor_defs
