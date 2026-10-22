import json
import os
import sqlite3
import sys
from collections import defaultdict
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
            if sym.symbol_type in ("class", "struct", "interface", "record", "enum", "annotation", "component"):
                classes_map[sym.name] = {
                    "name": sym.name,
                    "type": sym.symbol_type,
                    "summary": sym.docstring.split("\n")[0].strip() if sym.docstring else "",
                    "methods": [],
                }
            elif sym.symbol_type in ("method", "constructor"):
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

    def generate_from_db(self) -> Optional[Dict[str, Any]]:
        """从已建立的 SQLite 关系数据库毫秒级逆向组装大纲 (零重复磁盘与语法解析开销，耗时 <5ms)"""
        sqlite_file = self.db_path / "graph.sqlite3"
        if not sqlite_file.exists():
            return None

        try:
            conn = sqlite3.connect(str(sqlite_file))
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT file_path, symbol_name, chunk_type, start_line, end_line, docstring, route_info FROM nodes ORDER BY file_path, start_line"
            ).fetchall()
            conn.close()

            if not rows:
                return None

            files_map = defaultdict(lambda: {"classes_map": {}, "functions": [], "file_summary": ""})
            for r in rows:
                f_p = r["file_path"]
                sym_type = r["chunk_type"]
                sym_name = r["symbol_name"]
                doc = r["docstring"] or ""
                route = r["route_info"] or ""

                if not files_map[f_p]["file_summary"] and doc:
                    files_map[f_p]["file_summary"] = doc.split("\n")[0].strip()

                if sym_type in ("class", "struct", "interface", "record", "enum", "annotation", "component"):
                    files_map[f_p]["classes_map"][sym_name] = {
                        "name": sym_name,
                        "type": sym_type,
                        "summary": doc.split("\n")[0].strip() if doc else "",
                        "methods": [],
                    }
                elif sym_type in ("method", "constructor"):
                    if "." in sym_name:
                        cls_name, m_name = sym_name.split(".", 1)
                        if cls_name not in files_map[f_p]["classes_map"]:
                            files_map[f_p]["classes_map"][cls_name] = {
                                "name": cls_name,
                                "type": "class",
                                "summary": "",
                                "methods": [],
                            }
                        if m_name not in files_map[f_p]["classes_map"][cls_name]["methods"]:
                            files_map[f_p]["classes_map"][cls_name]["methods"].append(m_name)
                    else:
                        files_map[f_p]["functions"].append(
                            {"name": sym_name, "summary": doc.split("\n")[0].strip() if doc else "", "route": route}
                        )
                elif sym_type == "function":
                    files_map[f_p]["functions"].append(
                        {"name": sym_name, "summary": doc.split("\n")[0].strip() if doc else "", "route": route}
                    )

            modules = []
            for f_p in sorted(files_map.keys()):
                d = files_map[f_p]
                ext = Path(f_p).suffix.lower()
                lang = EXTENSION_LANG_MAP.get(ext, "unknown")
                modules.append(
                    {
                        "rel_path": f_p,
                        "language": lang,
                        "summary": d["file_summary"],
                        "classes": list(d["classes_map"].values()),
                        "functions": d["functions"],
                    }
                )

            outline_data = {
                "repo_name": self.repo_path.name,
                "repo_path": str(self.repo_path),
                "total_modules": len(modules),
                "modules": modules,
            }

            try:
                self.db_path.mkdir(parents=True, exist_ok=True)
                cache_file = self.db_path / "outline.json"
                cache_file.write_text(json.dumps(outline_data, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception:
                pass

            return outline_data
        except Exception:
            return None

    def generate(self) -> Dict[str, Any]:
        """生成整个项目的多语言架构大纲字典 (冷启动扫描回退)"""
        # 优先使用遵循 .gitignore 的 CodeIndexer.scan_files 扫描真实源文件
        try:
            from code_search_mcp.indexer import CodeIndexer
            target_files = CodeIndexer(self.repo_path).scan_files()
        except Exception:
            target_files = []
            for root, dirs, files in os.walk(self.repo_path):
                dirs[:] = [d for d in dirs if d not in DEFAULT_IGNORE_DIRS and not d.startswith(".")]
                for file in sorted(files):
                    ext = Path(file).suffix.lower()
                    if ext in EXTENSION_LANG_MAP and file not in DEFAULT_IGNORE_FILES:
                        target_files.append(Path(root) / file)

        files_info = []
        for full_p in sorted(target_files):
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
        # 优先从已有的 SQLite 图谱毫秒级提取，避免冷启动全盘重复语法树解析
        db_outline = self.generate_from_db()
        if db_outline:
            return db_outline
        return self.generate()

    def format_as_markdown(self, outline: Dict[str, Any], max_depth: int = 3) -> str:
        """Format architecture outline into compact token-efficient Markdown"""
        repo_name = outline.get("repo_name", "Codebase")
        total_modules = outline.get("total_modules", 0)
        lines = [
            f"# 🏛️ Architecture Outline: {repo_name} ({total_modules} source files)\n",
            "> 💡 **Usage Tip**: This outline summarizes module responsibilities and exported symbols. Identify relevant modules here first, then call `search_codebase` or `exact_search` for line-level details.\n",
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
                    lines.append(f"  - **{c_type}** `{c_name}`{c_sum} methods: {methods_str}")
                else:
                    lines.append(f"  - **{c_type}** `{c_name}`{c_sum}")

            functions = mod.get("functions", [])
            for fn in functions:
                fn_name = fn["name"]
                fn_sum = f" ({fn['summary']})" if fn.get("summary") else ""
                route_str = f" `[{fn['route']}]`" if fn.get("route") else ""
                lines.append(f"  - **function** `{fn_name}()`{route_str}{fn_sum}")

            lines.append("")

        return "\n".join(lines)
