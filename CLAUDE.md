# CLAUDE.md — Claude Code & Desktop Developer Guide

> Operational instructions and best practices for Anthropic's Claude Code and Claude Desktop agents working in or integrating with `code-search-graph`.

---

## 1. Quick Reference & Commands

### Build & Test Commands
```bash
# Run the fast automated CLI test suite (12 tests)
.venv\Scripts\python.exe tests/test_cli.py

# Run unit tests with pytest
.venv\Scripts\pytest -q tests/test_vue_parser.py
.venv\Scripts\pytest -q

# Build distribution packages (wheel + sdist)
uv build

# Reinstall CLI globally for local validation
uv tool install --force .
```

### Running the CLI
```bash
# Check version & system info card
code-search-graph --version

# View all options and help
code-search-graph --help

# Index repository with live progress bar
code-search-graph index .

# Semantic search with syntax-highlighted preview
code-search-graph search "user authentication and token validation"

# Exact literal or regex search via embedded ripgrep
code-search-graph exact "hash_password"

# Display multi-language architecture outline map
code-search-graph outline

# End-to-end surgical feature exploration
code-search-graph explore "user login workflow"

# Upstream and downstream call graph analysis
code-search-graph callers "verify_password"
code-search-graph callees "AuthService.login"

# Change impact blast-radius analysis before refactoring
code-search-graph impact "AuthService" --depth 3

# Cache inspection and cleanup
code-search-graph cache
code-search-graph clean --orphaned
```

---

## 2. Architecture & Code Structure

- **`src/code_search_mcp/cli.py`**: Typer command-line application, subcommands, and options.
- **`src/code_search_mcp/ui.py`**: Rich terminal interface, custom ASCII banners, system cards, syntax-highlighted search result cards, and dynamic `Progress` bars.
- **`src/code_search_mcp/server.py`**: FastMCP stdio server exposing 11 code search & call graph tools.
- **`src/code_search_mcp/indexer.py`**: Micro-batch streaming indexer with SQLite (structural nodes) and LanceDB (vector embeddings).
- **`src/code_search_mcp/graph_engine.py`**: On-demand caller/callee resolution, execution traces, and blast-radius analysis.
- **`src/code_search_mcp/searcher.py`**: 4-way RRF hybrid search fusing dense vectors, BM25 full text, ripgrep exact matching, and AST structure.
- **`src/code_search_mcp/outline.py`**: High-level token-efficient architecture map generator.
- **`src/code_search_mcp/ripgrep_engine.py`**: Embedded cross-platform static ripgrep integration.
- **`src/code_search_mcp/embeddings.py`**: Local vectorization with FastEmbed and ONNX Runtime.
- **`src/code_search_mcp/watcher.py`**: Kernel-level live file watcher with debounce.
- **`src/code_search_mcp/parsers/`**: Tree-sitter parsers for Python, TypeScript, JavaScript, Vue, Java, Go, and Rust.

---

## 3. Engineering Guidelines for Claude Code

1. **Memory Discipline**: Maintain streaming micro-batch processing (`STREAM_BATCH_SIZE = 300`). Never accumulate full repository chunks or embeddings in memory.
2. **MCP Stdio Integrity**: Never write anything to `stdout` during server execution. All logs, warnings, and messages must be written to `sys.stderr`.
3. **Windows UTF-8 Protection**: Windows console defaults to GBK. Ensure UTF-8 reconfigure logic and `legacy_windows=False` remain in place to prevent `UnicodeEncodeError`.
4. **Offline Capability**: Preserve offline zero-network defaults.

---

## 4. Guidelines for Using `code-search-graph` Tools in Any Project

When `code-search-graph` is configured as an MCP server, follow these rules to maximize accuracy and minimize token consumption:

1. **Understand Project Layout**: Call `get_codebase_outline()` first to review module structure and exported classes/functions instead of listing directories.
2. **Feature & Workflow Questions**: When asked about a feature (e.g., "how does login work?", "explain order checkout"), **call `explore_codebase(query=...)` once**. It provides entry routes, implementation snippets, and call hierarchies in a single response.
3. **Refactoring Protection**: **Always call `get_impact_radius(symbol_name=...)` before refactoring or editing** functions or classes to identify all upstream callers and exposed APIs.
4. **Call Graph Tracing**:
   - Upstream callers: `get_symbol_callers(symbol_name=...)`
   - Downstream dependencies: `get_symbol_callees(symbol_name=...)`
   - Full references: `find_references(symbol_or_keyword=...)`
5. **Exact Identifiers**: Use `exact_search(pattern=...)` for exact function names, config keys, or error codes.
6. **Token-Efficient Reading**: Use `get_file_content(path, start_line, end_line)` to read only necessary line ranges rather than loading entire files.
