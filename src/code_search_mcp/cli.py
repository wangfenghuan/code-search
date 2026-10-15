import argparse
import sys
from pathlib import Path

from code_search_mcp.indexer import CodeIndexer
from code_search_mcp.outline import ProjectOutlineGenerator
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

    # search 子命令
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


if __name__ == "__main__":
    main()
