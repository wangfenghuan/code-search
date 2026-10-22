import json
import re
import sqlite3
import threading
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from code_search_mcp.config import INDEX_SCHEMA_VERSION, get_repo_db_path
from code_search_mcp.multilang_parser import EXTENSION_LANG_MAP, TreeSitterParser
from code_search_mcp.ripgrep_engine import ExactSearchEngine

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
    """Lightweight multi-language code knowledge graph engine"""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.db_path = get_repo_db_path(self.repo_path)
        self.sqlite_path = self.db_path / "graph.sqlite3"
        self._conn: Optional[sqlite3.Connection] = None
        self._loaded = False

    def _get_db(self) -> sqlite3.Connection:
        if self._conn is None:
            self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.sqlite_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA cache_size=-64000;")
            self._conn.execute("PRAGMA temp_store=MEMORY;")
            self._conn.execute("PRAGMA mmap_size=268435456;")
        return self._conn

    def _close_db(self):
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def close(self):
        """释放底层 SQLite 数据库连接与内存句柄"""
        self._close_db()

    def _init_sqlite_schema(self, conn: sqlite3.Connection):
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                val TEXT
            );

            CREATE TABLE IF NOT EXISTS resolved_queries (
                query_type TEXT,
                symbol_name TEXT,
                PRIMARY KEY (query_type, symbol_name)
            );

            CREATE TABLE IF NOT EXISTS graph_query_cache (
                query_type TEXT,
                cache_key TEXT,
                result_json TEXT,
                created_at REAL,
                PRIMARY KEY (query_type, cache_key)
            );

            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY,
                file_path TEXT,
                symbol_name TEXT,
                chunk_type TEXT,
                start_line INTEGER,
                end_line INTEGER,
                code TEXT,
                docstring TEXT,
                route_info TEXT,
                module_name TEXT,
                qualified_name TEXT
            );

            CREATE TABLE IF NOT EXISTS calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                caller_id TEXT,
                caller_symbol TEXT,
                callee_name TEXT,
                callee_qualified TEXT,
                is_dynamic INTEGER DEFAULT 0,
                dynamic_expr TEXT DEFAULT '',
                source_file TEXT,
                FOREIGN KEY(caller_id) REFERENCES nodes(id)
            );

            CREATE TABLE IF NOT EXISTS resolved_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                caller_id TEXT,
                caller_symbol TEXT,
                caller_file TEXT,
                caller_module TEXT,
                caller_qualified TEXT,
                callee_id TEXT,
                callee_symbol TEXT,
                callee_file TEXT,
                callee_qualified TEXT,
                call_name TEXT,
                resolution_type TEXT,
                confidence REAL,
                is_dynamic INTEGER DEFAULT 0,
                dynamic_expr TEXT DEFAULT '',
                FOREIGN KEY(caller_id) REFERENCES nodes(id)
            );

            CREATE INDEX IF NOT EXISTS idx_nodes_sym ON nodes(symbol_name);
            CREATE INDEX IF NOT EXISTS idx_nodes_qual ON nodes(qualified_name);
            CREATE INDEX IF NOT EXISTS idx_nodes_file ON nodes(file_path);
            CREATE INDEX IF NOT EXISTS idx_nodes_line ON nodes(file_path, start_line, end_line);
            CREATE INDEX IF NOT EXISTS idx_nodes_route ON nodes(route_info);
            CREATE INDEX IF NOT EXISTS idx_calls_callee ON calls(callee_name);
            CREATE INDEX IF NOT EXISTS idx_calls_callee_qual ON calls(callee_qualified);
            CREATE INDEX IF NOT EXISTS idx_calls_caller ON calls(caller_symbol);
            CREATE INDEX IF NOT EXISTS idx_calls_caller_id ON calls(caller_id);

            CREATE INDEX IF NOT EXISTS idx_resolved_callee_sym ON resolved_edges(callee_symbol);
            CREATE INDEX IF NOT EXISTS idx_resolved_callee_qual ON resolved_edges(callee_qualified);
            CREATE INDEX IF NOT EXISTS idx_resolved_callee_id ON resolved_edges(callee_id);
            CREATE INDEX IF NOT EXISTS idx_resolved_caller_sym ON resolved_edges(caller_symbol);
            CREATE INDEX IF NOT EXISTS idx_resolved_caller_id ON resolved_edges(caller_id);
            CREATE INDEX IF NOT EXISTS idx_resolved_caller_file ON resolved_edges(caller_file);
            CREATE INDEX IF NOT EXISTS idx_resolved_callee_file ON resolved_edges(callee_file);
            CREATE INDEX IF NOT EXISTS idx_resolved_call_name ON resolved_edges(call_name);

            -- 复合覆盖索引：get_callers BFS 最常见访问模式 (callee_id IN (...) ORDER BY confidence DESC)
            CREATE INDEX IF NOT EXISTS idx_resolved_callee_id_conf
                ON resolved_edges(callee_id, confidence DESC, resolution_type, caller_id);
            -- 复合覆盖索引：get_callees BFS 最常见访问模式 (caller_id = ? ORDER BY confidence DESC)
            CREATE INDEX IF NOT EXISTS idx_resolved_caller_id_conf
                ON resolved_edges(caller_id, confidence DESC, resolution_type, callee_id);

            -- FTS5 Full-Text Search Virtual Table across code chunks (zero RAM, high-performance BM25 ranking)
            CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
                symbol_name,
                qualified_name,
                docstring,
                code,
                content='nodes',
                content_rowid='rowid',
                tokenize='unicode61'
            );

            CREATE TRIGGER IF NOT EXISTS nodes_ai AFTER INSERT ON nodes BEGIN
                INSERT INTO nodes_fts(rowid, symbol_name, qualified_name, docstring, code)
                VALUES (new.rowid, new.symbol_name, new.qualified_name, new.docstring, new.code);
            END;

            CREATE TRIGGER IF NOT EXISTS nodes_ad AFTER DELETE ON nodes BEGIN
                INSERT INTO nodes_fts(nodes_fts, rowid, symbol_name, qualified_name, docstring, code)
                VALUES('delete', old.rowid, old.symbol_name, old.qualified_name, old.docstring, old.code);
            END;

            CREATE TRIGGER IF NOT EXISTS nodes_au AFTER UPDATE ON nodes BEGIN
                INSERT INTO nodes_fts(nodes_fts, rowid, symbol_name, qualified_name, docstring, code)
                VALUES('delete', old.rowid, old.symbol_name, old.qualified_name, old.docstring, old.code);
                INSERT INTO nodes_fts(rowid, symbol_name, qualified_name, docstring, code)
                VALUES (new.rowid, new.symbol_name, new.qualified_name, new.docstring, new.code);
            END;
        """)

        try:
            n_row = conn.execute("SELECT count(*) as c FROM nodes").fetchone()
            if n_row and n_row["c"] > 0:
                f_row = conn.execute("SELECT count(*) as c FROM nodes_fts").fetchone()
                if f_row and f_row["c"] == 0:
                    conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild');")
        except Exception:
            pass

        conn.commit()

    def _get_query_cache(self, query_type: str, cache_key: str) -> Optional[Dict[str, Any]]:
        """Retrieve pre-computed query results from SQLite cache (<5ms response)"""
        try:
            conn = self._get_db()
            row = conn.execute(
                "SELECT result_json FROM graph_query_cache WHERE query_type = ? AND cache_key = ?",
                (query_type, cache_key),
            ).fetchone()
            if row and row["result_json"]:
                return json.loads(row["result_json"])
        except Exception:
            pass
        return None

    def _set_query_cache(self, query_type: str, cache_key: str, data: Dict[str, Any]):
        """Persist computed query results into SQLite cache"""
        try:
            conn = self._get_db()
            conn.execute(
                "INSERT OR REPLACE INTO graph_query_cache (query_type, cache_key, result_json, created_at) VALUES (?, ?, ?, ?)",
                (query_type, cache_key, json.dumps(data, ensure_ascii=False), time.time()),
            )
            conn.commit()
        except Exception:
            pass

    def _clear_query_cache(self):
        """Invalidate query cache when codebase is indexed or modified"""
        try:
            conn = self._get_db()
            conn.execute("DELETE FROM graph_query_cache;")
            conn.commit()
        except Exception:
            pass

    def search_fts(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """Fast BM25 keyword & identifier search across all indexed code chunks via SQLite FTS5 and CJK matching"""
        if not self.load():
            return []

        conn = self._get_db()
        results: List[Dict[str, Any]] = []
        seen_ids = set()

        # 1. 提取英数标识符分词执行 SQLite FTS5 BM25 检索
        clean_tokens = [re.sub(r'[^a-zA-Z0-9_]', '', t).strip() for t in query.split()]
        clean_tokens = [t for t in clean_tokens if t]
        if clean_tokens:
            fts_query = " OR ".join(f'"{t}"*' for t in clean_tokens)
            try:
                cursor = conn.execute(
                    """
                    SELECT 
                        n.id, n.file_path, n.symbol_name, n.chunk_type, n.start_line, n.end_line,
                        n.code, n.docstring, n.route_info, n.module_name, n.qualified_name,
                        bm25(nodes_fts) AS rank
                    FROM nodes_fts f
                    JOIN nodes n ON f.rowid = n.rowid
                    WHERE nodes_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (fts_query, top_k),
                )
                rows = cursor.fetchall()
                for r in rows:
                    cid = str(r["id"])
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)
                    code_lines = (r["code"] or "").splitlines()
                    preview = "\n".join(code_lines[:15]) + ("\n..." if len(code_lines) > 15 else "")
                    score = round(min(0.99, abs(float(r["rank"])) / (1.0 + abs(float(r["rank"])))), 4)
                    results.append(
                        {
                            "id": r["id"],
                            "file_path": r["file_path"],
                            "symbol_name": r["symbol_name"],
                            "symbol_type": r["chunk_type"],
                            "start_line": r["start_line"],
                            "end_line": r["end_line"],
                            "code": r["code"],
                            "code_preview": preview,
                            "docstring": r["docstring"] or "",
                            "route_info": r["route_info"] or "",
                            "score": score,
                            "source": "sqlite_fts5",
                        }
                    )
            except Exception:
                pass

        # 2. 提取中文字符串执行 SQLite 原生 LIKE 子串匹配 (解决 CJK 在 FTS5 unicode61 分词下的漏检)
        cjk_tokens = re.findall(r"[\u4e00-\u9fff]{1,}", query)
        if cjk_tokens:
            try:
                clauses = []
                params = []
                for tok in cjk_tokens[:4]:
                    clauses.append("(n.code LIKE ? OR n.docstring LIKE ? OR n.symbol_name LIKE ?)")
                    params.extend([f"%{tok}%", f"%{tok}%", f"%{tok}%"])
                cjk_sql = f"""
                    SELECT 
                        n.id, n.file_path, n.symbol_name, n.chunk_type, n.start_line, n.end_line,
                        n.code, n.docstring, n.route_info, n.module_name, n.qualified_name
                    FROM nodes n
                    WHERE {" OR ".join(clauses)}
                    LIMIT ?
                """
                cjk_cursor = conn.execute(cjk_sql, (*params, top_k))
                for r in cjk_cursor.fetchall():
                    cid = str(r["id"])
                    if cid in seen_ids:
                        continue
                    seen_ids.add(cid)
                    code_lines = (r["code"] or "").splitlines()
                    preview = "\n".join(code_lines[:15]) + ("\n..." if len(code_lines) > 15 else "")
                    results.append(
                        {
                            "id": r["id"],
                            "file_path": r["file_path"],
                            "symbol_name": r["symbol_name"],
                            "symbol_type": r["chunk_type"],
                            "start_line": r["start_line"],
                            "end_line": r["end_line"],
                            "code": r["code"],
                            "code_preview": preview,
                            "docstring": r["docstring"] or "",
                            "route_info": r["route_info"] or "",
                            "score": 0.88,
                            "source": "sqlite_cjk_match",
                        }
                    )
            except Exception:
                pass

        return results

    def _sync_from_lancedb(self) -> bool:
        """从 LanceDB 表 code_chunks 流式读取并构建 SQLite 图谱索引"""
        try:
            import lancedb
            db = lancedb.connect(str(self.db_path))
            tbl = db.open_table("code_chunks")
        except Exception:
            return False

        arrow_tbl = tbl.to_arrow()
        total_rows = arrow_tbl.num_rows
        chunks = []
        for i in range(total_rows):
            chunks.append({col: arrow_tbl.column(col)[i].as_py() for col in arrow_tbl.schema.names})
        return self.build_from_chunks(chunks)

    def init_clean_graph(self):
        """初始化图数据库并清空历史表，准备进行增量/流式构建"""
        conn = self._get_db()
        self._init_sqlite_schema(conn)
        conn.execute("DELETE FROM resolved_queries;")
        conn.execute("DELETE FROM resolved_edges;")
        conn.execute("DELETE FROM calls;")
        conn.execute("DELETE FROM nodes;")
        self._clear_query_cache()
        conn.commit()

    def stream_insert_chunks(self, chunks: Sequence[Any]):
        """流式分批写入节点到 SQLite (不驻留全量列表，毫秒级流式入库)"""
        conn = self._get_db()
        nodes_to_insert = []
        calls_to_insert = []

        for c in chunks:
            if isinstance(c, dict):
                node_id = str(c.get("id", ""))
                file_path = str(c.get("file_path", ""))
                sym_name = str(c.get("symbol_name", ""))
                chunk_type = str(c.get("chunk_type", ""))
                start_line = int(c.get("start_line", 1))
                end_line = int(c.get("end_line", 1))
                code = str(c.get("code", ""))
                docstring = str(c.get("docstring", "") or "")
                route_info = str(c.get("route_info", "") or "")
                module_name = str(c.get("module_name", "") or "")
                qualified_name = str(c.get("qualified_name", "") or "")
                calls_raw = c.get("calls", "[]")
            else:
                node_id = str(getattr(c, "id", f"{getattr(c, 'file_path', '')}:{getattr(c, 'start_line', 1)}:{getattr(c, 'symbol_name', '')}"))
                file_path = str(getattr(c, "file_path", ""))
                sym_name = str(getattr(c, "symbol_name", ""))
                chunk_type = str(getattr(c, "chunk_type", ""))
                start_line = int(getattr(c, "start_line", 1))
                end_line = int(getattr(c, "end_line", 1))
                code = str(getattr(c, "code", ""))
                docstring = str(getattr(c, "docstring", "") or "")
                route_info = str(getattr(c, "route_info", "") or "")
                module_name = str(getattr(c, "module_name", "") or "")
                qualified_name = str(getattr(c, "qualified_name", "") or "")
                calls_raw = getattr(c, "calls", "[]")

            nodes_to_insert.append((
                node_id, file_path, sym_name, chunk_type, start_line, end_line,
                code, docstring, route_info, module_name, qualified_name
            ))

            try:
                calls_list = json.loads(calls_raw) if isinstance(calls_raw, str) else list(calls_raw)
            except Exception:
                calls_list = []

            for call_item in calls_list:
                call_str = str(call_item).strip()
                if not call_str:
                    continue
                is_dynamic = 0
                dynamic_expr = ""
                callee_name = call_str
                callee_qual = ""

                if call_str.startswith("dynamic:"):
                    is_dynamic = 1
                    dynamic_expr = call_str[len("dynamic:"):].strip()
                    if dynamic_expr.startswith("getattr(") and ")" in dynamic_expr:
                        inner = dynamic_expr[len("getattr("):dynamic_expr.find(")")]
                        parts = [p.strip() for p in inner.split(",", 1)]
                        if len(parts) == 2:
                            callee_name = parts[1]
                    elif dynamic_expr.startswith("subscript(") and ")" in dynamic_expr:
                        inner = dynamic_expr[len("subscript("):dynamic_expr.find(")")]
                        parts = [p.strip() for p in inner.split(",", 1)]
                        if len(parts) == 2:
                            callee_name = parts[1]
                    elif dynamic_expr.startswith("index(") and ")" in dynamic_expr:
                        inner = dynamic_expr[len("index("):dynamic_expr.find(")")]
                        parts = [p.strip() for p in inner.split(",", 1)]
                        if len(parts) == 2:
                            callee_name = parts[1]
                elif call_str.startswith("<dynamic:"):
                    is_dynamic = 1

                calls_to_insert.append((
                    node_id, sym_name, callee_name, callee_qual, is_dynamic, dynamic_expr, file_path
                ))

        if nodes_to_insert:
            conn.executemany(
                "INSERT OR REPLACE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                nodes_to_insert
            )
        if calls_to_insert:
            conn.executemany(
                "INSERT INTO calls (caller_id, caller_symbol, callee_name, callee_qualified, is_dynamic, dynamic_expr, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
                calls_to_insert
            )
        conn.commit()

    def finalize_graph(self):
        """流式构建全部完成后记录元数据并提交"""
        conn = self._get_db()
        try:
            conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild');")
        except Exception:
            pass
        self._clear_query_cache()
        conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (INDEX_SCHEMA_VERSION,))
        conn.commit()

    def build_from_chunks(self, chunks: Sequence[Any]) -> bool:
        """从内存中的 CodeChunk 列表直接构建 SQLite 图谱索引与解析边（预构建消除首次查询延迟）"""
        conn = self._get_db()
        self._init_sqlite_schema(conn)

        # 清理旧数据，保证一致性
        conn.execute("DELETE FROM resolved_queries;")
        conn.execute("DELETE FROM resolved_edges;")
        conn.execute("DELETE FROM calls;")
        conn.execute("DELETE FROM nodes;")
        self._clear_query_cache()

        batch_size = 500
        nodes_to_insert = []
        calls_to_insert = []

        for c in chunks:
            if isinstance(c, dict):
                node_id = str(c.get("id", ""))
                file_path = str(c.get("file_path", ""))
                sym_name = str(c.get("symbol_name", ""))
                chunk_type = str(c.get("chunk_type", ""))
                start_line = int(c.get("start_line", 1))
                end_line = int(c.get("end_line", 1))
                code = str(c.get("code", ""))
                docstring = str(c.get("docstring", "") or "")
                route_info = str(c.get("route_info", "") or "")
                module_name = str(c.get("module_name", "") or "")
                qualified_name = str(c.get("qualified_name", "") or "")
                calls_raw = c.get("calls", "[]")
            else:
                node_id = str(getattr(c, "id", f"{getattr(c, 'file_path', '')}:{getattr(c, 'start_line', 1)}:{getattr(c, 'symbol_name', '')}"))
                file_path = str(getattr(c, "file_path", ""))
                sym_name = str(getattr(c, "symbol_name", ""))
                chunk_type = str(getattr(c, "chunk_type", ""))
                start_line = int(getattr(c, "start_line", 1))
                end_line = int(getattr(c, "end_line", 1))
                code = str(getattr(c, "code", ""))
                docstring = str(getattr(c, "docstring", "") or "")
                route_info = str(getattr(c, "route_info", "") or "")
                module_name = str(getattr(c, "module_name", "") or "")
                qualified_name = str(getattr(c, "qualified_name", "") or "")
                calls_raw = getattr(c, "calls", "[]")

            nodes_to_insert.append((
                node_id, file_path, sym_name, chunk_type, start_line, end_line,
                code, docstring, route_info, module_name, qualified_name
            ))

            try:
                calls_list = json.loads(calls_raw) if isinstance(calls_raw, str) else list(calls_raw)
            except Exception:
                calls_list = []

            for call_item in calls_list:
                call_str = str(call_item).strip()
                if not call_str:
                    continue
                is_dynamic = 0
                dynamic_expr = ""
                callee_name = call_str
                callee_qual = ""

                if call_str.startswith("dynamic:"):
                    is_dynamic = 1
                    dynamic_expr = call_str[len("dynamic:"):].strip()
                    if dynamic_expr.startswith("getattr(") and ")" in dynamic_expr:
                        inner = dynamic_expr[len("getattr("):dynamic_expr.find(")")]
                        parts = [p.strip() for p in inner.split(",", 1)]
                        if len(parts) == 2:
                            callee_name = parts[1]
                    elif dynamic_expr.startswith("subscript(") and ")" in dynamic_expr:
                        inner = dynamic_expr[len("subscript("):dynamic_expr.find(")")]
                        parts = [p.strip() for p in inner.split(",", 1)]
                        if len(parts) == 2:
                            callee_name = parts[1]
                    elif dynamic_expr.startswith("index(") and ")" in dynamic_expr:
                        inner = dynamic_expr[len("index("):dynamic_expr.find(")")]
                        parts = [p.strip() for p in inner.split(",", 1)]
                        if len(parts) == 2:
                            callee_name = parts[1]
                elif call_str.startswith("<dynamic:"):
                    is_dynamic = 1
                    dynamic_expr = call_str
                    callee_name = call_str
                else:
                    if "." in call_str:
                        callee_qual = call_str
                        callee_name = call_str.split(".")[-1]
                    else:
                        callee_name = call_str

                calls_to_insert.append((
                    node_id, sym_name, callee_name, callee_qual, is_dynamic, dynamic_expr, file_path
                ))

            if len(nodes_to_insert) >= batch_size:
                conn.executemany(
                    "INSERT OR REPLACE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    nodes_to_insert
                )
                nodes_to_insert.clear()

            if len(calls_to_insert) >= batch_size:
                conn.executemany(
                    "INSERT INTO calls (caller_id, caller_symbol, callee_name, callee_qualified, is_dynamic, dynamic_expr, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    calls_to_insert
                )
                calls_to_insert.clear()

        if nodes_to_insert:
            conn.executemany(
                "INSERT OR REPLACE INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                nodes_to_insert
            )
        if calls_to_insert:
            conn.executemany(
                "INSERT INTO calls (caller_id, caller_symbol, callee_name, callee_qualified, is_dynamic, dynamic_expr, source_file) VALUES (?, ?, ?, ?, ?, ?, ?)",
                calls_to_insert
            )

        # 仅当显式提供了调用边（如全量带调用的单元测试）时执行全局遍历；全库轻量索引时跳过，依赖按需秒级解析
        if calls_to_insert:
            self._resolve_all_edges(conn)

        try:
            conn.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild');")
        except Exception:
            pass

        conn.execute("INSERT OR REPLACE INTO meta VALUES ('schema_version', ?)", (INDEX_SCHEMA_VERSION,))
        conn.commit()
        return True

    def _resolve_all_edges(self, conn: sqlite3.Connection):
        """Pass 2: 全局符号解析与拓扑链接 (Global Resolution Pass)
        在所有文件完成 Stage 1 纯物理提取后，基于跨文件符号表与作用域层次执行二次匹配，
        生成高确信度的 resolved_edges 确定性边表，彻底根除跨文件调用串线与盲目推测。
        """
        conn.execute("DELETE FROM resolved_edges;")

        cursor = conn.execute("SELECT id, symbol_name, chunk_type, file_path, module_name, qualified_name FROM nodes")
        all_node_rows = cursor.fetchall()

        by_id: Dict[str, sqlite3.Row] = {}
        by_qual: Dict[str, List[sqlite3.Row]] = defaultdict(list)
        by_sym: Dict[str, List[sqlite3.Row]] = defaultdict(list)
        by_file_sym: Dict[Tuple[str, str], List[sqlite3.Row]] = defaultdict(list)
        by_dir_sym: Dict[Tuple[str, str], List[sqlite3.Row]] = defaultdict(list)
        by_mod_sym: Dict[Tuple[str, str], List[sqlite3.Row]] = defaultdict(list)

        for r in all_node_rows:
            by_id[r["id"]] = r
            sym = r["symbol_name"]
            qual = r["qualified_name"]
            fpath = r["file_path"]
            fdir = Path(fpath).parent.as_posix()
            mod = r["module_name"]

            if qual:
                by_qual[qual].append(r)
            if sym:
                by_sym[sym].append(r)
                by_file_sym[(fpath, sym)].append(r)
                by_dir_sym[(fdir, sym)].append(r)
                if mod:
                    by_mod_sym[(mod, sym)].append(r)

            if "." in sym:
                short_name = sym.split(".")[-1]
                by_sym[short_name].append(r)
                by_file_sym[(fpath, short_name)].append(r)
                by_dir_sym[(fdir, short_name)].append(r)
                if mod:
                    by_mod_sym[(mod, short_name)].append(r)

        by_qual_tail: Dict[str, List[Tuple[str, sqlite3.Row]]] = defaultdict(list)
        for qual, qnodes in by_qual.items():
            tail = qual.split(".")[-1]
            by_qual_tail[tail].append((qual, qnodes[0]))

        raw_calls_cursor = conn.execute("""
            SELECT DISTINCT
                c.caller_id, c.caller_symbol, c.source_file,
                n.module_name as caller_module, n.qualified_name as caller_qualified,
                c.callee_name, c.callee_qualified, c.is_dynamic, c.dynamic_expr
            FROM calls c
            JOIN nodes n ON c.caller_id = n.id
        """)
        raw_calls = raw_calls_cursor.fetchall()

        edges_to_insert = []
        seen_edges = set()
        batch_size = 5000

        for call in raw_calls:
            caller_id = call["caller_id"]
            caller_sym = call["caller_symbol"]
            caller_file = call["source_file"]
            caller_dir = Path(caller_file).parent.as_posix()
            caller_mod = call["caller_module"] or ""
            caller_qual = call["caller_qualified"] or ""
            c_name = call["callee_name"]
            c_qual = call["callee_qualified"] or ""
            is_dyn = call["is_dynamic"]
            dyn_expr = call["dynamic_expr"] or ""

            target_node: Optional[sqlite3.Row] = None
            res_type = "UNRESOLVED"
            conf = 0.0

            # Rule 1: 跨文件/模块完整限定名精确匹配 (EXACT_QUALIFIED)
            if c_qual and c_qual in by_qual:
                candidates = by_qual[c_qual]
                if len(candidates) == 1:
                    target_node = candidates[0]
                    res_type = "EXACT_QUALIFIED"
                    conf = 1.0
                else:
                    same_file = [c for c in candidates if c["file_path"] == caller_file]
                    if len(same_file) == 1:
                        target_node = same_file[0]
                        res_type = "EXACT_QUALIFIED"
                        conf = 0.98
                    else:
                        same_dir = [c for c in candidates if Path(c["file_path"]).parent.as_posix() == caller_dir]
                        if len(same_dir) == 1:
                            target_node = same_dir[0]
                            res_type = "EXACT_QUALIFIED"
                            conf = 0.95
                        else:
                            non_test = [c for c in candidates if "test" not in c["file_path"].lower()]
                            target_node = non_test[0] if non_test else candidates[0]
                            res_type = "EXACT_QUALIFIED"
                            conf = 0.90

            if not target_node and c_qual:
                c_tail = c_qual.split(".")[-1]
                for qk, qnode in by_qual_tail.get(c_tail, []):
                    if qk.endswith(c_qual) or c_qual.endswith(qk):
                        target_node = qnode
                        res_type = "EXACT_QUALIFIED"
                        conf = 0.95
                        break

            # Rule 1.5: 跨包重导出与子模块限定匹配 (PACKAGE_EXPORT)
            # 例如: 调用方 `from fastapi import Depends` -> c_qual = "fastapi.Depends"
            # 定义位于: `fastapi/params.py` -> qk = "fastapi.params.Depends"
            if not target_node and c_qual and "." in c_qual:
                pkg_prefix = c_qual.split(".")[0]
                leaf_name = c_qual.split(".")[-1]
                pkg_cands = []
                for qk, qnode in by_qual_tail.get(leaf_name, []):
                    if qk.startswith(pkg_prefix + ".") and (qnode["chunk_type"] in ("function", "class", "method", "struct", "interface") or not qnode["chunk_type"]):
                        pkg_cands.append(qnode)

                if pkg_cands:
                    non_test = [n for n in pkg_cands if "test" not in n["file_path"].lower()]
                    valid_cands = non_test if non_test else pkg_cands
                    if len(valid_cands) == 1:
                        target_node = valid_cands[0]
                        res_type = "PACKAGE_EXPORT"
                        conf = 0.95
                    else:
                        same_dir = [n for n in valid_cands if Path(n["file_path"]).parent.as_posix() == caller_dir]
                        if same_dir:
                            target_node = same_dir[0]
                            res_type = "PACKAGE_EXPORT"
                            conf = 0.95
                        else:
                            target_node = valid_cands[0]
                            res_type = "PACKAGE_EXPORT"
                            conf = 0.90

            # Rule 2: 同文件内作用域匹配 (SAME_FILE)
            if not target_node and c_name:
                same_file_cands = by_file_sym.get((caller_file, c_name), [])
                if same_file_cands:
                    target_node = same_file_cands[0]
                    res_type = "SAME_FILE"
                    conf = 1.0
                elif "." in caller_sym:
                    cls_prefix = caller_sym.split(".")[0]
                    method_key = f"{cls_prefix}.{c_name}"
                    same_cls_cands = by_file_sym.get((caller_file, method_key), [])
                    if same_cls_cands:
                        target_node = same_cls_cands[0]
                        res_type = "SAME_FILE"
                        conf = 1.0

            # Rule 3: 同目录/同包就近匹配 (SAME_DIR)
            if not target_node and c_name:
                dir_cands = by_dir_sym.get((caller_dir, c_name), [])
                if len(dir_cands) == 1:
                    target_node = dir_cands[0]
                    res_type = "SAME_DIR"
                    conf = 0.92
                elif len(dir_cands) > 1:
                    non_test = [n for n in dir_cands if "test" not in n["file_path"].lower()]
                    target_node = non_test[0] if non_test else dir_cands[0]
                    res_type = "SAME_DIR"
                    conf = 0.88

            # Rule 4: 同模块命名空间就近匹配 (SAME_MODULE)
            if not target_node and c_name and caller_mod:
                mod_cands = by_mod_sym.get((caller_mod, c_name), [])
                if len(mod_cands) == 1:
                    target_node = mod_cands[0]
                    res_type = "SAME_MODULE"
                    conf = 0.88
                elif len(mod_cands) > 1:
                    non_test = [n for n in mod_cands if "test" not in n["file_path"].lower()]
                    target_node = non_test[0] if non_test else mod_cands[0]
                    res_type = "SAME_MODULE"
                    conf = 0.82

            # Rule 5: 动态调用推断 (DYNAMIC)
            if not target_node and is_dyn and c_name:
                cands = by_sym.get(c_name, [])
                if cands:
                    sf = [n for n in cands if n["file_path"] == caller_file]
                    sd = [n for n in cands if Path(n["file_path"]).parent.as_posix() == caller_dir]
                    if sf:
                        target_node = sf[0]
                    elif sd:
                        target_node = sd[0]
                    else:
                        non_test = [n for n in cands if "test" not in n["file_path"].lower()]
                        target_node = non_test[0] if non_test else cands[0]
                    res_type = "DYNAMIC"
                    conf = 0.75

            # Rule 6: 全局符号消歧匹配 (GLOBAL_UNIQUE vs AMBIGUOUS)
            if not target_node and c_name:
                global_cands = by_sym.get(c_name, [])
                if len(global_cands) == 1:
                    target_node = global_cands[0]
                    res_type = "GLOBAL_UNIQUE"
                    conf = 0.85
                elif len(global_cands) > 1:
                    caller_is_test = "test" in caller_file.lower()
                    non_test = [n for n in global_cands if "test" not in n["file_path"].lower()]
                    cands_pool = global_cands if caller_is_test or not non_test else non_test

                    def_cands = [n for n in cands_pool if n["chunk_type"] in ("function", "class", "method", "struct", "interface")]
                    cands_pool = def_cands if def_cands else cands_pool

                    if len(cands_pool) == 1:
                        target_node = cands_pool[0]
                        res_type = "GLOBAL_UNIQUE"
                        conf = 0.82
                    else:
                        def _common_prefix_len(cand):
                            p1 = Path(caller_file).parts
                            p2 = Path(cand["file_path"]).parts
                            common = 0
                            for a, b in zip(p1, p2):
                                if a == b:
                                    common += 1
                                else:
                                    break
                            return common

                        cands_pool.sort(key=_common_prefix_len, reverse=True)
                        target_node = cands_pool[0]
                        res_type = "AMBIGUOUS"
                        conf = 0.65

            # Rule 7: 外部依赖或标准库调用 (EXTERNAL)
            if not target_node:
                res_type = "EXTERNAL"
                conf = 1.0
                callee_id = None
                callee_sym = c_name
                callee_file = None
                callee_qual = c_qual or c_name
            else:
                callee_id = target_node["id"]
                callee_sym = target_node["symbol_name"]
                callee_file = target_node["file_path"]
                callee_qual = target_node["qualified_name"] or target_node["symbol_name"]

            edge_key = (caller_id, callee_id, c_name, res_type, is_dyn)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            edges_to_insert.append((
                caller_id, caller_sym, caller_file, caller_mod, caller_qual,
                callee_id, callee_sym, callee_file, callee_qual, c_name,
                res_type, conf, is_dyn, dyn_expr
            ))

            if len(edges_to_insert) >= batch_size:
                conn.executemany("""
                    INSERT INTO resolved_edges (
                        caller_id, caller_symbol, caller_file, caller_module, caller_qualified,
                        callee_id, callee_symbol, callee_file, callee_qualified, call_name,
                        resolution_type, confidence, is_dynamic, dynamic_expr
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, edges_to_insert)
                edges_to_insert.clear()

        if edges_to_insert:
            conn.executemany("""
                INSERT INTO resolved_edges (
                    caller_id, caller_symbol, caller_file, caller_module, caller_qualified,
                    callee_id, callee_symbol, callee_file, callee_qualified, call_name,
                    resolution_type, confidence, is_dynamic, dynamic_expr
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, edges_to_insert)

        # 立即释放图解析阶段的大型内存结构，彻底杜绝内存驻留导致后续向量嵌入 OOM
        del all_node_rows
        del raw_calls
        edges_to_insert.clear()
        seen_edges.clear()
        by_id.clear()
        by_qual.clear()
        by_sym.clear()
        by_file_sym.clear()
        by_dir_sym.clear()
        by_mod_sym.clear()
        by_qual_tail.clear()
        import gc
        gc.collect()

    def _is_query_resolved(self, query_type: str, symbol_name: str) -> bool:
        try:
            conn = self._get_db()
            row = conn.execute(
                "SELECT 1 FROM resolved_queries WHERE query_type = ? AND symbol_name = ?",
                (query_type, symbol_name),
            ).fetchone()
            return row is not None
        except Exception:
            return False

    def _mark_query_resolved(self, query_type: str, symbol_name: str):
        try:
            conn = self._get_db()
            conn.execute(
                "INSERT OR REPLACE INTO resolved_queries VALUES (?, ?)",
                (query_type, symbol_name),
            )
            conn.commit()
        except Exception:
            pass

    def _extract_file_imports(self, file_path: str, lang: str) -> Optional[Any]:
        try:
            p = Path(file_path)
            full_path = p if p.is_absolute() else (self.repo_path / file_path)
            if not full_path.exists():
                return None
            source = full_path.read_bytes()
            parser = TreeSitterParser()
            ts_p = parser._parsers.get(lang)
            if not ts_p:
                return None
            tree = ts_p.parse(source)
            imports = parser._extract_imports(tree.root_node, source, lang)
            del tree
            return imports
        except Exception:
            return None

    def _resolve_callers_on_demand(self, symbol_name: str):
        """On-demand upstream caller topology resolution:
        Scans code with ripgrep and resolves enclosing callers via SQLite node ranges.
        """
        if self._is_query_resolved("callers", symbol_name):
            return
        self._mark_query_resolved("callers", symbol_name)

        bare_name = symbol_name.split(".")[-1].strip()
        if not bare_name:
            return

        conn = self._get_db()
        # 1. 查询目标符号在 nodes 中的所有候选定义
        cursor = conn.execute(
            """
            SELECT id, symbol_name, qualified_name, file_path, start_line, end_line, module_name
            FROM nodes
            WHERE symbol_name = ? OR symbol_name LIKE ? OR qualified_name = ? OR qualified_name LIKE ?
            """,
            (symbol_name, f"%.{bare_name}", symbol_name, f"%.{bare_name}"),
        )
        def_rows = cursor.fetchall()
        def_ids = {r["id"] for r in def_rows}
        def_locs = set()
        for r in def_rows:
            fp = r["file_path"].replace("\\", "/")
            sl = r["start_line"]
            def_locs.add((fp, sl))
            try:
                rel_p = str(Path(fp).relative_to(self.repo_path)).replace("\\", "/")
                def_locs.add((rel_p, sl))
            except Exception:
                pass
            try:
                abs_p = str((self.repo_path / fp).resolve()).replace("\\", "/")
                def_locs.add((abs_p, sl))
            except Exception:
                pass

        # 2. 调用 ripgrep 在仓库中高速搜索 bare_name
        rg_engine = ExactSearchEngine(self.repo_path)
        pattern = r"\b" + re.escape(bare_name) + r"\b"
        search_res = rg_engine.search(pattern, is_regex=True, case_sensitive=True, max_results=500)
        matches = list(search_res.get("matches", []))
        if not matches:
            return

        edges_to_insert = []
        calls_to_insert = []
        seen_edges = set()

        def _match_path(p1: str, p2: str) -> bool:
            if not p1 or not p2:
                return False
            n1 = p1.replace("\\", "/").rstrip("/")
            n2 = p2.replace("\\", "/").rstrip("/")
            return n1 == n2 or n1.endswith("/" + n2) or n2.endswith("/" + n1)

        # 检查是否有 import alias (例如: from pkg_b.service import handle as handle_b)
        extra_matches = []
        for m in matches:
            line_txt = m.line_content
            if "import " in line_txt and " as " in line_txt:
                alias_m = re.search(r'\b(?:import\s+[^,;]*?\b' + re.escape(bare_name) + r'|from\s+[\w\.]+\s+import\s+[^,;]*?\b' + re.escape(bare_name) + r')\s+as\s+([a-zA-Z_]\w*)', line_txt)
                if alias_m:
                    alias_name = alias_m.group(1)
                    alias_res = rg_engine.search(r"\b" + re.escape(alias_name) + r"\b", is_regex=True, case_sensitive=True, file_glob=f"*{Path(m.file_path).name}", max_results=50)
                    for am in alias_res.get("matches", []):
                        if am.file_path == m.file_path and am.line_number != m.line_number:
                            extra_matches.append(am)
        matches.extend(extra_matches)

        file_imports_cache: Dict[str, Any] = {}
        caller_text_cache: Dict[str, str] = {}
        caller_node_cache: Dict[Tuple[str, int], Any] = {}

        for m in matches:
            f_path = m.file_path.replace("\\", "/")
            l_num = m.line_number

            # 排除定义点自身所在行
            if (f_path, l_num) in def_locs:
                continue

            # 3. 在 SQLite 中二分区间查出当前行归属的外层 caller node (使用 B-Tree 索引快速定位)
            loc_key = (f_path, l_num)
            if loc_key in caller_node_cache:
                caller_node = caller_node_cache[loc_key]
            else:
                f_abs = str((self.repo_path / f_path).resolve()).replace("\\", "/")
                caller_node = conn.execute(
                    """
                    SELECT id, symbol_name, chunk_type, file_path, start_line, end_line, module_name, qualified_name, code
                    FROM nodes
                    WHERE file_path IN (?, ?) AND start_line <= ? AND end_line >= ?
                    ORDER BY (end_line - start_line) ASC
                    LIMIT 1
                    """,
                    (f_path, f_abs, l_num, l_num),
                ).fetchone()
                caller_node_cache[loc_key] = caller_node

            if not caller_node:
                continue

            # 若自身调用自身定义行，跳过
            if caller_node["id"] in def_ids and caller_node["start_line"] == l_num:
                continue

            caller_id = caller_node["id"]
            caller_sym = caller_node["symbol_name"]
            caller_file = caller_node["file_path"]
            caller_mod = caller_node["module_name"] or ""
            caller_qual = caller_node["qualified_name"] or caller_sym

            # 4. 拓扑目标消歧
            target_node = None
            res_type = "GLOBAL_UNIQUE"
            conf = 0.85

            if def_rows:
                # 4.1 同文件就近
                same_f = [d for d in def_rows if _match_path(d["file_path"], caller_file)]
                if same_f:
                    target_node = same_f[0]
                    res_type = "SAME_FILE"
                    conf = 0.98
                else:
                    # 4.2 检查调用文件是否显式导入特定候选模块
                    if caller_file not in file_imports_cache:
                        ext = Path(caller_file).suffix.lower()
                        lang = EXTENSION_LANG_MAP.get(ext, "python")
                        file_imports_cache[caller_file] = self._extract_file_imports(caller_file, lang)
                    file_imports = file_imports_cache[caller_file]

                    matched_import_node = None
                    if file_imports:
                        for d in def_rows:
                            d_mod = d["module_name"] or ""
                            d_q = d["qualified_name"] or ""
                            if (d_mod and d_mod in file_imports.modules) or any(d_q == sym_q for sym_q in file_imports.symbols.values()):
                                matched_import_node = d
                                break
                    if not matched_import_node:
                        if caller_file not in caller_text_cache:
                            try:
                                cf_p = Path(caller_file)
                                full_f = cf_p if cf_p.is_absolute() else (self.repo_path / caller_file)
                                caller_text_cache[caller_file] = full_f.read_text(encoding="utf-8", errors="replace")
                            except Exception:
                                caller_text_cache[caller_file] = ""
                        caller_text = caller_text_cache[caller_file]

                        for d in def_rows:
                            d_mod = d["module_name"] or ""
                            if d_mod and (f"import {d_mod}" in caller_text or f"from {d_mod}" in caller_text):
                                matched_import_node = d
                                break

                    if matched_import_node:
                        target_node = matched_import_node
                        res_type = "EXACT_QUALIFIED"
                        conf = 0.95
                    else:
                        # 4.3 同目录就近
                        caller_dir = Path(caller_file).parent.as_posix()
                        same_d = [d for d in def_rows if _match_path(Path(d["file_path"]).parent.as_posix(), caller_dir)]
                        if len(same_d) == 1:
                            target_node = same_d[0]
                            res_type = "SAME_DIR"
                            conf = 0.92
                        elif len(same_d) > 1:
                            target_node = same_d[0]
                            res_type = "PACKAGE_EXPORT"
                            conf = 0.90
                        else:
                            if len(def_rows) == 1:
                                target_node = def_rows[0]
                                res_type = "GLOBAL_UNIQUE"
                                conf = 0.85
                            else:
                                target_node = def_rows[0]
                                res_type = "AMBIGUOUS"
                                conf = 0.65
            else:
                res_type = "EXTERNAL"
                conf = 0.50

            callee_id = target_node["id"] if target_node else None
            callee_sym = target_node["symbol_name"] if target_node else bare_name
            callee_file = target_node["file_path"] if target_node else None
            callee_qual = target_node["qualified_name"] if target_node else bare_name

            edge_key = (caller_id, callee_id, bare_name)
            if edge_key in seen_edges:
                continue
            seen_edges.add(edge_key)

            edges_to_insert.append((
                caller_id, caller_sym, caller_file, caller_mod, caller_qual,
                callee_id, callee_sym, callee_file, callee_qual, bare_name,
                res_type, conf, 0, ""
            ))
            calls_to_insert.append((
                caller_id, caller_sym, bare_name, callee_qual, 0, "", caller_file
            ))

        if edges_to_insert:
            conn.executemany(
                """
                INSERT OR IGNORE INTO resolved_edges (
                    caller_id, caller_symbol, caller_file, caller_module, caller_qualified,
                    callee_id, callee_symbol, callee_file, callee_qualified, call_name,
                    resolution_type, confidence, is_dynamic, dynamic_expr
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                edges_to_insert,
            )
        if calls_to_insert:
            conn.executemany(
                """
                INSERT INTO calls (
                    caller_id, caller_symbol, callee_name, callee_qualified,
                    is_dynamic, dynamic_expr, source_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                calls_to_insert,
            )
        conn.commit()

    def _resolve_callees_on_demand(self, symbol_name: str):
        """On-demand downstream callee extraction and disambiguation:
        Parses function body on-the-fly with tree-sitter when queried.
        """
        if self._is_query_resolved("callees", symbol_name):
            return
        self._mark_query_resolved("callees", symbol_name)

        conn = self._get_db()
        cursor = conn.execute(
            "SELECT id, symbol_name, chunk_type, file_path, start_line, end_line, code, module_name, qualified_name FROM nodes WHERE symbol_name = ? OR qualified_name = ? LIMIT 10",
            (symbol_name, symbol_name),
        )
        nodes = cursor.fetchall()
        if not nodes and "." in symbol_name:
            short = symbol_name.split(".")[-1]
            cursor = conn.execute(
                "SELECT id, symbol_name, chunk_type, file_path, start_line, end_line, code, module_name, qualified_name FROM nodes WHERE symbol_name = ? OR symbol_name LIKE ? OR qualified_name LIKE ? LIMIT 10",
                (short, f"%.{short}", f"%.{symbol_name}"),
            )
            nodes = cursor.fetchall()
        elif not nodes:
            cursor = conn.execute(
                "SELECT id, symbol_name, chunk_type, file_path, start_line, end_line, code, module_name, qualified_name FROM nodes WHERE symbol_name LIKE ? OR qualified_name LIKE ? LIMIT 10",
                (f"%.{symbol_name}", f"%.{symbol_name}"),
            )
            nodes = cursor.fetchall()

        if not nodes:
            return

        parser = TreeSitterParser()
        edges_to_insert = []
        calls_to_insert = []
        seen_edges = set()

        for node in nodes:
            caller_id = node["id"]
            caller_sym = node["symbol_name"]
            caller_file = node["file_path"]
            caller_mod = node["module_name"] or ""
            caller_qual = node["qualified_name"] or caller_sym
            code = node["code"] or ""
            if not code.strip():
                continue

            ext = Path(caller_file).suffix.lower()
            lang = EXTENSION_LANG_MAP.get(ext, "python")

            # 提取文件级 import 用于跨文件别名/实例化解析
            file_imports = self._extract_file_imports(caller_file, lang)

            try:
                call_items = parser.extract_calls_from_code(
                    code, lang=lang, imports=file_imports, module_name=caller_mod
                )
            except Exception:
                call_items = []

            for call_str in call_items:
                call_str = str(call_str).strip()
                if not call_str:
                    continue

                is_dyn = 1 if ("<dynamic:" in call_str or call_str.startswith("dynamic:")) else 0
                dyn_expr = call_str if is_dyn else ""
                c_name = call_str.replace("<dynamic:", "").replace(">", "").strip() if is_dyn else call_str
                c_name_bare = c_name.split(".")[-1] if "." in c_name else c_name

                # 若调用的符号名是 import 别名 (例如 handle_b)，转换为导入的目标全限定名
                if file_imports and c_name_bare in file_imports.symbols:
                    mapped_qname = file_imports.symbols[c_name_bare]
                    c_name = mapped_qname
                    c_name_bare = mapped_qname.split(".")[-1]

                # 在 nodes 表中匹配被调用目标定义
                cands_cursor = conn.execute(
                    """
                    SELECT id, symbol_name, chunk_type, file_path, start_line, end_line, module_name, qualified_name, docstring
                    FROM nodes
                    WHERE symbol_name = ? OR qualified_name = ? OR symbol_name = ? OR symbol_name LIKE ? OR qualified_name LIKE ?
                    """,
                    (c_name_bare, c_name, c_name, f"%.{c_name_bare}", f"%.{c_name}"),
                )
                cands = cands_cursor.fetchall()

                target_node = None
                res_type = "GLOBAL_UNIQUE"
                conf = 0.85

                if cands:
                    # 1. 显式限定名匹配 (EXACT_QUALIFIED)
                    if "." in c_name:
                        exact_qual = [c for c in cands if c["qualified_name"] == c_name or c["symbol_name"] == c_name]
                        if exact_qual:
                            target_node = exact_qual[0]
                            res_type = "EXACT_QUALIFIED"
                            conf = 0.95

                    if not target_node and file_imports:
                        # 检查是否通过 imports 明确导入
                        for c in cands:
                            c_q = c["qualified_name"] or c["symbol_name"]
                            c_m = c["module_name"] or ""
                            if (c_m and c_m in file_imports.modules) or (c_name_bare in file_imports.symbols):
                                target_node = c
                                res_type = "EXACT_QUALIFIED"
                                conf = 0.95
                                break

                    if not target_node:
                        # 2. 同文件就近
                        same_f = [c for c in cands if c["file_path"] == caller_file]
                        if len(same_f) == 1:
                            target_node = same_f[0]
                            res_type = "SAME_FILE"
                            conf = 0.98
                        else:
                            # 3. 同目录
                            caller_dir = Path(caller_file).parent.as_posix()
                            same_d = [c for c in cands if Path(c["file_path"]).parent.as_posix() == caller_dir]
                            if len(same_d) == 1:
                                target_node = same_d[0]
                                res_type = "SAME_DIR"
                                conf = 0.92
                            elif len(same_d) > 1:
                                target_node = same_d[0]
                                res_type = "PACKAGE_EXPORT"
                                conf = 0.90
                            else:
                                if len(cands) == 1:
                                    target_node = cands[0]
                                    res_type = "GLOBAL_UNIQUE"
                                    conf = 0.85
                                else:
                                    target_node = cands[0]
                                    res_type = "AMBIGUOUS"
                                    conf = 0.65
                else:
                    res_type = "EXTERNAL"
                    conf = 0.50

                callee_id = target_node["id"] if target_node else None
                callee_sym = target_node["symbol_name"] if target_node else c_name_bare
                callee_file = target_node["file_path"] if target_node else None
                callee_qual = target_node["qualified_name"] if target_node else c_name

                edge_key = (caller_id, callee_id, c_name_bare, is_dyn)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)

                edges_to_insert.append((
                    caller_id, caller_sym, caller_file, caller_mod, caller_qual,
                    callee_id, callee_sym, callee_file, callee_qual, c_name_bare,
                    res_type, conf, is_dyn, dyn_expr
                ))
                calls_to_insert.append((
                    caller_id, caller_sym, c_name_bare, callee_qual, is_dyn, dyn_expr, caller_file
                ))

        if edges_to_insert:
            conn.executemany(
                """
                INSERT OR IGNORE INTO resolved_edges (
                    caller_id, caller_symbol, caller_file, caller_module, caller_qualified,
                    callee_id, callee_symbol, callee_file, callee_qualified, call_name,
                    resolution_type, confidence, is_dynamic, dynamic_expr
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                edges_to_insert,
            )
        if calls_to_insert:
            conn.executemany(
                """
                INSERT INTO calls (
                    caller_id, caller_symbol, callee_name, callee_qualified,
                    is_dynamic, dynamic_expr, source_file
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                calls_to_insert,
            )
        conn.commit()

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
        """重载 LanceDB 最新切片并重建 SQLite 拓扑图"""
        self._loaded = False
        self._close_db()
        return self._sync_from_lancedb()

    def load(self) -> bool:
        """按需连接 SQLite 代码图谱库，若不存在则首次自 LanceDB 索引同步"""
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

        if self.sqlite_path.exists():
            try:
                conn = self._get_db()
                self._init_sqlite_schema(conn)
                row_nodes = conn.execute("SELECT count(*) as c FROM nodes").fetchone()
                if row_nodes and row_nodes['c'] > 0:
                    self._loaded = True
                    return True
            except Exception:
                pass

        success = self._sync_from_lancedb()
        if success:
            self._loaded = True
        return success

    @property
    def nodes(self) -> Dict[str, List[SymbolNode]]:
        """向后兼容属性：若有代码直接访问 nodes 字典，按需从 SQLite 组装"""
        conn = self._get_db()
        cursor = conn.execute("SELECT * FROM nodes")
        result: Dict[str, List[SymbolNode]] = defaultdict(list)
        for r in cursor.fetchall():
            node = SymbolNode(
                id=r['id'],
                file_path=r['file_path'],
                symbol_name=r['symbol_name'],
                chunk_type=r['chunk_type'],
                start_line=r['start_line'],
                end_line=r['end_line'],
                code=r['code'],
                docstring=r['docstring'],
                route_info=r['route_info'],
                calls=[],
                module_name=r['module_name'],
                qualified_name=r['qualified_name'],
            )
            if node.qualified_name:
                result[node.qualified_name].append(node)
            if node.symbol_name:
                result[node.symbol_name].append(node)
            if "." in node.symbol_name:
                result[node.symbol_name.split(".")[-1]].append(node)
        return result

    @property
    def all_nodes(self) -> List[SymbolNode]:
        """向后兼容属性：若有代码直接访问 all_nodes，按需从 SQLite 组装"""
        conn = self._get_db()
        cursor = conn.execute("SELECT * FROM nodes")
        return [
            SymbolNode(
                id=r['id'],
                file_path=r['file_path'],
                symbol_name=r['symbol_name'],
                chunk_type=r['chunk_type'],
                start_line=r['start_line'],
                end_line=r['end_line'],
                code=r['code'],
                docstring=r['docstring'],
                route_info=r['route_info'],
                calls=[],
                module_name=r['module_name'],
                qualified_name=r['qualified_name'],
            )
            for r in cursor.fetchall()
        ]

    @property
    def routes_map(self) -> Dict[str, str]:
        conn = self._get_db()
        cursor = conn.execute("SELECT symbol_name, route_info FROM nodes WHERE route_info != ''")
        return {r['symbol_name']: r['route_info'] for r in cursor.fetchall()}

    def disambiguate_target(
        self, caller_file: str, called_name: str, candidates: List[SymbolNode]
    ) -> Tuple[Optional[SymbolNode], bool, List[str]]:
        """在存在同名符号时，按同限定名 > 同文件 > 同目录 > 唯一性 进行拓扑消歧，无法唯一消歧时标记 ambiguous"""
        if not candidates:
            return None, False, []
        if len(candidates) == 1:
            return candidates[0], False, []

        exact_qname = [n for n in candidates if n.qualified_name == called_name]
        if len(exact_qname) == 1:
            return exact_qname[0], False, []

        same_file = [n for n in candidates if n.file_path == caller_file]
        if len(same_file) == 1:
            return same_file[0], False, []

        caller_dir = Path(caller_file).parent.as_posix()
        same_dir = [n for n in candidates if Path(n.file_path).parent.as_posix() == caller_dir]
        if len(same_dir) == 1:
            return same_dir[0], False, []

        cand_strs = [f"{n.qualified_name or n.symbol_name} ({n.file_path}#L{n.start_line})" for n in candidates]
        return candidates[0], True, cand_strs

    def get_callers(self, symbol_name: str, limit: int = 30, offset: int = 0) -> Dict[str, Any]:
        """查询调用了指定符号的所有上游调用方 (Who calls X)
        
        Args:
            symbol_name: 目标符号名（支持限定名如 module.ClassName.method）
            limit: 最多返回条数，默认 30，设为 0 表示不限制
            offset: 分页偏移量，默认 0
        """
        if not self.load():
            return {
                "status": "error",
                "message": f"未找到代码库索引，请先对 {self.repo_path} 执行 index_codebase",
                "callers": [],
            }

        cache_key = f"{symbol_name}:{limit}:{offset}"
        cached = self._get_query_cache("callers", cache_key)
        if cached is not None:
            return cached

        conn = self._get_db()
        # On-demand scanning and disambiguating upstream callers
        self._resolve_callers_on_demand(symbol_name)

        bare_name = symbol_name.split(".")[-1]
        # 如果 symbol_name 包含限定名，则精确按限定名查找目标定义；否则按 symbol_name 查找全库对应定义
        if "." in symbol_name:
            cursor = conn.execute(
                "SELECT id, symbol_name, qualified_name, file_path, start_line FROM nodes WHERE qualified_name = ? OR symbol_name = ?",
                (symbol_name, symbol_name),
            )
            def_rows = cursor.fetchall()
            if not def_rows:
                cursor = conn.execute(
                    "SELECT id, symbol_name, qualified_name, file_path, start_line FROM nodes WHERE qualified_name LIKE ? OR symbol_name LIKE ?",
                    (f"%.{symbol_name}", f"%.{bare_name}"),
                )
                def_rows = cursor.fetchall()
        else:
            cursor = conn.execute(
                "SELECT id, symbol_name, qualified_name, file_path, start_line FROM nodes WHERE symbol_name = ? OR qualified_name = ?",
                (symbol_name, symbol_name),
            )
            def_rows = cursor.fetchall()
            if not def_rows:
                cursor = conn.execute(
                    "SELECT id, symbol_name, qualified_name, file_path, start_line FROM nodes WHERE symbol_name LIKE ? OR qualified_name LIKE ?",
                    (f"%.{bare_name}", f"%.{bare_name}"),
                )
                def_rows = cursor.fetchall()

        is_defined_in_repo = len(def_rows) > 0
        unique_defs = list({f"{r['file_path']}:{r['start_line']}": r for r in def_rows}.values())
        is_ambiguous_def = len(unique_defs) > 1
        ambig_defs = (
            [f"{r['qualified_name'] or r['symbol_name']} ({r['file_path']}#L{r['start_line']})" for r in unique_defs]
            if is_ambiguous_def
            else []
        )

        target_node_ids = [r['id'] for r in def_rows]

        # 按需从 SQLite resolved_edges 查询确定性拓扑调用者 (高确信度过滤)
        if target_node_ids:
            id_placeholders = ",".join("?" for _ in target_node_ids)
            query_sql = f"""
                SELECT DISTINCT
                    n.id, n.symbol_name, n.chunk_type, n.file_path, n.start_line, n.end_line,
                    n.route_info, n.docstring, n.code, e.is_dynamic, e.dynamic_expr,
                    e.resolution_type, e.confidence, e.callee_qualified
                FROM resolved_edges e
                JOIN nodes n ON e.caller_id = n.id
                WHERE (e.callee_id IN ({id_placeholders}) OR e.callee_qualified = ?)
                  AND e.confidence >= 0.25
                  AND e.resolution_type != 'EXTERNAL'
                ORDER BY e.confidence DESC, n.file_path, n.start_line
            """
            cursor = conn.execute(query_sql, target_node_ids + [symbol_name])
            caller_rows = cursor.fetchall()
        else:
            query_sql = """
                SELECT DISTINCT
                    n.id, n.symbol_name, n.chunk_type, n.file_path, n.start_line, n.end_line,
                    n.route_info, n.docstring, n.code, e.is_dynamic, e.dynamic_expr,
                    e.resolution_type, e.confidence, e.callee_qualified
                FROM resolved_edges e
                JOIN nodes n ON e.caller_id = n.id
                WHERE (e.callee_symbol = ? OR e.callee_qualified = ? OR e.call_name = ?)
                  AND e.resolution_type != 'EXTERNAL'
                ORDER BY e.confidence DESC, n.file_path, n.start_line
            """
            cursor = conn.execute(query_sql, (symbol_name, symbol_name, bare_name))
            caller_rows = cursor.fetchall()

        matched_callers = []
        callers_seen = set()
        for r in caller_rows:
            uniq = f"{r['file_path']}:{r['symbol_name']}:{r['start_line']}"
            if uniq not in callers_seen:
                callers_seen.add(uniq)
                lines = (r['code'] or '').splitlines()
                preview = "\n".join(lines[:12]) + ("\n..." if len(lines) > 12 else "")
                doc = r['docstring'] or ""
                if r['is_dynamic']:
                    dyn_note = f" [⚡ 动态调用: {r['dynamic_expr']}]"
                    doc = (doc + dyn_note) if doc else dyn_note
                matched_callers.append(
                    {
                        "caller_symbol": r['symbol_name'],
                        "symbol_type": r['chunk_type'],
                        "file_path": r['file_path'],
                        "start_line": r['start_line'],
                        "end_line": r['end_line'],
                        "route_info": r['route_info'],
                        "docstring": doc,
                        "code_preview": preview,
                        "is_dynamic": bool(r['is_dynamic']),
                        "dynamic_expr": r['dynamic_expr'] or "",
                        "resolution_type": r['resolution_type'],
                        "confidence": float(r['confidence']),
                    }
                )

        total_count = len(matched_callers)
        if limit > 0:
            paged_callers = matched_callers[offset: offset + limit]
        else:
            paged_callers = matched_callers[offset:] if offset else matched_callers

        res = {
            "status": "success",
            "target_symbol": symbol_name,
            "defined_in_repo": is_defined_in_repo,
            "ambiguous_definitions": ambig_defs,
            "total_count": total_count,
            "callers_count": len(paged_callers),
            "has_more": (offset + len(paged_callers)) < total_count,
            "callers": paged_callers,
        }
        self._set_query_cache("callers", cache_key, res)
        return res

    def get_callees(self, symbol_name: str, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        """查询指定符号直接调用的下游函数与模块 (What X calls)
        
        Args:
            symbol_name: 目标符号名（支持限定名）
            limit: 最多返回条数，默认 50，设为 0 表示不限制
            offset: 分页偏移量，默认 0
        """
        if not self.load():
            return {
                "status": "error",
                "message": f"未找到代码库索引，请先对 {self.repo_path} 执行 index_codebase",
                "callees": [],
            }

        cache_key = f"{symbol_name}:{limit}:{offset}"
        cached = self._get_query_cache("callees", cache_key)
        if cached is not None:
            return cached

        conn = self._get_db()
        # On-demand extracting function-body callees and establishing edges
        self._resolve_callees_on_demand(symbol_name)

        cursor = conn.execute(
            "SELECT id, symbol_name, qualified_name, file_path, start_line, docstring FROM nodes WHERE symbol_name = ? OR qualified_name = ? LIMIT 5",
            (symbol_name, symbol_name),
        )
        nodes = cursor.fetchall()
        if not nodes and "." in symbol_name:
            short = symbol_name.split(".")[-1]
            cursor = conn.execute(
                "SELECT id, symbol_name, qualified_name, file_path, start_line, docstring FROM nodes WHERE symbol_name = ? OR symbol_name LIKE ? OR qualified_name LIKE ? LIMIT 5",
                (short, f"%.{short}", f"%.{symbol_name}"),
            )
            nodes = cursor.fetchall()
        elif not nodes:
            cursor = conn.execute(
                "SELECT id, symbol_name, qualified_name, file_path, start_line, docstring FROM nodes WHERE symbol_name LIKE ? OR qualified_name LIKE ? LIMIT 5",
                (f"%.{symbol_name}", f"%.{symbol_name}"),
            )
            nodes = cursor.fetchall()

        if not nodes:
            return {
                "status": "not_found",
                "target_symbol": symbol_name,
                "message": f"未在索引中找到符号: {symbol_name}",
                "callees": [],
            }

        caller_node = nodes[0]
        caller_file = caller_node['file_path']

        cursor = conn.execute(
            """
            SELECT DISTINCT 
                e.callee_id, e.callee_symbol, e.callee_qualified, e.callee_file,
                e.call_name, e.resolution_type, e.confidence, e.is_dynamic, e.dynamic_expr,
                n.chunk_type, n.start_line, n.docstring
            FROM resolved_edges e
            LEFT JOIN nodes n ON e.callee_id = n.id
            WHERE e.caller_id = ? OR e.caller_symbol = ? OR e.caller_qualified = ? OR e.caller_symbol LIKE ?
            ORDER BY e.confidence DESC, e.call_name
            """,
            (caller_node['id'], caller_node['symbol_name'], symbol_name, f"%.{symbol_name}"),
        )
        edge_rows = cursor.fetchall()

        callees_detail = []
        seen_callees = set()
        for erow in edge_rows:
            c_name = erow['call_name']
            if c_name in seen_callees:
                continue
            seen_callees.add(c_name)

            is_dyn = bool(erow['is_dynamic'])
            dyn_expr = erow['dynamic_expr'] or ""
            res_type = erow['resolution_type']

            if res_type == "EXTERNAL" or erow['callee_id'] is None:
                doc = f"[⚡ 动态调用: {dyn_expr}]" if (is_dyn and dyn_expr) else ""
                callees_detail.append(
                    {
                        "target_symbol": c_name,
                        "defined_in_repo": False,
                        "file_path": None,
                        "qualified_name": "",
                        "symbol_type": "external_or_builtin",
                        "start_line": None,
                        "docstring": doc,
                        "ambiguous": False,
                        "candidates": [],
                        "is_dynamic": is_dyn,
                        "dynamic_expr": dyn_expr,
                        "resolution_type": res_type,
                        "confidence": float(erow['confidence']),
                    }
                )
            else:
                doc = erow['docstring'] or ""
                if is_dyn and dyn_expr:
                    doc = f"[⚡ 动态调用: {dyn_expr}] " + doc

                is_ambig = (res_type == "AMBIGUOUS")
                cand_list = []
                if is_ambig:
                    c_cursor = conn.execute(
                        "SELECT qualified_name, symbol_name, file_path, start_line FROM nodes WHERE symbol_name = ? OR symbol_name LIKE ?",
                        (c_name, f"%.{c_name}")
                    )
                    cand_list = [f"{r['qualified_name'] or r['symbol_name']} ({r['file_path']}#L{r['start_line']})" for r in c_cursor.fetchall()]

                callees_detail.append(
                    {
                        "target_symbol": c_name,
                        "defined_in_repo": True,
                        "file_path": erow['callee_file'],
                        "qualified_name": erow['callee_qualified'] or "",
                        "symbol_type": erow['chunk_type'] or "symbol",
                        "start_line": erow['start_line'],
                        "docstring": doc,
                        "ambiguous": is_ambig,
                        "candidates": cand_list,
                        "is_dynamic": is_dyn,
                        "dynamic_expr": dyn_expr,
                        "resolution_type": res_type,
                        "confidence": float(erow['confidence']),
                    }
                )

        total_count = len(callees_detail)
        if limit > 0:
            paged_callees = callees_detail[offset: offset + limit]
        else:
            paged_callees = callees_detail[offset:] if offset else callees_detail

        res = {
            "status": "success",
            "target_symbol": symbol_name,
            "total_count": total_count,
            "callees_count": len(paged_callees),
            "has_more": (offset + len(paged_callees)) < total_count,
            "callees": paged_callees,
        }
        self._set_query_cache("callees", cache_key, res)
        return res

    def get_impact_radius(self, symbol_name: str, max_depth: int = 3) -> Dict[str, Any]:
        """影响面/爆炸半径分析 (Blast Radius):
        计算修改该符号后，直接和间接被波及的上游调用链路、关联文件及受影响的外部 API 路由
        """
        if not self.load():
            return {
                "status": "error",
                "message": f"未找到代码库索引，请先执行 index_codebase",
            }

        cache_key = f"{symbol_name}:{max_depth}"
        cached = self._get_query_cache("impact", cache_key)
        if cached is not None:
            return cached

        conn = self._get_db()
        visited_symbols: Set[str] = set()
        queue = deque([(symbol_name, 0, [symbol_name], None)])
        impacted_tree = []
        impacted_files: Set[str] = set()
        impacted_routes: List[Dict[str, str]] = []
        routes_seen: Set[str] = set()

        while queue:
            curr_sym, depth, path, curr_id = queue.popleft()
            if curr_sym in visited_symbols or depth >= max_depth:
                continue
            visited_symbols.add(curr_sym)
            self._resolve_callers_on_demand(curr_sym)

            cur_ids = [curr_id] if curr_id else []
            if not cur_ids:
                if "." in curr_sym:
                    cur_defs = conn.execute(
                        "SELECT id FROM nodes WHERE qualified_name = ? OR symbol_name = ?",
                        (curr_sym, curr_sym)
                    ).fetchall()
                    if not cur_defs:
                        cur_defs = conn.execute(
                            "SELECT id FROM nodes WHERE qualified_name LIKE ? OR symbol_name = ?",
                            (f"%.{curr_sym}", curr_sym)
                        ).fetchall()
                else:
                    cur_defs = conn.execute(
                        "SELECT id FROM nodes WHERE symbol_name = ? OR qualified_name = ?",
                        (curr_sym, curr_sym)
                    ).fetchall()

                cur_ids = [d['id'] for d in cur_defs]

            if cur_ids:
                id_ph = ",".join("?" for _ in cur_ids)
                query_sql = f"""
                    SELECT DISTINCT 
                        n.id, n.symbol_name, n.chunk_type, n.file_path, n.start_line, 
                        n.route_info, e.is_dynamic, e.dynamic_expr, e.resolution_type, e.confidence
                    FROM resolved_edges e
                    JOIN nodes n ON e.caller_id = n.id
                    WHERE (e.callee_id IN ({id_ph}) OR e.callee_qualified = ?)
                      AND e.confidence >= 0.25
                      AND e.resolution_type != 'EXTERNAL'
                """
                cursor = conn.execute(query_sql, cur_ids + [curr_sym])
                callers = cursor.fetchall()
            else:
                query_sql = """
                    SELECT DISTINCT 
                        n.id, n.symbol_name, n.chunk_type, n.file_path, n.start_line, 
                        n.route_info, e.is_dynamic, e.dynamic_expr, e.resolution_type, e.confidence
                    FROM resolved_edges e
                    JOIN nodes n ON e.caller_id = n.id
                    WHERE (e.callee_symbol = ? OR e.callee_qualified = ? OR e.call_name = ?)
                      AND e.confidence >= 0.25
                      AND e.resolution_type != 'EXTERNAL'
                """
                cursor = conn.execute(query_sql, (curr_sym, curr_sym, curr_sym))
                callers = cursor.fetchall()

            for c in callers:
                # 忽略整文件虚块与纯文本块，仅追踪结构化实体
                if c['chunk_type'] == 'file' or c['symbol_name'].startswith('['):
                    continue

                impacted_files.add(c['file_path'])
                item = {
                    "depth": depth + 1,
                    "symbol": c['symbol_name'],
                    "type": c['chunk_type'],
                    "file_path": c['file_path'],
                    "line": c['start_line'],
                    "route": c['route_info'],
                    "propagation_path": " -> ".join(path + [c['symbol_name']]),
                    "is_dynamic": bool(c['is_dynamic']),
                    "dynamic_expr": c['dynamic_expr'] or "",
                    "resolution_type": c['resolution_type'],
                    "confidence": float(c['confidence']),
                }
                impacted_tree.append(item)

                if c['route_info'] and c['route_info'] not in routes_seen:
                    routes_seen.add(c['route_info'])
                    impacted_routes.append(
                        {
                            "route": c['route_info'],
                            "handler": c['symbol_name'],
                            "file_path": c['file_path'],
                            "line": str(c['start_line']),
                        }
                    )

                if c['symbol_name'] not in visited_symbols and (depth + 1) < max_depth:
                    if len(queue) < 100:
                        queue.append((c['symbol_name'], depth + 1, path + [c['symbol_name']], c['id']))

        res = {
            "status": "success",
            "target_symbol": symbol_name,
            "max_analyzed_depth": max_depth,
            "total_impacted_symbols": len(impacted_tree),
            "impacted_files_count": len(impacted_files),
            "impacted_files": sorted(list(impacted_files)),
            "impacted_external_routes": impacted_routes,
            "impact_propagation_chain": impacted_tree,
        }
        self._set_query_cache("impact", cache_key, res)
        return res

    def build_call_tree(self, root_sym: str, max_depth: int = 3) -> Dict[str, Any]:
        """对指定根节点进行 BFS 下游展开，生成调用树与链路节点 (Fix #9)
        
        优化：批量 BFS (Batched Frontier SQL) — 每层只发起一次 SQL 查询，
        而非对每个节点分别调用 get_callees()，将 DB 往返从 O(N×depth) 降至 O(depth)。
        """
        if not self.load():
            return {
                "symbol": root_sym,
                "defined_in_repo": False,
                "file_path": None,
                "line": None,
                "docstring": "",
                "children": [],
            }

        cache_key = f"{root_sym}:{max_depth}"
        cached = self._get_query_cache("call_tree", cache_key)
        if cached is not None:
            return cached

        tree_node: Dict[str, Any] = {
            "symbol": root_sym,
            "defined_in_repo": True,
            "file_path": None,
            "line": None,
            "docstring": "",
            "children": [],
        }
        conn = self._get_db()
        cursor = conn.execute(
            "SELECT id, file_path, start_line, docstring FROM nodes WHERE symbol_name = ? OR qualified_name = ? LIMIT 1",
            (root_sym, root_sym),
        )
        row = cursor.fetchone()
        root_id: Optional[str] = None
        if row:
            tree_node["file_path"] = row['file_path']
            tree_node["line"] = row['start_line']
            tree_node["docstring"] = row['docstring']
            root_id = row['id']

        # BFS 状态：{symbol_name: tree_node_dict}，用于快速追加子节点
        visited: Set[str] = {root_sym}
        # 当前层的 frontier：(tree_node, symbol_name, node_id_or_None)
        frontier = [(tree_node, root_sym, root_id)]

        for depth in range(1, max_depth + 1):
            if not frontier:
                break

            # 按需解析本层所有符号的下游调用
            for (_, sym, _) in frontier:
                self._resolve_callees_on_demand(sym)

            # 收集本层所有 caller_id（已知）与 caller_symbol（回退）
            ids_in_frontier: List[str] = [nid for (_, _, nid) in frontier if nid]
            syms_in_frontier: List[str] = [sym for (_, sym, nid) in frontier if not nid]

            # 构建批量 SQL：一次性取出本层所有节点的下游 callee 边
            edge_rows: List[Any] = []
            if ids_in_frontier:
                ph = ",".join("?" for _ in ids_in_frontier)
                edge_rows += conn.execute(f"""
                    SELECT DISTINCT
                        e.caller_id,
                        e.callee_id, e.callee_symbol, e.callee_qualified, e.callee_file,
                        e.call_name, e.resolution_type, e.confidence, e.is_dynamic, e.dynamic_expr,
                        n.chunk_type, n.start_line, n.docstring
                    FROM resolved_edges e
                    LEFT JOIN nodes n ON e.callee_id = n.id
                    WHERE e.caller_id IN ({ph})
                    ORDER BY e.confidence DESC
                """, ids_in_frontier).fetchall()

            if syms_in_frontier:
                ph = ",".join("?" for _ in syms_in_frontier)
                edge_rows += conn.execute(f"""
                    SELECT DISTINCT
                        e.caller_id,
                        e.callee_id, e.callee_symbol, e.callee_qualified, e.callee_file,
                        e.call_name, e.resolution_type, e.confidence, e.is_dynamic, e.dynamic_expr,
                        n.chunk_type, n.start_line, n.docstring
                    FROM resolved_edges e
                    LEFT JOIN nodes n ON e.callee_id = n.id
                    WHERE e.caller_symbol IN ({ph})
                    ORDER BY e.confidence DESC
                """, syms_in_frontier).fetchall()

            # 按 caller_id 分组边，映射到对应的父节点
            caller_id_to_tree: Dict[str, Any] = {nid: tn for (tn, _, nid) in frontier if nid}
            caller_sym_to_tree: Dict[str, Any] = {sym: tn for (tn, sym, nid) in frontier if not nid}

            next_frontier = []
            seen_per_parent: Dict[str, Set[str]] = {}  # caller_id -> 已插入 callee_name 集合

            for erow in edge_rows:
                parent_id = erow['caller_id']
                parent_node = caller_id_to_tree.get(parent_id) or caller_sym_to_tree.get(erow['caller_id'] or '')
                if parent_node is None:
                    continue  # 无法匹配父节点，跳过

                c_name = erow['call_name'] or erow['callee_symbol'] or ''
                if not c_name:
                    continue

                pkey = parent_id or id(parent_node)
                if pkey not in seen_per_parent:
                    seen_per_parent[pkey] = set()
                if c_name in seen_per_parent[pkey]:
                    continue
                seen_per_parent[pkey].add(c_name)

                in_repo = (erow['callee_id'] is not None and erow['resolution_type'] != 'EXTERNAL')
                child_item = {
                    "symbol": c_name,
                    "defined_in_repo": in_repo,
                    "file_path": erow['callee_file'],
                    "line": erow['start_line'],
                    "docstring": erow['docstring'] or "",
                    "children": [],
                    "is_dynamic": bool(erow['is_dynamic']),
                    "dynamic_expr": erow['dynamic_expr'] or "",
                }
                parent_node["children"].append(child_item)

                if in_repo and c_name not in visited and depth < max_depth:
                    visited.add(c_name)
                    next_frontier.append((child_item, c_name, erow['callee_id']))

            frontier = next_frontier

        self._set_query_cache("call_tree", cache_key, tree_node)
        return tree_node


    def format_tree_ascii(self, node: Dict[str, Any], prefix: str = "", is_last: bool = True, is_root: bool = True) -> List[str]:
        """Format call tree as ASCII directory tree lines"""
        lines = []
        sym = node["symbol"]
        f_info = f" ({node['file_path']}#L{node['line']})" if node.get("file_path") else " (external/built-in)"
        doc = f" — *{node['docstring'].strip()}*" if node.get("docstring") else ""
        dyn_badge = " [⚡dynamic]" if node.get("is_dynamic") else ""

        if is_root:
            lines.append(f"`{sym}`{dyn_badge}{f_info}{doc}")
        else:
            connector = "└── ➡️ " if is_last else "├── ➡️ "
            lines.append(f"{prefix}{connector}`{sym}`{dyn_badge}{f_info}{doc}")

        children = node.get("children", [])
        seen_targets = set()
        deduped_children = []
        for ch in children:
            target_key = f"{ch.get('file_path')}:{ch.get('line')}" if ch.get("file_path") else ch.get("symbol")
            if target_key in seen_targets:
                continue
            seen_targets.add(target_key)
            deduped_children.append(ch)

        in_repo = [c for c in deduped_children if c.get("defined_in_repo")]
        external = [c for c in deduped_children if not c.get("defined_in_repo")]
        filtered_children = in_repo + external[:3]

        for i, child in enumerate(filtered_children):
            child_is_last = (i == len(filtered_children) - 1)
            next_prefix = "" if is_root else (prefix + ("    " if is_last else "│   "))
            lines.extend(self.format_tree_ascii(child, prefix=next_prefix, is_last=child_is_last, is_root=False))

        return lines

    def explore_feature(self, query: str, top_k: int = 3, max_depth: int = 3) -> Dict[str, Any]:
        """End-to-end surgical exploration (explore_feature):
        Semantic recall + BFS multi-tier execution trace + routes and source code evidence.
        """
        if not self.load():
            return {
                "status": "error",
                "message": f"Codebase index not found, please run index_codebase first",
            }

        from code_search_mcp.searcher import CodeSearcher
        searcher = CodeSearcher(self.repo_path)
        # Expand initial candidate pool to cover multi-module flows
        matches = searcher.search(query=query, top_k=max(top_k * 2, 6))

        if not matches:
            return {
                "status": "no_match",
                "query": query,
                "message": f"No core code modules found matching '{query}'",
            }

        markdown_sections = []
        markdown_sections.append(f"# 🧭 Surgical Feature Exploration: {query}\n")
        markdown_sections.append(f"> 💡 **Single-Call Complete Context**: Aggregates semantic entry points, HTTP routes, multi-tier BFS dependency trees, and source code evidence.\n")

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

            markdown_sections.append(f"## 🎯 Execution Flow {flow_idx}: `{sym_name}` ({file_path}#L{start_line}-L{end_line})")

            # Route awareness
            if route_info:
                markdown_sections.append(f"- 🌐 **Associated External Route**: `{route_info}`")
            else:
                impact = self.get_impact_radius(sym_name, max_depth=3)
                up_routes = impact.get("impacted_external_routes", [])
                if up_routes:
                    r = up_routes[0]
                    markdown_sections.append(f"- 🌐 **Associated Trigger Route**: `{r['route']}` (handled by `{r['handler']}` at `{r['file_path']}`:L{r['line']})")

            if docstring:
                markdown_sections.append(f"- 📝 **Description**: {docstring}")

            # BFS multi-tier dependency tree
            call_tree = self.build_call_tree(sym_name, max_depth=max_depth)
            tree_lines = self.format_tree_ascii(call_tree)
            if len(tree_lines) > 1:
                markdown_sections.append("\n### 🛣️ End-to-End Call Chain (Execution Trace):")
                markdown_sections.append("```text\n" + "\n".join(tree_lines) + "\n```")

            def mark_children(n: Dict[str, Any]):
                for ch in n.get("children", []):
                    ch_sym = ch["symbol"]
                    global_expanded_symbols.add(ch_sym)
                    if ch.get("file_path"):
                        all_involved_files.add(ch["file_path"])
                    mark_children(ch)
            mark_children(call_tree)

            # Upstream callers
            callers_res = self.get_callers(sym_name)
            callers = callers_res.get("callers", [])
            if callers:
                markdown_sections.append("\n### ⬆️ Direct Upstream Triggers (Callers):")
                for c in callers[:3]:
                    c_sym = c['caller_symbol']
                    c_file = c['file_path']
                    c_line = c['start_line']
                    route_note = f" [route: `{c['route_info']}`]" if c.get('route_info') else ""
                    markdown_sections.append(f"  - ⬅️ Called by `{c_sym}` at `{c_file}`:L{c_line}{route_note}")

            # Core implementation snippet
            markdown_sections.append(f"\n### 📦 Core Implementation Source Code:")
            markdown_sections.append(f"```{m.get('language', 'text')}\n{code}\n```\n")

            flow_idx += 1

        if all_involved_files:
            markdown_sections.append("### 📁 Involved Source Files:")
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
    """Format callers as Markdown evidence report"""
    if res.get("status") != "success":
        return f"❌ {res.get('message', 'Failed to query upstream callers')}"

    target = res.get("target_symbol", "")
    callers = res.get("callers", [])
    count = res.get("callers_count", 0)
    is_defined = res.get("defined_in_repo", True)

    lines = [f"# 📞 Upstream Callers: `{target}` ({count} calls found)\n"]
    ambig_defs = res.get("ambiguous_definitions", [])
    if ambig_defs:
        lines.append(f"> ⚠️ **Multiple Definitions**: Symbol `{target}` has multiple independent definitions in codebase: {', '.join(ambig_defs)}. Listing all callers.\n")

    if not is_defined:
        lines.append(f"> ⚠️ **Note**: Symbol `{target}` is not defined in local codebase (may be external library or standard library).\n")

    if count == 0:
        lines.append("No upstream callers found calling this symbol.")
        return "\n".join(lines)

    for idx, c in enumerate(callers, start=1):
        sym = c['caller_symbol']
        f_path = c['file_path']
        s_line = c['start_line']
        route = f" 🌐 [route: `{c['route_info']}`]" if c.get('route_info') else ""
        doc = f" — *{c['docstring']}*" if c.get('docstring') else ""
        lines.append(f"### {idx}. `{sym}` ({f_path}#L{s_line}){route}{doc}")
        if c.get("code_preview"):
            lines.append("```python\n" + c["code_preview"] + "\n```")
    return "\n".join(lines)


def format_callees_markdown(res: Dict[str, Any]) -> str:
    """Format callees as Markdown dependency list"""
    if res.get("status") != "success":
        return f"❌ {res.get('message', 'Failed to query downstream dependencies')}"

    target = res.get("target_symbol", "")
    callees = res.get("callees", [])
    count = res.get("callees_count", 0)

    lines = [f"# 🎯 Downstream Callees: `{target}` ({count} targets called)\n"]
    if count == 0:
        lines.append("No function or method calls detected within this symbol (leaf function).")
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
                ambig_note = f"\n    ⚠️ *[Ambiguity: multiple candidates found, resolved to `{f_path}:L{s_line}`; alternatives: {', '.join(c['candidates'])}]*"
            lines.append(f"- **{idx}. `{sym}`**{qname_tag} ➡️ (defined at `{f_path}`:L{s_line}){doc}{ambig_note}")
        else:
            lines.append(f"- **{idx}. `{sym}`** (external library or built-in)")

    return "\n".join(lines)


def format_impact_markdown(res: Dict[str, Any]) -> str:
    """Format blast radius impact analysis report as Markdown"""
    if res.get("status") != "success":
        return f"❌ {res.get('message', 'Failed to analyze impact radius')}"

    target = res.get("target_symbol", "")
    total_syms = res.get("total_impacted_symbols", 0)
    files = res.get("impacted_files", [])
    routes = res.get("impacted_external_routes", [])
    chain = res.get("impact_propagation_chain", [])

    lines = [f"# 💥 Change Impact Blast-Radius Analysis: `{target}`\n"]
    lines.append(f"> ⚠️ **Risk Assessment**: Modifying `{target}` could impact **{total_syms} upstream symbols**, **{len(files)} source files**, and **{len(routes)} external API routes**.\n")

    if routes:
        lines.append("## 🌐 Directly/Indirectly Affected External API Routes (Priority for regression testing):")
        for r in routes:
            lines.append(f"- `{r['route']}` (handled by `{r['handler']}` at `{r['file_path']}`:L{r['line']})")
        lines.append("")

    if files:
        lines.append("## 📁 Affected Source Files:")
        for f in files:
            lines.append(f"- `{f}`")
        lines.append("")

    if chain:
        lines.append("## 🌲 Dependency Propagation Tree:")
        for item in chain:
            depth = item['depth']
            sym = item['symbol']
            f_path = item['file_path']
            line = item['line']
            route_tag = f" 🌐 [route: `{item['route']}`]" if item.get('route') else ""
            indent = "  " * (depth - 1)
            lines.append(f"{indent}- [depth {depth}] `{sym}` ({f_path}:L{line}){route_tag}")

    return "\n".join(lines)


def format_references_markdown(res: Dict[str, Any]) -> str:
    """Format cross-module reference analysis report as Markdown"""
    if res.get("status") != "success":
        return f"❌ {res.get('message', 'Failed to find references')}"

    target = res.get("target", "")
    ast_callers = res.get("structural_callers", [])
    text_refs = res.get("textual_references", [])
    total = res.get("total_references", 0)

    lines = [f"# 🔍 Cross-Module Reference Analysis: `{target}` ({total} references found)\n"]
    if total == 0:
        lines.append("No explicit references to this symbol or keyword found in the codebase.")
        return "\n".join(lines)

    if ast_callers:
        lines.append(f"## 📞 1. Explicit AST Code Callers ({len(ast_callers)} calls):")
        for idx, c in enumerate(ast_callers, start=1):
            sym = c["caller_symbol"]
            f_path = c["file_path"]
            s_line = c["start_line"]
            route = f" 🌐 [route: `{c['route_info']}`]" if c.get("route_info") else ""
            doc = f" — *{c['docstring']}*" if c.get("docstring") else ""
            lines.append(f"- **{idx}. `{sym}`** (`{f_path}`:L{s_line}){route}{doc}")
        lines.append("")

    if text_refs:
        lines.append(f"## 📝 2. Config / String / Literal References ({len(text_refs)} text matches):")
        for idx, m in enumerate(text_refs, start=1):
            f_path = m.get("file_path", "")
            line = m.get("line_number", 0)
            content = m.get("content", "").strip()
            lines.append(f"- **{idx}. `{f_path}`:L{line}**")
            lines.append(f"  ```\n  {content}\n  ```")
        lines.append("")

    return "\n".join(lines)

