"""code-search-mcp terminal UI components (Rich CLI UI)

Provides modern terminal output formatting:
- Brand gradient logo banner
- Status cards & progress indicators
- Syntax-highlighted code previews
- Structured summary tables & panels
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

from rich.box import DOUBLE_EDGE, HEAVY, MINIMAL, ROUNDED, SIMPLE
from rich.console import Console
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
console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)

LOGO_BANNER = r"""[bold cyan]  ___          _        ___                       _      [/bold cyan]
[bold cyan] / __|___  __| |___   / __| ___ __ _ _ _ __ |_ |__   [/bold cyan]
[bold blue]| (__/ _ \/ _` / -_)  \__ \/ -_) _` | '_/ _| ' \  / -_)  [/bold blue]
[bold blue] \___\___/\__,_\___|  |___/\___\__,_|_| \__|_||_| \___|  [/bold blue][bold yellow]⚡ MCP[/bold yellow]"""

TAGLINE = "[dim]⚡ Local lightweight code semantic search & structural graph engine (AST + Vector + BM25 + Ripgrep)[/dim]"


def print_banner():
    """Print top-level brand banner"""
    console.print()
    console.print(LOGO_BANNER)
    console.print(TAGLINE)
    console.print()


def print_error(msg: str):
    """Print formatted error message to stderr"""
    err_console.print(f"[bold red]❌ Error:[/bold red] {msg}")


def print_index_result(res: dict[str, Any], elapsed_seconds: Optional[float] = None):
    """Render index completion summary card"""
    table = Table(show_header=False, box=ROUNDED, border_style="green", padding=(0, 2))
    table.add_column("Key", style="bold cyan", width=18)
    table.add_column("Value", style="white")

    table.add_row("📂 Repository", f"[bold]{res.get('repo_path')}[/bold]")
    table.add_row("📄 Files Indexed", f"[bold yellow]{res.get('indexed_files')}[/bold yellow] files")
    table.add_row("🧩 Syntax Chunks", f"[bold green]{res.get('indexed_chunks')}[/bold green] chunks")
    
    if "model_name" in res:
        table.add_row("🤖 Embedding Model", f"[cyan]{res.get('model_name')}[/cyan] ({res.get('vector_dimension', 512)} dim)")
    if elapsed_seconds is not None:
        table.add_row("⏱️ Elapsed Time", f"[bold magenta]{elapsed_seconds:.2f}s[/bold magenta]")

    panel = Panel(
        table,
        title="[bold green]✅ Indexing Complete! Codebase Ready[/bold green]",
        border_style="green",
        expand=False,
    )
    console.print(panel)


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
    }
    return mapping.get(ext, "text")


def print_search_results(
    results: list[dict[str, Any]],
    query: str,
    repo_path: Path,
    compact: bool = True,
):
    """Render hybrid search results with syntax highlighting"""
    header_text = Text()
    header_text.append("🔍 Search Results ", style="bold cyan")
    header_text.append(f"| Query: \"{query}\" ", style="bold yellow")
    header_text.append(f"| Target: {repo_path.name}", style="dim")

    console.print(Panel(header_text, border_style="cyan"))

    if not results:
        console.print(Panel("[yellow]⚠️ No matching code snippets found for this query[/yellow]", border_style="yellow"))
        return

    for idx, r in enumerate(results, 1):
        rel_path = r.get("file_path", "")
        start_line = r.get("start_line", 1)
        end_line = r.get("end_line", start_line)
        score = r.get("score", 0.0)
        chunk_type = r.get("chunk_type", "code")
        symbol_name = r.get("symbol_name", "")
        code_text = r.get("code", "").strip()

        title_str = (
            f"[bold green]#{idx}[/bold green] "
            f"[bold cyan]{rel_path}:{start_line}-{end_line}[/bold cyan] "
            f"[bold magenta]({chunk_type}{': ' + symbol_name if symbol_name else ''})[/bold magenta] "
            f"[dim green]Score: {score:.3f}[/dim green]"
        )

        lexer = _detect_lexer(rel_path)

        if compact:
            lines = code_text.splitlines()
            if len(lines) > 8:
                preview_code = "\n".join(lines[:8]) + f"\n... ({len(lines) - 8} lines collapsed, use --full to view all)"
            else:
                preview_code = code_text
            syntax = Syntax(preview_code, lexer, theme="monokai", line_numbers=True, start_line=start_line)
        else:
            syntax = Syntax(code_text, lexer, theme="monokai", line_numbers=True, start_line=start_line)

        console.print(Panel(syntax, title=title_str, title_align="left", border_style="bright_blue"))


def print_exact_results(exact_res: dict[str, Any]):
    """Render Ripgrep exact literal & regex search results"""
    pattern = exact_res.get("pattern", "")
    matches = exact_res.get("matches", [])
    total = exact_res.get("total_matches", len(matches))

    header = Text()
    header.append("🎯 Exact Matches (Ripgrep) ", style="bold magenta")
    header.append(f"| Pattern: \"{pattern}\" ", style="bold yellow")
    header.append(f"| Matches: {total}", style="bold green")

    console.print(Panel(header, border_style="magenta"))

    if not matches:
        console.print("[yellow]   No exact literal matches found.[/yellow]")
        return

    table = Table(box=ROUNDED, border_style="magenta", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Location (file:line)", style="bold cyan", width=38)
    table.add_column("Line Content", style="white")

    for i, m in enumerate(matches, 1):
        if hasattr(m, "file_path"):
            pos = f"{m.file_path}:{m.line_number}"
            line_content = m.line_content.strip()
        else:
            pos = f"{m.get('file_path', m.get('file', ''))}:{m.get('line_number', m.get('line', ''))}"
            line_content = m.get("line_content", m.get("text", "")).strip()
        table.add_row(str(i), pos, line_content)

    console.print(table)


def print_markdown(content: str, title: str = "", border_style: str = "blue"):
    """Render rich Markdown content (outline, explore, callers, callees, impact)"""
    md = Markdown(content)
    if title:
        console.print(Panel(md, title=f"[bold]{title}[/bold]", border_style=border_style, padding=(1, 2)))
    else:
        console.print(md)


def print_cache_table(summary: dict[str, Any], entries: list[Any]):
    """Render global index cache summary table"""
    table = Table(
        title=f"📦 code-search-mcp Global Index Cache\n[dim]Storage Root: {summary.get('cache_root')}[/dim]",
        box=ROUNDED,
        border_style="cyan",
        header_style="bold cyan",
        show_lines=True,
    )

    table.add_column("#", justify="center", style="dim", width=4)
    table.add_column("Status", justify="center", width=18)
    table.add_column("Size", justify="right", style="bold yellow", width=12)
    table.add_column("Scale", justify="center", style="cyan", width=22)
    table.add_column("Last Updated", justify="center", style="dim", width=18)
    table.add_column("Repository Path", style="white")

    for i, e in enumerate(entries, 1):
        status_tag = "[bold green]✅ Active[/bold green]" if e.repo_exists else "[bold red]⚠️ Orphaned[/bold red]"
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
        console.print(Panel("[yellow]No index cache records found.[/yellow]", border_style="yellow"))
    else:
        console.print(table)

    summary_text = (
        f"📊 [bold]Summary[/bold]: [bold cyan]{summary['total_entries']}[/bold cyan] repositories | "
        f"Total size: [bold yellow]{summary['total_size_mb']:.2f} MB[/bold yellow]"
    )
    if summary.get("orphaned_entries", 0) > 0:
        summary_text += (
            f"\n💡 Found [bold red]{summary['orphaned_entries']}[/bold red] orphaned caches "
            f"([bold red]{summary['orphaned_size_mb']:.2f} MB)\n"
            f"   Run [bold green]code-search-mcp clean --orphaned[/bold green] to free up disk space."
        )
    console.print(Panel(summary_text, border_style="green", expand=False))
    console.print()


def print_clean_result(res: dict[str, Any]):
    """Render cache cleaning summary results"""
    is_dry = res.get("dry_run", False)
    prefix_badge = "[bold yellow]🔍 [Dry Run][/bold yellow]" if is_dry else "[bold green]🧹 [Cleaned][/bold green]"
    
    console.print()
    table = Table(box=ROUNDED, border_style="yellow" if is_dry else "green", show_header=True)
    table.add_column("Hash ID", style="dim", width=12)
    table.add_column("Repository Path", style="white")
    table.add_column("Freed Space", style="bold yellow", justify="right", width=12)

    for item in res.get("deleted_items", []):
        table.add_row(item.get("hash", ""), item.get("repo_path", ""), f"{item.get('size_mb', 0)} MB")

    title = f"{prefix_badge} Matched {res.get('matched_entries', 0)} cache entries, freed space: {res.get('freed_mb', 0):.2f} MB"
    console.print(Panel(table, title=title, border_style="yellow" if is_dry else "green"))

    if is_dry:
        console.print("💡 [dim]Dry run preview. Remove [bold]--dry-run[/bold] to delete files.[/dim]\n")
    else:
        console.print(f"✅ [bold green]Clean complete! Successfully freed {res.get('freed_mb', 0):.2f} MB.[/bold green]\n")


def print_watch_banner(target: Path, debounce: int):
    """Render live file watcher startup banner"""
    watch_text = (
        f"📡 [bold green]Live File Watcher Started[/bold green]: [bold cyan]{target}[/bold cyan]\n"
        f"   Debounce: [yellow]{debounce}ms[/yellow] | Watching: Python, TypeScript, JavaScript, Go\n"
        f"   [dim]Watching for changes (Press [bold red]Ctrl+C[/bold red] to stop)...[/dim]"
    )
    console.print(Panel(watch_text, border_style="green"))
