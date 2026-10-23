"""code-search-graph terminal UI components (Rich CLI UI)

Provides modern terminal output formatting:
- Brand gradient logo banner
- Status cards & progress indicators
- Syntax-highlighted code previews
- Structured summary tables & panels
"""

from __future__ import annotations

import platform
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from rich import box
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

# Ensure UTF-8 output on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Global shared Console instances
console = Console(highlight=False, legacy_windows=False)
err_console = Console(stderr=True, highlight=False, legacy_windows=False)

VERSION = "0.8.8"

LOGO_BANNER = r"""[bold bright_cyan]   ____ ___  ____  _____     ____  _____    _    ____   ____ _   _ 
  / ___/ _ \|  _ \| ____|   / ___|| ____|  / \  |  _ \ / ___| | | |
 | |  | | | | | | |  _| ____\___ \|  _|   / _ \ | |_) | |  _| |_| |
 | |__| |_| | |_| | |__|_____|__) | |___ / ___ \|  _ <| |_| |  _  |
  \____\___/|____/|_____|   |____/|_____/_/   \_\_| \_\\____|_| |_|[/bold bright_cyan]"""

TAGLINE = "[dim]⚡ Local AST Call Graph & Intelligent Hybrid Semantic Code Search Engine[/dim]"
LANG_SUPPORT = "[dim]Supported: [cyan]Python[/cyan] • [cyan]TypeScript[/cyan] • [cyan]JavaScript[/cyan] • [cyan]Vue[/cyan] • [cyan]Java[/cyan] • [cyan]Go[/cyan] • [cyan]Rust[/cyan][/dim]"


def print_banner():
    """Print top-level brand banner"""
    console.print()
    console.print(LOGO_BANNER)
    console.print(TAGLINE)
    console.print(LANG_SUPPORT)
    console.print()


def print_error(msg: str):
    """Print formatted error message to stderr"""
    err_console.print(
        Panel(
            f"[bold red]❌ Error:[/bold red] {msg}",
            border_style="red",
            box=box.ROUNDED,
            expand=False,
            padding=(0, 2),
        )
    )


def print_version():
    """Render comprehensive version & environment info card"""
    from code_search_mcp.config import get_cache_root

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold bright_cyan", justify="left")
    table.add_column(style="white", justify="left")

    table.add_row("⚡ Version", f"[bold bright_green]{VERSION}[/bold bright_green]")
    table.add_row("🐍 Python Runtime", f"{platform.python_version()} ({platform.platform()})")
    table.add_row("📦 Cache Directory", f"[dim]{get_cache_root()}[/dim]")
    from code_search_mcp.config import DEFAULT_MODEL_NAME, VECTOR_DIMENSION
    table.add_row("🧠 Default Model", f"{DEFAULT_MODEL_NAME} [dim]({VECTOR_DIMENSION} dim, ONNX)[/dim]")
    table.add_row("🔍 Exact Search", "Ripgrep [dim](Embedded SIMD)[/dim]")
    table.add_row("🌐 GitHub Repo", "[cyan]https://github.com/wangfenghuan/code-search[/cyan]")
    table.add_row("📦 PyPI Package", "[cyan]https://pypi.org/project/code-search-graph/[/cyan]")

    panel = Panel(
        table,
        title="[bold bright_cyan]code-search-graph System Info[/bold bright_cyan]",
        border_style="bright_blue",
        box=box.ROUNDED,
        padding=(1, 2),
        expand=False,
    )
    console.print()
    console.print(panel)
    console.print()


