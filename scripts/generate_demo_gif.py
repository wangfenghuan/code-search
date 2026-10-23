"""
Studio-grade GIF demo generator for code-search-graph.
Creates pixel-perfect, Retina-sharp animated terminal demonstration for README.md.
"""
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import code_search_mcp.ui as ui
from rich.console import Console
from code_search_mcp.config import get_repo_db_path
from code_search_mcp.graph_engine import CodeGraphEngine, format_impact_markdown
from code_search_mcp.outline import ProjectOutlineGenerator
from code_search_mcp.searcher import CodeSearcher

EDGE_EXE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
SAMPLE_PROJECT = PROJECT_ROOT / "tests" / "sample_project"

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  ::-webkit-scrollbar {{ display: none !important; width: 0 !important; height: 0 !important; }}
  html, body {{
    background: #0b0f14;
    overflow: hidden;
    width: 1060px;
    height: 690px;
    display: flex;
    justify-content: center;
    align-items: center;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  }}
  .window {{
    width: 980px;
    height: 620px;
    background: #181825;
    border-radius: 12px;
    box-shadow: 0 25px 60px rgba(0, 0, 0, 0.75), 0 0 0 1px rgba(255, 255, 255, 0.12);
    overflow: hidden;
    display: flex;
    flex-direction: column;
  }}
  .title-bar {{
    background: #11111b;
    padding: 12px 18px;
    display: flex;
    align-items: center;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    position: relative;
    flex-shrink: 0;
  }}
  .traffic-lights {{
    display: flex;
    gap: 8px;
    z-index: 2;
  }}
  .dot {{
    width: 12px;
    height: 12px;
    border-radius: 50%;
  }}
  .dot-red {{ background: #ff5f56; }}
  .dot-yellow {{ background: #ffbd2e; }}
  .dot-green {{ background: #27c93f; }}
  .window-title {{
    position: absolute;
    left: 0;
    right: 0;
    text-align: center;
    color: #a6adc8;
    font-size: 13px;
    font-family: "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-weight: 500;
    letter-spacing: 0.3px;
  }}
  .terminal-body {{
    padding: 20px 24px;
    font-family: "Cascadia Code", "Fira Code", "Consolas", monospace;
    font-size: 13px;
    line-height: 1.42;
    color: #cdd6f4;
    flex: 1;
    overflow: hidden;
    background: #181825;
  }}
  .prompt-line {{
    margin-bottom: 10px;
    display: flex;
    align-items: center;
    font-size: 13px;
  }}
  .prompt-user {{ color: #a6e3a1; font-weight: bold; }}
  .prompt-sep {{ color: #6c7086; }}
  .prompt-dir {{ color: #89b4fa; font-weight: bold; }}
  .prompt-symbol {{ color: #cdd6f4; margin-right: 8px; font-weight: bold; }}
  .prompt-cmd {{ color: #f9e2af; font-weight: bold; }}
  .cursor {{
    display: inline-block;
    width: 8px;
    height: 15px;
    background: #cdd6f4;
    vertical-align: middle;
    margin-left: 4px;
  }}
  pre {{
    margin: 0;
    white-space: pre-wrap;
    word-break: break-all;
    font-family: inherit;
    font-size: inherit;
  }}
</style>
</head>
<body>
  <div class="window">
    <div class="title-bar">
      <div class="traffic-lights">
        <div class="dot dot-red"></div>
        <div class="dot dot-yellow"></div>
        <div class="dot dot-green"></div>
      </div>
      <div class="window-title">⚡ code-search-graph — bash — 94×26</div>
    </div>
    <div class="terminal-body">
      <div class="prompt-line">
        <span class="prompt-user">developer@workstation</span><span class="prompt-sep">:</span><span class="prompt-dir">~/code-search-graph</span><span class="prompt-symbol">$</span><span class="prompt-cmd">{command}</span>{cursor_html}
      </div>
      {output_html}
    </div>
  </div>
</body>
</html>
"""


def capture_scene_html(command: str, is_typing: bool, render_func=None) -> str:
    """Capture a terminal scene as HTML string"""
    cursor_html = '<span class="cursor"></span>' if is_typing else ''
    output_html = ''

    if not is_typing and render_func:
        output_buffer = io.StringIO()
        rec_console = Console(
            file=output_buffer,
            record=True,
            width=92,
            color_system="truecolor",
            highlight=False,
            legacy_windows=False
        )
        old_console = ui.console
        ui.console = rec_console
        try:
            render_func(rec_console)
            raw_html = rec_console.export_html(inline_styles=True)
            if "<pre" in raw_html:
                pre_start = raw_html.find("<pre")
                content_start = raw_html.find(">", pre_start) + 1
                pre_end = raw_html.find("</pre>", content_start)
                output_html = f"<pre>{raw_html[content_start:pre_end]}</pre>"
            else:
                output_html = f"<pre>{raw_html}</pre>"
        finally:
            ui.console = old_console

    return HTML_TEMPLATE.format(
        command=command,
        cursor_html=cursor_html,
        output_html=output_html
    )


def render_scene_to_image(html_content: str, temp_dir: Path, idx: int) -> Image.Image:
    """Render HTML string to a PNG image using headless Edge"""
    html_file = temp_dir / f"scene_{idx:03d}.html"
    png_file = temp_dir / f"scene_{idx:03d}.png"
    html_file.write_text(html_content, encoding="utf-8")

    cmd = [
        EDGE_EXE,
        "--headless",
        "--disable-gpu",
        "--window-size=1060,690",
        f"--screenshot={png_file}",
        html_file.as_uri(),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    img = Image.open(png_file)
    return img.copy()


def main():
    print("🎬 Generating studio-grade demo GIF for code-search-graph README...")
    temp_dir = PROJECT_ROOT / "scripts" / "gif_frames"
    temp_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = PROJECT_ROOT / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    durations = []

    # -------------------------------------------------------------
    # Scene 1: System Info (code-search-graph --version)
    # -------------------------------------------------------------
    print("  [1/5] Scene 1: code-search-graph --version")
    cmd1 = "code-search-graph --version"
    h = capture_scene_html("code-search-graph --v", is_typing=True)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(250)

    h = capture_scene_html(cmd1, is_typing=True)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(350)

    def r_version(con):
        ui.print_version()

    h = capture_scene_html(cmd1, is_typing=False, render_func=r_version)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(2800)

    # -------------------------------------------------------------
    # Scene 2: Indexing Repository (code-search-graph index)
    # -------------------------------------------------------------
    print("  [2/5] Scene 2: code-search-graph index tests/sample_project")
    cmd2 = "code-search-graph index tests/sample_project"
    h = capture_scene_html("code-search-graph index tests/", is_typing=True)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(250)

    h = capture_scene_html(cmd2, is_typing=True)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(350)

    def r_index(con):
        con.print(f"[bold cyan][code-search-graph][/bold cyan] Scanning repository: [dim]{SAMPLE_PROJECT}[/dim]")
        con.print("[bold cyan][code-search-graph][/bold cyan] Discovered 8 source files")
        con.print("[bold cyan][code-search-graph][/bold cyan] Streaming micro-batch indexing (AST + LanceDB + SQLite)...")
        res_data = {
            "repo_path": str(SAMPLE_PROJECT),
            "indexed_files": 8,
            "indexed_chunks": 43,
        }
        ui.print_index_result(res_data, elapsed_seconds=0.18)

    h = capture_scene_html(cmd2, is_typing=False, render_func=r_index)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(3000)

    # -------------------------------------------------------------
    # Scene 3: 4-Way Hybrid Search
    # -------------------------------------------------------------
    print("  [3/5] Scene 3: code-search-graph search \"verify password\"")
    cmd3 = 'code-search-graph search "verify password"'
    h = capture_scene_html('code-search-graph search "verify', is_typing=True)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(250)

    h = capture_scene_html(cmd3, is_typing=True)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(350)

    def r_search(con):
        searcher = CodeSearcher(SAMPLE_PROJECT)
        results = searcher.search("verify password", top_k=2)
        ui.print_search_results(results, "verify password", SAMPLE_PROJECT, compact=True)

    h = capture_scene_html(cmd3, is_typing=False, render_func=r_search)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(3600)

    # -------------------------------------------------------------
    # Scene 4: Blast-Radius Impact Analysis
    # -------------------------------------------------------------
    print("  [4/5] Scene 4: code-search-graph impact verify_password")
    cmd4 = "code-search-graph impact verify_password"
    h = capture_scene_html("code-search-graph impact verify", is_typing=True)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(250)

    h = capture_scene_html(cmd4, is_typing=True)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(350)

    def r_impact(con):
        engine = CodeGraphEngine.get_instance(SAMPLE_PROJECT)
        res = engine.get_impact_radius("verify_password", max_depth=3)
        ui.print_markdown(format_impact_markdown(res))

    h = capture_scene_html(cmd4, is_typing=False, render_func=r_impact)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(3600)

    # -------------------------------------------------------------
    # Scene 5: Architecture Outline Map
    # -------------------------------------------------------------
    print("  [5/5] Scene 5: code-search-graph outline")
    cmd5 = "code-search-graph outline"
    h = capture_scene_html("code-search-graph out", is_typing=True)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(250)

    h = capture_scene_html(cmd5, is_typing=True)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(350)

    def r_outline(con):
        gen = ProjectOutlineGenerator(SAMPLE_PROJECT)
        data = gen.get_cached_or_generate()
        full_md = gen.format_as_markdown(data)
        lines = full_md.splitlines()
        clean_lines = lines[:23]
        clean_lines.append("")
        clean_lines.append("*... (3 more modules: order_service.rs, payment_service.ts, database.py)*")
        ui.print_markdown("\n".join(clean_lines))

    h = capture_scene_html(cmd5, is_typing=False, render_func=r_outline)
    frames.append(render_scene_to_image(h, temp_dir, len(frames)))
    durations.append(3600)

    # -------------------------------------------------------------
    # Compile & Optimize GIF
    # -------------------------------------------------------------
    output_gif = assets_dir / "demo.gif"
    print(f"📦 Compiling {len(frames)} frames into animated GIF: {output_gif}...")

    crop_box = (18, 10, 1306, 765)
    target_width = 960
    target_height = 562

    processed_frames = []
    for f in frames:
        f_cropped = f.crop(crop_box)
        f_resized = f_cropped.resize((target_width, target_height), Image.Resampling.LANCZOS)
        p_frame = f_resized.convert("RGB").quantize(colors=256, method=Image.Resampling.LANCZOS)
        processed_frames.append(p_frame)

    processed_frames[0].save(
        output_gif,
        save_all=True,
        append_images=processed_frames[1:],
        duration=durations,
        loop=0,
        optimize=True
    )

    size_kb = output_gif.stat().st_size / 1024
    print(f"✨ Successfully generated demo GIF: {output_gif} ({size_kb:.1f} KB, {target_width}x{target_height})")


if __name__ == "__main__":
    main()
