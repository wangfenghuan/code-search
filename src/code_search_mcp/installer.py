"""一键安装与全自动客户端配置模块 (One-Click Auto-Installer)

启发自 CodeGraph 与现代开发工具工程实践：
彻底免去用户手动配置 JSON、找路径、配权限的繁琐步骤。
支持一键自动检测并配置：
1. Claude Code (~/.claude.json)
2. Claude Desktop (claude_desktop_config.json: Win / Mac / Linux)
3. Cursor (.cursor/mcp.json 及全局设置)
4. Windsurf (~/.codeium/windsurf/mcp_config.json)
5. Cline / Roo Code (VS Code 扩展全局设置)
6. 自动注入 CLAUDE.md / .cursorrules 最佳实践工具调用规则（防止 AI 上下文爆炸）
"""

import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def get_client_config_paths() -> Dict[str, Path]:
    """根据操作系统自动解析主流 AI 客户端的 MCP 配置文件路径"""
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

    # 3. Cursor (全局与当前工作区)
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

    # 5. Cline (VS Code Extension)
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
    """生成标准 MCP Server 配置块"""
    if mode == "uvx":
        return {
            "command": "uvx",
            "args": ["code-search-mcp", "serve"],
        }
    elif mode == "uv":
        base_dir = repo_path or str(Path.cwd().resolve())
        return {
            "command": "uv",
            "args": ["--directory", base_dir, "run", "code-search-mcp", "serve"],
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
            "args": ["run", "-i", "--rm", "-v", f"{repo_path or '.'}:/workspace", "code-search-mcp:latest"],
        }
    else:
        return {
            "command": "uvx",
            "args": ["code-search-mcp", "serve"],
        }


def safe_merge_json(file_path: Path, server_key: str, server_config: Dict[str, Any]) -> Tuple[bool, str]:
    """安全合并 JSON 配置，创建备份并保留用户已有的所有配置项"""
    try:
        data: Dict[str, Any] = {}
        if file_path.exists():
            try:
                # 备份原始文件
                backup_path = file_path.with_suffix(f"{file_path.suffix}.bak")
                shutil.copy2(file_path, backup_path)
                data = json.loads(file_path.read_text(encoding="utf-8"))
            except Exception:
                data = {}

        # 确保根键为 dict
        if not isinstance(data, dict):
            data = {}

        # 针对不同客户端的 schema 进行针对性合并
        if "mcpServers" not in data:
            data["mcpServers"] = {}

        data["mcpServers"][server_key] = server_config

        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return True, f"已安全写入配置 -> {file_path}"
    except Exception as e:
        return False, f"写入失败 {file_path}: {e}"


RECOMMENDED_RULES_CONTENT = """# Code Search & Architecture MCP Guidelines (启发自 CodeGraph)

本项目已接入 `code-search-mcp` 本地代码知识图谱与语义检索服务。在探索、重构和编写代码时，请遵循以下规则以节省 Token 与最大化准确率：

## 1. 探索与定位
- **了解全貌**: 优先调用 `get_codebase_outline()` 查看全局多语言架构地图，了解各模块核心职责，避免盲目全盘搜索。
- **业务全链路**: 询问业务功能（如“用户认证流程”、“支付退款逻辑”）时，**优先且仅需调用一次** `explore_codebase(query=...)`，直接获得包含路由入口、核心源码与下游拓扑的端到端报告。
- **概念/意图搜索**: 当不知道确切函数名时，使用 `search_codebase(query=...)`，默认以 `compact` 紧凑模式返回代码摘要。
- **字面量/配置项搜索**: 已知确切标识符、错误码、环境变量 Key 时，使用 `exact_search(pattern=...)`，基于 ripgrep 秒级定位。

## 2. 重构与改动保护（防线上故障）
- **影响面评估**: 在修改或重构任何重要函数/类前，**必须先调用** `get_impact_radius(symbol_name=...)`，获取直接和间接波及的上游模块、关联文件与对外 Web 路由。
- **调用拓扑追踪**: 
  - 追踪谁调用了目标函数：`get_symbol_callers(symbol_name=...)`
  - 追踪目标函数依赖了谁：`get_symbol_callees(symbol_name=...)`
  - 全仓库反向引用分析：`find_references(symbol_name=...)`

## 3. Token 极省最佳实践
- 严禁对大文件全量读取；若需查看某段函数完整实现，配合 `get_file_content(path, start_line, end_line)` 按需精准提取行区间。
"""


