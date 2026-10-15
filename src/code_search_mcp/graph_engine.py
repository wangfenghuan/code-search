import json
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import lancedb

from code_search_mcp.config import INDEX_SCHEMA_VERSION, get_repo_db_path
from code_search_mcp.searcher import CodeSearcher

_engine_cache: Dict[str, "CodeGraphEngine"] = {}
_cache_lock = threading.Lock()


@dataclass
class SymbolNode:
    id: str
    file_path: str
    symbol_name: str
    chunk_type: str
    start_line: int
    end_line: int
    code: str
    docstring: str
    route_info: str
    calls: List[str]
    module_name: str = ""
    qualified_name: str = ""


class CodeGraphEngine:
    """轻量级多语言代码知识图谱引擎 (启发自 CodeGraph)

    核心能力:
    1. 上游追踪 (get_callers): 谁调用了这个符号
    2. 下游追踪 (get_callees): 这个符号调用了哪些下级函数与服务
    3. 爆炸半径 (get_impact_radius): 改动该符号会影响哪些上层模块、测试与外部 API 路由
    4. 一键探索 (explore_feature): 语义检索 + 拓扑图双向展开，1 次调用直出全链路证据
    """

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.db_path = get_repo_db_path(self.repo_path)
        self.nodes: Dict[str, List[SymbolNode]] = defaultdict(list)
        self.all_nodes: List[SymbolNode] = []
        self.callers_map: Dict[str, List[SymbolNode]] = defaultdict(list)
        self.routes_map: Dict[str, str] = {}
        self._loaded = False

    @classmethod
    def get_instance(cls, repo_path: str | Path) -> "CodeGraphEngine":
        """获取或创建代码库对应的图引擎单例"""
        resolved = str(Path(repo_path).resolve())
        with _cache_lock:
            if resolved not in _engine_cache:
                engine = cls(resolved)
                engine.load()
                _engine_cache[resolved] = engine
            return _engine_cache[resolved]

    @classmethod
    def invalidate_cache(cls, repo_path: str | Path):
        """使指定仓库的图引擎缓存失效并重载最新数据"""
        resolved = str(Path(repo_path).resolve())
        with _cache_lock:
            if resolved in _engine_cache:
                _engine_cache[resolved].reload()

    def reload(self) -> bool:
        """重载 LanceDB 最新切片并重建内存拓扑图"""
        self._loaded = False
        self.nodes.clear()
        self.all_nodes.clear()
        self.callers_map.clear()
        self.routes_map.clear()
        return self.load()

    def load(self) -> bool:
        """加载 LanceDB 索引并构建符号调用拓扑图"""
        if self._loaded:
            return True

        if not self.db_path.exists():
            return False

        # 校验版本控制
        meta_file = self.db_path / "meta.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                if meta.get("schema_version") != INDEX_SCHEMA_VERSION:
                    return False
            except Exception:
                pass

        try:
            db = lancedb.connect(str(self.db_path))
            tbl = db.open_table("code_chunks")
            records = tbl.to_arrow().to_pylist()
            for row in records:
                calls_raw = row.get("calls", "[]")
                try:
                    calls_list = json.loads(calls_raw) if isinstance(calls_raw, str) else list(calls_raw)
                except Exception:
                    calls_list = []

                node = SymbolNode(
                    id=str(row.get("id", "")),
                    file_path=str(row.get("file_path", "")),
                    symbol_name=str(row.get("symbol_name", "")),
                    chunk_type=str(row.get("chunk_type", "")),
                    start_line=int(row.get("start_line", 1)),
                    end_line=int(row.get("end_line", 1)),
                    code=str(row.get("code", "")),
                    docstring=str(row.get("docstring", "")),
                    route_info=str(row.get("route_info", "")),
                    calls=calls_list,
                    module_name=str(row.get("module_name", "")),
                    qualified_name=str(row.get("qualified_name", "")),
                )
                self.all_nodes.append(node)
                # 1. 优先使用全限定名索引
                if node.qualified_name:
                    self.nodes[node.qualified_name].append(node)
                # 2. 原符号名索引
                if node.symbol_name:
                    self.nodes[node.symbol_name].append(node)
                # 3. 尾部短名索引
                if "." in node.symbol_name:
                    short_name = node.symbol_name.split(".")[-1]
                    self.nodes[short_name].append(node)

                if node.route_info:
                    self.routes_map[node.symbol_name] = node.route_info

            # 构建反向调用图 callers_map
            for node in self.all_nodes:
                for target in node.calls:
                    self.callers_map[target].append(node)

            self._loaded = True
            return True
        except Exception:
            return False

    def disambiguate_target(
        self, caller_file: str, called_name: str, candidates: List[SymbolNode]
    ) -> Tuple[Optional[SymbolNode], bool, List[str]]:
        """在存在同名符号时，按同限定名 > 同文件 > 同目录 > 唯一性 进行拓扑消歧，无法唯一消歧时标记 ambiguous"""
        if not candidates:
            return None, False, []
        if len(candidates) == 1:
            return candidates[0], False, []

        # 1. 优先匹配完全相同的全限定名
        exact_qname = [n for n in candidates if n.qualified_name == called_name]
        if len(exact_qname) == 1:
            return exact_qname[0], False, []

        # 2. 优先同一文件
        same_file = [n for n in candidates if n.file_path == caller_file]
        if len(same_file) == 1:
            return same_file[0], False, []

        # 3. 优先同一目录
        caller_dir = Path(caller_file).parent.as_posix()
        same_dir = [n for n in candidates if Path(n.file_path).parent.as_posix() == caller_dir]
        if len(same_dir) == 1:
            return same_dir[0], False, []

        # 4. 无法自动唯一消歧，返回第一个候选并标明歧义候选列表
        cand_strs = [f"{n.qualified_name or n.symbol_name} ({n.file_path}#L{n.start_line})" for n in candidates]
        return candidates[0], True, cand_strs

    def get_callers(self, symbol_name: str) -> Dict[str, Any]:
        """查询调用了指定符号的所有上游调用方 (Who calls X)"""
        if not self.load():
            return {
                "status": "error",
                "message": f"未找到代码库索引，请先对 {self.repo_path} 执行 index_codebase",
                "callers": [],
            }

        # 支持完整名称或方法名匹配
        target_keys = [symbol_name]
        if "." in symbol_name:
            target_keys.append(symbol_name.split(".")[-1])

        is_defined_in_repo = any(k in self.nodes for k in target_keys)
        def_nodes = self.nodes.get(symbol_name, [])
        unique_defs = list({f"{n.file_path}:{n.start_line}": n for n in def_nodes}.values())
        is_ambiguous_def = len(unique_defs) > 1
        ambig_defs = (
            [f"{n.qualified_name or n.symbol_name} ({n.file_path}#L{n.start_line})" for n in unique_defs]
            if is_ambiguous_def
            else []
        )

        callers_seen: Set[str] = set()
        matched_callers: List[Dict[str, Any]] = []

        for k in target_keys:
            for caller in self.callers_map.get(k, []):
                unique_key = f"{caller.file_path}:{caller.symbol_name}:{caller.start_line}"
                if unique_key not in callers_seen:
                    callers_seen.add(unique_key)
                    # 摘取前 12 行代码作为预览
                    lines = caller.code.splitlines()
                    preview = "\n".join(lines[:12]) + ("\n..." if len(lines) > 12 else "")
                    matched_callers.append(
                        {
                            "caller_symbol": caller.symbol_name,
                            "symbol_type": caller.chunk_type,
                            "file_path": caller.file_path,
                            "start_line": caller.start_line,
                            "end_line": caller.end_line,
                            "route_info": caller.route_info,
                            "docstring": caller.docstring,
                            "code_preview": preview,
                        }
                    )

        return {
            "status": "success",
            "target_symbol": symbol_name,
            "defined_in_repo": is_defined_in_repo,
            "ambiguous_definitions": ambig_defs,
            "callers_count": len(matched_callers),
            "callers": matched_callers,
        }

    def get_callees(self, symbol_name: str) -> Dict[str, Any]:
        """查询指定符号直接调用的下游函数与模块 (What X calls)"""
        if not self.load():
            return {
                "status": "error",
                "message": f"未找到代码库索引，请先对 {self.repo_path} 执行 index_codebase",
                "callees": [],
            }

        nodes = self.nodes.get(symbol_name, [])
        if not nodes:
            return {
                "status": "not_found",
                "target_symbol": symbol_name,
                "message": f"未在索引中找到符号: {symbol_name}",
                "callees": [],
            }

        caller_node = nodes[0]
        caller_file = caller_node.file_path

        all_calls = set()
        for n in nodes:
            all_calls.update(n.calls)

        callees_detail = []
        for called in sorted(all_calls):
            # 尝试在索引中定位该符号的具体定义
            target_nodes = self.nodes.get(called, [])
            if target_nodes:
                def_node, is_ambiguous, candidate_list = self.disambiguate_target(caller_file, called, target_nodes)
                callees_detail.append(
                    {
                        "target_symbol": called,
                        "defined_in_repo": True,
                        "file_path": def_node.file_path if def_node else None,
                        "qualified_name": def_node.qualified_name if def_node else "",
                        "symbol_type": def_node.chunk_type if def_node else "symbol",
                        "start_line": def_node.start_line if def_node else None,
                        "docstring": def_node.docstring if def_node else "",
                        "ambiguous": is_ambiguous,
                        "candidates": candidate_list,
                    }
                )
            else:
                callees_detail.append(
                    {
                        "target_symbol": called,
                        "defined_in_repo": False,
                        "file_path": None,
                        "qualified_name": "",
                        "symbol_type": "external_or_builtin",
                        "start_line": None,
                        "docstring": "",
                        "ambiguous": False,
                        "candidates": [],
                    }
                )

        return {
            "status": "success",
            "target_symbol": symbol_name,
            "callees_count": len(callees_detail),
            "callees": callees_detail,
        }

    def get_impact_radius(self, symbol_name: str, max_depth: int = 3) -> Dict[str, Any]:
        """影响面/爆炸半径分析 (Blast Radius):
        计算修改该符号后，直接和间接被波及的上游调用链路、关联文件及受影响的外部 API 路由
        """
        if not self.load():
            return {
                "status": "error",
                "message": f"未找到代码库索引，请先执行 index_codebase",
            }

        visited_symbols: Set[str] = set()
        queue = deque([(symbol_name, 0, [symbol_name])])
        impacted_tree = []
        impacted_files: Set[str] = set()
        impacted_routes: List[Dict[str, str]] = []
        routes_seen: Set[str] = set()

        while queue:
            curr_sym, depth, path = queue.popleft()
            if curr_sym in visited_symbols or depth >= max_depth:
                continue
            visited_symbols.add(curr_sym)

            # 查询调用方
            keys = [curr_sym]
            if "." in curr_sym:
                keys.append(curr_sym.split(".")[-1])

            callers = []
            for k in keys:
                callers.extend(self.callers_map.get(k, []))

            for c in callers:
                impacted_files.add(c.file_path)
                item = {
                    "depth": depth + 1,
                    "symbol": c.symbol_name,
                    "type": c.chunk_type,
                    "file_path": c.file_path,
                    "line": c.start_line,
                    "route": c.route_info,
                    "propagation_path": " -> ".join(path + [c.symbol_name]),
                }
                impacted_tree.append(item)

                if c.route_info and c.route_info not in routes_seen:
                    routes_seen.add(c.route_info)
                    impacted_routes.append(
                        {
                            "route": c.route_info,
                            "handler": c.symbol_name,
                            "file_path": c.file_path,
                            "line": str(c.start_line),
                        }
                    )

                if c.symbol_name not in visited_symbols:
                    queue.append((c.symbol_name, depth + 1, path + [c.symbol_name]))

        return {
            "status": "success",
            "target_symbol": symbol_name,
            "max_analyzed_depth": max_depth,
            "total_impacted_symbols": len(impacted_tree),
            "impacted_files_count": len(impacted_files),
            "impacted_files": sorted(list(impacted_files)),
            "impacted_external_routes": impacted_routes,
            "impact_propagation_chain": impacted_tree,
        }

    def build_call_tree(self, root_sym: str, max_depth: int = 3) -> Dict[str, Any]:
        """对指定根节点进行 BFS 下游展开，生成调用树与链路节点 (Fix #9)"""
        tree_node: Dict[str, Any] = {
            "symbol": root_sym,
            "defined_in_repo": True,
            "file_path": None,
            "line": None,
            "docstring": "",
            "children": [],
        }
        root_defs = self.nodes.get(root_sym, [])
        if root_defs:
            tree_node["file_path"] = root_defs[0].file_path
            tree_node["line"] = root_defs[0].start_line
            tree_node["docstring"] = root_defs[0].docstring

        visited = {root_sym}
        queue = deque([(tree_node, root_sym, 1)])

        while queue:
            curr_item, curr_sym, depth = queue.popleft()
            if depth > max_depth:
                continue

            callees_data = self.get_callees(curr_sym)
            callees = callees_data.get("callees", [])
            for c in callees:
                c_sym = c["target_symbol"]
                in_repo = c.get("defined_in_repo", False)
                child_item = {
                    "symbol": c_sym,
                    "defined_in_repo": in_repo,
                    "file_path": c.get("file_path"),
                    "line": c.get("start_line"),
                    "docstring": c.get("docstring", ""),
                    "children": [],
                }
                curr_item["children"].append(child_item)
                if in_repo and c_sym not in visited and depth < max_depth:
                    visited.add(c_sym)
                    queue.append((child_item, c_sym, depth + 1))

        return tree_node

    def format_tree_ascii(self, node: Dict[str, Any], prefix: str = "", is_last: bool = True, is_root: bool = True) -> List[str]:
        """将调用树格式化为目录树 ASCII 字符串列表 (Fix #11)"""
        lines = []
        sym = node["symbol"]
        f_info = f" ({node['file_path']}#L{node['line']})" if node.get("file_path") else " (外部库/内置)"
        doc = f" — *{node['docstring'].strip()}*" if node.get("docstring") else ""

        if is_root:
            lines.append(f"`{sym}`{f_info}{doc}")
        else:
            connector = "└── ➡️ " if is_last else "├── ➡️ "
            lines.append(f"{prefix}{connector}`{sym}`{f_info}{doc}")

        children = node.get("children", [])
        # 去重相同文件行号的同义符号名
        seen_targets = set()
        deduped_children = []
        for ch in children:
            target_key = f"{ch.get('file_path')}:{ch.get('line')}" if ch.get("file_path") else ch.get("symbol")
            if target_key in seen_targets:
                continue
            seen_targets.add(target_key)
            deduped_children.append(ch)

        # 优先展示仓库内的实现，外部内置函数最多展示 3 个
        in_repo = [c for c in deduped_children if c.get("defined_in_repo")]
        external = [c for c in deduped_children if not c.get("defined_in_repo")]
        filtered_children = in_repo + external[:3]

        for i, child in enumerate(filtered_children):
            child_is_last = (i == len(filtered_children) - 1)
            next_prefix = "" if is_root else (prefix + ("    " if is_last else "│   "))
            lines.extend(self.format_tree_ascii(child, prefix=next_prefix, is_last=child_is_last, is_root=False))

        return lines

    def explore_feature(self, query: str, top_k: int = 3, max_depth: int = 3) -> Dict[str, Any]:
        """一键全链路手术级探索 (explore_feature):
        语义召回入口 + BFS 多层调用链路展开 + 路由全景与代码证据聚合，
        让 AI Agent 仅需 1 次工具调用即可获得业务完整执行拓扑与证据。
        """
        if not self.load():
            return {
                "status": "error",
                "message": f"未找到代码库索引，请先执行 index_codebase",
            }

        searcher = CodeSearcher(self.repo_path)
        # 扩大初始召回候选，保证跨多模块复杂链路被完全覆盖 (Fix #8)
        matches = searcher.search(query=query, top_k=max(top_k * 2, 6))

        if not matches:
            return {
                "status": "no_match",
                "query": query,
                "message": f"未找到与 '{query}' 相关的核心代码模块",
            }

        markdown_sections = []
        markdown_sections.append(f"# 🧭 业务全链路手术级探索: {query}\n")
        markdown_sections.append(f"> 💡 **一次调用直达完整上下文**: 聚合了语义命中入口、HTTP 外部路由、下游多层 BFS 调用依赖树与核心源码。\n")

        # 收集所有已展开的子节点用于跨 entry 去重 (Fix #10)
        global_expanded_symbols: Set[str] = set()
        flow_idx = 1
        all_involved_files: Set[str] = set()

        for m in matches:
            sym_name = m.get("symbol_name", "")
            file_path = m.get("file_path", "")
            route_info = m.get("route_info", "")
            docstring = m.get("docstring", "")
            code = m.get("code", "")
            start_line = m.get("start_line", 1)
            end_line = m.get("end_line", 1)

            # 去重：如果该符号已经在前置流的子树中详细展开过，跳过外层重复列出 (Fix #10)
            if sym_name in global_expanded_symbols:
                continue
            if flow_idx > top_k:
                break

            all_involved_files.add(file_path)
            global_expanded_symbols.add(sym_name)

            markdown_sections.append(f"## 🎯 业务调用链路 {flow_idx}: `{sym_name}` ({file_path}#L{start_line}-L{end_line})")

            # 路由感知
            if route_info:
                markdown_sections.append(f"- 🌐 **关联外部路由**: `{route_info}`")
            else:
                impact = self.get_impact_radius(sym_name, max_depth=3)
                up_routes = impact.get("impacted_external_routes", [])
                if up_routes:
                    r = up_routes[0]
                    markdown_sections.append(f"- 🌐 **关联触发路由**: `{r['route']}` (由 `{r['handler']}` 处理，位于 `{r['file_path']}`:L{r['line']})")

            if docstring:
                markdown_sections.append(f"- 📝 **功能描述**: {docstring}")

            # BFS 多层下游依赖树构建与 ASCII 拓扑展示 (Fix #9, #11)
            call_tree = self.build_call_tree(sym_name, max_depth=max_depth)
            tree_lines = self.format_tree_ascii(call_tree)
            if len(tree_lines) > 1:
                markdown_sections.append("\n### 🛣️ 端到端多层调用链路 (Execution Trace):")
                markdown_sections.append("```text\n" + "\n".join(tree_lines) + "\n```")

            def mark_children(n: Dict[str, Any]):
                for ch in n.get("children", []):
                    ch_sym = ch["symbol"]
                    global_expanded_symbols.add(ch_sym)
                    if ch.get("file_path"):
                        all_involved_files.add(ch["file_path"])
                    mark_children(ch)
            mark_children(call_tree)

            # 上游触发者 (Callers)
            callers_res = self.get_callers(sym_name)
            callers = callers_res.get("callers", [])
            if callers:
                markdown_sections.append("\n### ⬆️ 直接上游触发方 (Callers):")
                for c in callers[:3]:
                    c_sym = c['caller_symbol']
                    c_file = c['file_path']
                    c_line = c['start_line']
                    route_note = f" [触发路由: `{c['route_info']}`]" if c.get('route_info') else ""
                    markdown_sections.append(f"  - ⬅️ 被 `{c_sym}` 调用 (位于 `{c_file}`:L{c_line}){route_note}")

            # 附带源码证据
            markdown_sections.append(f"\n### 📦 核心源码实现片段:")
            markdown_sections.append(f"```{m.get('language', 'text')}\n{code}\n```\n")

            flow_idx += 1

        if all_involved_files:
            markdown_sections.append("### 📁 链路涉及代码文件清单:")
            for f in sorted(list(all_involved_files)):
                markdown_sections.append(f"- `{f}`")

        full_markdown = "\n".join(markdown_sections)
        return {
            "status": "success",
            "query": query,
            "entry_matches_count": flow_idx - 1,
            "involved_files": sorted(list(all_involved_files)),
            "surgical_context_markdown": full_markdown,
        }

    def find_references(self, query: str) -> Dict[str, Any]:
        """跨模块反向引用综合分析 (Find All References, Fix #20):
        聚合 AST 代码调用者 (Structural Callers) 与 ripgrep 跨文件字面量/配置项引用 (Textual References)
        """
        if not self.load():
            return {
                "status": "error",
                "message": f"未找到代码库索引，请先执行 index_codebase",
                "references": [],
            }

        # 1. 结构化 AST 调用方
        callers_res = self.get_callers(query)
        ast_callers = callers_res.get("callers", [])

        # 2. 跨文件精准文本/配置项引用
        from code_search_mcp.ripgrep_engine import ExactSearchEngine
        exact_engine = ExactSearchEngine(self.repo_path)
        ripgrep_res = exact_engine.search(query, max_results=30)
        raw_matches = ripgrep_res.get("matches", [])

        # 去重：过滤掉与 AST 重合的调用行
        ast_locations = {f"{c['file_path']}:{c['start_line']}" for c in ast_callers}
        text_refs = []
        for m in raw_matches:
            f_path = getattr(m, "file_path", None) or (m.get("file_path", "") if isinstance(m, dict) else "")
            l_num = getattr(m, "line_number", None) or (m.get("line_number", 0) if isinstance(m, dict) else 0)
            content = getattr(m, "line_content", None) or (m.get("line_content", "") if isinstance(m, dict) else "")
            loc = f"{f_path}:{l_num}"
            if loc not in ast_locations:
                text_refs.append({
                    "file_path": f_path,
                    "line_number": l_num,
                    "content": content,
                })

        return {
            "status": "success",
            "target": query,
            "defined_in_repo": callers_res.get("defined_in_repo", False),
            "structural_callers_count": len(ast_callers),
            "structural_callers": ast_callers,
            "textual_references_count": len(text_refs),
            "textual_references": text_refs,
            "total_references": len(ast_callers) + len(text_refs),
        }


