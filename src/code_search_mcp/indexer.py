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
from code_search_mcp.outline import ProjectOutlineGenerator


@dataclass
class CodeChunk:
    id: str
    file_path: str
    full_path: str
    symbol_name: str
    chunk_type: str  # function, async_function, class, method, top_level
    start_line: int
    end_line: int
    code: str
    docstring: Optional[str]
    decorators: str
    route_info: str
    enriched_text: str


def format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """从 AST 提取易读的函数参数签名"""
    args = []
    # 位置参数
    for arg in node.args.args:
        ann = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
        args.append(f"{arg.arg}{ann}")
    # 变长位置参数
    if node.args.vararg:
        ann = f": {ast.unparse(node.args.vararg.annotation)}" if node.args.vararg.annotation else ""
        args.append(f"*{node.args.vararg.arg}{ann}")
    # 关键字参数
    for arg in node.args.kwonlyargs:
        ann = f": {ast.unparse(arg.annotation)}" if arg.annotation else ""
        args.append(f"{arg.arg}{ann}")
    # 变长关键字参数
    if node.args.kwarg:
        ann = f": {ast.unparse(node.args.kwarg.annotation)}" if node.args.kwarg.annotation else ""
        args.append(f"**{node.args.kwarg.arg}{ann}")

    return f"({', '.join(args)})"


def extract_route_info(decorator_nodes: List[ast.expr]) -> str:
    """智能解析主流 Web 框架 (FastAPI/Flask/Django/Tornado) 的路由装饰器"""
    for dec in decorator_nodes:
        dec_str = ast.unparse(dec)
        # FastAPI / Flask 模式: @router.post("/login"), @app.get("/items/{id}")
        for method in ["get", "post", "put", "delete", "patch", "options", "head"]:
            pattern = f".{method}("
            if pattern in dec_str:
                return f"HTTP {method.upper()} {dec_str[dec_str.find(pattern) + len(pattern) - 1:]}"

        # Flask @app.route("/login", methods=["POST"])
        if ".route(" in dec_str:
            return f"ROUTE {dec_str[dec_str.find('.route(') + 6:]}"

    return ""


