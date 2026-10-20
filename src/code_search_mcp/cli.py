import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from code_search_mcp.indexer import CodeIndexer
from code_search_mcp.outline import ProjectOutlineGenerator
from code_search_mcp.ripgrep_engine import ExactSearchEngine
from code_search_mcp.searcher import CodeSearcher, resolve_repo_path
from code_search_mcp.server import run_server
from code_search_mcp.ui import (
    console,
    print_banner,
    print_cache_table,
    print_clean_result,
    print_error,
    print_exact_results,
    print_index_result,
    print_markdown,
    print_search_results,
    print_watch_banner,
)

# 确保在 Windows 控制台环境下正常输出 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


app = typer.Typer(
    name="code-search-mcp",
    help="""
⚡ code-search-mcp: 本地轻量代码语义搜索与图谱分析引擎 (AST + Vector + BM25 + Ripgrep)

常用命令示例 (Examples):
  code-search-mcp index .                           # 扫描并为当前代码库构建语义与 AST 索引
  code-search-mcp search "用户登录认证与密码校验"   # 语义混合检索 (高亮语法代码块)
  code-search-mcp exact "hash_password"             # 使用 ripgrep 极速精准字面量/正则查找
  code-search-mcp outline                           # 生成多语言全局架构骨架大纲 (极省 Token)
  code-search-mcp explore "用户注册与鉴权流程"      # 一键全链路业务手术级探索 (CodeGraph 风格)
  code-search-mcp callers "verify_token"            # 查询谁调用了指定函数或类
  code-search-mcp callees "AuthService.login"       # 查询指定函数直接依赖调用的下游符号
  code-search-mcp impact "User" --depth 3           # 改动爆炸半径分析 (跨文件反向传递)
  code-search-mcp cache                             # 查看全局索引缓存清单与磁盘占用
  code-search-mcp clean --orphaned                  # 一键安全清理孤儿幽灵缓存释放空间
  code-search-mcp install                           # 一键向导式配置 Claude/Cursor/Windsurf MCP
""",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
)


@app.callback(invoke_without_command=True)
def main_callback(ctx: typer.Context):
    """code-search-mcp 核心入口与全局调度"""
    if ctx.invoked_subcommand is None:
        # 如果不是在交互式终端运行（如 Claude Desktop / Cursor 等以 stdio 管道接入），启动 MCP 服务
        if not sys.stdin.isatty():
            run_server()
        else:
            print_banner()
            console.print(ctx.get_help())
            raise typer.Exit(code=0)


@app.command("serve", help="以 MCP stdio 协议启动服务")
def serve_cmd():
    run_server()


@app.command("index", help="扫描并索引指定代码库")
def index_cmd(
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="代码库根目录路径（位置参数，与 --path 等价，默认当前目录）",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="代码库根目录路径（与位置参数等价，默认当前目录）",
    ),
    skip_vector: bool = typer.Option(
        False,
        "--skip-vector",
        help="跳过向量嵌入，仅构建 CodeGraph 结构调用图与架构大纲（超大仓库秒级索引，零内存压力）",
    ),
    force_vector: bool = typer.Option(
        False,
        "--force-vector",
        help="强制启用全量流式向量嵌入（即使仓库源文件数超过阈值）",
    ),
    threshold: int = typer.Option(
        2000,
        "--threshold",
        help="自动切换轻量模式的文件数阈值（默认 2000）",
    ),
):
    raw_path = path or positional_path or "."
    target = Path(raw_path).resolve()
    if not target.exists() or not target.is_dir():
        print_error(f"目标路径 '{target}' 不存在或非目录")
        raise typer.Exit(code=1)

    indexer = CodeIndexer(target)
    t0 = time.perf_counter()
    with console.status(f"[bold cyan]正在解析代码库并构建向量与 AST 索引 ({target.name})...[/bold cyan]", spinner="dots"):
        res = indexer.index_all(
            skip_vector=skip_vector,
            force_vector=force_vector,
            vector_threshold=threshold,
        )
    elapsed = time.perf_counter() - t0
    print_index_result(res, elapsed_seconds=elapsed)


@app.command("outline", help="查看代码库全局架构大纲地图")
def outline_cmd(
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="代码库根目录路径（位置参数，与 --path 等价，默认当前或最近索引项目）",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="目标代码库路径（默认当前或最近索引项目）",
    ),
):
    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("未找到目标代码库")
        raise typer.Exit(code=1)

    with console.status("[bold cyan]正在提取代码库全局架构骨架地图...[/bold cyan]", spinner="dots"):
        gen = ProjectOutlineGenerator(target)
        outline_data = gen.get_cached_or_generate()
    print_markdown(gen.format_as_markdown(outline_data))


