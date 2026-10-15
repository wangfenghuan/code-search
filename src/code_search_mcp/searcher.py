import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import lancedb

from code_search_mcp.config import get_db_dir, get_repo_db_path
from code_search_mcp.embeddings import EmbeddingEngine


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


def calculate_symbol_boost(query: str, symbol_name: str, file_path: str, route_info: str) -> float:
    """计算精确符号、文件名与路由的关键词加权，用于提升中英文混合检索的准确度"""
    boost = 0.0
    q_lower = query.lower()
    sym_lower = symbol_name.lower()
    file_lower = file_path.lower()
    route_lower = route_info.lower()

    # 提取 query 中的英文标识符
    identifiers = re.findall(r"[a-zA-Z0-9_]{3,}", q_lower)

    # 1. 符号名精确包含检查
    for ident in identifiers:
        if ident == sym_lower:
            boost += 0.40
            break
        elif sym_lower.startswith(f"{ident}.") or f".{ident}." in sym_lower or sym_lower.endswith(f".{ident}"):
            boost += 0.35
            break
        elif ident in sym_lower:
            boost += 0.25
            break

    # 2. 路由匹配加权（例如 query 含有 "post" 或 "/login"）
    if route_lower:
        for ident in identifiers:
            if ident in route_lower:
                boost += 0.30
                break

    # 3. 文件名匹配加权
    for ident in identifiers:
        if ident in file_lower:
            boost += 0.15
            break

    # 4. 中文关键词对常用符号的启发式对齐
    chinese_map = {
        "登录": ["login", "auth", "signin", "authenticate"],
        "注册": ["register", "signup"],
        "密码": ["password", "hasher", "passwd"],
        "连接池": ["pool", "connection"],
        "事务": ["transaction", "tx"],
        "用户": ["user", "account"],
        "支付": ["pay", "payment", "order"],
        "登出": ["logout", "signout"],
        "校验": ["verify", "validate", "check"],
    }

    for zh_kw, en_terms in chinese_map.items():
        if zh_kw in q_lower:
            for term in en_terms:
                if term in sym_lower or term in file_lower:
                    boost += 0.15
                    break

    return min(boost, 0.50)


class CodeSearcher:
    """结合语义向量与精确符号加权的高准确度检索器"""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.db_path = get_repo_db_path(self.repo_path)
        self.embedding_engine = EmbeddingEngine.get_instance()

    def is_indexed(self) -> bool:
        if not self.db_path.exists():
            return False
        meta_file = self.db_path / "meta.json"
        if not meta_file.exists():
            return False
        try:
            db = lancedb.connect(str(self.db_path))
            return "code_chunks" in db.table_names()
        except Exception:
            return False

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """执行混合召回（语义向量 + 符号精确匹配）与加权重排"""
        if not self.is_indexed():
            return []

        query_vec = self.embedding_engine.embed_query(query)
        if not query_vec:
            return []

        db = lancedb.connect(str(self.db_path))
        table = db.open_table("code_chunks")

        # 1. 向量相似度召回
        candidate_limit = max(top_k * 6, 40)
        search_query = table.search(query_vec).limit(candidate_limit)
        vector_records = search_query.to_list()

        candidates_map: Dict[str, Dict[str, Any]] = {}
        for r in vector_records:
            cid = r.get("id")
            candidates_map[cid] = r

        # 2. 精确符号多路召回（若提问中包含具体英文类名/方法名/路由片段）
        identifiers = re.findall(r"[a-zA-Z0-9_]{3,}", query.lower())
        if identifiers:
            for ident in identifiers:
                try:
                    # 使用 LanceDB SQL 过滤快速召回确切符号
                    symbol_matched = (
                        table.search()
                        .where(f"lower(symbol_name) LIKE '%{ident}%' OR lower(route_info) LIKE '%{ident}%'")
                        .limit(20)
                        .to_list()
                    )
                    for r in symbol_matched:
                        cid = r.get("id")
                        if cid not in candidates_map:
                            candidates_map[cid] = r
                except Exception:
                    pass

        # 3. 统一重排打分
        scored_candidates = []
        for r in candidates_map.values():
            dist = r.get("_distance")
            # 若不是向量检索直接返回的结果，默认给平均基底相似度
            base_sim = round(1.0 / (1.0 + float(dist)), 4) if dist is not None else 0.45

            symbol_name = r.get("symbol_name", "")
            file_path = r.get("file_path", "")
            route_info = r.get("route_info", "")

            # 符号与关键词增强
            boost = calculate_symbol_boost(query, symbol_name, file_path, route_info)
            final_score = round(min(base_sim * (1.0 + boost), 1.0), 4)
            language = r.get("language", "code")

            scored_candidates.append(
                {
                    "file_path": file_path,
                    "full_path": r.get("full_path"),
                    "language": language,
                    "symbol_name": symbol_name,
                    "chunk_type": r.get("chunk_type"),
                    "start_line": int(r.get("start_line", 1)),
                    "end_line": int(r.get("end_line", 1)),
                    "docstring": r.get("docstring", ""),
                    "route_info": route_info,
                    "decorators": r.get("decorators", ""),
                    "similarity": final_score,
                    "code": r.get("code", ""),
                }
            )

        # 按综合加权分从高到低排序取 top_k
        scored_candidates.sort(key=lambda x: x["similarity"], reverse=True)
        return scored_candidates[:top_k]


def format_search_results(results: List[Dict[str, Any]], query: str, compact: bool = True) -> str:
    """格式化输出，支持 compact 极省 Token 模式"""
    if not results:
        return f"未能找到与 '{query}' 相关的代码片段。可能该代码库尚未索引，或无相关实现。"

    output_lines = [f"## 代码检索结果: \"{query}\" (找到 {len(results)} 个最相关代码块)\n"]
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

        if compact and total_lines > 12:
            # 紧凑模式：截取前 10 行并提示深入查看
            preview_code = "\n".join(code_lines[:10])
            output_lines.append(
                f"```python\n{preview_code}\n# ... (剩余 {total_lines - 10} 行代码，调用 get_file_content 传入起始行 {start_l} 查看完整实现)\n```\n"
            )
        else:
            output_lines.append(f"```python\n{code}\n```\n")

    return "\n".join(output_lines)
