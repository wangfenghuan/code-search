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

try:
    from mcp.types import ToolAnnotations
except ImportError:
    ToolAnnotations = None


def make_annotations(read_only: bool, destructive: bool = False):
    """Helper to construct MCP ToolAnnotations with readOnlyHint and destructiveHint."""
    if ToolAnnotations is not None:
        return ToolAnnotations(readOnlyHint=read_only, destructiveHint=destructive)
    return None


from code_search_mcp.graph_engine import (
    CodeGraphEngine,
    format_callers_markdown,
    format_callees_markdown,
    format_impact_markdown,
    format_references_markdown,
    format_diff_context_markdown,
)
from code_search_mcp.indexer import CodeIndexer
from code_search_mcp.outline import ProjectOutlineGenerator
from code_search_mcp.ripgrep_engine import ExactSearchEngine, format_exact_results
from code_search_mcp.searcher import CodeSearcher, format_search_results, resolve_repo_path
from code_search_mcp.watcher import get_or_create_watcher

# Create FastMCP instance with unified name
mcp = FastMCP("code-search-graph")


@mcp.tool(
    description="Scan and index a multi-language codebase to build AST call graphs and vector embeddings. Use when initializing a new repository or manually refreshing the code index.",
    annotations=make_annotations(read_only=False, destructive=False),
)
def index_codebase(path: str, skip_vector: bool = False, force_vector: bool = False) -> str:
    """Scan and index a multi-language codebase to build AST call graphs and vector embeddings. Use when initializing a new repository or manually refreshing the code index.

    Args:
        path: Root directory path of the codebase (relative or absolute)
        skip_vector: Whether to skip vector embeddings (default: False; automatically enabled for large repos >2000 files to avoid high memory/time, indexing outline and SQLite graph only)
        force_vector: Force full streaming vector embeddings even for large repositories (default: False)

    Returns:
        Summary of indexing results including file count, chunk count, and indexing mode
    """
    try:
        repo_dir = Path(path).resolve()
        if not repo_dir.exists() or not repo_dir.is_dir():
            return f"Error: Path '{path}' does not exist or is not a valid directory."

        indexer = CodeIndexer(repo_dir)
        res = indexer.index_all(skip_vector=skip_vector, force_vector=force_vector)

        # Automatically start live background watcher
        get_or_create_watcher(repo_dir, auto_start=True)

        mode_str = "lightweight structured mode (no vectors)" if not res.get("vector_indexed", True) else "full streaming vector mode"

        return (
            f"Codebase indexing completed successfully!\n"
            f"- Target Path: {res['repo_path']}\n"
            f"- Indexing Mode: {mode_str}\n"
            f"- Indexed Source Files: {res['indexed_files']}\n"
            f"- Extracted Code Chunks: {res['indexed_chunks']}\n"
            f"- 📡 Live File Watcher: Active (monitoring Python/TS/JS/Vue/Go/Java/Rust for instant incremental sync)\n"
            f"Tip: Call `get_codebase_outline()` to view architectural map, or `get_watch_status()` to inspect watcher."
        )
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] index_codebase error: {e}\n")
        return f"Failed to index codebase: {str(e)}"


