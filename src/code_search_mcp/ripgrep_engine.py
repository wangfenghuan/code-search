import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from code_search_mcp.config import DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_FILES


@dataclass
class MatchItem:
    file_path: str
    line_number: int
    line_content: str
    match_preview: str


def find_system_ripgrep() -> Optional[str]:
    """探测 ripgrep (rg) 二进制：
    1. 优先使用项目自带跨平台预编译二进制 (Windows: rg.exe, Linux: x86_64-musl/arm64, macOS: Apple Silicon/Intel)
    2. 检查系统 PATH 环境变量 (shutil.which("rg"))
    3. 检查常见安装路径与主流开发工具 (Homebrew, Cargo, VS Code / Cursor 内置模块)
    """
    import platform

    # 1. 优先查本包自带预编译二进制（区分 Windows、Linux、macOS 及 CPU 架构）
    bin_dir = Path(__file__).resolve().parent / "bin"
    if bin_dir.exists():
        system = sys.platform
        machine = platform.machine().lower()
        is_arm = machine in ("arm64", "aarch64")

        candidates: List[str] = []
        if system == "win32":
            candidates = ["rg.exe"]
        elif system == "darwin":
            # macOS: 优先根据架构选择对应预编译二进制
            if is_arm:
                candidates = ["rg-aarch64-apple-darwin", "rg"]
            else:
                candidates = ["rg-x86_64-apple-darwin", "rg"]
        elif system.startswith("linux"):
            # Linux: 静态 musl 优先，无 glibc 依赖，支持任意发行版与容器
            if is_arm:
                candidates = ["rg-aarch64-unknown-linux-gnu", "rg"]
            else:
                candidates = ["rg-x86_64-unknown-linux-musl", "rg"]
        else:
            candidates = ["rg"]

        for cand_name in candidates:
            cand_path = bin_dir / cand_name
            if cand_path.exists() and cand_path.is_file():
                if system != "win32" and not os.access(cand_path, os.X_OK):
                    try:
                        os.chmod(cand_path, 0o755)
                    except Exception:
                        pass
                return str(cand_path)

    # 2. 查系统 PATH
    rg_in_path = shutil.which("rg") or shutil.which("rg.exe")
    if rg_in_path:
        return rg_in_path

    # 3. 检查常见安装路径与开发工具 (兼容 Windows / macOS Homebrew / Linux)
    user_home = Path.home()
    candidate_paths = [
        # macOS Homebrew / 系统路径
        Path("/opt/homebrew/bin/rg"),
        Path("/usr/local/bin/rg"),
        # Linux standard paths
        Path("/usr/bin/rg"),
        Path("/bin/rg"),
        # Cargo & 包管理器
        user_home / ".cargo" / "bin" / "rg",
        user_home / ".cargo" / "bin" / "rg.exe",
        user_home / "scoop" / "shims" / "rg.exe",
        Path("C:/ProgramData/chocolatey/bin/rg.exe"),
        # VS Code 内置
        user_home / "AppData/Local/Programs/Microsoft VS Code/resources/app/node_modules/@vscode/ripgrep/bin/rg.exe",
        user_home / ".vscode/extensions/node_modules/@vscode/ripgrep/bin/rg",
        # Cursor 内置
        user_home / "AppData/Local/Programs/cursor/resources/app/node_modules/@vscode/ripgrep/bin/rg.exe",
        user_home / ".cursor/extensions/node_modules/@vscode/ripgrep/bin/rg",
    ]

    for p in candidate_paths:
        if p.exists() and p.is_file():
            return str(p)

    return None


