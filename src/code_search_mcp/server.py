import json
import os
import sys
import time
from pathlib import Path
from typing import Optional

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
except ImportError:
    from mcp.server.fastmcp import FastMCP

from code_search_mcp.graph_engine import (
    CodeGraphEngine,
    format_callers_markdown,
    format_callees_markdown,
    format_impact_markdown,
    format_references_markdown,
)
from code_search_mcp.indexer import CodeIndexer
from code_search_mcp.outline import ProjectOutlineGenerator
from code_search_mcp.ripgrep_engine import ExactSearchEngine, format_exact_results
from code_search_mcp.searcher import CodeSearcher, format_search_results, resolve_repo_path
from code_search_mcp.watcher import get_or_create_watcher

# 创建 FastMCP 实例
mcp = FastMCP("code-search-mcp")


@mcp.tool()
def index_codebase(path: str, skip_vector: bool = False, force_vector: bool = False) -> str:
    """扫描并索引指定路径下的多语言代码库，生成代码知识图谱、架构大纲与向量数据库，并自动激活后台实时热监听器。

    Args:
        path: 代码库的根目录路径（支持相对路径或绝对路径）
        skip_vector: 是否跳过向量嵌入（默认 False；对 >2000 文件的超大仓库将自动开启以避免高负载与耗时，仅构建 CodeGraph 结构图与大纲）
        force_vector: 是否强制启用全量流式向量嵌入（默认 False；设为 True 时即使大仓库也执行真流式向量化，内存恒定极小）

    Returns:
        索引结果摘要（包含文件数、生成的代码块数与索引模式）
    """
    try:
        repo_dir = Path(path).resolve()
        if not repo_dir.exists() or not repo_dir.is_dir():
            return f"错误: 路径 '{path}' 不存在或不是一个有效目录。"

        indexer = CodeIndexer(repo_dir)
        res = indexer.index_all(skip_vector=skip_vector, force_vector=force_vector)

        # 自动启动该仓库的后台实时热监听器，后续任意代码保存操作均自动毫秒级增量同步
        get_or_create_watcher(repo_dir, auto_start=True)

        mode_str = "轻量结构化模式 (免向量)" if not res.get("vector_indexed", True) else "全量流式向量模式"

        return (
            f"成功完成代码库索引！\n"
            f"- 目标路径: {res['repo_path']}\n"
            f"- 索引模式: {mode_str}\n"
            f"- 扫描多语言源文件数: {res['indexed_files']}\n"
            f"- 提取代码块数: {res['indexed_chunks']}\n"
            f"- 📡 后台热更新监听器: 已启动 (监控 Python/TS/JS/Go/Java/Rust，改动保存即刻增量生效)\n"
            f"提示: 可随时调用 `get_codebase_outline()` 查看全局架构大纲，或使用 `get_watch_status()` 查看同步状态。"
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
    """【意图与概念语义检索】使用自然语言描述业务功能，通过 Dense 向量与 BM25 全文检索的 RRF 融合算法查找代码。

    🎯 适用场景：
    - 当你想按功能意图、业务概念或自然语言提问（如“用户登录认证流程”、“密码加密加盐”、“订单超时取消”、“支付回调处理”）寻找代码时；
    - 当你不知道确切的函数名或模块名，需要全局意图召回时。

    ⚠️ 适用边界：如果你已经知道确切的标识符名称、错误码（如 'ERR_AUTH'）、配置项 Key（如 'DATABASE_URL'）或特定字面量，请优先调用 `exact_search`。

    Args:
        query: 自然语言业务描述，如“用户登录认证逻辑”、“POST /login 接口实现”、“数据库连接池配置”等
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
    """【字面量与正则精准检索】基于底层工业级 ripgrep，极速查找确切代码文本、标识符、配置项、错误码或正则。

    🎯 适用场景：
    - 当你拥有确切的代码字面量时（如确切函数名 'verify_password'、配置项 Key 'SECRET_KEY'、错误码 'ERR_INVALID_TOKEN'）；
    - 当你想在全仓库中精确查找某个 API URL 路径字符串（如 '/api/v1/auth'）的所有引用位置；
    - 当你需要进行跨多文件的正则表达式查找时。

    ⚠️ 适用边界：如果你不知道确切的名字，只是想按模糊业务含义探索代码，请调用 `search_codebase`。

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


@mcp.tool()
def explore_codebase(query: str, path: str = "", top_k: int = 2) -> str:
    """【旗舰级探索工具（启发自 CodeGraph）】：1 次调用直出全链路业务上下文。
    自动结合自然语言语义检索与多语言代码知识图谱，聚合返回入口路由、核心实现、上下游依赖与源码证据，
    彻底避免多次调用 read/grep 翻找文件，极大节省 Token 与工具交互轮次。

    Args:
        query: 业务功能或架构疑问（如“用户登录鉴权与密码哈希校验流程”、“在线支付与退款逻辑”）
        path: 代码库根目录路径（可选，默认当前项目）
        top_k: 聚合的核心入口数量（默认 2 个）

    Returns:
        包含入口定义、外部路由、上游调用方、下游依赖及核心源码的手术级 Markdown 报告
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "错误: 未能推断或找到目标代码库路径。请在参数中提供 path。"

        engine = CodeGraphEngine.get_instance(target_repo)
        res = engine.explore_feature(query=query, top_k=top_k)
        if res.get("status") == "success":
            return res.get("surgical_context_markdown", "")
        return res.get("message", "探索失败")
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] explore_codebase 发生错误: {e}\n")
        return f"探索代码库失败: {str(e)}"


@mcp.tool()
def get_symbol_callers(symbol_name: str, path: str = "", limit: int = 30, offset: int = 0) -> str:
    """查询代码库中谁调用了该函数或类（Call Graph 上游调用关系追踪）。
    返回所有调用方符号、所在文件、行号、触发路由及代码预览。

    Args:
        symbol_name: 目标符号名称（如 "verify_password" 或 "AuthService.login"）
        path: 代码库根目录路径（可选，默认当前项目）

    Returns:
        上游调用者列表及代码证据 Markdown
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "错误: 未能推断或找到目标代码库路径。请在参数中提供 path。"

        engine = CodeGraphEngine.get_instance(target_repo)
        res = engine.get_callers(symbol_name)
        return format_callers_markdown(res)
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] get_symbol_callers 发生错误: {e}\n")
        return f"查询上游调用方失败: {str(e)}"


