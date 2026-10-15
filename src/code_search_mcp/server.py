import json
import os
import sys
from pathlib import Path
from typing import Optional

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from code_search_mcp.indexer import CodeIndexer
from code_search_mcp.outline import ProjectOutlineGenerator
from code_search_mcp.ripgrep_engine import ExactSearchEngine, format_exact_results
from code_search_mcp.searcher import CodeSearcher, format_search_results, resolve_repo_path

# 创建 FastMCP 实例
mcp = FastMCP("code-search-mcp")


@mcp.tool()
def index_codebase(path: str) -> str:
    """扫描并索引指定路径下的 Python 代码库，生成用于语义搜索的向量数据库和项目架构大纲。

    Args:
        path: 代码库的根目录路径（支持相对路径或绝对路径）

    Returns:
        索引结果摘要（包含文件数和生成的代码块数）
    """
    try:
        repo_dir = Path(path).resolve()
        if not repo_dir.exists() or not repo_dir.is_dir():
            return f"错误: 路径 '{path}' 不存在或不是一个有效目录。"

        indexer = CodeIndexer(repo_dir)
        res = indexer.index_all()
        return (
            f"成功完成代码库索引！\n"
            f"- 目标路径: {res['repo_path']}\n"
            f"- 扫描 Python 文件数: {res['indexed_files']}\n"
            f"- 提取代码块数: {res['indexed_chunks']}\n"
            f"提示: 可随时调用 `get_codebase_outline()` 查看全局架构大纲。"
        )
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] index_codebase 发生错误: {e}\n")
        return f"索引代码库失败: {str(e)}"


@mcp.tool()
def get_codebase_outline(path: str = "", max_depth: int = 3) -> str:
    """获取代码库的全局架构大纲地图（极省 Token）。
    展示项目所有核心模块、文件职责摘要、包含的类与核心函数列表。
    【极力推荐】：在大仓库中接手新任务时，优先调用本工具快速理清项目拓扑与模块分布，避免盲目全盘搜索。

    Args:
        path: 代码库根目录路径（可选，未指定时默认使用当前或最近索引项目）
        max_depth: 遍历目录的最大层级（默认 3 层）

    Returns:
        精炼紧凑的项目架构大纲 Markdown
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "错误: 未能推断或找到目标代码库路径。请在参数中指定 path。"

        gen = ProjectOutlineGenerator(target_repo)
        outline_data = gen.get_cached_or_generate()
        return gen.format_as_markdown(outline_data, max_depth=max_depth)
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] get_codebase_outline 发生错误: {e}\n")
        return f"获取项目大纲失败: {str(e)}"


@mcp.tool()
def search_codebase(query: str, path: str = "", top_k: int = 5, compact: bool = True) -> str:
    """使用自然语言语义 + 符号精准加权搜索代码库，返回最相关的函数、类或接口片段。
    支持中英文混合理解、Web 路由接口识别与精确标识符匹配。

    Args:
        query: 自然语言查询语句，如“用户登录认证逻辑”、“POST /login 接口”、“数据库连接池配置”等
        path: 代码库根目录路径（可选，未指定时默认使用当前项目或最近一次索引的项目）
        top_k: 返回最相关的结果数量（默认 5 个）
        compact: 是否启用极简 Token 节省模式（默认 True：返回核心签名、摘要与核心前 10 行预览；False：输出完整实现代码）

    Returns:
        包含文件路径、行号范围、符号名称、Web 路由与代码片段的 Markdown 格式结果
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "错误: 未能推断或找到目标代码库路径。请在参数中提供 path，或先调用 index_codebase 进行索引。"

        searcher = CodeSearcher(target_repo)
        if not searcher.is_indexed():
            return (
                f"代码库 '{target_repo}' 尚未构建索引。\n"
                f"请先调用 `index_codebase(path='{target_repo}')` 生成索引后再进行检索。"
            )

        results = searcher.search(query=query, top_k=top_k)
        return format_search_results(results, query, compact=compact)
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] search_codebase 发生错误: {e}\n")
        return f"代码检索失败: {str(e)}"


@mcp.tool()
def exact_search(
    pattern: str,
    path: str = "",
    is_regex: bool = False,
    case_sensitive: bool = False,
    file_glob: str = "",
    max_results: int = 20,
) -> str:
    """使用底层工业级 ripgrep 极速精准检索确切代码字面量、变量常量、错误码、URL 路由或正则。
    【带证据（100% 确定性）】：当你想查找确切的代码标识符、配置文件 Key、错误字符串时优先调用，0 毫秒延时且绝无幻觉。

    Args:
        pattern: 目标文本或正则表达式（如 "SECRET_KEY"、"ERR_AUTH_EXPIRED"、"api/v1/auth"）
        path: 代码库根目录路径（可选，默认当前项目）
        is_regex: 是否为正则表达式（默认 False：纯文本精确匹配）
        case_sensitive: 是否区分大小写（默认 False：忽略大小写）
        file_glob: 文件通配符过滤（如 "*.py"、"*.env"、"*.json"）
        max_results: 最大返回结果数量（默认 20 条）

    Returns:
        带文件路径、行号标尺与高亮匹配行的 Markdown 证据报告
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "错误: 未能推断或找到目标代码库路径。请在参数中提供 path。"

        engine = ExactSearchEngine(target_repo)
        res = engine.search(
            pattern=pattern,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            file_glob=file_glob,
            max_results=max_results,
        )
        return format_exact_results(res)
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] exact_search 发生错误: {e}\n")
        return f"精准搜索失败: {str(e)}"


@mcp.tool()
def get_file_content(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """读取指定代码文件的内容，可限定行号范围（支持行号标注方便阅读）。
    配合 search_codebase 的 compact 模式与 exact_search 使用，按需精准展开目标代码，大幅节省上下文 Token。

    Args:
        path: 代码文件的相对路径或绝对路径
        start_line: 起始行号（1-based，可选）
        end_line: 结束行号（1-based，包含，可选）

    Returns:
        包含行号前缀的文件内容
    """
    try:
        file_path = Path(path).resolve()
        if not file_path.exists() or not file_path.is_file():
            return f"错误: 文件 '{path}' 不存在。"

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"无法读取文件 '{path}': {e}"

        lines = content.splitlines()
        total_lines = len(lines)

        s = 1 if start_line is None else max(1, start_line)
        e = total_lines if end_line is None else min(total_lines, end_line)

        if s > total_lines:
            return f"起始行号 {s} 超过文件总行数 {total_lines}。"
        if s > e:
            return f"起始行号 {s} 大于结束行号 {e}。"

        output_lines = [f"# 文件: {file_path.name} (第 {s} 至 {e} 行，共 {total_lines} 行)\n```python"]
        for i in range(s, e + 1):
            line_str = lines[i - 1]
            output_lines.append(f"{i:4d} | {line_str}")
        output_lines.append("```")

        return "\n".join(output_lines)
    except Exception as e:
        return f"获取文件内容失败: {str(e)}"


def run_server():
    """以标准 stdio 运行 FastMCP 服务"""
    mcp.run()


if __name__ == "__main__":
    run_server()