def setup_workspace_rules(repo_dir: Path) -> List[str]:
    """在指定工作区初始化或更新 CLAUDE.md 和 .cursorrules"""
    messages = []
    # 1. CLAUDE.md
    claude_md = repo_dir / "CLAUDE.md"
    try:
        if claude_md.exists():
            existing = claude_md.read_text(encoding="utf-8")
            if "code-search-mcp" not in existing:
                claude_md.write_text(existing.rstrip() + "\n\n" + RECOMMENDED_RULES_CONTENT, encoding="utf-8")
                messages.append(f"✅ 已向已有 CLAUDE.md 追加工具使用规则 -> {claude_md}")
            else:
                messages.append(f"ℹ️ CLAUDE.md 已包含 code-search-mcp 规范，跳过")
        else:
            claude_md.write_text(RECOMMENDED_RULES_CONTENT, encoding="utf-8")
            messages.append(f"✅ 已创建 CLAUDE.md 最佳实践规则文件 -> {claude_md}")
    except Exception as e:
        messages.append(f"⚠️ 写入 CLAUDE.md 失败: {e}")

    # 2. .cursorrules
    cursor_rules = repo_dir / ".cursorrules"
    try:
        if cursor_rules.exists():
            existing = cursor_rules.read_text(encoding="utf-8")
            if "code-search-mcp" not in existing:
                cursor_rules.write_text(existing.rstrip() + "\n\n" + RECOMMENDED_RULES_CONTENT, encoding="utf-8")
                messages.append(f"✅ 已向已有 .cursorrules 追加工具使用规则 -> {cursor_rules}")
            else:
                messages.append(f"ℹ️ .cursorrules 已包含规则，跳过")
        else:
            cursor_rules.write_text(RECOMMENDED_RULES_CONTENT, encoding="utf-8")
            messages.append(f"✅ 已创建 .cursorrules 最佳实践规则文件 -> {cursor_rules}")
    except Exception as e:
        messages.append(f"⚠️ 写入 .cursorrules 失败: {e}")

    return messages


def run_installer(
    clients: Optional[List[str]] = None,
    mode: str = "auto",
    target_repo: Optional[Path] = None,
    write_rules: bool = True,
) -> None:
    """执行一键安装配置向导"""
    print("\n" + "=" * 65)
    print("🚀 code-search-mcp 一键极速安装与客户端自动配置向导")
    print("=" * 65)

    all_paths = get_client_config_paths()
    repo = target_repo or Path.cwd().resolve()

    # 自动探测最佳启动模式
    if mode == "auto":
        # 如果是在本仓库源码目录下运行且存在 uv.lock 或 .venv，优先使用当前 Python 环境
        venv_py = repo / ".venv" / ("Scripts" if platform.system() == "Windows" else "bin") / ("python.exe" if platform.system() == "Windows" else "python")
        if venv_py.exists():
            selected_mode = "python"
            py_path = str(venv_py)
            print(f"📦 检测到本地虚拟环境: {py_path}")
        elif shutil.which("uvx"):
            selected_mode = "uvx"
            py_path = None
            print("📦 检测到系统已安装 uvx，将使用免安装极速执行模式 (uvx code-search-mcp)")
        elif shutil.which("uv"):
            selected_mode = "uv"
            py_path = None
            print("📦 检测到系统已安装 uv，将使用 uv run 模式")
        else:
            selected_mode = "python"
            py_path = sys.executable
            print(f"📦 使用当前 Python 解释器: {py_path}")
    else:
        selected_mode = mode
        py_path = sys.executable

    server_config = build_server_config(mode=selected_mode, python_path=py_path, repo_path=str(repo))

    # 确定要配置的客户端清单
    if clients and "all" not in clients:
        selected_clients = clients
    else:
        selected_clients = list(all_paths.keys())

    print("\n🔍 正在扫描并自动配置 AI 客户端...")
    configured_count = 0

    for client_name in selected_clients:
        if client_name not in all_paths:
            continue
        cfg_path = all_paths[client_name]

        # 如果是父目录存在或者是当前工作区，积极创建配置
        parent_exists = cfg_path.parent.exists()
        is_workspace = "workspace" in client_name or client_name == "claude-code"

        # 判断是否应该写入
        should_write = parent_exists or is_workspace or cfg_path.exists()
        if should_write:
            ok, msg = safe_merge_json(cfg_path, "code-search-mcp", server_config)
            status_icon = "✅" if ok else "❌"
            print(f"  {status_icon} [{client_name.upper()}] {msg}")
            if ok:
                configured_count += 1
        else:
            print(f"  ⏭️  [{client_name.upper()}] 未检测到安装目录 ({cfg_path.parent})，已跳过")

    # 写入工作区规范
    if write_rules:
        print(f"\n📝 正在为代码库配置 AI 工具使用规范 (CLAUDE.md & .cursorrules)...")
        rule_logs = setup_workspace_rules(repo)
        for rlog in rule_logs:
            print(f"  {rlog}")

    print("\n" + "=" * 65)
    print(f"🎉 安装配置完成！共为 {configured_count} 个客户端配置了 MCP Server。")
    print("💡 使用方式:")
    print("   1. 重启你的 Claude Desktop / Cursor / Claude Code；")
    print("   2. 在对话框中即可直接使用:")
    print("      - explore_codebase: 业务功能全链路一键直达探索")
    print("      - get_codebase_outline: 极省 Token 的多语言项目架构地图")
    print("      - get_impact_radius: 修改核心代码前的改动爆炸半径分析")
    print("      - exact_search: 基于 ripgrep 的极速精准字面量与正则查找")
    print("=" * 65 + "\n")
