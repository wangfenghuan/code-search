import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import lancedb

from code_search_mcp.config import (
    DEFAULT_MODEL_NAME,
    INDEX_SCHEMA_VERSION,
    get_db_dir,
    get_repo_db_path,
)
from code_search_mcp.embeddings import EmbeddingEngine
from code_search_mcp.ripgrep_engine import ExactSearchEngine
from code_search_mcp.text_utils import (
    expand_query_with_splits,
    extract_natural_words_from_identifiers,
    split_camel_snake_case,
)


def resolve_repo_path(repo_path: Optional[str] = None) -> Optional[Path]:
    """解析代码库路径：若未指定则尝试推断当前目录或上次索引的项目"""
    if repo_path and repo_path.strip():
        p = Path(repo_path).resolve()
        if p.exists() and p.is_dir():
            return p

    # 如果在 Docker 容器内运行且挂载了 /workspace，优先作为默认工作空间
    docker_ws = Path("/workspace")
    if docker_ws.exists() and docker_ws.is_dir():
        try:
            # 只要不是完全空的挂载点就优先使用
            if any(docker_ws.iterdir()):
                return docker_ws
        except Exception:
            pass

    last_repo_file = get_db_dir() / "last_repo.txt"
    if last_repo_file.exists():
        try:
            saved_path = last_repo_file.read_text(encoding="utf-8").strip()
            p = Path(saved_path).resolve()
            if p.exists() and p.is_dir():
                return p
        except Exception:
            pass

    cwd = Path.cwd().resolve()
    return cwd


def compute_ast_match_score(
    query_lower: str,
    query_tokens: List[str],
    symbol_name: str,
    route_info: str,
    chunk_type: str,
) -> float:
    """计算代码块与查询的 AST 结构精确匹配得分 (用于 AST RRF 排名通道)"""
    score = 0.0
    sym_lower = (symbol_name or "").lower()
    route_lower = (route_info or "").lower()
    leaf_name = sym_lower.split(".")[-1]

    # 1. 符号名完全精确匹配
    if sym_lower in query_tokens or query_lower == sym_lower:
        score += 100.0
    elif leaf_name in query_tokens:
        score += 85.0
    elif any(token in sym_lower for token in query_tokens if len(token) >= 3):
        score += 60.0

    # 2. Web 接口路由完全或路径匹配
    if route_lower:
        for token in query_tokens:
            if len(token) >= 3 and token in route_lower:
                score += 80.0
                break

    # 3. 类名/结构体/记录等核心类型定义匹配
    if chunk_type in ("class", "struct", "record", "interface"):
        if sym_lower in query_tokens or leaf_name in query_tokens:
            score += 75.0

    # 4. 标识符自然语言拆词重合度匹配
    sym_splits = split_camel_snake_case(symbol_name)
    if sym_splits:
        overlap = set(sym_splits) & set(query_tokens)
        if overlap:
            score += 40.0 * (len(overlap) / len(sym_splits))

    return score


def calculate_symbol_boost(query: str, symbol_name: str, file_path: str, route_info: str) -> float:
    """保留兼容性接口：计算精确符号、文件名与路由的关键词匹配权重"""
    q_tokens = extract_natural_words_from_identifiers(query)
    score = compute_ast_match_score(query.lower(), q_tokens, symbol_name, route_info, "")
    return min(score / 200.0, 0.50)