def print_index_result(res: dict[str, Any], elapsed_seconds: Optional[float] = None):
    """Render index completion summary card"""
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold bright_cyan", justify="left")
    table.add_column(style="white", justify="left")

    repo_p = res.get("repo_path", "")
    table.add_row("📂 Repository", f"[bold bright_white]{repo_p}[/bold bright_white]")
    table.add_row("📄 Indexed Files", f"[bold bright_yellow]{res.get('indexed_files')}[/bold bright_yellow] files")
    table.add_row("🧩 Syntax Chunks", f"[bold bright_green]{res.get('indexed_chunks')}[/bold bright_green] AST blocks")

    if "model_name" in res:
        dim = res.get("vector_dimension", 384)
        table.add_row("🧠 Embedding Model", f"[cyan]{res.get('model_name')}[/cyan] [dim]({dim} dim, ONNX)[/dim]")

    if elapsed_seconds is not None:
        chunks = res.get("indexed_chunks", 0)
        speed_str = f" [dim]({chunks / elapsed_seconds:.1f} chunks/sec)[/dim]" if elapsed_seconds > 0 else ""
        table.add_row("⏱️ Elapsed Time", f"[bold magenta]{elapsed_seconds:.2f}s[/bold magenta]{speed_str}")

    footer = (
        "\n[dim]💡 Quick Start: [bold cyan]code-search-graph search \"query\"[/bold cyan] "
        "• [bold cyan]code-search-graph outline[/bold cyan][/dim]"
    )

    panel = Panel(
        Group(table, Text.from_markup(footer)),
        title="[bold bright_green]✨ Codebase Indexed & Knowledge Graph Ready ✨[/bold bright_green]",
        border_style="bright_cyan",
        box=box.ROUNDED,
        padding=(1, 2),
        expand=False,
    )
    console.print()
    console.print(panel)
    console.print()


def _detect_lexer(file_path: str) -> str:
    """Detect Pygments lexer based on file extension"""
    ext = Path(file_path).suffix.lower()
    mapping = {
        ".py": "python",
        ".ts": "typescript",
        ".tsx": "tsx",
        ".js": "javascript",
        ".jsx": "jsx",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".c": "c",
        ".cpp": "cpp",
        ".h": "c",
        ".json": "json",
        ".md": "markdown",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".toml": "toml",
        ".vue": "html",
        ".sql": "sql",
        ".sh": "bash",
        ".bash": "bash",
    }
    return mapping.get(ext, "text")


def print_search_results(
    results: list[dict[str, Any]],
    query: str,
    repo_path: Path,
    compact: bool = True,
):
    """Render hybrid search results with syntax highlighting and polished cards"""
    head_table = Table.grid(expand=True)
    head_table.add_column()
    head_table.add_column(justify="right")
    head_table.add_row(
        f"🔍 [bold bright_cyan]Search Results[/bold bright_cyan]  •  Query: [bold bright_yellow]\"{query}\"[/bold bright_yellow]",
        f"[dim]Target: [bold white]{repo_path.name}[/bold white]  •  Found: [bold cyan]{len(results)}[/bold cyan] matches[/dim]",
    )

    console.print()
    console.print(Panel(head_table, border_style="cyan", box=box.ROUNDED))

    if not results:
        console.print(
            Panel(
                f"[yellow]⚠️ No matching code snippets found for \"{query}\"[/yellow]\n"
                "[dim]Tip: Try broader search terms or run 'code-search-graph outline' to inspect structure.[/dim]",
                border_style="yellow",
                box=box.ROUNDED,
            )
        )
        console.print()
        return

    for idx, r in enumerate(results, 1):
        rel_path = r.get("file_path", "")
        start_line = r.get("start_line", 1)
        end_line = r.get("end_line", start_line)
        score = r.get("score", 0.0)
        chunk_type = r.get("chunk_type", "code")
        symbol_name = r.get("symbol_name", "")
        code_text = r.get("code", "").strip()

        # Visual hierarchy: Top rank gets bright cyan border, other ranks get blue / dim blue
        rank_badge = f"[bold bright_white on blue] #{idx} [/bold bright_white on blue]" if idx == 1 else f"[bold white on dim blue] #{idx} [/bold white on dim blue]"
        border_color = "bright_cyan" if idx == 1 else ("blue" if idx <= 3 else "dim blue")

        title_str = f" {rank_badge}  [bold bright_white]{rel_path}[/bold bright_white][dim]:{start_line}-{end_line}[/dim] "

        sym_part = f": [bold bright_white]{symbol_name}[/bold bright_white]" if symbol_name else ""
        subtitle_str = (
            f" 🏷️ [bold magenta]{chunk_type}[/bold magenta]{sym_part}"
            f"  [dim]•[/dim]  [bold bright_green]Score: {score:.3f}[/bold bright_green] "
        )

        lexer = _detect_lexer(rel_path)

        if compact:
            lines = code_text.splitlines()
            if len(lines) > 8:
                preview_code = (
                    "\n".join(lines[:8])
                    + f"\n\n# ... ({len(lines) - 8} lines collapsed, pass --full to view entire block)"
                )
            else:
                preview_code = code_text
            syntax = Syntax(preview_code, lexer, theme="monokai", line_numbers=True, start_line=start_line)
        else:
            syntax = Syntax(code_text, lexer, theme="monokai", line_numbers=True, start_line=start_line)

        console.print(
            Panel(
                syntax,
                title=title_str,
                title_align="left",
                subtitle=subtitle_str,
                subtitle_align="right",
                border_style=border_color,
                box=box.ROUNDED,
                padding=(0, 1),
            )
        )
    console.print()


