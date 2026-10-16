"""code-search-mcp 终端 UI 美化组件库 (Rich CLI UI)

提供美观现代的终端输出体验：
- 品牌渐变 Banner
- 索引/检索状态卡片与进度动画
- 语法高亮代码块 (Syntax Highlighting)
- 结构化表格与统计摘要面板 (Tables & Panels)
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

# 确保在 Windows 控制台环境下正常输出 UTF-8 与 Emoji
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 全局共享 Console 实例
console = Console(highlight=False)
err_console = Console(stderr=True, highlight=False)

LOGO_BANNER = r"""[bold cyan]  ___          _        ___                       _      [/bold cyan]
[bold cyan] / __|___  __| |___   / __| ___ __ _ _ _ __ |_ |__   [/bold cyan]
[bold blue]| (__/ _ \/ _` / -_)  \__ \/ -_) _` | '_/ _| ' \  / -_)  [/bold blue]
[bold blue] \___\___/\__,_\___|  |___/\___\__,_|_| \__|_||_| \___|  [/bold blue][bold yellow]⚡ MCP[/bold yellow]"""

TAGLINE = "[dim]⚡ 本地轻量代码语义搜索与图谱分析引擎 (AST + Vector + BM25 + Ripgrep)[/dim]"


def print_banner():
    """输出顶层品牌 Banner"""
    console.print()
    console.print(LOGO_BANNER)
    console.print(TAGLINE)
    console.print()


def print_error(msg: str):
    """统一输出错误信息"""
    err_console.print(f"[bold red]❌ 错误:[/bold red] {msg}")


def print_index_result(res: dict[str, Any], elapsed_seconds: Optional[float] = None):
    """美化索引完成输出卡片"""
    table = Table(show_header=False, box=ROUNDED, border_style="green", padding=(0, 2))
    table.add_column("Key", style="bold cyan", width=14)
    table.add_column("Value", style="white")

    table.add_row("📂 代码库根目录", f"[bold]{res.get('repo_path')}[/bold]")
    table.add_row("📄 扫描解析文件", f"[bold yellow]{res.get('indexed_files')}[/bold yellow] 个源文件")
    table.add_row("🧩 抽象语法切片", f"[bold green]{res.get('indexed_chunks')}[/bold green] 个语义代码块")
    
    if "model_name" in res:
        table.add_row("🤖 嵌入表示模型", f"[cyan]{res.get('model_name')}[/cyan] ({res.get('vector_dimension', 512)} 维)")
    if elapsed_seconds is not None:
        table.add_row("⏱️ 索引构建耗时", f"[bold magenta]{elapsed_seconds:.2f}s[/bold magenta]")

    panel = Panel(
        table,
        title="[bold green]✅ 索引成功！代码库构建完毕[/bold green]",
        border_style="green",
        expand=False,
    )
    console.print(panel)


def _detect_lexer(file_path: str) -> str:
    """根据文件后缀识别 Syntax 语法高亮器语言"""
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
    """美化语义与混合检索结果"""
    header_text = Text()
    header_text.append("🔍 代码检索结果 ", style="bold cyan")
    header_text.append(f"| 搜索意图: \"{query}\" ", style="bold yellow")
    header_text.append(f"| 目标项目: {repo_path.name}", style="dim")

    console.print(Panel(header_text, border_style="cyan"))

    if not results:
        console.print(Panel("[yellow]⚠️ 未检索到与该意图匹配的相关代码片段[/yellow]", border_style="yellow"))
        return

    for idx, r in enumerate(results, 1):
        rel_path = r.get("file_path", "")
        start_line = r.get("start_line", 1)
        end_line = r.get("end_line", start_line)
        score = r.get("score", 0.0)
        chunk_type = r.get("chunk_type", "code")
        symbol_name = r.get("symbol_name", "")
        code_text = r.get("code", "").strip()

        # 卡片头部徽标
        title_str = (
            f"[bold green]#{idx}[/bold green] "
            f"[bold cyan]{rel_path}:{start_line}-{end_line}[/bold cyan] "
            f"[bold magenta]({chunk_type}{': ' + symbol_name if symbol_name else ''})[/bold magenta] "
            f"[dim green]匹配分: {score:.3f}[/dim green]"
        )

        lexer = _detect_lexer(rel_path)

        if compact:
            # 紧凑模式：展示前 8 行预览，节省终端垂直空间
            lines = code_text.splitlines()
            if len(lines) > 8:
                preview_code = "\n".join(lines[:8]) + f"\n... (剩余 {len(lines) - 8} 行折叠，加 --full 查看完整内容)"
            else:
                preview_code = code_text
            syntax = Syntax(preview_code, lexer, theme="monokai", line_numbers=True, start_line=start_line)
        else:
            syntax = Syntax(code_text, lexer, theme="monokai", line_numbers=True, start_line=start_line)

        console.print(Panel(syntax, title=title_str, title_align="left", border_style="bright_blue"))


def print_exact_results(exact_res: dict[str, Any]):
    """美化 Ripgrep 确切字面量与正则搜索结果"""
    pattern = exact_res.get("pattern", "")
    matches = exact_res.get("matches", [])
    total = exact_res.get("total_matches", len(matches))

    header = Text()
    header.append("🎯 确凿字面量检索结果 (Ripgrep) ", style="bold magenta")
    header.append(f"| 表达式: \"{pattern}\" ", style="bold yellow")
    header.append(f"| 命中数: {total}", style="bold green")

    console.print(Panel(header, border_style="magenta"))

    if not matches:
        console.print("[yellow]   未找到完全匹配的字面量文本。[/yellow]")
        return

    table = Table(box=ROUNDED, border_style="magenta", show_header=True, header_style="bold magenta")
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("位置 (文件:行号)", style="bold cyan", width=38)
    table.add_column("命中代码行", style="white")

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
    """渲染富文本 Markdown 内容（如 outline, explore, callers, callees, impact）"""
    md = Markdown(content)
    if title:
        console.print(Panel(md, title=f"[bold]{title}[/bold]", border_style=border_style, padding=(1, 2)))
    else:
        console.print(md)


def print_cache_table(summary: dict[str, Any], entries: list[Any]):
    """美化输出全局缓存清单表格"""
    table = Table(
        title=f"📦 code-search-mcp 全局索引缓存清单\n[dim]存储根目录: {summary.get('cache_root')}[/dim]",
        box=ROUNDED,
        border_style="cyan",
        header_style="bold cyan",
        show_lines=True,
    )

    table.add_column("#", justify="center", style="dim", width=4)
    table.add_column("状态", justify="center", width=18)
    table.add_column("占用空间", justify="right", style="bold yellow", width=12)
    table.add_column("切片规模", justify="center", style="cyan", width=18)
    table.add_column("最后更新", justify="center", style="dim", width=18)
    table.add_column("代码库源码路径", style="white")

    for i, e in enumerate(entries, 1):
        status_tag = "[bold green]✅ 有效[/bold green]" if e.repo_exists else "[bold red]⚠️  孤儿(源码已失效)[/bold red]"
        up_str = datetime.fromtimestamp(e.last_updated).strftime("%Y-%m-%d %H:%M") if e.last_updated else "未知"
        r_path = e.repo_path or f"<哈希: {e.hash_id}>"
        table.add_row(
            str(i),
            status_tag,
            f"{e.size_mb:.2f} MB",
            f"{e.indexed_chunks} 块 ({e.indexed_files} 文件)",
            up_str,
            r_path,
        )

    console.print()
    if not entries:
        console.print(Panel("[yellow]暂无任何索引缓存记录。[/yellow]", border_style="yellow"))
    else:
        console.print(table)

    # 底部统计汇总卡片
    summary_text = (
        f"📊 [bold]汇总[/bold]: 共 [bold cyan]{summary['total_entries']}[/bold cyan] 个项目缓存 | "
        f"总占用: [bold yellow]{summary['total_size_mb']:.2f} MB[/bold yellow]"
    )
    if summary.get("orphaned_entries", 0) > 0:
        summary_text += (
            f"\n💡 发现 [bold red]{summary['orphaned_entries']}[/bold red] 个已删除项目的孤儿幽灵缓存 "
            f"([bold red]{summary['orphaned_size_mb']:.2f} MB[/bold red])\n"
            f"   运行 [bold green]code-search-mcp clean --orphaned[/bold green] 可一键清理释放磁盘空间。"
        )
    console.print(Panel(summary_text, border_style="green", expand=False))
    console.print()


def print_clean_result(res: dict[str, Any]):
    """美化缓存清理结果输出"""
    is_dry = res.get("dry_run", False)
    prefix_badge = "[bold yellow]🔍 [模拟预览][/bold yellow]" if is_dry else "[bold green]🧹 [已清理][/bold green]"
    
    console.print()
    table = Table(box=ROUNDED, border_style="yellow" if is_dry else "green", show_header=True)
    table.add_column("哈希 ID", style="dim", width=12)
    table.add_column("代码库路径", style="white")
    table.add_column("释放空间", style="bold yellow", justify="right", width=12)

    for item in res.get("deleted_items", []):
        table.add_row(item.get("hash", ""), item.get("repo_path", ""), f"{item.get('size_mb', 0)} MB")

    title = f"{prefix_badge} 匹配到 {res.get('matched_entries', 0)} 个缓存项目，释放磁盘空间: {res.get('freed_mb', 0):.2f} MB"
    console.print(Panel(table, title=title, border_style="yellow" if is_dry else "green"))

    if is_dry:
        console.print("💡 [dim]以上为模拟结果。去掉 [bold]--dry-run[/bold] 即可真正执行清理。[/dim]\n")
    else:
        console.print(f"✅ [bold green]清理完成！成功释放 {res.get('freed_mb', 0):.2f} MB 空间。[/bold green]\n")


def print_watch_banner(target: Path, debounce: int):
    """美化实时热监控启动提示"""
    watch_text = (
        f"📡 [bold green]启动代码库实时热监控[/bold green]: [bold cyan]{target}[/bold cyan]\n"
        f"   防抖延迟: [yellow]{debounce}ms[/yellow] | 监控语言: Python, TypeScript, JavaScript, Go\n"
        f"   [dim]正在监听文件变动 (按 [bold red]Ctrl+C[/bold red] 退出监控)...[/dim]"
    )
    console.print(Panel(watch_text, border_style="green"))
