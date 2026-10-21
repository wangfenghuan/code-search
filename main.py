"""Entrypoint script for code-search-graph. Supports `uv run main.py` for service or CLI."""

import sys
from code_search_mcp.cli import main

if __name__ == "__main__":
    main()