@mcp.tool()
def get_symbol_callees(symbol_name: str, path: str = "", limit: int = 50, offset: int = 0) -> str:
    """查询指定函数或方法内部直接调用的下游模块与函数列表（Call Graph 下游依赖追踪）。
    标明调用的符号是否在仓库内定义及其所在文件与功能说明。

    Args:
        symbol_name: 目标符号名称（如 "login_api" 或 "OrderManager.CreateOrder"）
        path: 代码库根目录路径（可选，默认当前项目）

    Returns:
        下游依赖清单 Markdown
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "错误: 未能推断或找到目标代码库路径。请在参数中提供 path。"

        engine = CodeGraphEngine.get_instance(target_repo)
        res = engine.get_callees(symbol_name)
        return format_callees_markdown(res)
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] get_symbol_callees 发生错误: {e}\n")
        return f"查询下游依赖失败: {str(e)}"


@mcp.tool()
def get_impact_radius(symbol_name: str, path: str = "", max_depth: int = 3) -> str:
    """【改动影响面分析（Blast Radius）】：在重构或修改代码前调用，
    通过调用图扩散分析该符号被哪些上游模块、测试和外部 Web/API 路由直接或间接依赖，防止改出未预料的线上 Bug。

    Args:
        symbol_name: 准备修改的目标符号（如 "hash_password"、"processPayment"）
        path: 代码库根目录路径（可选，默认当前项目）
        max_depth: 追踪扩散的最大层级（默认 3 层）

    Returns:
        爆炸半径评估报告（包含受影响符号数、文件清单、受波及 API 路由及扩散树）
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "错误: 未能推断或找到目标代码库路径。请在参数中提供 path。"

        engine = CodeGraphEngine.get_instance(target_repo)
        res = engine.get_impact_radius(symbol_name, max_depth=max_depth)
        return format_impact_markdown(res)
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] get_impact_radius 发生错误: {e}\n")
        return f"影响面分析失败: {str(e)}"