def format_callers_markdown(res: Dict[str, Any]) -> str:
    """格式化 callers 为 Markdown 证据报告"""
    if res.get("status") != "success":
        return f"❌ {res.get('message', '查询上游调用失败')}"

    target = res.get("target_symbol", "")
    callers = res.get("callers", [])
    count = res.get("callers_count", 0)
    is_defined = res.get("defined_in_repo", True)

    lines = [f"# 📞 符号上游调用方 (Callers): `{target}` (共 {count} 处调用)\n"]
    ambig_defs = res.get("ambiguous_definitions", [])
    if ambig_defs:
        lines.append(f"> ⚠️ **同名符号多定义提示**: 符号名 `{target}` 在代码库中存在多处独立定义: {', '.join(ambig_defs)}。以下展示针对该名字的所有调用方。\n")

    if not is_defined:
        lines.append(f"> ⚠️ **提示**: 符号 `{target}` 在本地代码库中未检索到定义（可能属于第三方库、标准库或已被移除重构）。\n")

    if count == 0:
        lines.append("未发现任何显式调用该符号的上游模块（可能是顶级入口、外部暴露接口或未被直接引用的方法）。")
        return "\n".join(lines)

    for idx, c in enumerate(callers, start=1):
        sym = c['caller_symbol']
        f_path = c['file_path']
        s_line = c['start_line']
        route = f" 🌐 [接口: `{c['route_info']}`]" if c.get('route_info') else ""
        doc = f" — *{c['docstring']}*" if c.get('docstring') else ""
        lines.append(f"### {idx}. `{sym}` ({f_path}#L{s_line}){route}{doc}")
        if c.get("code_preview"):
            lines.append("```python\n" + c["code_preview"] + "\n```")
    return "\n".join(lines)


