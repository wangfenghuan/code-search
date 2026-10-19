import ast
import gc
import hashlib
import json
import os
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import lancedb

from code_search_mcp.config import (
    DEFAULT_IGNORE_DIRS,
    DEFAULT_IGNORE_FILES,
    DEFAULT_MODEL_NAME,
    INDEX_SCHEMA_VERSION,
    VECTOR_DIMENSION,
    get_repo_db_path,
    get_vector_dimension,
)
from code_search_mcp.embeddings import EmbeddingEngine
from code_search_mcp.multilang_parser import EXTENSION_LANG_MAP, TreeSitterParser, get_module_name_from_path
from code_search_mcp.outline import ProjectOutlineGenerator
from code_search_mcp.text_utils import extract_natural_words_from_identifiers
def _create_fts_index_safe(table, field_name: str = "enriched_text"):
    """安全创建全文检索 FTS 索引，优先使用 LanceDB 现代 FTS 配置 API，消除 DeprecatedWarning"""
    try:
        from lancedb.index import FTS
        table.create_index(field_name, config=FTS(), replace=True)
    except Exception:
        try:
            table.create_fts_index(field_name, replace=True)
        except Exception:
            pass


@dataclass
class CodeChunk:
    id: str
    file_path: str
    full_path: str
    language: str
    symbol_name: str
    chunk_type: str  # function, async_function, class, method, struct, top_level
    start_line: int
    end_line: int
    code: str
    docstring: Optional[str]
    decorators: str
    route_info: str
    enriched_text: str
    calls: str = "[]"
    module_name: str = ""
    qualified_name: str = ""


def build_enriched_text(
    rel_path: str,
    language: str,
    symbol_name: str,
    chunk_type: str,
    signature: str,
    docstring: Optional[str],
    route_info: str,
    decorators: str,
    code: str,
    module_name: str = "",
) -> str:
    """构建多语言语义富化文本（注入语言标签、模块限定、路由、文档说明与代码）"""
    lines = [
        f"文件路径: {rel_path}",
    ]
    if module_name:
        lines.append(f"所属模块: {module_name}")
    lines.extend([
        f"编程语言: {language}",
        f"代码符号: {symbol_name}",
        f"符号类型: {chunk_type}",
    ])
    if route_info:
        lines.append(f"Web接口路由: {route_info}")
    if decorators:
        lines.append(f"装饰器: {decorators}")
    if signature:
        lines.append(f"参数签名: {signature}")
    if docstring:
        lines.append(f"功能文档说明: {docstring.strip()}")

    # 标识符自然语言拆词注入（Camel/Snake Case Splitting）：
    # 自动将 verifyJwtTokenSignature 或 verify_jwt_token 拆解为自然语言词组 verify jwt token signature
    # 消除 bge-small-zh 将英文长标识符切碎成无意义 sub-words 的问题（仅用于向量富化，不改变展示源码）
    split_words = extract_natural_words_from_identifiers(symbol_name, route_info, signature, code[:300])
    if split_words:
        lines.append(f"标识符自然语言拆词: {' '.join(split_words)}")

    lines.append("实现代码:")

    # 保护超长代码，保留头部和尾部核心上下文
    code_lines = code.splitlines()
    if len(code_lines) > 100:
        truncated_code = "\n".join(code_lines[:60]) + "\n... (中间关键分支保留) ...\n" + "\n".join(code_lines[-25:])
        lines.append(truncated_code)
    else:
        lines.append(code)

    return "\n".join(lines)