@mcp.tool(
    description="Get a high-level architectural outline map of modules, classes, and key functions. Call first in unfamiliar repositories to understand project structure without reading full files.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def get_codebase_outline(path: str = "", max_depth: int = 3) -> str:
    """Get a high-level architectural outline map of modules, classes, and key functions. Call first in unfamiliar repositories to understand project structure without reading full files.

    Args:
        path: Root directory path of the repository (optional, defaults to current or most recently indexed repo)
        max_depth: Maximum directory traversal depth (default: 3)

    Returns:
        Compact Markdown architectural outline
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "Error: Could not resolve target repository path. Please specify 'path' argument."

        gen = ProjectOutlineGenerator(target_repo)
        outline_data = gen.get_cached_or_generate()
        return gen.format_as_markdown(outline_data, max_depth=max_depth)
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] get_codebase_outline error: {e}\n")
        return f"Failed to get codebase outline: {str(e)}"


@mcp.tool(
    description="Semantic hybrid code search using natural language (Vector + BM25 RRF). Use when searching by intent, feature concepts, or business logic without knowing exact symbol names.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def search_codebase(query: str, path: str = "", top_k: int = 5, compact: bool = True) -> str:
    """Semantic hybrid code search using natural language (Vector + BM25 RRF). Use when searching by intent, feature concepts, or business logic without knowing exact symbol names.

    Args:
        query: Natural language query describing desired functionality or feature
        path: Root directory path of the codebase (optional, defaults to current or recent repo)
        top_k: Number of top relevant results to return (default: 5)
        compact: Enable token-saving compact mode with core signatures and 10-line preview (default: True)

    Returns:
        Markdown report containing file paths, line ranges, symbols, routes, and syntax snippets
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "Error: Target repository not found. Please provide 'path' or run index_codebase first."

        searcher = CodeSearcher(target_repo)
        if not searcher.is_indexed():
            return (
                f"Repository '{target_repo}' is not yet indexed.\n"
                f"Please run `index_codebase(path='{target_repo}')` first."
            )

        results = searcher.search(query=query, top_k=top_k)
        return format_search_results(results, query, compact=compact)
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] search_codebase error: {e}\n")
        return f"Code search failed: {str(e)}"


@mcp.tool(
    description="Fast exact literal or regex search powered by embedded ripgrep. Use when you know exact identifiers, config keys, error codes, or route strings.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def exact_search(
    pattern: str,
    path: str = "",
    is_regex: bool = False,
    case_sensitive: bool = False,
    file_glob: str = "",
    max_results: int = 20,
) -> str:
    """Fast exact literal or regex search powered by embedded ripgrep. Use when you know exact identifiers, config keys, error codes, or route strings.

    Args:
        pattern: Target literal string or regex pattern (e.g. 'SECRET_KEY', 'ERR_AUTH_EXPIRED')
        path: Root directory path (optional, defaults to current project)
        is_regex: Whether pattern is a regular expression (default: False)
        case_sensitive: Whether match is case sensitive (default: False)
        file_glob: File glob filter pattern (e.g. '*.py', '*.ts')
        max_results: Maximum number of matches to return (default: 20)

    Returns:
        Markdown evidence report with file paths, line numbers, and matching lines
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "Error: Could not resolve target repository path. Please provide 'path'."

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
        sys.stderr.write(f"[code-search-graph] exact_search error: {e}\n")
        return f"Exact search failed: {str(e)}"


@mcp.tool(
    description="Read specific line ranges or full content of a file with line numbers. Use to inspect targeted code snippets discovered by search_codebase or exact_search while conserving context tokens.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def get_file_content(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """Read specific line ranges or full content of a file with line numbers. Use to inspect targeted code snippets discovered by search_codebase or exact_search while conserving context tokens.

    Args:
        path: Relative or absolute path to the file
        start_line: 1-based start line number (optional)
        end_line: 1-based end line number inclusive (optional)

    Returns:
        File contents with line numbers
    """
    try:
        file_path = Path(path).resolve()
        if not file_path.exists() or not file_path.is_file():
            return f"Error: File '{path}' does not exist."

        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"Failed to read file '{path}': {e}"

        lines = content.splitlines()
        total_lines = len(lines)

        s = 1 if start_line is None else max(1, start_line)
        e = total_lines if end_line is None else min(total_lines, end_line)

        if s > total_lines:
            return f"Start line {s} exceeds total lines ({total_lines})."
        if s > e:
            return f"Start line {s} is greater than end line {e}."

        output_lines = [f"# File: {file_path.name} (Lines {s}-{e} of {total_lines})\n```"]
        for i in range(s, e + 1):
            line_str = lines[i - 1]
            output_lines.append(f"{i:4d} | {line_str}")
        output_lines.append("```")

        return "\n".join(output_lines)
    except Exception as e:
        return f"Failed to get file content: {str(e)}"


@mcp.tool(
    description="Flagship single-call surgical exploration tool. Combines semantic search with call graph traversal to return entry routes, core implementations, and dependencies in one shot.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def explore_codebase(query: str, path: str = "", top_k: int = 2) -> str:
    """Flagship single-call surgical exploration tool. Combines semantic search with call graph traversal to return entry routes, core implementations, and dependencies in one shot.

    Args:
        query: Feature workflow or architectural question (e.g. 'user login authentication and password verification', 'payment refund processing')
        path: Repository root path (optional, defaults to current project)
        top_k: Number of entry points to aggregate (default: 2)

    Returns:
        Surgical Markdown report with entry points, routes, call hierarchy, and source code
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "Error: Could not resolve target repository path. Please provide 'path'."

        engine = CodeGraphEngine.get_instance(target_repo)
        res = engine.explore_feature(query=query, top_k=top_k)
        if res.get("status") == "success":
            return res.get("surgical_context_markdown", "")
        return res.get("message", "Exploration failed")
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] explore_codebase error: {e}\n")
        return f"Codebase exploration failed: {str(e)}"