def print_exact_results(exact_res: dict[str, Any]):
    """Render Ripgrep exact literal & regex search results"""
    pattern = exact_res.get("pattern", "")
    matches = exact_res.get("matches", [])
    total = exact_res.get("total_matches", len(matches))

    head_table = Table.grid(expand=True)
    head_table.add_column()
    head_table.add_column(justify="right")
    head_table.add_row(
        f"🎯 [bold magenta]Exact Matches (Ripgrep)[/bold magenta]  •  Pattern: [bold bright_yellow]\"{pattern}\"[/bold bright_yellow]",
        f"[dim]Matches: [bold bright_green]{total}[/bold bright_green][/dim]",
    )

    console.print()
    console.print(Panel(head_table, border_style="magenta", box=box.ROUNDED))

    if not matches:
        console.print("[yellow]   No exact literal matches found.[/yellow]\n")
        return

    table = Table(
        box=box.ROUNDED,
        border_style="magenta",
        show_header=True,
        header_style="bold magenta",
        expand=True,
    )
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Location (file:line)", style="bold cyan", width=36)
    table.add_column("Matched Line Content", style="white")

    for i, m in enumerate(matches, 1):
        if hasattr(m, "file_path"):
            pos = f"{m.file_path}:{m.line_number}"
            line_content = m.line_content.strip()
        else:
            pos = f"{m.get('file_path', m.get('file', ''))}:{m.get('line_number', m.get('line', ''))}"
            line_content = m.get("line_content", m.get("text", "")).strip()
        table.add_row(str(i), pos, line_content)

    console.print(table)
    console.print()


def print_markdown(content: str, title: str = "", border_style: str = "bright_blue"):
    """Render rich Markdown content (outline, explore, callers, callees, impact)"""
    md = Markdown(content)
    if title:
        console.print()
        console.print(
            Panel(
                md,
                title=f"[bold bright_cyan]{title}[/bold bright_cyan]",
                border_style=border_style,
                box=box.ROUNDED,
                padding=(1, 2),
            )
        )
        console.print()
    else:
        console.print()
        console.print(md)
        console.print()


def print_cache_table(summary: dict[str, Any], entries: list[Any]):
    """Render global index cache summary table"""
    table = Table(
        title=f"📦 code-search-graph Global Index Cache\n[dim]Storage Root: {summary.get('cache_root')}[/dim]",
        box=box.ROUNDED,
        border_style="cyan",
        header_style="bold cyan",
        show_lines=True,
    )

    table.add_column("#", justify="center", style="dim", width=4)
    table.add_column("Status", justify="center", width=16)
    table.add_column("Size", justify="right", style="bold bright_yellow", width=12)
    table.add_column("Scale", justify="center", style="cyan", width=24)
    table.add_column("Last Updated", justify="center", style="dim", width=18)
    table.add_column("Repository Path", style="white")

    for i, e in enumerate(entries, 1):
        status_tag = "[bold green]● Active[/bold green]" if e.repo_exists else "[bold red]○ Orphaned[/bold red]"
        up_str = datetime.fromtimestamp(e.last_updated).strftime("%Y-%m-%d %H:%M") if e.last_updated else "Unknown"
        r_path = e.repo_path or f"<hash: {e.hash_id}>"
        table.add_row(
            str(i),
            status_tag,
            f"{e.size_mb:.2f} MB",
            f"{e.indexed_chunks} chunks ({e.indexed_files} files)",
            up_str,
            r_path,
        )

    console.print()
    if not entries:
        console.print(Panel("[yellow]No index cache records found.[/yellow]", border_style="yellow", box=box.ROUNDED))
    else:
        console.print(table)

    summary_lines = [
        f"📊 [bold]Summary[/bold]: [bold cyan]{summary['total_entries']}[/bold cyan] repositories | "
        f"Total size: [bold bright_yellow]{summary['total_size_mb']:.2f} MB[/bold bright_yellow]"
    ]
    if summary.get("orphaned_entries", 0) > 0:
        summary_lines.append(
            f"💡 Found [bold red]{summary['orphaned_entries']}[/bold red] orphaned caches "
            f"([bold red]{summary['orphaned_size_mb']:.2f} MB)\n"
            f"   Run [bold green]code-search-graph clean --orphaned[/bold green] to free up disk space."
        )
    console.print(Panel("\n".join(summary_lines), border_style="green", box=box.ROUNDED, expand=False))
    console.print()