class CodeSearcher:
    """结合语义向量、FTS 全文检索、ripgrep 符号检索与 AST 路由结构的多路 RRF 检索器"""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.db_path = get_repo_db_path(self.repo_path)
        self.embedding_engine = EmbeddingEngine.get_instance()
        self.exact_engine = ExactSearchEngine(self.repo_path)
        # LanceDB 连接缓存：避免每次 search() 都重复执行 connect()+open_table() 磁盘 I/O
        self._lancedb_conn = None
        self._lancedb_table = None
        self._cached_mtime = 0.0

    def _get_table(self):
        """懒加载并缓存 LanceDB 连接与表句柄（通过 meta.json mtime 自动感知增量更新）"""
        meta_file = self.db_path / "meta.json"
        curr_mtime = meta_file.stat().st_mtime if meta_file.exists() else 0.0
        if self._lancedb_conn is None or self._lancedb_table is None or self._cached_mtime != curr_mtime:
            self._lancedb_conn = lancedb.connect(str(self.db_path))
            self._lancedb_table = self._lancedb_conn.open_table("code_chunks")
            self._cached_mtime = curr_mtime
        return self._lancedb_table

    def _invalidate_cache(self):
        """索引重建后清除连接缓存，强制下次 search 重新连接"""
        self._lancedb_conn = None
        self._lancedb_table = None
        self._cached_mtime = 0.0

    def is_indexed(self) -> bool:
        if not self.db_path.exists():
            return False
        meta_file = self.db_path / "meta.json"
        if not meta_file.exists():
            return False
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            # 校验 schema 版本与模型一致性，旧版本或模型不兼容时返回 False 触发重建
            if meta.get("schema_version") != INDEX_SCHEMA_VERSION:
                self._invalidate_cache()
                return False
            # 如果是轻量模式 (未建立向量库)，检查 SQLite graph.sqlite3 是否存在且有数据
            if not meta.get("vector_indexed", True):
                sqlite_path = self.db_path / "graph.sqlite3"
                return sqlite_path.exists()
            if meta.get("model_name") != DEFAULT_MODEL_NAME:
                self._invalidate_cache()
                return False
            tbl = self._get_table()
            return len(tbl) > 0
        except Exception:
            self._invalidate_cache()
            return False

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """执行工业级多路 RRF 倒数排名融合检索：
        通道 1: LanceDB Dense 向量语义相似度召回 (仅在 vector_indexed=True 时启用)
        通道 2: LanceDB BM25 / FTS 全文检索召回 (轻量模式使用 SQLite 词法匹配)
        通道 3: 内置 ripgrep 确切代码符号匹配召回
        通道 4: AST 路由与类名/函数名精确结构匹配

        通过 RRF_Score = sum(1 / (k + rank_i)) 统一归一化，彻底摒弃手工调参的硬编码加权。
        """
        if not self.is_indexed():
            return []

        meta_file = self.db_path / "meta.json"
        is_vector_indexed = True
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                is_vector_indexed = meta.get("vector_indexed", True)
            except Exception:
                pass

        candidate_limit = max(top_k * 6, 40)
        candidates_map: Dict[str, Dict[str, Any]] = {}

        # 提取 query 关键符号词集（包含原始与 Camel/Snake 拆解词）
        raw_tokens = re.findall(r"[a-zA-Z0-9_]{2,}", query.lower())
        split_tokens = []
        for tok in raw_tokens:
            split_tokens.extend(split_camel_snake_case(tok))
        all_query_tokens = list(dict.fromkeys(raw_tokens + split_tokens))

        dense_rank: Dict[str, int] = {}
        sparse_rank: Dict[str, int] = {}

        if is_vector_indexed:
            # 1. 查询文本标识符自然语言展开 (强化 bge-small-zh 对长标识符的捕捉)
            expanded_query = expand_query_with_splits(query)
            query_vec = self.embedding_engine.embed_query(expanded_query)

            table = self._get_table()
            if query_vec and table is not None:
                # 通道 1: Dense 向量语义相似度检索 (Vector Dense Channel)
                try:
                    dense_records = table.search(query_vec).limit(candidate_limit).to_list()
                    for r_idx, r in enumerate(dense_records):
                        cid = str(r.get("id"))
                        candidates_map[cid] = r
                        dense_rank[cid] = r_idx
                except Exception:
                    pass

            if table is not None:
                # 通道 2: LanceDB BM25 / 全文检索 (Sparse FTS Channel)
                try:
                    sparse_records = table.search(query, query_type="fts").limit(candidate_limit).to_list()
                    for s_idx, r in enumerate(sparse_records):
                        cid = str(r.get("id"))
                        if cid not in candidates_map:
                            candidates_map[cid] = r
                        sparse_rank[cid] = s_idx
                except Exception:
                    # 降级：若未建 FTS 索引或异常，使用精确标识符 SQL 过滤作为词法召回
                    if all_query_tokens:
                        ident_clauses = " OR ".join(
                            [
                                f"lower(symbol_name) LIKE '%{ident}%' OR lower(route_info) LIKE '%{ident}%' OR lower(code) LIKE '%{ident}%'"
                                for ident in all_query_tokens[:4]
                            ]
                        )
                        try:
                            fallback_records = table.search().where(ident_clauses).limit(candidate_limit).to_list()
                            for s_idx, r in enumerate(fallback_records):
                                cid = str(r.get("id"))
                                if cid not in candidates_map:
                                    candidates_map[cid] = r
                                sparse_rank[cid] = s_idx
                        except Exception:
                            pass
        else:
            # 轻量模式: 从 SQLite nodes 表检索候选符号
            sqlite_path = self.db_path / "graph.sqlite3"
            if sqlite_path.exists():
                try:
                    import sqlite3
                    conn = sqlite3.connect(str(sqlite_path))
                    conn.row_factory = sqlite3.Row
                    clauses = []
                    params = []
                    for tok in all_query_tokens[:5]:
                        clauses.append("(symbol_name LIKE ? OR route_info LIKE ? OR code LIKE ?)")
                        params.extend([f"%{tok}%", f"%{tok}%", f"%{tok}%"])
                    where_clause = " OR ".join(clauses) if clauses else "1=1"
                    sql = f"SELECT id, file_path, symbol_name, chunk_type, start_line, end_line, code, docstring, route_info, module_name, qualified_name FROM nodes WHERE {where_clause} LIMIT {candidate_limit}"
                    rows = conn.execute(sql, params).fetchall()
                    for s_idx, r in enumerate(rows):
                        r_dict = dict(r)
                        cid = str(r_dict.get("id"))
                        candidates_map[cid] = r_dict
                        sparse_rank[cid] = s_idx
                    conn.close()
                except Exception:
                    pass

        # ---------------------------------------------------------
        # 通道 3: 内置 ripgrep 确切代码符号匹配 (Ripgrep Match Channel)
        # ---------------------------------------------------------
        ripgrep_rank: Dict[str, int] = {}
        ripgrep_hits: Dict[str, int] = defaultdict(int)

        rg_tokens: List[str] = [t for t in all_query_tokens if len(t) >= 3 and not t.isdigit()][:4]
        for token in rg_tokens:
            try:
                rg_res = self.exact_engine.search(
                    pattern=token,
                    is_regex=False,
                    case_sensitive=False,
                    max_results=20,
                )
                for m in rg_res.get("matches", []):
                    rel_file = m.get("file", "").replace("\\", "/")
                    line_num = int(m.get("line_number", 0))
                    if not rel_file or line_num <= 0:
                        continue

                    # 检查是否命中已有候选代码块
                    matched_cid = None
                    for cid, c in list(candidates_map.items()):
                        c_file = c.get("file_path", "").replace("\\", "/")
                        if c_file == rel_file and int(c.get("start_line", 0)) <= line_num <= int(c.get("end_line", 0)):
                            matched_cid = cid
                            break

                    # 若 ripgrep 命中但尚未在候选池中，从 LanceDB 范围补全该代码块
                    if not matched_cid:
                        try:
                            safe_file = rel_file.replace("'", "''")
                            where_sql = f"file_path = '{safe_file}' AND start_line <= {line_num} AND end_line >= {line_num}"
                            pulled = table.search().where(where_sql).limit(1).to_list()
                            if pulled:
                                matched_cid = str(pulled[0].get("id"))
                                candidates_map[matched_cid] = pulled[0]
                        except Exception:
                            pass

                    if matched_cid:
                        ripgrep_hits[matched_cid] += 1
            except Exception:
                pass

        if ripgrep_hits:
            sorted_rg = sorted(ripgrep_hits.items(), key=lambda x: x[1], reverse=True)
            for r_idx, (cid, _) in enumerate(sorted_rg):
                ripgrep_rank[cid] = r_idx

        # ---------------------------------------------------------
        # 通道 4: AST 路由与类名/函数名精确匹配 (AST Match Channel)
        # ---------------------------------------------------------
        ast_rank: Dict[str, int] = {}
        ast_scores: Dict[str, float] = {}
        for cid, r in candidates_map.items():
            s_name = r.get("symbol_name", "")
            r_info = r.get("route_info", "")
            c_type = r.get("chunk_type", "")
            score = compute_ast_match_score(
                query_lower=query.lower(),
                query_tokens=all_query_tokens,
                symbol_name=s_name,
                route_info=r_info,
                chunk_type=c_type,
            )
            if score > 0:
                ast_scores[cid] = score

        if ast_scores:
            sorted_ast = sorted(ast_scores.items(), key=lambda x: x[1], reverse=True)
            for a_idx, (cid, _) in enumerate(sorted_ast):
                ast_rank[cid] = a_idx

        # ---------------------------------------------------------
        # 核心融合算法: Reciprocal Rank Fusion (RRF) 统一归一化
        # RRF_Score = sum( 1 / (k + rank_i) )
        # ---------------------------------------------------------
        k_rrf = 60.0
        active_channels = [ch for ch in (dense_rank, sparse_rank, ripgrep_rank, ast_rank) if ch]
        num_active = len(active_channels) if active_channels else 1
        max_possible_rrf = num_active * (1.0 / (k_rrf + 1.0))

        rrf_scores: Dict[str, float] = defaultdict(float)
        for ch in active_channels:
            for cid, rank in ch.items():
                rrf_scores[cid] += 1.0 / (k_rrf + rank + 1.0)

        # ---------------------------------------------------------
        # 生成最终检索结果（替代硬编码加权，返回统一归一化的 similarity）
        # ---------------------------------------------------------
        scored_candidates = []
        for cid, r in candidates_map.items():
            base_rrf = rrf_scores.get(cid, 0.0)
            norm_sim = min(base_rrf / max_possible_rrf, 1.0)
            final_score = round(norm_sim, 4)

            scored_candidates.append(
                {
                    "file_path": r.get("file_path", ""),
                    "full_path": r.get("full_path"),
                    "language": r.get("language", "code"),
                    "symbol_name": r.get("symbol_name", ""),
                    "chunk_type": r.get("chunk_type"),
                    "start_line": int(r.get("start_line", 1)),
                    "end_line": int(r.get("end_line", 1)),
                    "docstring": r.get("docstring", ""),
                    "route_info": r.get("route_info", ""),
                    "decorators": r.get("decorators", ""),
                    "similarity": final_score,
                    "code": r.get("code", ""),
                    "_distance": r.get("_distance"),
                }
            )

        scored_candidates.sort(
            key=lambda x: (
                x["similarity"],
                -float(x["_distance"]) if x.get("_distance") is not None else 0.0,
            ),
            reverse=True,
        )
        return scored_candidates[:top_k]


