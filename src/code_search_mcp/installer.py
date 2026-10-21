"""One-Click Auto-Installer and MCP Client Configuration Wizard

Inspired by modern developer tooling best practices:
Eliminates manual JSON edits, path lookups, and configuration errors.
Automatically detects and configures:
1. Claude Code (~/.claude.json)
2. Claude Desktop (claude_desktop_config.json: Win / Mac / Linux)
3. Cursor (.cursor/mcp.json and global storage)
4. Windsurf (~/.codeium/windsurf/mcp_config.json)
5. Cline / Roo Code (VS Code Extension global settings)
6. Injects token-efficient guidelines into CLAUDE.md / .cursorrules
"""

import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_client_config_paths() -> Dict[str, Path]:
    """Resolve MCP client configuration file paths by OS"""
    home = Path.home()
    system = platform.system()
    paths: Dict[str, Path] = {}

    # 1. Claude Code
    paths["claude-code"] = home / ".claude.json"

    # 2. Claude Desktop
    if system == "Windows":
        appdata = Path(os.getenv("APPDATA", str(home / "AppData" / "Roaming")))
        paths["claude-desktop"] = appdata / "Claude" / "claude_desktop_config.json"
    elif system == "Darwin":
        paths["claude-desktop"] = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    else:
        paths["claude-desktop"] = home / ".config" / "Claude" / "claude_desktop_config.json"

    # 3. Cursor (workspace & global)
    paths["cursor-workspace"] = Path.cwd() / ".cursor" / "mcp.json"
    if system == "Windows":
        appdata = Path(os.getenv("APPDATA", str(home / "AppData" / "Roaming")))
        paths["cursor-global"] = appdata / "Cursor" / "User" / "globalStorage" / "cursor.mcp.json"
    elif system == "Darwin":
        paths["cursor-global"] = home / "Library" / "Application Support" / "Cursor" / "User" / "globalStorage" / "cursor.mcp.json"
    else:
        paths["cursor-global"] = home / ".config" / "Cursor" / "User" / "globalStorage" / "cursor.mcp.json"

    # 4. Windsurf
    paths["windsurf"] = home / ".codeium" / "windsurf" / "mcp_config.json"

    # 5. Cline / Roo Code (VS Code Extension)
    if system == "Windows":
        appdata = Path(os.getenv("APPDATA", str(home / "AppData" / "Roaming")))
        paths["cline"] = appdata / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
        paths["roo-code"] = appdata / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json"
    elif system == "Darwin":
        paths["cline"] = home / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
        paths["roo-code"] = home / "Library" / "Application Support" / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json"
    else:
        paths["cline"] = home / ".config" / "Code" / "User" / "globalStorage" / "saoudrizwan.claude-dev" / "settings" / "cline_mcp_settings.json"
        paths["roo-code"] = home / ".config" / "Code" / "User" / "globalStorage" / "rooveterinaryinc.roo-cline" / "settings" / "cline_mcp_settings.json"

    return paths