@app.command("search", help="语义搜索已索引的代码")
def search_cmd(
    query: str = typer.Argument(..., help="自然语言搜索关键词"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="目标代码库路径（位置参数，与 --path 等价）",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="目标代码库路径（默认当前或最近索引项目）",
    ),
    top_k: int = typer.Option(
        5,
        "--top-k",
        "-k",
        help="返回结果数量（默认 5）",
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help="是否输出完整代码（默认紧凑模式节省 Token）",
    ),
):
    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("未找到目标代码库，请先执行 index 命令")
        raise typer.Exit(code=1)

    searcher = CodeSearcher(target)
    if not searcher.is_indexed():
        console.print(f"[yellow]提示: 代码库 '{target}' 尚未建立索引，正在为您自动建立初始索引...[/yellow]")
        indexer = CodeIndexer(target)
        indexer.index_all()

    with console.status("[bold cyan]正在执行混合多路召回检索 (RRF + Vector + BM25)...[/bold cyan]", spinner="dots"):
        results = searcher.search(query, top_k=top_k)
    print_search_results(results, query, target, compact=not full)


@app.command("exact", help="使用 ripgrep 极速精准字面量/正则搜索")
def exact_cmd(
    pattern: str = typer.Argument(..., help="要搜索的确切文本或正则表达式"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="目标代码库路径（位置参数，与 --path 等价）",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="目标代码库路径（默认当前或最近索引项目）",
    ),
    regex: bool = typer.Option(
        False,
        "--regex",
        "-r",
        help="启用正则表达式匹配",
    ),
    case_sensitive: bool = typer.Option(
        False,
        "--case-sensitive",
        "-c",
        help="区分大小写",
    ),
    glob: str = typer.Option(
        "",
        "--glob",
        "-g",
        help="文件通配符过滤（如 '*.py'）",
    ),
    max_results: int = typer.Option(
        20,
        "--max",
        "-m",
        help="最大结果数量（默认 20）",
    ),
):
    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("未找到目标代码库")
        raise typer.Exit(code=1)

    engine = ExactSearchEngine(target)
    with console.status(f"[bold magenta]正在调用 Ripgrep 极速检索: {pattern}...[/bold magenta]", spinner="dots"):
        res = engine.search(
            pattern=pattern,
            is_regex=regex,
            case_sensitive=case_sensitive,
            file_glob=glob,
            max_results=max_results,
        )
    print_exact_results(res)


@app.command("explore", help="一键直达全链路业务探索（CodeGraph 风格）")
def explore_cmd(
    query: str = typer.Argument(..., help="业务问题或功能描述"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="目标代码库路径（位置参数，与 --path 等价）",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="目标代码库路径",
    ),
    top_k: int = typer.Option(
        2,
        "--top-k",
        "-k",
        help="聚合的核心入口数（默认 2）",
    ),
):
    from code_search_mcp.graph_engine import CodeGraphEngine

    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("未找到目标代码库")
        raise typer.Exit(code=1)

    engine = CodeGraphEngine(target)
    with console.status(f"[bold cyan]正在执行业务全链路拓扑分析: {query}...[/bold cyan]", spinner="dots"):
        res = engine.explore_feature(query, top_k=top_k)
    if res.get("status") == "success":
        print_markdown(res.get("surgical_context_markdown", ""))
    else:
        print_error(res.get("message", "探索失败"))
        raise typer.Exit(code=1)


@app.command("callers", help="查询谁调用了指定函数或类")
def callers_cmd(
    symbol: str = typer.Argument(..., help="目标符号名称"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="目标代码库路径（位置参数，与 --path 等价）",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="目标代码库路径",
    ),
):
    from code_search_mcp.graph_engine import CodeGraphEngine, format_callers_markdown

    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("未找到目标代码库")
        raise typer.Exit(code=1)

    engine = CodeGraphEngine(target)
    with console.status(f"[bold cyan]正在追踪 '{symbol}' 的上游调用方...[/bold cyan]", spinner="dots"):
        res = engine.get_callers(symbol)
    print_markdown(format_callers_markdown(res))


@app.command("callees", help="查询指定函数直接调用的下游模块")
def callees_cmd(
    symbol: str = typer.Argument(..., help="目标符号名称"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="目标代码库路径（位置参数，与 --path 等价）",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="目标代码库路径",
    ),
):
    from code_search_mcp.graph_engine import CodeGraphEngine, format_callees_markdown

    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("未找到目标代码库")
        raise typer.Exit(code=1)

    engine = CodeGraphEngine(target)
    with console.status(f"[bold cyan]正在追踪 '{symbol}' 的下游依赖调用...[/bold cyan]", spinner="dots"):
        res = engine.get_callees(symbol)
    print_markdown(format_callees_markdown(res))


