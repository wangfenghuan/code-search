import argparse
import sys
from pathlib import Path

from code_search_mcp.indexer import CodeIndexer
from code_search_mcp.outline import ProjectOutlineGenerator
from code_search_mcp.ripgrep_engine import ExactSearchEngine, format_exact_results
from code_search_mcp.searcher import CodeSearcher, format_search_results, resolve_repo_path
from code_search_mcp.server import run_server

# 确保在 Windows 控制台环境下正常输出 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(
        description="code-search-mcp: 本地轻量代码语义搜索 MCP 服务与 CLI 工具"
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

    # 如果无参数，默认以 MCP stdio 运行服务
    if args.command is None or args.command == "serve":
        run_server()
        return

    if args.command == "index":
        target = Path(args.path).resolve()
        if not target.exists() or not target.is_dir():
            print(f"错误: 目标路径 '{target}' 不存在或非目录", file=sys.stderr)
            sys.exit(1)
        indexer = CodeIndexer(target)
        res = indexer.index_all()
        print(f"✅ 索引成功！代码库: {res['repo_path']}")
        print(f"   扫描文件: {res['indexed_files']} 个 | 切片代码块: {res['indexed_chunks']} 个")

    elif args.command == "outline":
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print("错误: 未找到目标代码库", file=sys.stderr)
            sys.exit(1)
        gen = ProjectOutlineGenerator(target)
        outline_data = gen.get_cached_or_generate()
        print(gen.format_as_markdown(outline_data))

    elif args.command == "search":
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print("错误: 未找到目标代码库，请先执行 index 命令", file=sys.stderr)
            sys.exit(1)
        searcher = CodeSearcher(target)
        if not searcher.is_indexed():
            print(f"提示: 代码库 '{target}' 尚未建立索引，正在为您自动建立初始索引...", file=sys.stderr)
            indexer = CodeIndexer(target)
            indexer.index_all()

        results = searcher.search(args.query, top_k=args.top_k)
        print(format_search_results(results, args.query, compact=not args.full))

    elif args.command == "exact":
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print("错误: 未找到目标代码库", file=sys.stderr)
            sys.exit(1)
        engine = ExactSearchEngine(target)
        res = engine.search(
            pattern=args.pattern,
            is_regex=args.regex,
            case_sensitive=args.case_sensitive,
            file_glob=args.glob,
            max_results=args.max,
        )
        print(format_exact_results(res))

    elif args.command == "explore":
        from code_search_mcp.graph_engine import CodeGraphEngine
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print("错误: 未找到目标代码库", file=sys.stderr)
            sys.exit(1)
        engine = CodeGraphEngine(target)
        res = engine.explore_feature(args.query, top_k=args.top_k)
        if res.get("status") == "success":
            print(res.get("surgical_context_markdown", ""))
        else:
            print(res.get("message", "探索失败"))

    elif args.command == "callers":
        from code_search_mcp.graph_engine import CodeGraphEngine, format_callers_markdown
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print("错误: 未找到目标代码库", file=sys.stderr)
            sys.exit(1)
        engine = CodeGraphEngine(target)
        res = engine.get_callers(args.symbol)
        print(format_callers_markdown(res))

    elif args.command == "callees":
        from code_search_mcp.graph_engine import CodeGraphEngine, format_callees_markdown
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print("错误: 未找到目标代码库", file=sys.stderr)
            sys.exit(1)
        engine = CodeGraphEngine(target)
        res = engine.get_callees(args.symbol)
        print(format_callees_markdown(res))

    elif args.command == "impact":
        from code_search_mcp.graph_engine import CodeGraphEngine, format_impact_markdown
        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print("错误: 未找到目标代码库", file=sys.stderr)
            sys.exit(1)
        engine = CodeGraphEngine(target)
        res = engine.get_impact_radius(args.symbol, max_depth=args.depth)
        print(format_impact_markdown(res))

    elif args.command == "watch":
        import time
        from code_search_mcp.watcher import RepoWatcher

        target = resolve_repo_path(args.path)
        if not target or not target.exists():
            print("错误: 未找到目标代码库", file=sys.stderr)
            sys.exit(1)

        print(f"📡 启动代码库实时热监控: {target}")
        print(f"   防抖延迟: {args.debounce}ms | 监控语言: Python, TypeScript, JavaScript, Go")
        print("   正在监听文件变动 (按 Ctrl+C 退出监控)...\n")

        watcher = RepoWatcher(target, debounce_ms=args.debounce)
        watcher.start()
        try:
            while watcher.is_running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            watcher.stop()
            print("\n👋 已安全停止监控")

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
            print("\n" + "=" * 70)
            print(f"📦 code-search-mcp 全局索引缓存清单 (存储根目录: {summary['cache_root']})")
            print("=" * 70)
            if not entries:
                print("   暂无任何索引缓存记录。")
            else:
                for i, e in enumerate(entries, 1):
                    status_tag = "✅ 有效" if e.repo_exists else "⚠️  孤儿(源码已失效)"
                    up_str = datetime.fromtimestamp(e.last_updated).strftime("%Y-%m-%d %H:%M") if e.last_updated else "未知"
                    r_path = e.repo_path or f"<哈希: {e.hash_id}>"
                    print(f"[{i:2d}] {status_tag} | 占用: {e.size_mb:>6.2f} MB | 切片: {e.indexed_chunks} 块 ({e.indexed_files} 文件) | 更新: {up_str}")
                    print(f"     源码路径: {r_path}")

            print("-" * 70)
            print(f"📊 汇总: 共 {summary['total_entries']} 个项目缓存 | 总占用: {summary['total_size_mb']:.2f} MB")
            if summary['orphaned_entries'] > 0:
                print(f"💡 发现 {summary['orphaned_entries']} 个已删除项目的孤儿幽灵缓存 ({summary['orphaned_size_mb']:.2f} MB)")
                print(f"   运行 `code-search-mcp clean --orphaned` 可一键清理释放空间。")
            print("=" * 70 + "\n")

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

        prefix = "🔍 [模拟预览]" if res["dry_run"] else "🧹 [已清理]"
        print(f"\n{prefix} 匹配到 {res['matched_entries']} 个缓存项目，释放磁盘空间: {res['freed_mb']:.2f} MB")
        for item in res["deleted_items"]:
            print(f"   • {item['hash']}: {item['repo_path']} ({item['size_mb']} MB)")

        if res["dry_run"]:
            print("\n💡 以上为模拟结果。去掉 --dry-run 即可真正执行清理。")
        else:
            print(f"\n✅ 清理完成！成功释放 {res['freed_mb']:.2f} MB 空间。\n")


if __name__ == "__main__":
    main()