@mcp.tool()
def find_references(symbol_or_keyword: str, path: str = "") -> str:
    """全仓库跨模块反向引用查询 (Find All References, Fix #20)。
    同时聚合 AST 结构化调用者 (Structural Callers) 与 ripgrep 跨文件字面量/配置项引用 (Textual References)。
    适用场景：查询某个 API、函数、错误码或配置项在全仓库中被哪些地方读取或调用。

    Args:
        symbol_or_keyword: 目标函数名、方法名、配置项 Key、错误码或文本
        path: 代码库根目录路径（可选，未指定时默认当前项目）

    Returns:
        包含显式代码调用与配置文件字面量引用的完整 Markdown 报告
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "错误: 未能推断或找到目标代码库路径。请在参数中提供 path。"

        graph = CodeGraphEngine.get_instance(target_repo)
        res = graph.find_references(symbol_or_keyword)
        return format_references_markdown(res)
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] find_references 发生错误: {e}\n")
        return f"查询反向引用失败: {str(e)}"


@mcp.tool()
def get_watch_status(path: str = "") -> str:
    """获取代码库实时热监听器（Watcher）的运行状态与增量同步历史。
    实时监控 Python/TS/JS/Go 源文件的保存与增删，毫秒级增量更新索引。

    Args:
        path: 代码库根目录路径（可选，默认当前项目）

    Returns:
        包含监听器状态、防抖配置、同步统计与最近事件的 Markdown 报告
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "错误: 未能推断或找到目标代码库路径。"

        watcher = get_or_create_watcher(target_repo, auto_start=False)
        is_active = watcher.is_running
        status_badge = "🟢 正在运行 (Active)" if is_active else "⚪ 未启动 (Inactive)"

        lines = [
            "### 📡 代码库实时热监听状态 (Watch Status)",
            f"- **监控仓库**: `{target_repo}`",
            f"- **当前状态**: {status_badge}",
            f"- **防抖延迟**: {watcher.debounce_ms} ms (连续保存聚合)",
            f"- **已完成同步次数**: {watcher.sync_count} 次",
            f"- **最近同步时间**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(watcher.last_sync_time)) if watcher.last_sync_time else '暂无变更同步'}",
        ]

        if not is_active:
            lines.append("\n> 💡 提示: 监听器未启动。可调用 `index_codebase()` 建立索引并自动激活后台热监听。")
        else:
            lines.append("\n> ⚡ 提示: 当您在编辑器中保存代码时，后台将自动在 0.3s 内完成 AST 解析与向量增量同步，无需重新全量索引。")

        if watcher.recent_events:
            lines.append("\n#### ⏱️ 最近文件同步历史 (Recent Sync Events)")
            lines.append("| 触发时间 | 变更文件 | 同步动作 | 提取代码块 |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for ev in reversed(watcher.recent_events[-10:]):
                action = "增量更新" if ev.get("status") == "updated" else "移除索引"
                lines.append(f"| {ev.get('time')} | `{ev.get('file')}` | {action} | {ev.get('chunks', 0)} |")

        return "\n".join(lines)
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] get_watch_status 发生错误: {e}\n")
        return f"获取监听状态失败: {str(e)}"


def run_server():
    """以标准 stdio 运行 FastMCP 服务，并在启动时对已知仓库自动拉起热监听"""
    try:
        target_repo = resolve_repo_path("")
        if target_repo and target_repo.exists():
            db_dir = target_repo / ".code_search"
            if db_dir.exists():
                get_or_create_watcher(target_repo, auto_start=True)
    except Exception as e:
        sys.stderr.write(f"[code-search-mcp] 服务启动自动拉起热监听异常: {e}\n")

    mcp.run()


if __name__ == "__main__":
    run_server()