def build_server_config(
    mode: str = "uvx",
    python_path: Optional[str] = None,
    repo_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Generate standard MCP server configuration block"""
    if mode == "uvx":
        return {
            "command": "uvx",
            "args": ["code-search-graph", "serve"],
        }
    elif mode == "uv":
        base_dir = repo_path or str(Path.cwd().resolve())
        return {
            "command": "uv",
            "args": ["--directory", base_dir, "run", "code-search-graph", "serve"],
        }
    elif mode == "python":
        py_bin = python_path or sys.executable
        return {
            "command": py_bin,
            "args": ["-m", "code_search_mcp.cli", "serve"],
        }
    elif mode == "docker":
        return {
            "command": "docker",
            "args": ["run", "-i", "--rm", "-v", f"{repo_path or '.'}:/workspace", "code-search-graph:latest"],
        }
    else:
        return {
            "command": "uvx",
            "args": ["code-search-graph", "serve"],
        }


def safe_merge_json(file_path: Path, server_key: str, server_config: Dict[str, Any]) -> Tuple[bool, str]:
    """Safely merge JSON configuration, creating backup and preserving existing entries"""
    try:
        data: Dict[str, Any] = {}
        if file_path.exists():
            try:
                backup_path = file_path.with_suffix(f"{file_path.suffix}.bak")
                shutil.copy2(file_path, backup_path)
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        if not isinstance(data, dict):
            data = {}

        if "mcpServers" not in data:
            data["mcpServers"] = {}

        # Replace legacy key if present
        if "code-search-mcp" in data["mcpServers"] and server_key == "code-search-graph":
            del data["mcpServers"]["code-search-mcp"]

        data["mcpServers"][server_key] = server_config

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, f"Configuration written -> {file_path}"
    except Exception as e:
        return False, f"Failed to write {file_path}: {e}"


RECOMMENDED_RULES_CONTENT = """# Code Search & Architecture MCP Guidelines

This project is integrated with `code-search-graph` local code knowledge graph and semantic search service. When exploring, refactoring, or authoring code, follow these guidelines to minimize token usage and maximize accuracy:

## 1. Exploration & Navigation
- **High-Level Overview**: Call `get_codebase_outline()` first to view the multi-language architectural map and understand module responsibilities without blind grep searches.
- **Feature Workflows**: When asking about business features (e.g., "user auth flow", "payment callback"), **call `explore_codebase(query=...)` once** to receive an end-to-end report containing routes, core logic, and downstream dependencies.
- **Intent / Semantic Search**: When searching by natural language concepts rather than exact symbol names, use `search_codebase(query=...)` (returns compact code snippets by default).
- **Exact Literals / Constants**: When searching exact identifiers, error codes, or config keys, use `exact_search(pattern=...)` for sub-second ripgrep search.

## 2. Refactoring & Blast-Radius Protection
- **Impact Assessment**: Before modifying or refactoring critical functions or classes, **always call** `get_impact_radius(symbol_name=...)` to identify upstream callers, affected files, and exposed Web APIs.
- **Call Hierarchy**:
  - Trace callers: `get_symbol_callers(symbol_name=...)`
  - Trace callees: `get_symbol_callees(symbol_name=...)`
  - Cross-module references: `find_references(symbol_name=...)`

## 3. Token-Efficient Best Practices
- Avoid reading entire large files; use `get_file_content(path, start_line, end_line)` to extract line-precise function implementations on demand.
"""


def setup_workspace_rules(repo_dir: Path) -> List[str]:
    """Initialize or update CLAUDE.md and .cursorrules in workspace"""
    messages = []
    # 1. CLAUDE.md
    claude_md = repo_dir / "CLAUDE.md"
    try:
        if claude_md.exists():
            existing = claude_md.read_text(encoding="utf-8")
            if "code-search-graph" not in existing and "code-search-mcp" not in existing:
                claude_md.write_text(existing.rstrip() + "\n\n" + RECOMMENDED_RULES_CONTENT, encoding="utf-8")
                messages.append(f"✅ Appended guidelines to existing CLAUDE.md -> {claude_md}")
            else:
                messages.append(f"ℹ️ CLAUDE.md already contains code-search-graph guidelines, skipped")
        else:
            claude_md.write_text(RECOMMENDED_RULES_CONTENT, encoding="utf-8")
            messages.append(f"✅ Created CLAUDE.md with best practices -> {claude_md}")
    except Exception as e:
        messages.append(f"⚠️ Failed to write CLAUDE.md: {e}")

    # 2. .cursorrules
    cursor_rules = repo_dir / ".cursorrules"
    try:
        if cursor_rules.exists():
            existing = cursor_rules.read_text(encoding="utf-8")
            if "code-search-graph" not in existing and "code-search-mcp" not in existing:
                cursor_rules.write_text(existing.rstrip() + "\n\n" + RECOMMENDED_RULES_CONTENT, encoding="utf-8")
                messages.append(f"✅ Appended guidelines to existing .cursorrules -> {cursor_rules}")
            else:
                messages.append(f"ℹ️ .cursorrules already contains guidelines, skipped")
        else:
            cursor_rules.write_text(RECOMMENDED_RULES_CONTENT, encoding="utf-8")
            messages.append(f"✅ Created .cursorrules with best practices -> {cursor_rules}")
    except Exception as e:
        messages.append(f"⚠️ Failed to write .cursorrules: {e}")

    return messages


def run_installer(
    clients: Optional[List[str]] = None,
    mode: str = "auto",
    target_repo: Optional[Path] = None,
    write_rules: bool = True,
) -> None:
    """Run one-click installer and configuration wizard"""
    print("\n" + "=" * 65)
    print("🚀 code-search-graph Auto-Installer & Client Configuration Wizard")
    print("=" * 65)

    all_paths = get_client_config_paths()
    repo = target_repo or Path.cwd().resolve()

    # Automatically detect optimal launch mode
    if mode == "auto":
        venv_py = repo / ".venv" / ("Scripts" if platform.system() == "Windows" else "bin") / ("python.exe" if platform.system() == "Windows" else "python")
        if venv_py.exists():
            selected_mode = "python"
            py_path = str(venv_py)
            print(f"📦 Detected local virtualenv: {py_path}")
        elif shutil.which("uvx"):
            selected_mode = "uvx"
            py_path = None
            print("📦 Detected uvx installed, using zero-install execution mode (uvx code-search-graph)")
        elif shutil.which("uv"):
            selected_mode = "uv"
            py_path = None
            print("📦 Detected uv installed, using uv run mode")
        else:
            selected_mode = "python"
            py_path = sys.executable
            print(f"📦 Using Python interpreter: {py_path}")
    else:
        selected_mode = mode
        py_path = sys.executable

    server_config = build_server_config(mode=selected_mode, python_path=py_path, repo_path=str(repo))

    if clients and "all" not in clients:
        selected_clients = clients
    else:
        selected_clients = list(all_paths.keys())

    print("\n🔍 Scanning and configuring AI clients...")
    configured_count = 0

    for client_name in selected_clients:
        if client_name not in all_paths:
            continue
        cfg_path = all_paths[client_name]

        parent_exists = cfg_path.parent.exists()
        is_workspace = "workspace" in client_name or client_name == "claude-code"

        should_write = parent_exists or is_workspace or cfg_path.exists()
        if should_write:
            ok, msg = safe_merge_json(cfg_path, "code-search-graph", server_config)
            status_icon = "✅" if ok else "❌"
            print(f"  {status_icon} [{client_name.upper()}] {msg}")
            if ok:
                configured_count += 1
        else:
            print(f"  ⏭️  [{client_name.upper()}] Directory not found ({cfg_path.parent}), skipped")

    if write_rules:
        print(f"\n📝 Setting up workspace rules (CLAUDE.md & .cursorrules)...")
        rule_logs = setup_workspace_rules(repo)
        for rlog in rule_logs:
            print(f"  {rlog}")

    print("\n" + "=" * 65)
    print(f"🎉 Installation complete! Configured MCP Server for {configured_count} client(s).")
    print("💡 Next steps:")
    print("   1. Restart your Claude Desktop / Cursor / Claude Code;")
    print("   2. You can now use the following tools directly in chat:")
    print("      - explore_codebase: One-click surgical feature exploration")
    print("      - get_codebase_outline: High-level multi-language architecture map")
    print("      - get_impact_radius: Blast-radius impact analysis before refactoring")
    print("      - exact_search: Ripgrep-powered exact literal and regex search")
    print("=" * 65 + "\n")