@app.command("impact", help="改动影响面/爆炸半径分析")
def impact_cmd(
    symbol: str = typer.Argument(..., help="准备修改的目标符号"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="目标代码库路径（位置参数，与 --path 等价）",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="目标代码库路径",
    ),
    depth: int = typer.Option(
        3,
        "--depth",
        "-d",
        help="追踪最大层级（默认 3）",
    ),
):
    from code_search_mcp.graph_engine import CodeGraphEngine, format_impact_markdown

    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("未找到目标代码库")
        raise typer.Exit(code=1)

    engine = CodeGraphEngine(target)
    with console.status(f"[bold cyan]正在计算 '{symbol}' 的改动爆炸半径...[/bold cyan]", spinner="dots"):
        res = engine.get_impact_radius(symbol, max_depth=depth)
    print_markdown(format_impact_markdown(res))


@app.command("watch", help="启动前台实时热更新文件监控器")
def watch_cmd(
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="代码库根目录路径（位置参数，与 --path 等价，默认当前或最近索引项目）",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="目标代码库路径（默认当前或最近索引项目）",
    ),
    debounce: int = typer.Option(
        1500,
        "--debounce",
        "-d",
        help="防抖延迟毫秒数（默认 1500ms）",
    ),
):
    from code_search_mcp.watcher import RepoWatcher

    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("未找到目标代码库")
        raise typer.Exit(code=1)

    print_watch_banner(target, debounce)

    watcher = RepoWatcher(target, debounce_ms=debounce)
    watcher.start()
    try:
        while watcher.is_running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        watcher.stop()
        console.print("\n[bold yellow]👋 已安全停止监控[/bold yellow]\n")


@app.command("install", help="一键全自动安装并配置 Claude/Cursor/Windsurf/Cline MCP 与规范")
def install_cmd(
    clients: str = typer.Option(
        "all",
        "--clients",
        "-c",
        help="要配置的目标客户端（如 claude-code,cursor 或 all，默认 all）",
    ),
    mode: str = typer.Option(
        "auto",
        "--mode",
        "-m",
        help="MCP 启动运行模式（auto / uvx / uv / python / docker，默认 auto 自动检测）",
    ),
    repo: str = typer.Option(
        "",
        "--repo",
        "-r",
        help="目标代码库根目录路径（用于初始化规则，默认当前目录）",
    ),
    no_rules: bool = typer.Option(
        False,
        "--no-rules",
        help="跳过自动写入 CLAUDE.md 与 .cursorrules 规范",
    ),
):
    from code_search_mcp.installer import run_installer

    target = Path(repo).resolve() if repo else Path.cwd().resolve()
    client_list = [c.strip().lower() for c in clients.split(",")] if clients != "all" else None
    run_installer(
        clients=client_list,
        mode=mode,
        target_repo=target,
        write_rules=not no_rules,
    )


@app.command("cache", help="查看全局索引缓存清单与磁盘占用")
def cache_cmd(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="以 JSON 格式输出统计信息",
    ),
):
    import json
    from datetime import datetime
    from code_search_mcp.cache_manager import CacheManager

    mgr = CacheManager()
    summary = mgr.get_summary()

    if json_output:
        entries = [
            {
                "hash": e.hash_id,
                "repo_path": e.repo_path,
                "repo_exists": e.repo_exists,
                "size_mb": e.size_mb,
                "indexed_files": e.indexed_files,
                "indexed_chunks": e.indexed_chunks,
                "last_updated": datetime.fromtimestamp(e.last_updated).strftime("%Y-%m-%d %H:%M:%S") if e.last_updated else None,
            }
            for e in mgr.list_entries()
        ]
        print(json.dumps({"summary": summary, "entries": entries}, ensure_ascii=False, indent=2))
    else:
        entries = mgr.list_entries()
        print_cache_table(summary, entries)


@app.command("clean", help="清理代码库索引缓存与无用临时数据")
def clean_cmd(
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="目标代码库路径（位置参数，与 --path 等价）",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="仅清理指定代码库的缓存（默认当前或指定项目）",
    ),
    all_caches: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="清空所有代码库的缓存数据",
    ),
    orphaned: bool = typer.Option(
        False,
        "--orphaned",
        "-o",
        help="仅清理项目源目录已不存在的孤儿幽灵缓存（默认推荐）",
    ),
    days: Optional[int] = typer.Option(
        None,
        "--days",
        "-d",
        help="清理超过指定天数未更新的陈旧缓存",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="模拟预览将要清理的内容和释放的磁盘空间，不实际删除",
    ),
):
    from code_search_mcp.cache_manager import CacheManager

    mgr = CacheManager()
    clean_target = path or positional_path or None
    is_orphaned = orphaned or (not all_caches and not days and not clean_target)
    res = mgr.clean(
        all_caches=all_caches,
        orphaned_only=is_orphaned,
        older_than_days=days,
        target_repo=clean_target,
        dry_run=dry_run,
    )
    print_clean_result(res)


def main():
    app(prog_name="code-search-mcp")


if __name__ == "__main__":
    main()
