# AGENTS.md — Autonomous Coding Agent Guidelines

> Universal operational guide for AI agents (OpenAI Codex, Claude Code, Cursor, Windsurf, Devin, Cline, Copilot, Antigravity) working in or developing the `code-search-graph` repository.

---

## 1. Project Overview & Architecture

`code-search-graph` is a fast, local, lightweight code intelligence engine and Model Context Protocol (MCP) server. It combines tree-sitter AST call graphs, local vector embeddings, LanceDB, embedded ripgrep, and full-text search into a single unified service.

### Key Directory Structure

```text
code-search-mcp/
├── pyproject.toml              # PEP 621 packaging metadata, scripts & dependencies
├── README.md                   # Primary documentation (English + Chinese summary)
├── AGENTS.md                   # Universal instructions for AI agents
├── CLAUDE.md                   # Claude Code configuration & workflows
├── src/
│   └── code_search_mcp/        # Core Python package
│       ├── __init__.py         # Public exports (main, CodeIndexer, CodeSearcher, mcp)
│       ├── cli.py              # Typer CLI application & command dispatchers
│       ├── ui.py               # Rich terminal UI, cards, progress bars & banners
│       ├── server.py           # FastMCP stdio server exposing 11 code intelligence tools
│       ├── indexer.py          # Micro-batch streaming indexer (SQLite + LanceDB)
│       ├── searcher.py         # 4-way RRF hybrid search (Dense Vector + BM25 + Ripgrep + AST)
│       ├── graph_engine.py     # On-demand call graph resolution, BFS trace & blast radius
│       ├── outline.py          # Multi-language high-level architectural outline generator
│       ├── ripgrep_engine.py   # Embedded ripgrep integration & exact search engine
│       ├── embeddings.py       # FastEmbed / ONNX Runtime local vector embeddings
│       ├── watcher.py          # OS-native kernel file watcher for sub-second auto sync
│       ├── config.py           # Path management (~/.code-search-graph) & global constants
│       ├── installer.py        # One-click client auto-config (Claude, Cursor, Windsurf)
│       ├── text_utils.py       # CamelCase / snake_case splitting & token extraction
│       ├── bin/                # Bundled static ripgrep binaries (macOS, Linux, Windows)
│       ├── models/             # Bundled offline ONNX model weights
│       └── parsers/            # Tree-sitter AST syntax parsers
│           ├── common.py       # Base CodeChunk, RawCall & CodeSymbol definitions
│           ├── dispatcher.py   # Language routing by file extension
│           ├── python.py       # Python AST parser & call extractor
│           ├── javascript.py   # TypeScript & JavaScript parser
│           ├── vue.py          # Vue Single File Component (.vue SFC) parser
│           ├── java.py         # Java Spring Boot & class parser
│           ├── go.py           # Go struct & function parser
│           └── rust.py         # Rust trait, struct & impl parser
└── tests/                      # Automated test suite & benchmarks
    ├── test_cli.py             # CLI end-to-end subcommand test suite (12 tests)
    ├── test_vue_parser.py      # Vue SFC template & script parser tests
    └── sample_project/         # Multi-language sample project used for testing
```

---

## 2. Development & Testing Commands

### Setup & Installation
```bash
# Initialize virtual environment with uv
uv venv
.venv\Scripts\activate   # Windows
# source .venv/bin/activate  # macOS / Linux

# Install dependencies in editable mode
uv pip install -e .

# Install global CLI binary for testing
uv tool install --force .
```

### Running Tests
```bash
# Run the fast CLI end-to-end test suite
.venv\Scripts\python.exe tests/test_cli.py

# Run Vue parser unit test
.venv\Scripts\python.exe -m pytest tests/test_vue_parser.py -v

# Run full test suite with pytest
.venv\Scripts\pytest -q
```

### Running the CLI
```bash
# Check version & system card
code-search-graph --version

# View help and examples
code-search-graph --help

# Index a repository with live progress bar
code-search-graph index tests/sample_project

# Hybrid semantic search with syntax cards
code-search-graph search "user login" --path tests/sample_project

# Exact search via embedded ripgrep
code-search-graph exact "verify_password" --path tests/sample_project

# Architecture outline map
code-search-graph outline tests/sample_project
```

### Packaging & Build
```bash
# Build wheel and sdist with uv
uv build
```

---

## 3. Core Architectural Invariants

When modifying or extending this codebase, always preserve the following core guarantees:

### 1. Bounded Memory (< 160MB RAM)
- **Never collect all code chunks in memory simultaneously.**
- The indexer uses a strict streaming micro-batch pipeline (`STREAM_BATCH_SIZE = 300`). Chunks are parsed, flushed to SQLite, and embedded in micro-batches with explicit `gc.collect()`.
- FastEmbed inference threads are bounded (`EMBEDDING_THREADS = min(4, cpu_count)`).

### 2. Pure Stdio for MCP Protocol
- When running in MCP mode (`server.py` / `code-search-graph serve`), **stdout is strictly reserved for JSON-RPC messages**.
- **Never write debug prints or logs to `sys.stdout`.** All logs, banners, warnings, and error messages must go to `sys.stderr` via `sys.stderr.write()` or `rich.Console(stderr=True)`.

### 3. Windows Terminal & UTF-8 Safety
- Windows terminal encoding can default to GBK, causing `UnicodeEncodeError` when emitting Unicode symbols (e.g. `⚡`, `📁`).
- Always include the UTF-8 reconfigure block at entry points:
  ```python
  if sys.platform == "win32":
      try:
          sys.stdout.reconfigure(encoding="utf-8", errors="replace")
          sys.stderr.reconfigure(encoding="utf-8", errors="replace")
      except Exception:
          pass
  ```
- Use `Console(highlight=False, legacy_windows=False)` for Rich consoles on Windows.

### 4. Zero-Network Offline First
- By default, the package bundles precompiled static ripgrep binaries in `bin/` and supports bundled ONNX model weights in `models/`.
- If downloading external models, the cache defaults to `~/.code-search-graph/models` with seamless fallback to `~/.code-search-mcp/models` and official mirror fallback (`https://hf-mirror.com`).

---

## 4. Best Practices for AI Agents Using `code-search-graph`

When an AI agent is working inside any project that has `code-search-graph` configured, prioritize tools in this order to minimize token usage and latency:

1. **Understand Project Layout**: Call `get_codebase_outline()` first. Never run blind `glob` or recursive directory listings.
2. **Feature & Workflow Exploration**: Call `explore_codebase(query=...)` once. It aggregates the entry route, core implementation, and downstream call tree in a single round-trip.
3. **Refactoring & Modifying Code**: **Always call `get_impact_radius(symbol_name=...)` before editing** important functions or classes, or **call `get_diff_context()` during PR code review** to inspect current changes. It reveals affected upstream callers, exposed HTTP routes, and recommended unit tests to protect against regressions.
4. **Exact Identifiers & Constants**: Use `exact_search(pattern=...)` for sub-second ripgrep lookups of exact symbols, config keys, or error codes.
5. **Reading Code**: Avoid reading entire large files. Use `get_file_content(path, start_line, end_line)` to inspect only the required lines.
6. **Dead Code & Cleanup**: Call `find_dead_code()` to detect uncalled functions and zombie code before refactoring or deleting obsolete features.
