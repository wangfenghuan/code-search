"""Svelte 单文件组件 (.svelte SFC) 专属解析器与 AST 转换引擎

支持 Svelte 3/4 与 Svelte 5 单文件组件：
1. 提取组件视图块作为顶层 component 符号，提取 UI 事件绑定与模板调用（如 on:click, onclick, bind:value）
2. 提取 <script> 与 <script context="module"> 脚本块，利用 JavaScript/TypeScript 语法树进行 AST 符号与调用边提取
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
)
from .javascript import TSJSParser


class SvelteParser(BaseLanguageParser):
    """Svelte 单文件组件 (.svelte SFC) 专属解析器"""

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
        """构建带有原文件行数与空白字符填充的脚本字节流，确保 AST 行列号与原始 .svelte 文件 100% 对齐"""
        start_idx = match.start(2)
        end_idx = match.end(2)
        prefix = re.sub(r"[^\n]", " ", content[:start_idx])
        suffix = re.sub(r"[^\n]", " ", content[end_idx:])
        padded = prefix + match.group(2) + suffix
        return padded.encode("utf-8")

    def _extract_template_calls(self, template_code: str) -> List[str]:
        """从 Svelte 模板中提取事件绑定调用与组件引用 (如 on:click={handleClick}, onclick={handleClick}, bind:value={name})"""
        calls = []
        seen = set()

        # 1. Svelte 3/4: on:click={fn}, on:submit|preventDefault={fn}
        # 2. Svelte 5: onclick={fn}, onsubmit={fn}, onkeydown={fn}
        # 3. bind:value={variable}
        # 4. 函数插值表达式: {formatDate(item.time)}, {t('key')}
        event_patterns = [
            r"""on:[\w\.-]+(?:\|[\w\.-]+)*\s*=\s*\{(?:\s*\(\s*\)\s*=>\s*)?([a-zA-Z_$][a-zA-Z0-9_$]*)""",
            r"""\bon[a-zA-Z]+\s*=\s*\{(?:\s*\(\s*\)\s*=>\s*)?([a-zA-Z_$][a-zA-Z0-9_$]*)""",
            r"""bind:[\w\.-]+\s*=\s*\{([a-zA-Z_$][a-zA-Z0-9_$]*)""",
            r"""\{([a-zA-Z_$][a-zA-Z0-9_$]*)\s*\(""",
        ]
        ignored_tokens = {
            "true", "false", "null", "undefined", "if", "each", "await", "then", "catch",
            "as", "key", "const", "let", "var", "function", "return", "this",
        }

        for pat in event_patterns:
            for m in re.finditer(pat, template_code):
                fn = m.group(1).strip()
                if fn and fn not in seen and fn not in ignored_tokens:
                    seen.add(fn)
                    calls.append(fn)

        # 5. 自定义子组件调用 (如 <UserCard />, <NavigationDrawer>)
        comp_pattern = r"""<([A-Z][a-zA-Z0-9_$]*)\b"""
        for m in re.finditer(comp_pattern, template_code):
            c_name = m.group(1).strip()
            if c_name and c_name not in seen:
                seen.add(c_name)
                calls.append(c_name)

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

        # 1. 计算组件名称 (如 src/components/UserCard.svelte -> UserCard, routes/login/+page.svelte -> LoginPage)
        file_path_obj = Path(file_path)
        file_stem = file_path_obj.stem
        parent_name = file_path_obj.parent.name

        if file_stem.startswith("+"):  # SvelteKit 约定路由文件 (+page.svelte, +layout.svelte)
            clean_stem = file_stem.lstrip("+")
            comp_name = f"{parent_name.capitalize()}{clean_stem.capitalize()}" if parent_name else f"{clean_stem.capitalize()}Component"
        elif file_stem == "index" and parent_name:
            comp_name = f"{parent_name.capitalize()}View"
        else:
            comp_name = file_stem[0].upper() + file_stem[1:] if file_stem else "SvelteComponent"

        # 2. 移除 <script> 块后的纯模板代码与样式
        template_content = re.sub(r"<script\b[^>]*>[\s\S]*?<\/script>", "", content, flags=re.I)
        template_calls = self._extract_template_calls(template_content) if include_calls else []

        # 3. 将整个 Svelte 组件作为顶层 component 符号记录
        total_lines = content.count("\n") + 1
        symbols.append(
            ParsedSymbol(
                name=comp_name,
                symbol_type="component",
                start_line=1,
                end_line=total_lines,
                code=content[:800],  # 截取前导代码切片作为符号特征
                docstring=f"Svelte component: {comp_name}",
                route_info="",
                signature=f"<svelte> ({comp_name})",
                calls=template_calls,
                file_path=file_path,
                module_name=module_name,
                qualified_name=f"{module_name}.{comp_name}" if module_name else comp_name,
            )
        )

        # 4. 提取并解析所有 <script> / <script context="module"> 块
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