def format_search_results(results: List[Dict[str, Any]], query: str = "", compact: bool = True, full: bool = False) -> str:
    """格式化检索结果供 MCP 或 CLI 输出，支持 compact 极省 Token 模式"""
    if not results:
        q_tip = f"与 '{query}' " if query else ""
        return f"未能找到{q_tip}相关的代码片段。可能该代码库尚未索引，或无相关实现。"

    q_title = f": \"{query}\"" if query else ""
    output_lines = [f"## 代码检索结果{q_title} (找到 {len(results)} 个最相关代码块，多路 RRF 倒数排名融合)\n"]
    for i, item in enumerate(results, start=1):
        rel_path = item["file_path"]
        symbol = item["symbol_name"]
        lang = item.get("language", "code")
        start_l = item["start_line"]
        end_l = item["end_line"]
        sim = item["similarity"]
        chunk_type = item["chunk_type"]
        route = item.get("route_info")
        doc = item.get("docstring", "").strip()
        code = item["code"].strip()

        header_tags = [f"语言: {lang}", f"得分: {sim}", f"类型: {chunk_type}"]
        if route:
            header_tags.append(f"接口: `{route}`")

        output_lines.append(f"### [{i}] `{rel_path}:{start_l}-{end_l}` — `{symbol}`")
        output_lines.append(f"- **元数据**: {' | '.join(header_tags)}")
        if doc:
            first_doc = doc.split("\n")[0]
            output_lines.append(f"- **文档说明**: *{first_doc}*")

        code_lines = code.splitlines()
        total_lines = len(code_lines)

        if not full and compact and total_lines > 12:
            preview_code = "\n".join(code_lines[:10])
            output_lines.append(
                f"```{lang}\n{preview_code}\n# ... (剩余 {total_lines - 10} 行代码，调用 get_file_content 传入起始行 {start_l} 查看完整实现)\n```\n"
            )
        else:
            output_lines.append(f"```{lang}\n{code}\n```\n")

    return "\n".join(output_lines)