def format_callees_markdown(res: Dict[str, Any]) -> str:
    """格式化 callees 为 Markdown 依赖清单"""
    if res.get("status") != "success":
        return f"❌ {res.get('message', '查询下游依赖失败')}"

    target = res.get("target_symbol", "")
    callees = res.get("callees", [])
    count = res.get("callees_count", 0)

    lines = [f"# 🎯 符号下游依赖调用 (Callees): `{target}` (共 {count} 个调用目标)\n"]
    if count == 0:
        lines.append("该符号内部未检测到任何函数/方法调用（叶子节点函数）。")
        return "\n".join(lines)

    for idx, c in enumerate(callees, start=1):
        sym = c['target_symbol']
        in_repo = c.get('defined_in_repo', False)
        if in_repo:
            f_path = c.get('file_path')
            s_line = c.get('start_line')
            qname = c.get('qualified_name')
            qname_tag = f" (`{qname}`)" if qname and qname != sym else ""
            doc = f" — *{c.get('docstring')}*" if c.get('docstring') else ""
            ambig_note = ""
            if c.get("ambiguous") and c.get("candidates"):
                ambig_note = f"\n    ⚠️ *[重名歧义提示: 存在多处同名候选，当前推断为 `{f_path}:L{s_line}`; 备选: {', '.join(c['candidates'])}]*"
            lines.append(f"- **{idx}. `{sym}`**{qname_tag} ➡️ (定义于 `{f_path}`:L{s_line}){doc}{ambig_note}")
        else:
            lines.append(f"- **{idx}. `{sym}`** (外部库依赖或内置函数)")

    return "\n".join(lines)


