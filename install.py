#!/usr/bin/env python3
"""code-search-mcp 一键极速安装与客户端自动配置脚本

运行方式：
    python install.py
    uv run install.py
"""

import sys
from pathlib import Path

# 将 src 目录加入模块搜索路径
src_dir = Path(__file__).resolve().parent / "src"
if src_dir.exists():
    sys.path.insert(0, str(src_dir))

from code_search_mcp.installer import run_installer

if __name__ == "__main__":
    run_installer()
