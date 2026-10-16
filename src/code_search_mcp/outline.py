import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from code_search_mcp.config import DEFAULT_IGNORE_DIRS, DEFAULT_IGNORE_FILES, get_repo_db_path
from code_search_mcp.multilang_parser import EXTENSION_LANG_MAP, TreeSitterParser


class ProjectOutlineGenerator:
    """提取多语言代码库的轻量级全局架构大纲（骨架树），供 AI 极省 Token 地理清项目拓扑"""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path.resolve()
        self.db_path = get_repo_db_path(self.repo_path)
        self.parser = TreeSitterParser()

    def extract_file_skeleton(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """从多语言源文件中提取精简模块签名"""
        try:
            rel_path = str(file_path.relative_to(self.repo_path)).replace("\\", "/")
        except ValueError:
            rel_path = str(file_path).replace("\\", "/")

        ext = file_path.suffix.lower()
        lang = EXTENSION_LANG_MAP.get(ext, "unknown")

        symbols = self.parser.parse_file(file_path)
        if not symbols:
            return None

        # 提取文件级概要（如果第一个符号有注释，或者从顶部注释推断）
        file_summary = ""
        for s in symbols:
            if s.docstring:
                file_summary = s.docstring.split("\n")[0].strip()
                break

        classes_map: Dict[str, Dict[str, Any]] = {}
        functions: List[Dict[str, Any]] = []

        for sym in symbols:
            if sym.symbol_type in ("class", "struct", "interface"):
                classes_map[sym.name] = {
                    "name": sym.name,
                    "type": sym.symbol_type,
                    "summary": sym.docstring.split("\n")[0].strip() if sym.docstring else "",
                    "methods": [],
                }
            elif sym.symbol_type == "method":
                # 分离 ClassName.methodName
                if "." in sym.name:
                    cls_name, m_name = sym.name.split(".", 1)
                    if cls_name not in classes_map:
                        classes_map[cls_name] = {
                            "name": cls_name,
                            "type": "class",
                            "summary": "",
                            "methods": [],
                        }
                    if m_name not in classes_map[cls_name]["methods"]:
                        classes_map[cls_name]["methods"].append(m_name)
                else:
                    if not any(f["name"] == sym.name for f in functions):
                        functions.append(
                            {
                                "name": sym.name,
                                "summary": sym.docstring.split("\n")[0].strip() if sym.docstring else "",
                                "route": sym.route_info,
                            }
                        )
            elif sym.symbol_type == "function":
                if not any(f["name"] == sym.name for f in functions):
                    functions.append(
                        {
                            "name": sym.name,
                            "summary": sym.docstring.split("\n")[0].strip() if sym.docstring else "",
                            "route": sym.route_info,
                        }
                    )

        return {
            "rel_path": rel_path,
            "language": lang,
            "summary": file_summary,
            "classes": list(classes_map.values()),
            "functions": functions,
        }

    def generate(self) -> Dict[str, Any]:
        """生成整个项目的多语言架构大纲字典"""
        files_info = []
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]
            for file in sorted(files):
                ext = Path(file).suffix.lower()
                if ext in EXTENSION_LANG_MAP and file not in DEFAULT_IGNORE_FILES:
                    full_p = Path(root) / file
                    info = self.extract_file_skeleton(full_p)
                    if info:
                        files_info.append(info)

        outline_data = {
            "repo_name": self.repo_path.name,
            "repo_path": str(self.repo_path),
            "total_modules": len(files_info),
            "modules": files_info,
        }

        # 缓存大纲至 LanceDB 所在目录
        try:
            cache_file = self.db_path / "outline.json"
            cache_file.write_text(json.dumps(outline_data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        return outline_data

    def get_cached_or_generate(self) -> Dict[str, Any]:
        cache_file = self.db_path / "outline.json"
        if cache_file.exists():
            try:
                return json.loads(cache_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        return self.generate()

    def format_as_markdown(self, outline: Dict[str, Any], max_depth: int = 3) -> str:
        """将多语言架构大纲转化为紧凑结构、极省 Token 的 Markdown"""
        repo_name = outline.get("repo_name", "项目")
        total_modules = outline.get("total_modules", 0)
        lines = [
            f"# 🏛️ 项目全局多语言架构大纲: {repo_name} (共 {total_modules} 个核心源文件)\n",
            "> 💡 **使用提示**: 此大纲展示项目所有 Python/TS/JS/Go 模块职责与暴露符号。请优先根据大纲定位模块，再使用 `search_codebase` 或 `exact_search` 精准查看细节。\n",
        ]

        modules = outline.get("modules", [])
        for mod in modules:
            rel_p = mod["rel_path"]
            lang = mod.get("language", "code")
            summary = f" — *{mod['summary']}*" if mod.get("summary") else ""
            lines.append(f"### 📄 `[{lang}]` `{rel_p}`{summary}")

            classes = mod.get("classes", [])
            for c in classes:
                c_name = c["name"]
                c_type = c.get("type", "class")
                c_sum = f" ({c['summary']})" if c.get("summary") else ""
                methods_str = ", ".join(f"`{m}()`" for m in c.get("methods", []))
                if methods_str:
                    lines.append(f"  - **{c_type}** `{c_name}`{c_sum} 包含方法: {methods_str}")
                else:
                    lines.append(f"  - **{c_type}** `{c_name}`{c_sum}")

            functions = mod.get("functions", [])
            for fn in functions:
                fn_name = fn["name"]
                fn_sum = f" ({fn['summary']})" if fn.get("summary") else ""
                route_str = f" `[{fn['route']}]`" if fn.get("route") else ""
                lines.append(f"  - **函数** `{fn_name}()`{route_str}{fn_sum}")

            lines.append("")

        return "\n".join(lines)