def print_clean_result(res: dict[str, Any]):
    """Render cache cleaning summary results"""
    is_dry = res.get("dry_run", False)
    prefix_badge = "[bold yellow]🔍 [Dry Run][/bold yellow]" if is_dry else "[bold green]🧹 [Cleaned][/bold green]"

    console.print()
    table = Table(box=box.ROUNDED, border_style="yellow" if is_dry else "green", show_header=True)
    table.add_column("Hash ID", style="dim", width=12)
    table.add_column("Repository Path", style="white")
    table.add_column("Freed Space", style="bold bright_yellow", justify="right", width=12)

    for item in res.get("deleted_items", []):
        table.add_row(item.get("hash", ""), item.get("repo_path", ""), f"{item.get('size_mb', 0)} MB")

    title = f"{prefix_badge} Matched {res.get('matched_entries', 0)} cache entries, freed: {res.get('freed_mb', 0):.2f} MB"
    console.print(Panel(table, title=title, border_style="yellow" if is_dry else "green", box=box.ROUNDED))

    if is_dry:
        console.print("💡 [dim]Dry run preview. Run without [bold]--dry-run[/bold] to permanently delete.[/dim]\n")
    else:
        console.print(f"✅ [bold green]Clean complete! Successfully freed {res.get('freed_mb', 0):.2f} MB.[/bold green]\n")


def print_watch_banner(target: Path, debounce: int):
    """Render live file watcher startup banner"""
    watch_text = (
        f"📡 [bold bright_green]Live File Watcher Started[/bold bright_green]: [bold bright_cyan]{target}[/bold bright_cyan]\n"
        f"   Debounce: [yellow]{debounce}ms[/yellow] | Watching: Python, TypeScript, JavaScript, Vue, Java, Go, Rust\n"
        f"   [dim]Monitoring for file changes (Press [bold red]Ctrl+C[/bold red] to stop)...[/dim]"
    )
    console.print()
    console.print(Panel(watch_text, border_style="green", box=box.ROUNDED))
    console.print()


def run_indexing_with_progress(
    indexer: Any,
    skip_vector: bool = False,
    force_vector: bool = False,
    vector_threshold: int = 2000,
) -> tuple[dict[str, Any], float]:
    """Execute repository indexing with a modern, informative Rich Progress bar"""
    import time
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    t0 = time.perf_counter()
    with Progress(
        SpinnerColumn(spinner_name="dots", style="bold bright_cyan"),
        TextColumn("[bold bright_cyan]{task.description}[/bold bright_cyan]"),
        BarColumn(bar_width=28, style="dim", complete_style="bright_cyan", finished_style="bright_green"),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TextColumn("[dim]•[/dim]"),
        TextColumn("[bold bright_green]{task.fields[chunks]}[/bold bright_green] [dim]chunks[/dim]"),
        TextColumn("[dim]•[/dim]"),
        TimeElapsedColumn(),
        console=console,
        transient=True,
    ) as progress:
        task_id = progress.add_task("Indexing codebase...", total=100, chunks=0)

        def on_progress(done_files: int, total_files: int, current_file: str, chunks_count: int):
            display_file = current_file if len(current_file) <= 24 else f"...{current_file[-21:]}"
            progress.update(
                task_id,
                total=total_files,
                completed=done_files,
                description=f"Parsing: [white]{display_file}[/white]",
                chunks=chunks_count,
            )

        res = indexer.index_all(
            skip_vector=skip_vector,
            force_vector=force_vector,
            vector_threshold=vector_threshold,
            progress_callback=on_progress,
        )

    elapsed = time.perf_counter() - t0
    return res, elapsed
