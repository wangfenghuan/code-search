import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

from code_search_mcp.config import resolve_repo_path
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
    print_version,
    print_watch_banner,
    run_indexing_with_progress,
)

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


app = typer.Typer(
    name="code-search-graph",
    help="""
⚡ code-search-graph: Local AST Call Graph & Intelligent Hybrid Semantic Code Search Engine

Common Examples:
  code-search-graph index .                           # Scan & index repository with vector embeddings & AST
  code-search-graph search "user auth and token"      # Hybrid semantic code search (with syntax highlighting)
  code-search-graph exact "hash_password"             # Ultra-fast exact literal / regex search via ripgrep
  code-search-graph outline                           # Multi-language high-level architecture map (token saver)
  code-search-graph explore "user login & auth flow"  # End-to-end surgical feature exploration
  code-search-graph callers "verify_token"            # Find who calls a specific function or class
  code-search-graph callees "AuthService.login"       # Find downstream dependencies called by a function
  code-search-graph impact "User" --depth 3           # Blast-radius impact analysis (cross-file reverse propagation)
  code-search-graph cache                             # View global index cache entries & disk usage
  code-search-graph clean --orphaned                  # Safely clean orphaned caches to free disk space
  code-search-graph install                           # One-click auto-config for Claude / Cursor / Windsurf MCP
""",
    add_completion=False,
    no_args_is_help=False,
    rich_markup_mode="rich",
)


def version_callback(value: bool):
    if value:
        print_version()
        raise typer.Exit(code=0)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version: Optional[bool] = typer.Option(
        None,
        "--version",
        "-v",
        help="Show detailed system and version information",
        callback=version_callback,
        is_eager=True,
    ),
):
    """code-search-graph core entry point and dispatcher"""
    if ctx.invoked_subcommand is None:
        # If not running in an interactive terminal (e.g. piped stdio from Claude Desktop / Cursor), launch MCP server
        if not sys.stdin.isatty():
            from code_search_mcp.server import run_server

            run_server()
        else:
            print_banner()
            console.print(ctx.get_help())
            raise typer.Exit(code=0)


@app.command("serve", help="Start server with MCP stdio protocol")
def serve_cmd():
    from code_search_mcp.server import run_server

    run_server()


@app.command("index", help="Scan and index the specified repository")
def index_cmd(
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="Repository root path (positional argument, equivalent to --path, default: current directory)",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Repository root path (equivalent to positional argument, default: current directory)",
    ),
    skip_vector: bool = typer.Option(
        False,
        "--skip-vector",
        help="Skip vector embeddings, build only structural call graph and outline (instant indexing, zero RAM load)",
    ),
    force_vector: bool = typer.Option(
        False,
        "--force-vector",
        help="Force full streaming vector embeddings even if source files exceed threshold",
    ),
    threshold: int = typer.Option(
        2000,
        "--threshold",
        help="File count threshold to automatically switch to lightweight mode (default: 2000)",
    ),
):
    raw_path = path or positional_path or "."
    target = Path(raw_path).resolve()
    if not target.exists() or not target.is_dir():
        print_error(f"Target path '{target}' does not exist or is not a directory")
        raise typer.Exit(code=1)

    from code_search_mcp.indexer import CodeIndexer

    indexer = CodeIndexer(target)
    res, elapsed = run_indexing_with_progress(
        indexer,
        skip_vector=skip_vector,
        force_vector=force_vector,
        vector_threshold=threshold,
    )
    print_index_result(res, elapsed_seconds=elapsed)


@app.command("outline", help="Show codebase high-level architecture outline map")
def outline_cmd(
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="Repository root path (positional argument, default: current or most recently indexed repo)",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Target repository path (default: current or most recently indexed repo)",
    ),
):
    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("Target repository not found")
        raise typer.Exit(code=1)

    with console.status("[bold cyan]Extracting codebase architectural outline map...[/bold cyan]", spinner="dots"):
        from code_search_mcp.outline import ProjectOutlineGenerator

        gen = ProjectOutlineGenerator(target)
        outline_data = gen.get_cached_or_generate()
    print_markdown(gen.format_as_markdown(outline_data))