class UniversalCodeChunker:
    """基于 Tree-sitter 的多语言统一切片器"""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).resolve()
        self.ts_parser = TreeSitterParser()

    def _fallback_text_chunks(self, file_path: Path, rel_path: str, lang: str) -> List[CodeChunk]:
        """降级纯文本滑动窗口切片：针对超大文件 (>1MB) 或异常文件，确保不崩溃并保留搜索能力"""
        chunks: List[CodeChunk] = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            return chunks
        lines = content.splitlines()
        if not lines:
            return chunks

        mod_name = get_module_name_from_path(rel_path)
        window_size = 100
        overlap = 25
        step = max(1, window_size - overlap)
        part_idx = 1

        for start_idx in range(0, len(lines), step):
            window_lines = lines[start_idx : start_idx + window_size]
            if not window_lines:
                break
            sub_code = "\n".join(window_lines)
            part_name = f"[text-chunk#{part_idx}]"
            part_start = start_idx + 1
            part_end = min(start_idx + len(window_lines), len(lines))
            sub_enriched = build_enriched_text(
                rel_path=rel_path,
                language=lang,
                symbol_name=part_name,
                chunk_type="text_window",
                signature="",
                docstring=f"大文件纯文本分块 (第 {part_idx} 部分)",
                route_info="",
                decorators="",
                code=sub_code,
                module_name=mod_name,
            )
            chunks.append(
                CodeChunk(
                    id=str(uuid.uuid4()),
                    file_path=rel_path,
                    full_path=str(file_path.resolve()),
                    language=lang,
                    symbol_name=part_name,
                    chunk_type="text_window",
                    start_line=part_start,
                    end_line=part_end,
                    code=sub_code,
                    docstring=None,
                    decorators="",
                    route_info="",
                    enriched_text=sub_enriched,
                    calls="[]",
                    module_name=mod_name,
                    qualified_name=f"{mod_name}.{part_name}" if mod_name else part_name,
                )
            )
            part_idx += 1
            if start_idx + window_size >= len(lines):
                break
        return chunks

    def parse_file(self, file_path: Path, include_calls: bool = False) -> List[CodeChunk]:
        try:
            rel_path = str(file_path.resolve().relative_to(self.repo_root)).replace("\\", "/")
        except ValueError:
            rel_path = str(file_path).replace("\\", "/")

        ext = file_path.suffix.lower()
        lang = EXTENSION_LANG_MAP.get(ext, "unknown")

        # 1. 复杂度熔断：检查文件大小 (>1MB 自动降级为滑动窗口纯文本块)
        try:
            file_size = file_path.stat().st_size
        except Exception:
            file_size = 0

        if file_size > 1024 * 1024:
            return self._fallback_text_chunks(file_path, rel_path, lang)

        # 2. 安全调用 AST 解析，任何异常安全降级 (默认轻量符号定义提取，跳过调用边遍历)
        try:
            symbols = self.ts_parser.parse_file(file_path, rel_path=rel_path, include_calls=include_calls)
        except Exception as e:
            sys.stderr.write(f"[code-search-mcp] AST 解析异常，降级为文本分块 {rel_path}: {e}\n")
            return self._fallback_text_chunks(file_path, rel_path, lang)

        chunks: List[CodeChunk] = []

        if symbols:
            for s in symbols:
                code_lines = s.code.splitlines()
                # 如果符号代码超过 120 行，进行滑动窗口分块 (Windowed Chunking)，防止大函数语义稀释
                if len(code_lines) > 120 and s.symbol_type in ("function", "method", "async_function"):
                    window_size = 80
                    overlap = 20
                    step = window_size - overlap
                    part_idx = 1
                    for start_idx in range(0, len(code_lines), step):
                        window_lines = code_lines[start_idx : start_idx + window_size]
                        if not window_lines:
                            break
                        sub_code = "\n".join(window_lines)
                        part_name = f"{s.name}#part{part_idx}"
                        part_start = s.start_line + start_idx
                        part_end = min(s.start_line + start_idx + len(window_lines) - 1, s.end_line)
                        sub_enriched = build_enriched_text(
                            rel_path=rel_path,
                            language=lang,
                            symbol_name=part_name,
                            chunk_type=s.symbol_type,
                            signature=s.signature,
                            docstring=f"{s.docstring or ''} (分块第 {part_idx} 部分)".strip(),
                            route_info=s.route_info,
                            decorators="",
                            code=sub_code,
                            module_name=s.module_name,
                        )
                        chunks.append(
                            CodeChunk(
                                id=str(uuid.uuid4()),
                                file_path=rel_path,
                                full_path=str(file_path),
                                language=lang,
                                symbol_name=part_name,
                                chunk_type=s.symbol_type,
                                start_line=part_start,
                                end_line=part_end,
                                code=sub_code,
                                docstring=s.docstring,
                                decorators="",
                                route_info=s.route_info,
                                enriched_text=sub_enriched,
                                calls=json.dumps(s.calls or [], ensure_ascii=False),
                                module_name=s.module_name,
                                qualified_name=f"{s.qualified_name}#part{part_idx}" if s.qualified_name else part_name,
                            )
                        )
                        part_idx += 1
                        if start_idx + window_size >= len(code_lines):
                            break
                else:
                    enriched = build_enriched_text(
                        rel_path=rel_path,
                        language=lang,
                        symbol_name=s.name,
                        chunk_type=s.symbol_type,
                        signature=s.signature,
                        docstring=s.docstring,
                        route_info=s.route_info,
                        decorators="",
                        code=s.code,
                        module_name=s.module_name,
                    )
                    chunks.append(
                        CodeChunk(
                            id=str(uuid.uuid4()),
                            file_path=rel_path,
                            full_path=str(file_path),
                            language=lang,
                            symbol_name=s.name,
                            chunk_type=s.symbol_type,
                            start_line=s.start_line,
                            end_line=s.end_line,
                            code=s.code,
                            docstring=s.docstring,
                            decorators="",
                            route_info=s.route_info,
                            enriched_text=enriched,
                            calls=json.dumps(s.calls or [], ensure_ascii=False),
                            module_name=s.module_name,
                            qualified_name=s.qualified_name,
                        )
                    )
        else:
            # 降级：如果未提取出符号（如纯脚本、初始化配置），作为一个文件块保留
            try:
                content = file_path.read_text(encoding="utf-8", errors="replace")
                if content.strip():
                    total_lines = len(content.splitlines())
                    enriched = build_enriched_text(
                        rel_path=rel_path,
                        language=lang,
                        symbol_name="[file]",
                        chunk_type="file",
                        signature="",
                        docstring="模块级脚本或配置文件",
                        route_info="",
                        decorators="",
                        code=content,
                    )
                    mod_name = get_module_name_from_path(rel_path)
                    chunks.append(
                        CodeChunk(
                            id=str(uuid.uuid4()),
                            file_path=rel_path,
                            full_path=str(file_path),
                            language=lang,
                            symbol_name="[file]",
                            chunk_type="file",
                            start_line=1,
                            end_line=total_lines,
                            code=content,
                            docstring=None,
                            decorators="",
                            route_info="",
                            enriched_text=enriched,
                            calls="[]",
                            module_name=mod_name,
                            qualified_name=f"{mod_name}.[file]" if mod_name else "[file]",
                        )
                    )
            except Exception:
                pass

        return chunks