@mcp.tool(
    description="Find all upstream functions, methods, and Web routes that call a specific symbol. Use to trace where and how a function is invoked across the codebase.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def get_symbol_callers(symbol_name: str, path: str = "", limit: int = 30, offset: int = 0) -> str:
    """Find all upstream functions, methods, and Web routes that call a specific symbol. Use to trace where and how a function is invoked across the codebase.

    Args:
        symbol_name: Target symbol name (e.g. 'verify_password' or 'AuthService.login')
        path: Repository root path (optional, defaults to current project)
        limit: Maximum callers to return (default: 30)
        offset: Offset for pagination (default: 0)

    Returns:
        Markdown report of upstream callers and code previews
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "Error: Could not resolve target repository path. Please provide 'path'."

        engine = CodeGraphEngine.get_instance(target_repo)
        res = engine.get_callers(symbol_name)
        return format_callers_markdown(res)
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] get_symbol_callers error: {e}\n")
        return f"Failed to get symbol callers: {str(e)}"


@mcp.tool(
    description="Find all downstream functions and dependencies called by a specific symbol. Use to inspect what a function invokes and identify in-repo vs external library calls.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def get_symbol_callees(symbol_name: str, path: str = "", limit: int = 50, offset: int = 0) -> str:
    """Find all downstream functions and dependencies called by a specific symbol. Use to inspect what a function invokes and identify in-repo vs external library calls.

    Args:
        symbol_name: Target symbol name (e.g. 'login_api' or 'OrderManager.CreateOrder')
        path: Repository root path (optional, defaults to current project)
        limit: Maximum callees to return (default: 50)
        offset: Offset for pagination (default: 0)

    Returns:
        Markdown report of downstream dependencies
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "Error: Could not resolve target repository path. Please provide 'path'."

        engine = CodeGraphEngine.get_instance(target_repo)
        res = engine.get_callees(symbol_name)
        return format_callees_markdown(res)
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] get_symbol_callees error: {e}\n")
        return f"Failed to get symbol callees: {str(e)}"


@mcp.tool(
    description="Change impact blast-radius analysis before refactoring or editing code. Traverses call graphs via BFS to reveal affected upstream symbols, files, and Web API routes.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def get_impact_radius(symbol_name: str, path: str = "", max_depth: int = 3, max_results: int = 50) -> str:
    """Change impact blast-radius analysis before refactoring or editing code. Traverses call graphs via BFS to reveal affected upstream symbols, files, and Web API routes.

    Args:
        symbol_name: Target symbol to modify (e.g. 'hash_password', 'processPayment')
        path: Repository root path (optional, defaults to current project)
        max_depth: Maximum propagation depth (default: 3)
        max_results: Maximum number of impacted symbols to track (default: 50, prevents BFS explosion)

    Returns:
        Blast-radius assessment report with impacted symbols, files, API routes, and propagation tree
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "Error: Could not resolve target repository path. Please provide 'path'."

        engine = CodeGraphEngine.get_instance(target_repo)
        res = engine.get_impact_radius(symbol_name, max_depth=max_depth, max_results=max_results)
        return format_impact_markdown(res)
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] get_impact_radius error: {e}\n")
        return f"Failed to analyze impact radius: {str(e)}"


@mcp.tool(
    description="Find all references to a symbol or keyword across the codebase. Combines AST structural callers with ripgrep textual references in configs and strings.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def find_references(symbol_or_keyword: str, path: str = "") -> str:
    """Find all references to a symbol or keyword across the codebase. Combines AST structural callers with ripgrep textual references in configs and strings.

    Args:
        symbol_or_keyword: Target function name, method name, config key, error code, or literal
        path: Repository root path (optional, defaults to current project)

    Returns:
        Markdown report of explicit code callers and configuration string references
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "Error: Could not resolve target repository path. Please provide 'path'."

        graph = CodeGraphEngine.get_instance(target_repo)
        res = graph.find_references(symbol_or_keyword)
        return format_references_markdown(res)
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] find_references error: {e}\n")
        return f"Failed to find references: {str(e)}"