@app.command("search", help="Semantic hybrid search across indexed code")
def search_cmd(
    query: str = typer.Argument(..., help="Natural language search query or keywords"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="Target repository path (positional argument, equivalent to --path)",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Target repository path (default: current or most recently indexed repo)",
    ),
    top_k: int = typer.Option(
        5,
        "--top-k",
        "-k",
        help="Number of results to return (default: 5)",
    ),
    full: bool = typer.Option(
        False,
        "--full",
        help="Output full code snippets instead of compact preview",
    ),
):
    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("Target repository not found. Please run 'index' first.")
        raise typer.Exit(code=1)

    from code_search_mcp.searcher import CodeSearcher

    searcher = CodeSearcher(target)
    if not searcher.is_indexed():
        console.print(f"[dim]Notice: Repository '{target.name}' is not yet indexed. Creating initial index...[/dim]")
        from code_search_mcp.indexer import CodeIndexer

        indexer = CodeIndexer(target)
        run_indexing_with_progress(indexer)

    with console.status("[bold cyan]Performing hybrid multi-channel search (RRF + Vector + BM25)...[/bold cyan]", spinner="dots"):
        results = searcher.search(query, top_k=top_k)
    print_search_results(results, query, target, compact=not full)


@app.command("exact", help="Fast exact literal or regex search via ripgrep")
def exact_cmd(
    pattern: str = typer.Argument(..., help="Exact string or regular expression to search for"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="Target repository path (positional argument, equivalent to --path)",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Target repository path (default: current or most recently indexed repo)",
    ),
    regex: bool = typer.Option(
        False,
        "--regex",
        "-r",
        help="Enable regular expression matching",
    ),
    case_sensitive: bool = typer.Option(
        False,
        "--case-sensitive",
        "-c",
        help="Case-sensitive matching",
    ),
    glob: str = typer.Option(
        "",
        "--glob",
        "-g",
        help="File glob filter (e.g. '*.py')",
    ),
    max_results: int = typer.Option(
        20,
        "--max",
        "-m",
        help="Maximum number of results (default: 20)",
    ),
):
    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("Target repository not found")
        raise typer.Exit(code=1)

    from code_search_mcp.ripgrep_engine import ExactSearchEngine

    engine = ExactSearchEngine(target)
    with console.status(f"[bold magenta]Searching via Ripgrep: {pattern}...[/bold magenta]", spinner="dots"):
        res = engine.search(
            pattern=pattern,
            is_regex=regex,
            case_sensitive=case_sensitive,
            file_glob=glob,
            max_results=max_results,
        )
    print_exact_results(res)


@app.command("explore", help="End-to-end surgical feature exploration")
def explore_cmd(
    query: str = typer.Argument(..., help="Feature question or workflow description"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="Target repository path (positional argument, equivalent to --path)",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Target repository path",
    ),
    top_k: int = typer.Option(
        2,
        "--top-k",
        "-k",
        help="Number of core entry points to aggregate (default: 2)",
    ),
):
    from code_search_mcp.graph_engine import CodeGraphEngine

    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("Target repository not found")
        raise typer.Exit(code=1)

    engine = CodeGraphEngine(target)
    with console.status(f"[bold cyan]Analyzing topological feature flow: {query}...[/bold cyan]", spinner="dots"):
        res = engine.explore_feature(query, top_k=top_k)
    if res.get("status") == "success":
        print_markdown(res.get("surgical_context_markdown", ""))
    else:
        print_error(res.get("message", "Exploration failed"))
        raise typer.Exit(code=1)


@app.command("callers", help="Find who calls a specific function or class")
def callers_cmd(
    symbol: str = typer.Argument(..., help="Target symbol name"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="Target repository path (positional argument, equivalent to --path)",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Target repository path",
    ),
):
    from code_search_mcp.graph_engine import CodeGraphEngine, format_callers_markdown

    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("Target repository not found")
        raise typer.Exit(code=1)

    engine = CodeGraphEngine(target)
    with console.status(f"[bold cyan]Tracing upstream callers for '{symbol}'...[/bold cyan]", spinner="dots"):
        res = engine.get_callers(symbol)
    print_markdown(format_callers_markdown(res))


@app.command("callees", help="Find downstream functions directly called by a symbol")
def callees_cmd(
    symbol: str = typer.Argument(..., help="Target symbol name"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="Target repository path (positional argument, equivalent to --path)",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Target repository path",
    ),
):
    from code_search_mcp.graph_engine import CodeGraphEngine, format_callees_markdown

    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("Target repository not found")
        raise typer.Exit(code=1)

    engine = CodeGraphEngine(target)
    with console.status(f"[bold cyan]Tracing downstream dependencies for '{symbol}'...[/bold cyan]", spinner="dots"):
        res = engine.get_callees(symbol)
    print_markdown(format_callees_markdown(res))


