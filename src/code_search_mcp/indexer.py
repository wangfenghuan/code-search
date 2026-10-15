import ast
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import lancedb

from code_search_mcp.config import (
    DEFAULT_IGNORE_DIRS,
    DEFAULT_IGNORE_FILES,
    get_repo_db_path,
)
from code_search_mcp.embeddings import EmbeddingEngine
from code_search_mcp.multilang_parser import EXTENSION_LANG_MAP, TreeSitterParser
from code_search_mcp.outline import ProjectOutlineGenerator


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
) -> str:
    """构建多语言语义富化文本（注入语言标签、路由、文档说明与代码）"""
    lines = [
        f"文件路径: {rel_path}",
        f"编程语言: {language}",
        f"代码符号: {symbol_name}",
        f"符号类型: {chunk_type}",
    ]
    if route_info:
        lines.append(f"Web接口路由: {route_info}")
    if decorators:
        lines.append(f"装饰器: {decorators}")
    if signature:
        lines.append(f"参数签名: {signature}")
    if docstring:
        lines.append(f"功能文档说明: {docstring.strip()}")
    lines.append("实现代码:")

    # 保护超长代码，保留头部和尾部核心上下文
    code_lines = code.splitlines()
    if len(code_lines) > 100:
        truncated_code = "\n".join(code_lines[:60]) + "\n... (中间代码省略) ...\n" + "\n".join(code_lines[-20:])
        lines.append(truncated_code)
    else:
        lines.append(code)

    return "\n".join(lines)


class UniversalCodeChunker:
    """基于 Tree-sitter 的多语言统一切片器"""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self.ts_parser = TreeSitterParser()

    def parse_file(self, file_path: Path) -> List[CodeChunk]:
        try:
            rel_path = str(file_path.relative_to(self.repo_root)).replace("\\", "/")
        except ValueError:
            rel_path = str(file_path).replace("\\", "/")

        ext = file_path.suffix.lower()
        lang = EXTENSION_LANG_MAP.get(ext, "unknown")

        symbols = self.ts_parser.parse_file(file_path)
        chunks: List[CodeChunk] = []

        if symbols:
            for s in symbols:
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

    def index_all(self, batch_size: int = 32) -> Dict[str, Any]:
        """全量切片、提取架构大纲、向量化并存储至 LanceDB"""
        sys.stderr.write(f"[code-search-mcp] 开始扫描多语言代码库: {self.repo_path}\n")
        files = self.scan_files()
        sys.stderr.write(f"[code-search-mcp] 找到 {len(files)} 个源文件 (Python/TS/JS/Go)\n")

        # 生成并缓存全局架构大纲
        outline_gen = ProjectOutlineGenerator(self.repo_path)
        outline_gen.generate()

        chunker = UniversalCodeChunker(self.repo_path)
        all_chunks: List[CodeChunk] = []

        for f in files:
            file_chunks = chunker.parse_file(f)
            all_chunks.extend(file_chunks)

        total_chunks = len(all_chunks)
        sys.stderr.write(f"[code-search-mcp] 共切出 {total_chunks} 个多语言语义代码块\n")

        if total_chunks == 0:
            return {
                "status": "success",
                "repo_path": str(self.repo_path),
                "indexed_files": len(files),
                "indexed_chunks": 0,
            }

        # 批量向量化
        texts = [chunk.enriched_text for chunk in all_chunks]
        sys.stderr.write(f"[code-search-mcp] 正在批量生成向量嵌入...\n")
        vectors = self.embedding_engine.embed_documents(texts, batch_size=batch_size)

        # 组装 LanceDB 数据集
        data = []
        for chunk, vec in zip(all_chunks, vectors):
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
                    "vector": vec,
                }
            )

        # 写入 LanceDB
        db = lancedb.connect(str(self.db_path))
        table_name = "code_chunks"
        sys.stderr.write(f"[code-search-mcp] 正在持久化至 LanceDB ({self.db_path})...\n")
        table = db.create_table(table_name, data=data, mode="overwrite")

        # 记录元信息
        meta_file = self.db_path / "meta.json"
        meta = {
            "repo_path": str(self.repo_path),
            "indexed_files": len(files),
            "indexed_chunks": total_chunks,
        }
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

        # 记录最后索引路径
        last_repo_file = self.db_path.parent / "last_repo.txt"
        last_repo_file.write_text(str(self.repo_path), encoding="utf-8")

        sys.stderr.write(f"[code-search-mcp] 索引构建完成！共 {len(files)} 文件，{total_chunks} 代码块\n")
        return {
            "status": "success",
            "repo_path": str(self.repo_path),
            "indexed_files": len(files),
            "indexed_chunks": total_chunks,
        }