@mcp.tool(
    description="Analyze git diff changes to calculate blast radius and affected Web routes/tests. Use during code reviews, PR inspection, or before committing code.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def get_diff_context(target: str = "HEAD", path: str = "", max_depth: int = 3, max_results: int = 50) -> str:
    """Analyze git diff changes against graph to calculate blast radius, affected Web routes, and recommended tests.

    Args:
        target: Git ref, commit, or branch to diff against (default: 'HEAD', comparing working tree and staged changes)
        path: Repository root path (optional, defaults to current project)
        max_depth: Maximum propagation depth for blast radius (default: 3)
        max_results: Maximum number of impacted symbols to track (default: 50)

    Returns:
        Markdown report containing modified symbols, affected external API routes, unit tests, and propagation tree
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "Error: Could not resolve target repository path. Please provide 'path'."

        engine = CodeGraphEngine.get_instance(target_repo)
        res = engine.get_diff_context(target=target, max_depth=max_depth, max_results=max_results)
        return format_diff_context_markdown(res)
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] get_diff_context error: {e}\n")
        return f"Failed to analyze git diff context: {str(e)}"


@mcp.tool(
    description="Check status and recent sync history of the live background file watcher. Use to verify if real-time auto-sync is active for your repository.",
    annotations=make_annotations(read_only=True, destructive=False),
)
def get_watch_status(path: str = "") -> str:
    """Check status and recent sync history of the live background file watcher. Use to verify if real-time auto-sync is active for your repository.

    Args:
        path: Repository root path (optional, defaults to current project)

    Returns:
        Markdown report with watcher status, debounce settings, and recent file events
    """
    try:
        target_repo = resolve_repo_path(path)
        if target_repo is None or not target_repo.exists():
            return "Error: Could not resolve target repository path."

        watcher = get_or_create_watcher(target_repo, auto_start=False)
        is_active = watcher.is_running
        status_badge = "🟢 Active (Running)" if is_active else "⚪ Inactive"

        lines = [
            "### 📡 Live File Watcher Status",
            f"- **Repository**: `{target_repo}`",
            f"- **Status**: {status_badge}",
            f"- **Debounce Delay**: {watcher.debounce_ms} ms",
            f"- **Total Incremental Syncs**: {watcher.sync_count}",
            f"- **Last Sync Time**: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(watcher.last_sync_time)) if watcher.last_sync_time else 'None'}",
        ]

        if not is_active:
            lines.append("\n> 💡 Tip: Watcher is inactive. Run `index_codebase()` to initialize index and start live watcher.")
        else:
            lines.append("\n> ⚡ Tip: Saving files in your editor will automatically trigger incremental AST & vector sync within ~0.3s.")

        if watcher.recent_events:
            lines.append("\n#### ⏱️ Recent Sync Events")
            lines.append("| Timestamp | File Path | Action | Chunks |")
            lines.append("| :--- | :--- | :--- | :--- |")
            for ev in reversed(watcher.recent_events[-10:]):
                action = "Updated" if ev.get("status") == "updated" else "Deleted"
                lines.append(f"| {ev.get('time')} | `{ev.get('file')}` | {action} | {ev.get('chunks', 0)} |")

        return "\n".join(lines)
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] get_watch_status error: {e}\n")
        return f"Failed to get watch status: {str(e)}"


def run_server():
    """Run FastMCP server over standard stdio protocol with auto-watcher activation"""
    try:
        target_repo = resolve_repo_path("")
        if target_repo and target_repo.exists():
            db_dir = target_repo / ".code_search"
            if db_dir.exists():
                get_or_create_watcher(target_repo, auto_start=True)
    except Exception as e:
        sys.stderr.write(f"[code-search-graph] Server startup watcher error: {e}\n")

    mcp.run()


if __name__ == "__main__":
    run_server()
