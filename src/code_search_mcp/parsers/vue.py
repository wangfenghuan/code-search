"""Vue 单文件组件 (.vue SFC) 专属解析器与 AST 转换引擎

支持 Vue 2 与 Vue 3 单文件组件：
1. 提取 <template> 视图块作为组件顶层符号，提取 UI 事件绑定与模板调用（如 @click, @submit, v-model）
2. 提取 <script> 与 <script setup> 脚本块，利用 JavaScript/TypeScript 语法树进行 AST 符号与调用边提取
3. 严格保留原始文件行号与字符偏移，确保代码跳转与引用精准定位
"""

import bisect
import re
from pathlib import Path
from typing import Any, Callable, List, Optional

from tree_sitter import Node, Parser

from .common import (
    BaseLanguageParser,
    FileImports,
    JS_LANG,
    TS_LANG,
    ParsedSymbol,
    get_module_name_from_path,
)
from .javascript import TSJSParser


class VueParser(BaseLanguageParser):
    """Vue 单文件组件 (.vue SFC) 专属解析器"""

    def __init__(self, tsjs_parser: Optional[TSJSParser] = None):
        self.tsjs_parser = tsjs_parser or TSJSParser()
        self._js_parser = Parser(JS_LANG) if JS_LANG else None
        self._ts_parser = Parser(TS_LANG) if TS_LANG else None

    def extract_imports(self, root: Node, source: bytes, **kwargs) -> FileImports:
        content = source.decode("utf-8", errors="replace")
        script_matches = list(re.finditer(r"<script\b([^>]*)>([\s\S]*?)<\/script>", content, re.I))
        if not script_matches:
            return FileImports()

        merged_imports = FileImports()
        for sm in script_matches:
            attrs = sm.group(1).lower()
            is_ts = 'lang="ts"' in attrs or "lang='ts'" in attrs or 'lang="typescript"' in attrs
            script_bytes = self._build_padded_script(content, sm)
            parser = self._ts_parser if (is_ts and self._ts_parser) else self._js_parser
            if parser:
                tree = parser.parse(script_bytes)
                sub_imp = self.tsjs_parser.extract_imports(tree.root_node, script_bytes)
                merged_imports.symbols.update(sub_imp.symbols)
                merged_imports.modules.update(sub_imp.modules)
                merged_imports.instances.update(sub_imp.instances)
                del tree
        return merged_imports

    def extract_calls_from_matches(
        self,
        matches: Any,
        source: bytes,
        imports: Optional[FileImports],
        module_name: str,
        current_class: str = "",
        **kwargs,
    ) -> List[str]:
        return self.tsjs_parser.extract_calls_from_matches(
            matches, source, imports, module_name, current_class=current_class, **kwargs
        )

    def _build_padded_script(self, content: str, match: re.Match) -> bytes:
        """构建带有原文件行数与空白字符填充的脚本字节流，确保 AST 行列号与原始 .vue 文件 100% 对齐"""
        start_idx = match.start(2)
        end_idx = match.end(2)
        prefix = re.sub(r"[^\n]", " ", content[:start_idx])
        suffix = re.sub(r"[^\n]", " ", content[end_idx:])
        padded = prefix + match.group(2) + suffix
        return padded.encode("utf-8")

    def _extract_template_calls(self, template_code: str) -> List[str]:
        """从 Vue 模板中提取事件绑定调用 (如 @click="handleLogin", @submit.prevent="handleSubmit")"""
        calls = []
        seen = set()
        event_patterns = [
            r"""(?:@[\w\.-]+|v-on:[\w\.-]+)\s*=\s*["']\s*([a-zA-Z_$][a-zA-Z0-9_$]*)""",
            r"""v-model(?::[\w\.-]+)?\s*=\s*["']\s*([a-zA-Z_$][a-zA-Z0-9_$]*)""",
        ]
        for pat in event_patterns:
            for m in re.finditer(pat, template_code):
                fn = m.group(1).strip()
                if fn and fn not in seen and fn not in ("true", "false", "null", "undefined"):
                    seen.add(fn)
                    calls.append(fn)
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
        content = source.decode("utf-8", errors="replace")

        # 1. 计算组件名称 (如 views/login/index.vue -> LoginView 或 index.vue)
        file_stem = Path(file_path).stem
        parent_name = Path(file_path).parent.name
        if file_stem == "index" and parent_name:
            comp_name = f"{parent_name.capitalize()}View"
        else:
            comp_name = file_stem.capitalize()

        # 2. 提取 <template> 视图块
        template_match = re.search(r"<template\b[^>]*>([\s\S]*?)<\/template>", content, re.I)
        if template_match:
            tpl_start_idx = template_match.start()
            tpl_end_idx = template_match.end()
            tpl_start_line = content[:tpl_start_idx].count("\n") + 1
            tpl_end_line = content[:tpl_end_idx].count("\n") + 1
            tpl_code = template_match.group(0)
            template_calls = self._extract_template_calls(tpl_code) if include_calls else []

            symbols.append(
                ParsedSymbol(
                    name=comp_name,
                    symbol_type="component",
                    start_line=tpl_start_line,
                    end_line=tpl_end_line,
                    code=tpl_code,
                    docstring=f"Vue component: {comp_name}",
                    route_info="",
                    signature=f"<template> ({comp_name})",
                    calls=template_calls,
                    file_path=file_path,
                    module_name=module_name,
                    qualified_name=f"{module_name}.{comp_name}" if module_name else comp_name,
                )
            )

        # 3. 提取并解析所有 <script> / <script setup> 块
        script_matches = list(re.finditer(r"<script\b([^>]*)>([\s\S]*?)<\/script>", content, re.I))
        for sm in script_matches:
            attrs = sm.group(1).lower()
            is_ts = 'lang="ts"' in attrs or "lang='ts'" in attrs or 'lang="typescript"' in attrs
            script_bytes = self._build_padded_script(content, sm)
            parser = self._ts_parser if (is_ts and self._ts_parser) else self._js_parser
            if not parser:
                continue

            script_tree = parser.parse(script_bytes)
            sub_line_starts = [0] + [m.end() for m in re.finditer(b"\n", script_bytes)]
            def sub_byte_to_line(b: int) -> int:
                return bisect.bisect_right(sub_line_starts, b)

            sub_imports = imports or self.tsjs_parser.extract_imports(script_tree.root_node, script_bytes)
            self.tsjs_parser.parse(
                script_tree,
                script_bytes,
                symbols,
                imports=sub_imports,
                module_name=module_name,
                file_path=file_path,
                byte_to_line=sub_byte_to_line,
                include_calls=include_calls,
                lang="typescript" if is_ts else "javascript",
            )
            del script_tree