def format_impact_markdown(res: Dict[str, Any]) -> str:
    """格式化爆炸半径/影响面分析结果为 Markdown"""
    if res.get("status") != "success":
        return f"❌ {res.get('message', '影响面分析失败')}"

    target = res.get("target_symbol", "")
    total_syms = res.get("total_impacted_symbols", 0)
    files = res.get("impacted_files", [])
    routes = res.get("impacted_external_routes", [])
    chain = res.get("impact_propagation_chain", [])

    lines = [f"# 💥 符号修改爆炸半径/影响面分析: `{target}`\n"]
    lines.append(f"> ⚠️ **改动风险评估**: 修改 `{target}` 将可能波及 **{total_syms} 个上游符号**、**{len(files)} 个源文件**，涉及 **{len(routes)} 个外部 API 路由**。\n")

    if routes:
        lines.append("## 🌐 受直接/间接影响的外部暴露接口 (需重点回归测试):")
        for r in routes:
            lines.append(f"- `{r['route']}` (由 `{r['handler']}` 处理，位于 `{r['file_path']}`:L{r['line']})")
        lines.append("")

    if files:
        lines.append("## 📁 受影响的代码文件:")
        for f in files:
            lines.append(f"- `{f}`")
        lines.append("")

    if chain:
        lines.append("## 🌲 调用依赖扩散路径 (Propagation Tree):")
        for item in chain:
            depth = item['depth']
            sym = item['symbol']
            f_path = item['file_path']
            line = item['line']
            route_tag = f" 🌐 [接口: `{item['route']}`]" if item.get('route') else ""
            indent = "  " * (depth - 1)
            lines.append(f"{indent}- [深度 {depth}] `{sym}` ({f_path}:L{line}){route_tag}")

    return "\n".join(lines)


