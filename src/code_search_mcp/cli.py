import argparse
import sys
import time
from pathlib import Path

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


def main():
    parser = argparse.ArgumentParser(
        prog="code-search-mcp",
        description="""
  ___          _        ___                       _      
 / __|___  __| |___   / __| ___ __ _ _ _ __ |_ |__   
| (__/ _ \/ _` / -_)  \__ \/ -_) _` | '_/ _| ' \  / -_) 
 \___\___/\__,_\___|  |___/\___\__,_|_| \__|_||_| \___|  ⚡ MCP

⚡ 本地轻量代码语义搜索与图谱分析引擎 (AST + Vector + BM25 + Ripgrep)
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
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
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # index 子命令
    index_parser = subparsers.add_parser("index", help="扫描并索引指定代码库")
    index_parser.add_argument(
        "path",
        nargs="?",
        default=".",
        help="代码库根目录路径（默认当前目录）",
    )
    index_parser.add_argument(
        "--skip-vector",
        action="store_true",
        help="跳过向量嵌入，仅构建 CodeGraph 结构调用图与架构大纲（超大仓库秒级索引，零内存压力）",
    )
    index_parser.add_argument(
        "--force-vector",
        action="store_true",
        help="强制启用全量流式向量嵌入（即使仓库源文件数超过阈值）",
    )
    index_parser.add_argument(
        "--threshold",
        type=int,
        default=2000,
        help="自动切换轻量模式的文件数阈值（默认 2000）",
    )

    # outline 子命令
    outline_parser = subparsers.add_parser("outline", help="查看代码库全局架构大纲地图")
    outline_parser.add_argument(
        "path",
        nargs="?",
        default="",
        help="代码库根目录路径（默认当前或最近索引项目）",
    )

    # search 子命令 (语义 + 混合)
    search_parser = subparsers.add_parser("search", help="语义搜索已索引的代码")
    search_parser.add_argument("query", help="自然语言搜索关键词")
    search_parser.add_argument(
        "--path",
        "-p",
        default="",
        help="目标代码库路径（默认当前或最近索引项目）",
    )
    search_parser.add_argument(
        "--top-k",
        "-k",
        type=int,
        default=5,
        help="返回结果数量（默认 5）",
    )
    search_parser.add_argument(
        "--full",
        action="store_true",
        help="是否输出完整代码（默认紧凑模式节省 Token）",
    )

    # exact 子命令 (ripgrep 精确匹配)
    exact_parser = subparsers.add_parser("exact", help="使用 ripgrep 极速精准字面量/正则搜索")
    exact_parser.add_argument("pattern", help="要搜索的确切文本或正则表达式")
    exact_parser.add_argument(
        "--path",
        "-p",
        default="",
        help="目标代码库路径（默认当前或最近索引项目）",
    )
    exact_parser.add_argument(
        "--regex",
        "-r",
        action="store_true",
        help="启用正则表达式匹配",
    )
    exact_parser.add_argument(
        "--case-sensitive",
        "-c",
        action="store_true",
        help="区分大小写",
    )
    exact_parser.add_argument(
        "--glob",
        "-g",
        default="",
        help="文件通配符过滤（如 '*.py'）",
    )
    exact_parser.add_argument(
        "--max",
        "-m",
        type=int,
        default=20,
        help="最大结果数量（默认 20）",
    )

    # explore 子命令 (一键手术级探索)
    explore_parser = subparsers.add_parser("explore", help="一键直达全链路业务探索（CodeGraph 风格）")
    explore_parser.add_argument("query", help="业务问题或功能描述")
    explore_parser.add_argument("--path", "-p", default="", help="目标代码库路径")
    explore_parser.add_argument("--top-k", "-k", type=int, default=2, help="聚合的核心入口数（默认 2）")

    # callers 子命令 (上游调用追踪)
    callers_parser = subparsers.add_parser("callers", help="查询谁调用了指定函数或类")
    callers_parser.add_argument("symbol", help="目标符号名称")
    callers_parser.add_argument("--path", "-p", default="", help="目标代码库路径")

    # callees 子命令 (下游依赖追踪)
    callees_parser = subparsers.add_parser("callees", help="查询指定函数直接调用的下游模块")
    callees_parser.add_argument("symbol", help="目标符号名称")
    callees_parser.add_argument("--path", "-p", default="", help="目标代码库路径")

    # impact 子命令 (改动影响面分析)
    impact_parser = subparsers.add_parser("impact", help="改动影响面/爆炸半径分析")
    impact_parser.add_argument("symbol", help="准备修改的目标符号")
    impact_parser.add_argument("--path", "-p", default="", help="目标代码库路径")
    impact_parser.add_argument("--depth", "-d", type=int, default=3, help="追踪最大层级（默认 3）")

    # watch 子命令 (实时热监控增量更新)
    watch_parser = subparsers.add_parser("watch", help="启动前台实时热更新文件监控器")
    watch_parser.add_argument("path", nargs="?", default="", help="代码库根目录路径（默认当前或最近索引项目）")
    watch_parser.add_argument("--debounce", "-d", type=int, default=1500, help="防抖延迟毫秒数（默认 1500ms）")

    # install 子命令 (一键全自动配置 Claude Desktop / Claude Code / Cursor / Windsurf / Cline)
    install_parser = subparsers.add_parser("install", help="一键全自动安装并配置 Claude/Cursor/Windsurf/Cline MCP 与规范")
    install_parser.add_argument("--clients", "-c", default="all", help="要配置的目标客户端（如 claude-code,cursor 或 all，默认 all）")
    install_parser.add_argument("--mode", "-m", choices=["auto", "uvx", "uv", "python", "docker"], default="auto", help="MCP 启动运行模式（默认 auto 自动检测）")
    install_parser.add_argument("--repo", "-r", default="", help="目标代码库根目录路径（用于初始化规则，默认当前目录）")
    install_parser.add_argument("--no-rules", action="store_true", help="跳过自动写入 CLAUDE.md 与 .cursorrules 规范")

    # cache 子命令 (查看全局缓存状态与占用)
    cache_parser = subparsers.add_parser("cache", help="查看全局索引缓存清单与磁盘占用")
    cache_parser.add_argument("--json", action="store_true", help="以 JSON 格式输出统计信息")

    # clean 子命令 (清理缓存与释放磁盘空间)
    clean_parser = subparsers.add_parser("clean", help="清理代码库索引缓存与无用临时数据")
    clean_parser.add_argument("--all", "-a", action="store_true", help="清空所有代码库的缓存数据")
    clean_parser.add_argument("--orphaned", "-o", action="store_true", help="仅清理项目源目录已不存在的孤儿幽灵缓存（默认推荐）")
    clean_parser.add_argument("--days", "-d", type=int, default=None, help="清理超过指定天数未更新的陈旧缓存")
    clean_parser.add_argument("--path", "-p", default="", help="仅清理指定代码库的缓存（默认当前或指定项目）")
    clean_parser.add_argument("--dry-run", action="store_true", help="模拟预览将要清理的内容和释放的磁盘空间，不实际删除")

    # serve 子命令（默认或作为 MCP 启动）
    serve_parser = subparsers.add_parser("serve", help="以 MCP stdio 协议启动服务")

    args = parser.parse_args()

    # 如果无参数
    if args.command is None:
        # 如果是在交互式控制台直接运行，展示美化 Banner 与命令引导
        if sys.stdin.isatty():
            print_banner()
            parser.print_help()
            return
        else:
            # 否则作为 MCP stdio 协议运行服务
            run_server()
            return

    if args.command == "serve":
        run_server()
        return

    if args.command == "index":
        target = Path(args.path).resolve()
        if not target.exists() or not target.is_dir():
            print_error(f"目标路径 '{target}' 不存在或非目录")
            sys.exit(1)
        indexer = CodeIndexer(target)
        t0 = time.perf_counter()
        with console.status(f"[bold cyan]正在解析代码库并构建向量与 AST 索引 ({target.name})...[/bold cyan]", spinner="dots"):
            res = indexer.index_all(
                skip_vector=args.skip_vector,
                force_vector=args.force_vector,
                vector_threshold=args.threshold,
            )
        elapsed = time.perf_counter() - t0
        print_index_result(res, elapsed_seconds=elapsed)

    elif args.command == "outline":
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print_error("未找到目标代码库")
            sys.exit(1)
        with console.status("[bold cyan]正在提取代码库全局架构骨架地图...[/bold cyan]", spinner="dots"):
            gen = ProjectOutlineGenerator(target)
            outline_data = gen.get_cached_or_generate()
        print_markdown(gen.format_as_markdown(outline_data))

    elif args.command == "search":
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print_error("未找到目标代码库，请先执行 index 命令")
            sys.exit(1)
        searcher = CodeSearcher(target)
        if not searcher.is_indexed():
            console.print(f"[yellow]提示: 代码库 '{target}' 尚未建立索引，正在为您自动建立初始索引...[/yellow]")
            indexer = CodeIndexer(target)
            indexer.index_all()

        with console.status("[bold cyan]正在执行混合多路召回检索 (RRF + Vector + BM25)...[/bold cyan]", spinner="dots"):
            results = searcher.search(args.query, top_k=args.top_k)
        print_search_results(results, args.query, target, compact=not args.full)

    elif args.command == "exact":
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print_error("未找到目标代码库")
            sys.exit(1)
        engine = ExactSearchEngine(target)
        with console.status(f"[bold magenta]正在调用 Ripgrep 极速检索: {args.pattern}...[/bold magenta]", spinner="dots"):
            res = engine.search(
                pattern=args.pattern,
                is_regex=args.regex,
                case_sensitive=args.case_sensitive,
                file_glob=args.glob,
                max_results=args.max,
            )
        print_exact_results(res)

    elif args.command == "explore":
        from code_search_mcp.graph_engine import CodeGraphEngine
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print_error("未找到目标代码库")
            sys.exit(1)
        engine = CodeGraphEngine(target)
        with console.status(f"[bold cyan]正在执行业务全链路拓扑分析: {args.query}...[/bold cyan]", spinner="dots"):
            res = engine.explore_feature(args.query, top_k=args.top_k)
        if res.get("status") == "success":
            print_markdown(res.get("surgical_context_markdown", ""))
        else:
            print_error(res.get("message", "探索失败"))

    elif args.command == "callers":
        from code_search_mcp.graph_engine import CodeGraphEngine, format_callers_markdown
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print_error("未找到目标代码库")
            sys.exit(1)
        engine = CodeGraphEngine(target)
        with console.status(f"[bold cyan]正在追踪 '{args.symbol}' 的上游调用方...[/bold cyan]", spinner="dots"):
            res = engine.get_callers(args.symbol)
        print_markdown(format_callers_markdown(res))

    elif args.command == "callees":
        from code_search_mcp.graph_engine import CodeGraphEngine, format_callees_markdown
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print_error("未找到目标代码库")
            sys.exit(1)
        engine = CodeGraphEngine(target)
        with console.status(f"[bold cyan]正在追踪 '{args.symbol}' 的下游依赖调用...[/bold cyan]", spinner="dots"):
            res = engine.get_callees(args.symbol)
        print_markdown(format_callees_markdown(res))

    elif args.command == "impact":
        from code_search_mcp.graph_engine import CodeGraphEngine, format_impact_markdown
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print_error("未找到目标代码库")
            sys.exit(1)
        engine = CodeGraphEngine(target)
        with console.status(f"[bold cyan]正在计算 '{args.symbol}' 的改动爆炸半径...[/bold cyan]", spinner="dots"):
            res = engine.get_impact_radius(args.symbol, max_depth=args.depth)
        print_markdown(format_impact_markdown(res))

    elif args.command == "watch":
        from code_search_mcp.watcher import RepoWatcher

        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print_error("未找到目标代码库")
            sys.exit(1)

        print_watch_banner(target, args.debounce)

        watcher = RepoWatcher(target, debounce_ms=args.debounce)
        watcher.start()
        try:
            while watcher.is_running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            watcher.stop()
            console.print("\n[bold yellow]👋 已安全停止监控[/bold yellow]\n")

    elif args.command == "install":
        from code_search_mcp.installer import run_installer

        target = Path(args.repo).resolve() if args.repo else Path.cwd().resolve()
        client_list = [c.strip().lower() for c in args.clients.split(",")] if args.clients != "all" else None
        run_installer(
            clients=client_list,
            mode=args.mode,
            target_repo=target,
            write_rules=not args.no_rules,
        )

    elif args.command == "cache":
        import json
        from datetime import datetime
        from code_search_mcp.cache_manager import CacheManager

        mgr = CacheManager()
        summary = mgr.get_summary()

        if args.json:
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

    elif args.command == "clean":
        from code_search_mcp.cache_manager import CacheManager

        mgr = CacheManager()
        # 如果未指定特殊参数，默认以孤儿清理为主
        is_orphaned = args.orphaned or (not args.all and not args.days and not args.path)
        res = mgr.clean(
            all_caches=args.all,
            orphaned_only=is_orphaned,
            older_than_days=args.days,
            target_repo=args.path if args.path else None,
            dry_run=args.dry_run,
        )
        print_clean_result(res)


if __name__ == "__main__":
    main()