def build_enriched_text(
    rel_path: str,
    symbol_name: str,
    chunk_type: str,
    signature: str,
    docstring: Optional[str],
    route_info: str,
    decorators: str,
    code: str,
) -> str:
    """构建用于向量化的高质量语义文本（增强路由、中文注释与上下文富化）"""
    lines = [
        f"文件路径: {rel_path}",
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


class PythonAstChunker:
    """针对 Python 代码的语义级 AST 切片器"""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def parse_file(self, file_path: Path) -> List[CodeChunk]:
        chunks: List[CodeChunk] = []
        try:
            rel_path = str(file_path.relative_to(self.repo_root)).replace("\\", "/")
        except ValueError:
            rel_path = str(file_path).replace("\\", "/")

        try:
            source = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            sys.stderr.write(f"[code-search-mcp] 读取文件异常 {file_path}: {e}\n")
            return []

        if not source.strip():
            return []

        source_lines = source.splitlines(keepends=True)
        total_lines = len(source_lines)

        try:
            tree = ast.parse(source, filename=str(file_path))
        except SyntaxError:
            # 语法解析错误（可能为旧版本 Python 代码），降级为全文件块
            doc = "（语法解析异常，降级保留）"
            enriched = build_enriched_text(rel_path, "[file]", "file", "", doc, "", "", source)
            return [
                CodeChunk(
                    id=str(uuid.uuid4()),
                    file_path=rel_path,
                    full_path=str(file_path),
                    symbol_name="[file]",
                    chunk_type="file",
                    start_line=1,
                    end_line=total_lines,
                    code=source,
                    docstring=None,
                    decorators="",
                    route_info="",
                    enriched_text=enriched,
                )
            ]

        module_doc = ast.get_docstring(tree)
        covered_lines = set()

        # 1. 遍历顶级节点
        for node in tree.body:
            # 顶级类
            if isinstance(node, ast.ClassDef):
                cls_start = node.lineno
                cls_end = getattr(node, "end_lineno", cls_start)
                cls_doc = ast.get_docstring(node)
                cls_name = node.name
                cls_decorators = ", ".join([ast.unparse(d) for d in getattr(node, "decorator_list", [])])

                # 记录类占据的行
                for l in range(cls_start, cls_end + 1):
                    covered_lines.add(l)

                cls_code = "".join(source_lines[cls_start - 1 : cls_end])
                cls_enriched = build_enriched_text(
                    rel_path, cls_name, "class", "", cls_doc, "", cls_decorators, cls_code
                )
                chunks.append(
                    CodeChunk(
                        id=str(uuid.uuid4()),
                        file_path=rel_path,
                        full_path=str(file_path),
                        symbol_name=cls_name,
                        chunk_type="class",
                        start_line=cls_start,
                        end_line=cls_end,
                        code=cls_code,
                        docstring=cls_doc,
                        decorators=cls_decorators,
                        route_info="",
                        enriched_text=cls_enriched,
                    )
                )

                # 提取类的方法
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        m_start = item.lineno
                        m_end = getattr(item, "end_lineno", m_start)
                        m_doc = ast.get_docstring(item)
                        m_name = f"{cls_name}.{item.name}"
                        m_sig = format_signature(item)
                        m_code = "".join(source_lines[m_start - 1 : m_end])
                        m_type = "async_method" if isinstance(item, ast.AsyncFunctionDef) else "method"
                        m_decorators = ", ".join([ast.unparse(d) for d in getattr(item, "decorator_list", [])])
                        m_route = extract_route_info(getattr(item, "decorator_list", []))

                        m_enriched = build_enriched_text(
                            rel_path, m_name, m_type, m_sig, m_doc, m_route, m_decorators, m_code
                        )
                        chunks.append(
                            CodeChunk(
                                id=str(uuid.uuid4()),
                                file_path=rel_path,
                                full_path=str(file_path),
                                symbol_name=m_name,
                                chunk_type=m_type,
                                start_line=m_start,
                                end_line=m_end,
                                code=m_code,
                                docstring=m_doc,
                                decorators=m_decorators,
                                route_info=m_route,
                                enriched_text=m_enriched,
                            )
                        )

            # 顶级函数
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                fn_start = node.lineno
                fn_end = getattr(node, "end_lineno", fn_start)
                fn_doc = ast.get_docstring(node)
                fn_name = node.name
                fn_sig = format_signature(node)
                fn_code = "".join(source_lines[fn_start - 1 : fn_end])
                fn_type = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
                fn_decorators = ", ".join([ast.unparse(d) for d in getattr(node, "decorator_list", [])])
                fn_route = extract_route_info(getattr(node, "decorator_list", []))

                for l in range(fn_start, fn_end + 1):
                    covered_lines.add(l)

                fn_enriched = build_enriched_text(
                    rel_path, fn_name, fn_type, fn_sig, fn_doc, fn_route, fn_decorators, fn_code
                )
                chunks.append(
                    CodeChunk(
                        id=str(uuid.uuid4()),
                        file_path=rel_path,
                        full_path=str(file_path),
                        symbol_name=fn_name,
                        chunk_type=fn_type,
                        start_line=fn_start,
                        end_line=fn_end,
                        code=fn_code,
                        docstring=fn_doc,
                        decorators=fn_decorators,
                        route_info=fn_route,
                        enriched_text=fn_enriched,
                    )
                )

        # 2. 顶层全局独立逻辑块
        top_uncovered = []
        for line_num, line in enumerate(source_lines, start=1):
            if line_num not in covered_lines and line.strip() and not line.strip().startswith("#"):
                top_uncovered.append((line_num, line))

        if top_uncovered:
            first_l = top_uncovered[0][0]
            last_l = top_uncovered[-1][0]
            top_code = "".join(l for _, l in top_uncovered)
            if len(top_code.strip()) > 30:
                top_enriched = build_enriched_text(
                    rel_path,
                    "[top_level]",
                    "top_level",
                    "",
                    module_doc,
                    "",
                    "",
                    top_code,
                )
                chunks.append(
                    CodeChunk(
                        id=str(uuid.uuid4()),
                        file_path=rel_path,
                        full_path=str(file_path),
                        symbol_name="[top_level]",
                        chunk_type="top_level",
                        start_line=first_l,
                        end_line=last_l,
                        code=top_code,
                        docstring=module_doc,
                        decorators="",
                        route_info="",
                        enriched_text=top_enriched,
                    )
                )

        return chunks


class CodeIndexer:
    """代码库扫描与向量化索引管理器"""

    def __init__(self, repo_path: str | Path):
        self.repo_path = Path(repo_path).resolve()
        self.db_path = get_repo_db_path(self.repo_path)
        self.embedding_engine = EmbeddingEngine.get_instance()

    def scan_files(self) -> List[Path]:
        """递归扫描所有有效的 Python 文件"""
        matched_files = []
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]
            for file in files:
                if file.endswith(".py") and file not in DEFAULT_IGNORE_FILES:
                    matched_files.append(Path(root) / file)
        return matched_files

    def index_all(self, batch_size: int = 32) -> Dict[str, Any]:
        """全量切片、提取架构大纲、向量化并存储至 LanceDB"""
        sys.stderr.write(f"[code-search-mcp] 开始扫描代码库: {self.repo_path}\n")
        files = self.scan_files()
        sys.stderr.write(f"[code-search-mcp] 找到 {len(files)} 个 Python 文件\n")

        # 生成并缓存全局架构大纲
        outline_gen = ProjectOutlineGenerator(self.repo_path)
        outline_gen.generate()

        chunker = PythonAstChunker(self.repo_path)
        all_chunks: List[CodeChunk] = []

        for f in files:
            file_chunks = chunker.parse_file(f)
            all_chunks.extend(file_chunks)

        total_chunks = len(all_chunks)
        sys.stderr.write(f"[code-search-mcp] 共切出 {total_chunks} 个语义代码块\n")

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
                    "symbol_name": chunk.symbol_name,
                    "chunk_type": chunk.chunk_type,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    "code": chunk.code,
                    "docstring": chunk.docstring or "",
                    "decorators": chunk.decorators,
                    "route_info": chunk.route_info,
                    "enriched_text": chunk.enriched_text,
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