def format_references_markdown(res: Dict[str, Any]) -> str:
    """格式化反向引用分析报告为 Markdown (Fix #20)"""
    if res.get("status") != "success":
        return f"❌ {res.get('message', '反向引用检索失败')}"

    target = res.get("target", "")
    ast_callers = res.get("structural_callers", [])
    text_refs = res.get("textual_references", [])
    total = res.get("total_references", 0)

    lines = [f"# 🔍 跨模块反向引用分析: `{target}` (共检索到 {total} 处引用)\n"]
    if total == 0:
        lines.append("未在代码库中发现任何对该符号或文本的显式引用。")
        return "\n".join(lines)

    if ast_callers:
        lines.append(f"## 📞 1. 代码符号显式调用方 ({len(ast_callers)} 处 AST 调用):")
        for idx, c in enumerate(ast_callers, start=1):
            sym = c["caller_symbol"]
            f_path = c["file_path"]
            s_line = c["start_line"]
            route = f" 🌐 [触发路由: `{c['route_info']}`]" if c.get("route_info") else ""
            doc = f" — *{c['docstring']}*" if c.get("docstring") else ""
            lines.append(f"- **{idx}. `{sym}`** (`{f_path}`:L{s_line}){route}{doc}")
        lines.append("")

    if text_refs:
        lines.append(f"## 📝 2. 配置/字符串/常量字面量引用 ({len(text_refs)} 处文本引用):")
        for idx, m in enumerate(text_refs, start=1):
            f_path = m.get("file_path", "")
            line = m.get("line_number", 0)
            content = m.get("content", "").strip()
            lines.append(f"- **{idx}. `{f_path}`:L{line}**")
            lines.append(f"  ```\n  {content}\n  ```")
        lines.append("")

    return "\n".join(lines)

