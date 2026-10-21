#!/usr/bin/env python3
"""One-click installer and client auto-config script for code-search-graph

Usage:
    python install.py
    uv run install.py
"""

import sys
from pathlib import Path

# Add src to module search path
src_dir = Path(__file__).resolve().parent / "src"
if src_dir.exists():
    sys.path.insert(0, str(src_dir))

from code_search_mcp.installer import run_installer

if __name__ == "__main__":
    run_installer()