class CodeIndexer:
    """多语言代码库扫描与向量化索引管理器"""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.db_path = get_repo_db_path(self.repo_path)
        self.embedding_engine = EmbeddingEngine.get_instance()

    def scan_files(self) -> List[Path]:
        """递归扫描所有支持的多语言源文件 (Python, JS, TS, Go)"""
        matched_files = []
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]
            for file in files:
                ext = Path(file).suffix.lower()
                if ext in EXTENSION_LANG_MAP and file not in DEFAULT_IGNORE_FILES:
                    matched_files.append(Path(root) / file)
        return matched_files

    def index_all(
        self,
        batch_size: int = 64,
        skip_vector: bool = False,
        force_vector: bool = False,
        vector_threshold: int = 2000,
    ) -> Dict[str, Any]:
        """全量切片、真流式持久化至 SQLite (结构图谱) 与 LanceDB (向量库)，彻底解决超大仓库 OOM 137"""
        sys.stderr.write(f"[code-search-mcp] 开始扫描多语言代码库: {self.repo_path}\n")
        files = self.scan_files()
        file_count = len(files)
        sys.stderr.write(f"[code-search-mcp] 找到 {file_count} 个多语言源文件\n")

        # 超大代码库智能探测与降级
        if file_count > vector_threshold and not force_vector and not skip_vector:
            skip_vector = True
            sys.stderr.write(
                f"[code-search-mcp] ⚠️ 检测到大型代码库 (共 {file_count} 个源文件 > 阈值 {vector_threshold})。\n"
                f"[code-search-mcp] 自动激活轻量结构化索引模式：构建架构大纲、CodeGraph 调用图谱 (SQLite) 与 ripgrep 确切检索，跳过耗时且高内存的向量嵌入以杜绝 OOM。\n"
                f"[code-search-mcp] (若仍需全量向量搜索，可通过 CLI 参数 --force-vector 或 MCP 参数 force_vector=True 强制启用流式嵌入)\n"
            )
            sys.stderr.flush()

        # 生成并缓存全局架构大纲
        outline_gen = ProjectOutlineGenerator(self.repo_path)
        outline_gen.generate()

        if file_count == 0:
            return {
                "status": "success",
                "repo_path": str(self.repo_path),
                "indexed_files": 0,
                "indexed_chunks": 0,
                "vector_indexed": not skip_vector,
            }

        # 1. 初始化 SQLite 图引擎（清空历史表准备流式构建）
        from code_search_mcp.graph_engine import CodeGraphEngine
        graph_engine = CodeGraphEngine.get_instance(self.repo_path)
        graph_engine.init_clean_graph()

        # 2. 如果启用向量索引，初始化 LanceDB 与已有向量复用表
        existing_vectors_map: Dict[str, Tuple[bytes, Any]] = {}
        db = None
        table = None
        table_name = "code_chunks"

        if not skip_vector:
            try:
                db_conn = lancedb.connect(str(self.db_path))
                resp = db_conn.list_tables() if hasattr(db_conn, "list_tables") else db_conn.table_names()
                tables = resp.tables if hasattr(resp, "tables") else list(resp)
                if "code_chunks" in tables:
                    old_tbl = db_conn.open_table("code_chunks")
                    try:
                        arrow_data = old_tbl.search().select(["file_path", "symbol_name", "start_line", "code", "vector"]).to_arrow()
                    except Exception:
                        arrow_data = old_tbl.to_arrow()
                    files_col = arrow_data.column("file_path").to_pylist()
                    sym_col = arrow_data.column("symbol_name").to_pylist()
                    start_col = arrow_data.column("start_line").to_pylist()
                    code_col = arrow_data.column("code").to_pylist()
                    vec_col = arrow_data.column("vector").to_pylist()
                    for f_p, s_n, s_l, c_d, v_c in zip(files_col, sym_col, start_col, code_col, vec_col):
                        key = f"{f_p}:{s_n}:{s_l}"
                        c_bytes = hashlib.md5(c_d.encode("utf-8")).digest() if isinstance(c_d, str) else b""
                        existing_vectors_map[key] = (c_bytes, v_c)
                    del arrow_data, files_col, sym_col, start_col, code_col, vec_col
                    gc.collect()
            except Exception:
                existing_vectors_map.clear()

            db = lancedb.connect(str(self.db_path))

        # 3. 真流式批次持久化 (Streaming Batch Persistence，内存恒定极小，杜绝全局积攒)
        STREAM_BATCH_SIZE = 300
        chunker = UniversalCodeChunker(self.repo_path)
        current_batch: List[CodeChunk] = []
        total_chunks = 0
        reused_total = 0
        embedded_total = 0

        mode_desc = "轻量结构化模式 (免向量)" if skip_vector else "真流式低显存向量模式"
        sys.stderr.write(f"[code-search-mcp] 开始流式解析与持久化 [{mode_desc}]...\n")
        sys.stderr.flush()

        def _flush_batch(batch: List[CodeChunk]) -> Any:
            nonlocal table, embedded_total, reused_total
            if not batch:
                return table

            # 1. 立即流式写入 SQLite nodes 表
            graph_engine.stream_insert_chunks(batch)

            # 2. 如果启用向量索引，分批推理并流式追加写入 LanceDB
            if not skip_vector and db is not None:
                batch_vectors: List[Any] = [None] * len(batch)
                batch_to_embed: List[str] = []
                batch_embed_indices: List[int] = []

                for i, chunk in enumerate(batch):
                    key = f"{chunk.file_path}:{chunk.symbol_name}:{chunk.start_line}"
                    chunk_hash = hashlib.md5(chunk.code.encode("utf-8")).digest()
                    if key in existing_vectors_map and existing_vectors_map[key][0] == chunk_hash:
                        batch_vectors[i] = existing_vectors_map[key][1]
                        reused_total += 1
                    else:
                        batch_to_embed.append(chunk.enriched_text)
                        batch_embed_indices.append(i)

                if batch_to_embed:
                    embedded_total += len(batch_to_embed)
                    new_vecs = self.embedding_engine.embed_documents(batch_to_embed, batch_size=batch_size or 32)
                    for idx_in_batch, vec in zip(batch_embed_indices, new_vecs):
                        batch_vectors[idx_in_batch] = vec
                    del new_vecs

                batch_data = []
                for chunk, vec in zip(batch, batch_vectors):
                    batch_data.append(
                        {
                            "id": chunk.id,
                            "file_path": chunk.file_path,
                            "full_path": chunk.full_path,
                            "language": chunk.language,
                            "symbol_name": chunk.symbol_name,
                            "chunk_type": chunk.chunk_type,
                            "start_line": chunk.start_line,
                            "end_line": chunk.end_line,
                            "code": chunk.code,
                            "docstring": chunk.docstring or "",
                            "decorators": chunk.decorators,
                            "route_info": chunk.route_info,
                            "enriched_text": chunk.enriched_text,
                            "calls": chunk.calls,
                            "module_name": chunk.module_name or "",
                            "qualified_name": chunk.qualified_name or "",
                            "vector": vec,
                        }
                    )

                if table is None:
                    table = db.create_table(table_name, data=batch_data, mode="overwrite")
                else:
                    table.add(batch_data)

                del batch_data
                del batch_vectors
                del batch_to_embed
                del batch_embed_indices

            return table

        for f in files:
            try:
                file_chunks = chunker.parse_file(f)
                if not file_chunks:
                    continue
                current_batch.extend(file_chunks)
                if len(current_batch) >= STREAM_BATCH_SIZE:
                    total_chunks += len(current_batch)
                    _flush_batch(current_batch)
                    current_batch.clear()
                    gc.collect()
            except Exception as e:
                sys.stderr.write(f"[code-search-mcp] 警告: 处理文件 {f} 异常，跳过: {e}\n")

        if current_batch:
            total_chunks += len(current_batch)
            _flush_batch(current_batch)
            current_batch.clear()
            gc.collect()

        # 4. 图引擎提交收尾
        graph_engine.finalize_graph()
        graph_engine.close()
        del graph_engine
        gc.collect()

        if reused_total > 0:
            sys.stderr.write(f"[code-search-mcp] 命中向量缓存: {reused_total} 个代码块已复用，实际推理 {embedded_total} 个新/改动代码块\n")
            sys.stderr.flush()

        existing_vectors_map.clear()
        gc.collect()

        # 5. 如果构建了向量表，建立全文 FTS 索引
        if not skip_vector and table is not None:
            _create_fts_index_safe(table, "enriched_text")

        # 6. 记录元信息
        meta_file = self.db_path / "meta.json"
        meta = {
            "schema_version": INDEX_SCHEMA_VERSION,
            "model_name": self.embedding_engine.model_name if not skip_vector else "",
            "vector_dimension": get_vector_dimension(self.embedding_engine.model_name) if not skip_vector else 0,
            "vector_indexed": not skip_vector,
            "repo_path": str(self.repo_path),
            "indexed_files": len(files),
            "indexed_chunks": total_chunks,
            "created_at": time.time(),
            "last_updated": time.time(),
        }
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # 记录最后索引路径
        last_repo_file = self.db_path.parent / "last_repo.txt"
        last_repo_file.write_text(str(self.repo_path), encoding="utf-8")

        # 通知图引擎缓存失效
        try:
            from code_search_mcp.graph_engine import CodeGraphEngine
            CodeGraphEngine.invalidate_cache(self.repo_path)
        except Exception:
            pass

        sys.stderr.write(f"[code-search-mcp] 索引与调用图谱构建完成！共 {len(files)} 文件，{total_chunks} 代码块\n")
        return {
            "status": "success",
            "repo_path": str(self.repo_path),
            "indexed_files": len(files),
            "indexed_chunks": total_chunks,
            "vector_indexed": not skip_vector,
        }

    def _sync_meta_stats(self, tbl=None):
        """同步更新 meta.json 中的文件数与切片数，避免增量删改导致元数据脱节"""
        meta_file = self.db_path / "meta.json"
        if not meta_file.exists():
            return
        try:
            if tbl is None:
                db = lancedb.connect(str(self.db_path))
                tbl = db.open_table("code_chunks")
            total_chunks = len(tbl)
            arrow_tbl = tbl.to_arrow()
            if "file_path" in arrow_tbl.column_names:
                unique_files = len(set(arrow_tbl.column("file_path").to_pylist()))
            else:
                unique_files = 0
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            meta["indexed_files"] = unique_files
            meta["indexed_chunks"] = total_chunks
            meta["last_updated"] = time.time()
            meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def delete_file_from_index(self, file_path: str | Path) -> bool:
        """从 LanceDB 中移除指定文件或目录下的所有切片记录（支持单文件与文件夹前缀递归清理）"""
        p = Path(file_path)
        if not p.is_absolute():
            f = (self.repo_path / p).resolve()
        else:
            f = p.resolve()

        try:
            rel_path = str(f.relative_to(self.repo_path)).replace("\\", "/")
        except ValueError:
            rel_path = str(f).replace("\\", "/")

        if not self.db_path.exists():
            return False

        try:
            db = lancedb.connect(str(self.db_path))
            tbl = db.open_table("code_chunks")
            safe_rel_path = rel_path.replace("'", "''")
            # 同时支持单文件完全匹配与子目录前缀匹配，彻底消除目录重命名/删除孤儿数据
            tbl.delete(f"file_path = '{safe_rel_path}' OR file_path LIKE '{safe_rel_path}/%'")
            self._sync_meta_stats(tbl)

            try:
                from code_search_mcp.graph_engine import CodeGraphEngine
                CodeGraphEngine.invalidate_cache(self.repo_path)
            except Exception:
                pass
            return True
        except Exception as e:
            sys.stderr.write(f"[code-search-mcp] 从索引删除文件 {rel_path} 失败: {e}\n")
            return False

    def index_file_incremental(self, file_path: str | Path) -> Dict[str, Any]:
        """单文件增量更新：先删除旧切片，再重新提取 AST、生成向量并插入 LanceDB"""
        p = Path(file_path)
        if not p.is_absolute():
            f = (self.repo_path / p).resolve()
        else:
            f = p.resolve()

        try:
            rel_path = str(f.relative_to(self.repo_path)).replace("\\", "/")
        except ValueError:
            rel_path = str(f).replace("\\", "/")

        # 1. 无论文件是修改还是删除，先清除旧切片
        self.delete_file_from_index(f)

        # 如果文件已不存在（被删除），更新大纲和图缓存并直接返回
        if not f.exists() or not f.is_file():
            try:
                ProjectOutlineGenerator(self.repo_path).generate()
            except Exception:
                pass
            try:
                from code_search_mcp.graph_engine import CodeGraphEngine
                CodeGraphEngine.invalidate_cache(self.repo_path)
            except Exception:
                pass
            return {
                "status": "deleted",
                "file_path": rel_path,
                "chunks_count": 0,
            }

        # 2. 重新解析新切片
        chunker = UniversalCodeChunker(self.repo_path)
        try:
            new_chunks = chunker.parse_file(f)
        except Exception as e:
            sys.stderr.write(f"[code-search-mcp] 警告: 增量解析文件 {f} 异常: {e}\n")
            new_chunks = []
        if not new_chunks:
            try:
                ProjectOutlineGenerator(self.repo_path).generate()
            except Exception:
                pass
            try:
                from code_search_mcp.graph_engine import CodeGraphEngine
                CodeGraphEngine.invalidate_cache(self.repo_path)
            except Exception:
                pass
            return {
                "status": "empty",
                "file_path": rel_path,
                "chunks_count": 0,
            }

        # 3. 向量化并插入 LanceDB
        texts = [chunk.enriched_text for chunk in new_chunks]
        vectors = self.embedding_engine.embed_documents(texts)

        data = []
        for chunk, vec in zip(new_chunks, vectors):
            data.append(
                {
                    "id": chunk.id,
                    "file_path": chunk.file_path,
                    "full_path": chunk.full_path,
                    "language": chunk.language,
                    "symbol_name": chunk.symbol_name,
                    "chunk_type": chunk.chunk_type,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "code": chunk.code,
                    "docstring": chunk.docstring or "",
                    "decorators": chunk.decorators,
                    "route_info": chunk.route_info,
                    "enriched_text": chunk.enriched_text,
                    "calls": chunk.calls,
                    "module_name": chunk.module_name or "",
                    "qualified_name": chunk.qualified_name or "",
                    "vector": vec,
                }
            )

        db = lancedb.connect(str(self.db_path))
        tbl = db.open_table("code_chunks")
        tbl.add(data)
        # 增量刷新全文 FTS 索引 (消除 LanceDB 废弃警告)
        _create_fts_index_safe(tbl, "enriched_text")
        self._sync_meta_stats(tbl)

        # 4. 刷新大纲缓存与图引擎缓存
        try:
            ProjectOutlineGenerator(self.repo_path).generate()
        except Exception:
            pass
        try:
            from code_search_mcp.graph_engine import CodeGraphEngine
            CodeGraphEngine.invalidate_cache(self.repo_path)
        except Exception:
            pass

        return {
            "status": "updated",
            "file_path": rel_path,
            "chunks_count": len(new_chunks),
        }

