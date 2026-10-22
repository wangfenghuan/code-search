"""code-search-graph: Local AST Call Graph & Intelligent Hybrid Semantic Code Search Engine"""

from typing import Any


def main(*args: Any, **kwargs: Any) -> Any:
    """CLI entrypoint forwarding to code_search_mcp.cli:main"""
    from code_search_mcp.cli import main as cli_main

    return cli_main(*args, **kwargs)


def __getattr__(name: str) -> Any:
    """Lazy-load heavy modules upon attribute access to eliminate top-level import overhead"""
    if name == "CodeIndexer":
        from code_search_mcp.indexer import CodeIndexer

        return CodeIndexer
    elif name == "CodeSearcher":
        from code_search_mcp.searcher import CodeSearcher

        return CodeSearcher
    elif name == "mcp":
        from code_search_mcp.server import mcp

        return mcp
    elif name == "main":
        return main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return ["main", "CodeIndexer", "CodeSearcher", "mcp"]


__all__ = ["main", "CodeIndexer", "CodeSearcher", "mcp"]