@app.command("impact", help="Analyze change impact blast-radius")
def impact_cmd(
    symbol: str = typer.Argument(..., help="Target symbol to modify"),
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="Target repository path (positional argument, equivalent to --path)",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Target repository path",
    ),
    depth: int = typer.Option(
        3,
        "--depth",
        "-d",
        help="Maximum traversal depth (default: 3)",
    ),
    max_results: int = typer.Option(
        50,
        "--max-results",
        "-m",
        help="Maximum number of impacted symbols to track (default: 50, prevents BFS explosion)",
    ),
):
    from code_search_mcp.graph_engine import CodeGraphEngine, format_impact_markdown

    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("Target repository not found")
        raise typer.Exit(code=1)

    engine = CodeGraphEngine(target)
    with console.status(f"[bold cyan]Calculating blast radius for '{symbol}'...[/bold cyan]", spinner="dots"):
        res = engine.get_impact_radius(symbol, max_depth=depth, max_results=max_results)
    print_markdown(format_impact_markdown(res))


@app.command("watch", help="Start live hot-reloading repository file watcher")
def watch_cmd(
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="Repository root path (positional argument, default: current or most recently indexed repo)",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Target repository path (default: current or most recently indexed repo)",
    ),
    debounce: int = typer.Option(
        1500,
        "--debounce",
        "-d",
        help="Debounce delay in milliseconds (default: 1500ms)",
    ),
):
    from code_search_mcp.watcher import RepoWatcher

    target = resolve_repo_path(path or positional_path or "")
    if not target or not target.exists():
        print_error("Target repository not found")
        raise typer.Exit(code=1)

    print_watch_banner(target, debounce)

    watcher = RepoWatcher(target, debounce_ms=debounce)
    watcher.start()
    try:
        while watcher.is_running:
            time.sleep(0.5)
    except KeyboardInterrupt:
        watcher.stop()
        console.print("\n[bold yellow]👋 File watcher safely stopped[/bold yellow]\n")


@app.command("install", help="One-click auto-installer for Claude/Cursor/Windsurf/Cline MCP")
def install_cmd(
    clients: str = typer.Option(
        "all",
        "--clients",
        "-c",
        help="Target clients to configure (e.g. claude-code,cursor or all, default: all)",
    ),
    mode: str = typer.Option(
        "auto",
        "--mode",
        "-m",
        help="MCP execution mode (auto / uvx / uv / python / docker, default: auto)",
    ),
    repo: str = typer.Option(
        "",
        "--repo",
        "-r",
        help="Target repository path for rules initialization (default: current directory)",
    ),
    no_rules: bool = typer.Option(
        False,
        "--no-rules",
        help="Skip writing CLAUDE.md and .cursorrules rules",
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


@app.command("cache", help="View global index cache entries and disk usage")
def cache_cmd(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Output statistics in JSON format",
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


@app.command("clean", help="Clean index caches and temporary data")
def clean_cmd(
    positional_path: Optional[str] = typer.Argument(
        None,
        metavar="[PATH]",
        help="Target repository path (positional argument, equivalent to --path)",
    ),
    path: Optional[str] = typer.Option(
        None,
        "--path",
        "-p",
        help="Only clean cache for specified repository",
    ),
    all_caches: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Clear caches for all repositories",
    ),
    orphaned: bool = typer.Option(
        False,
        "--orphaned",
        "-o",
        help="Only clean orphaned caches whose source directories no longer exist (recommended)",
    ),
    days: Optional[int] = typer.Option(
        None,
        "--days",
        "-d",
        help="Clean caches older than specified days",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Preview what would be cleaned and freed space without deleting",
    ),
):
    from code_search_mcp.cache_manager import CacheManager

    mgr = CacheManager()
    clean_target = path or positional_path or None
    is_orphaned = orphaned or (not all_caches and not days and not clean_target)
    with console.status("[bold yellow]Scanning and cleaning index cache...[/bold yellow]", spinner="dots"):
        res = mgr.clean(
            all_caches=all_caches,
            orphaned_only=is_orphaned,
            older_than_days=days,
            target_repo=clean_target,
            dry_run=dry_run,
        )
    print_clean_result(res)


def main():
    app(prog_name="code-search-graph")


if __name__ == "__main__":
    main()