class ExactSearchEngine:
    """精准文本与模式检索引擎：优先调用底层工业级 ripgrep，无环境时优雅降级为内置引擎"""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path.resolve()
        self.rg_path = find_system_ripgrep()

    def search(
        self,
        pattern: str,
        is_regex: bool = False,
        case_sensitive: bool = False,
        file_glob: str = "",
        max_results: int = 20,
    ) -> Dict[str, Any]:
        """执行精准文本匹配"""
        if self.rg_path:
            try:
                results = self._search_with_ripgrep(
                    pattern=pattern,
                    is_regex=is_regex,
                    case_sensitive=case_sensitive,
                    file_glob=file_glob,
                    max_results=max_results,
                )
                return {
                    "engine": "ripgrep (Rust SIMD accelerated)",
                    "pattern": pattern,
                    "matches": results,
                }
            except Exception as e:
                sys.stderr.write(f"[code-search-graph] ripgrep execution error, falling back to built-in engine: {e}\n")

        # Fallback
        results = self._search_with_python(
            pattern=pattern,
            is_regex=is_regex,
            case_sensitive=case_sensitive,
            file_glob=file_glob,
            max_results=max_results,
        )
        return {
            "engine": "Built-in multi-threaded text engine",
            "pattern": pattern,
            "matches": results,
        }

    def _search_with_ripgrep(
        self,
        pattern: str,
        is_regex: bool,
        case_sensitive: bool,
        file_glob: str,
        max_results: int,
    ) -> List[MatchItem]:
        cmd = [self.rg_path, "--json"]

        if not is_regex:
            cmd.append("--fixed-strings")

        if case_sensitive:
            cmd.append("--case-sensitive")
        else:
            cmd.append("--ignore-case")

        # 过滤忽略目录
        for d in DEFAULT_IGNORE_DIRS:
            cmd.extend(["--glob", f"!{d}/**"])

        if file_glob:
            cmd.extend(["--glob", file_glob])

        cmd.extend(["--max-count", str(max_results)])
        cmd.append(pattern)
        cmd.append(str(self.repo_path))

        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        matches: List[MatchItem] = []
        for line in process.stdout.splitlines():
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if data.get("type") == "match":
                    match_data = data.get("data", {})
                    abs_p = match_data.get("path", {}).get("text", "")
                    try:
                        rel_p = str(Path(abs_p).relative_to(self.repo_path)).replace("\\", "/")
                    except ValueError:
                        rel_p = abs_p.replace("\\", "/")

                    line_num = match_data.get("line_number", 1)
                    line_text = match_data.get("lines", {}).get("text", "").rstrip("\r\n")

                    matches.append(
                        MatchItem(
                            file_path=rel_p,
                            line_number=line_num,
                            line_content=line_text,
                            match_preview=line_text.strip(),
                        )
                    )
                    if len(matches) >= max_results:
                        break
            except Exception:
                continue

        return matches

    def _search_with_python(
        self,
        pattern: str,
        is_regex: bool,
        case_sensitive: bool,
        file_glob: str,
        max_results: int,
    ) -> List[MatchItem]:
        matches: List[MatchItem] = []
        flags = 0 if case_sensitive else re.IGNORECASE

        try:
            if is_regex:
                regex_matcher = re.compile(pattern, flags)
            else:
                regex_matcher = re.compile(re.escape(pattern), flags)
        except re.error as e:
            sys.stderr.write(f"[code-search-graph] Invalid regular expression '{pattern}': {e}\n")
            return []

        glob_pat = None
        if file_glob:
            import fnmatch
            glob_pat = file_glob

        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]

            for file in files:
                if file in DEFAULT_IGNORE_FILES:
                    continue
                if glob_pat and not fnmatch.fnmatch(file, glob_pat):
                    continue

                full_path = Path(root) / file
                try:
                    rel_p = str(full_path.relative_to(self.repo_path)).replace("\\", "/")
                except ValueError:
                    rel_p = str(full_path).replace("\\", "/")

                # 跳过大文件 (> 2MB)
                if full_path.stat().st_size > 2 * 1024 * 1024:
                    continue

                try:
                    content = full_path.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue

                for i, line in enumerate(content.splitlines(), start=1):
                    if regex_matcher.search(line):
                        matches.append(
                            MatchItem(
                                file_path=rel_p,
                                line_number=i,
                                line_content=line.rstrip(),
                                match_preview=line.strip(),
                            )
                        )
                        if len(matches) >= max_results:
                            return matches

        return matches


def format_exact_results(result_dict: Dict[str, Any]) -> str:
    """Format exact search results into token-efficient Markdown evidence report"""
    pattern = result_dict.get("pattern", "")
    engine = result_dict.get("engine", "")
    matches: List[MatchItem] = result_dict.get("matches", [])

    if not matches:
        return f"No exact matches found for pattern \"{pattern}\"."

    lines = [
        f"## 🎯 Exact Matches: \"{pattern}\" ({len(matches)} matches found)",
        f"> **Engine**: `{engine}` | **Confidence**: `100% Exact Match`\n",
    ]

    for i, m in enumerate(matches, start=1):
        lines.append(
            f"**[{i}]** `{m.file_path}:{m.line_number}`\n"
            f"```python\n{m.line_number:4d} | {m.line_content}\n```"
        )

    return "\n".join(lines)
