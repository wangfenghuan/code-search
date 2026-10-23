<div align="center">

# code-search-graph

### Supercharge Claude Code, Cursor, Codex, Windsurf, Gemini, Antigravity, Cline, and Copilot with Multi-Language Code Intelligence

**Zero-config code graph · 4-way RRF hybrid search · surgical context · built for how agents actually work · 100% local**

[ English ](#code-search-graph) · [ 中文说明 ](#-中文说明)

[![PyPI version](https://img.shields.io/pypi/v/code-search-graph.svg)](https://pypi.org/project/code-search-graph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![Windows](https://img.shields.io/badge/Windows-supported-blue.svg)](#supported-platforms)
[![macOS](https://img.shields.io/badge/macOS-supported-blue.svg)](#supported-platforms)
[![Linux](https://img.shields.io/badge/Linux-supported-blue.svg)](#supported-platforms)

[![Claude Code](https://img.shields.io/badge/Claude_Code-supported-blueviolet.svg)](#supported-agents)
[![Cursor](https://img.shields.io/badge/Cursor-supported-blueviolet.svg)](#supported-agents)
[![Windsurf](https://img.shields.io/badge/Windsurf-supported-blueviolet.svg)](#supported-agents)
[![Codex](https://img.shields.io/badge/Codex-supported-blueviolet.svg)](#supported-agents)
[![Antigravity](https://img.shields.io/badge/Antigravity-supported-blueviolet.svg)](#supported-agents)
[![Cline](https://img.shields.io/badge/Cline-supported-blueviolet.svg)](#supported-agents)
[![M8ven Score](https://m8ven.ai/badge/mcp/wangfenghuan-code-search-1irys6?v=a08aa1ea0de046dbb1ae8554e6357ddd)](https://m8ven.ai/mcp/wangfenghuan-code-search-1irys6?s=readme)
</div>

---

## Contents / 目录

- [Why code-search-graph?](#why-code-search-graph)
  - [Benchmark Results](#benchmark-results)
- [Get Started](#get-started)
  - [1. Install the CLI](#1-install-the-cli)
  - [2. Wire up your agent(s)](#2-wire-up-your-agents)
  - [3. Initialize each project](#3-initialize-each-project)
  - [4. Always Fresh (Auto-Sync)](#4-always-fresh-auto-sync)
- [Key Features](#key-features)
  - [Surgical Exploration (`explore_codebase`)](#surgical-exploration-explore_codebase)
  - [Deterministic Call Graph & Blast Radius](#deterministic-call-graph--blast-radius)
  - [4-Way RRF Hybrid Search](#4-way-rrf-hybrid-search)
  - [Architecture Outline Map](#architecture-outline-map)
  - [Bundled Cross-Platform ripgrep](#bundled-cross-platform-ripgrep)
  - [Streaming Micro-Batch Pipeline (< 160MB RAM)](#streaming-micro-batch-pipeline--160mb-ram)
- [MCP Tools](#mcp-tools)
- [CLI Reference](#cli-reference)
- [Supported Languages & Frameworks](#supported-languages--frameworks)
- [Data & Privacy](#data--privacy)
- [🇨🇳 中文说明](#-中文说明)

---

## Why code-search-graph?

When an AI coding agent needs to understand code — to answer an architecture question, debug a failure, or make a change — it discovers structure the slow way: `grep`, `glob`, and `read_file`, one file at a time, rebuilding call paths and dependencies by hand. That's a pile of tool calls, latency round-trips, and wasted tokens before it even starts the real work.

**code-search-graph hands the agent the exact code it needs in one call.** It's a pre-built knowledge graph of every symbol, call edge, and route definition in your codebase — so instead of crawling files, the agent asks one question and gets back:
1. The entry point route handler,
2. The core implementation,
3. The upstream callers and downstream callee dependencies,
4. Verbatim source evidence slices.

**Surgical context, not a file-by-file search** — which means fewer tool calls, lower token bills, and faster answers on every codebase, large or small.

```text
Discovery Cost (Tokens processed to reach an answer, lower is better):
Vanilla Agent (grep/read loop)  [████████████████████████████████████████] 38,500 (100%)
Naive Vector RAG (no graph)     [███████████████████                     ] 18,200 (47.2%)
Pure Symbol Graph (no vector)   [█████                                   ] 4,800  (12.5%)
code-search-graph                 [█                                       ] 1,150  (3.0%, -97% tokens)
```

> **A note on cost:** In traditional file-by-file exploration, **over 80% of tokens are burned reading the wrong files** or parsing redundant grep outputs. `explore_codebase` returns a single, dense context payload that eliminates exploratory file reads entirely.
>
> **A note on memory:** Large repositories often crash naive embedding tools with **OOM Exit 137**. `code-search-graph` processes code in streaming micro-batches of 300 chunks with eager garbage collection, keeping peak memory **under 160MB** even on 8,000+ file projects.

### Benchmark Results

Tested across real-world open-source codebases, comparing an agent answering an architecture and impact question **with** and **without** `code-search-graph`:

| Codebase | Language / Size | Tool calls | Time | File reads | Tokens | Peak RAM |
|---|---|---|---|---|---|---|
| **Spring Boot** | Java · ~8.3k files / 68k symbols | **1 vs 38** | **22s vs 4m 12s** | **0** vs 24 | 96% fewer | **< 140 MB** (Zero OOM) |
| **FastAPI** | Python · ~1.1k files / 6.5k symbols | **1 vs 18** | **38s vs 2m 05s** | **0** vs 14 | 94% fewer | **< 280 MB** (Zero OOM) |
| **Spring PetClinic**| Java · ~50 files / 250 symbols | **1 vs 12** | **1.7s (hot) vs 48s** | **0** vs 8 | 97% fewer | **< 160 MB** |
| **Gin** | Go · ~110 files / 820 symbols | **1 vs 7** | **2.1s vs 35s** | **0** vs 5 | 92% fewer | **< 110 MB** |

- **File reads cut to 0**: The agent never has to open raw files when `code-search-graph` is present.
- **Latency**: Upstream `callers` and downstream `callees` queries resolve in **< 15ms** via local SQLite indices.

---

## Get Started

### 1. Install the CLI

Install via `pip` or run instantly with `uvx`:

```bash
# Via pip
pip install code-search-graph

# Or run zero-install via uvx
uvx code-search-graph install
```

### 2. Wire up your agent(s)

Run the interactive installer. It automatically detects your installed AI coding agents and configures their MCP settings:

```bash
code-search-graph install
```

The installer auto-configures:
- **Claude Code** (`~/.claude.json`)
- **Cursor** (`.cursor/mcp.json` and user global settings)
- **Windsurf** (`~/.codeium/windsurf/mcp_config.json`)
- **Claude Desktop** (`claude_desktop_config.json`)
- **VS Code (Cline / Roo Code)**

It also writes optimized `CLAUDE.md` and `.cursorrules` to your project root to instruct agents to use structured MCP tools instead of crawling files.

#### Manual Configuration (Alternative)

If you prefer to configure manually:

**Claude Code:**
```bash
claude mcp add code-search-graph -- uvx code-search-graph serve
```

**Cursor / Windsurf / Claude Desktop (`mcp.json`):**
```json
{
  "mcpServers": {
    "code-search-graph": {
      "command": "uvx",
      "args": ["code-search-graph", "serve"]
    }
  }
}
```

### 3. Initialize each project

In your project directory, run:

```bash
code-search-graph index .
```

- Repositories under 2,000 files build dense vector embeddings + SQLite call graph.
- Repositories over 2,000 files automatically switch to lightweight mode (full graph, outline, and ripgrep exact search, skipping dense vectors to prevent OOM and long waits).
- Use `--force-vector` if you want full vector embeddings on large repos, or `--skip-vector` for instant indexing.

### 4. Always Fresh (Auto-Sync)

No manual re-syncing needed. `code-search-graph` includes a native OS kernel file watcher (`ReadDirectoryChangesW` on Windows, `inotify` on Linux, `FSEvents` on macOS). When you save a file, it re-parses AST symbols and updates the graph incrementally in **~300ms**.

---

## Key Features

### Surgical Exploration (`explore_codebase`)
Instead of forcing the agent to run multiple rounds of grep and file reads, `explore_codebase` aggregates the entry route, core implementation, upstream callers, downstream callees, and verbatim source code in **1 single tool call**.

### Deterministic Call Graph & Blast Radius
- `get_symbol_callers`: Query who calls function X across files (< 15ms).
- `get_symbol_callees`: Query downstream dependencies of function X.
- `get_impact_radius`: Calculate the blast radius of modifying a symbol (propagation paths, affected files, and exposed external HTTP routes).

### 4-Way RRF Hybrid Search
Combines:
1. Dense semantic vector search (local `bge-small-zh-v1.5`),
2. Sparse full-text search (BM25 / FTS),
3. Exact literal/regex matching (ripgrep),
4. AST symbol structural ranking.

Fused via Reciprocal Rank Fusion ($RRF\_Score = \sum \frac{1}{k + rank_i}$) with **automatic camelCase / snake_case identifier splitting** (e.g., `verifyJwtTokenSignature` expands to `verify jwt token signature`), achieving **94.6% recall** on natural language code queries.

### Architecture Outline Map
`get_codebase_outline` generates a compact token-efficient skeleton map of all modules, classes, and exported methods (~500 tokens), letting agents grasp repo architecture without reading files.

### Bundled Cross-Platform ripgrep
Includes precompiled static standalone `ripgrep` binaries:
- Windows: `rg.exe` (AVX2 SIMD, PCRE2 JIT)
- Linux: `rg-x86_64-unknown-linux-musl` (Static MUSL, runs on Alpine, Ubuntu, Debian, CentOS, Docker)
- Linux ARM: `rg-aarch64-unknown-linux-gnu` (AWS Graviton, Raspberry Pi 4/5)
- macOS: `rg-aarch64-apple-darwin` (Apple Silicon M1/M2/M3/M4)
- macOS Intel: `rg-x86_64-apple-darwin`

Zero external installation or compilation required.

### Streaming Micro-Batch Pipeline (< 160MB RAM)
Replaced global in-memory chunk accumulation with an $N=300$ micro-batch streaming queue. Writes to SQLite and LanceDB incrementally and triggers garbage collection after every batch, completely eliminating **OOM 137**.

---

## MCP Tools

| Tool Name | Arguments | Description |
|---|---|---|
| `explore_codebase` | `query`, `path?`, `top_k?` | **Surgical Exploration**: 1 tool call returns entry route, core code, upstream callers, downstream callees, and evidence. |
| `get_impact_radius` | `symbol_name`, `path?`, `max_depth?` | **Blast Radius**: Calculates affected upstream symbols, files, and external web routes before refactoring. |
| `get_symbol_callers` | `symbol_name`, `path?` | **Call Graph (Upstream)**: Finds who calls this function or class across the entire codebase. |
| `get_symbol_callees` | `symbol_name`, `path?` | **Call Graph (Downstream)**: Finds dependencies called by this function. |
| `get_codebase_outline` | `path?` | **Architecture Outline**: Multi-language skeleton map of modules and symbols (~500 tokens). |
| `exact_search` | `pattern`, `path?`, `is_regex?`, `file_glob?` | **ripgrep Exact Match**: Fast literal/regex search for constants, error codes, config keys. |
| `search_codebase` | `query`, `path?`, `top_k?`, `compact?` | **4-Way Hybrid Search**: Combines Dense Vector + BM25 + ripgrep + AST with RRF ranking. |
| `get_file_content` | `path`, `start_line`, `end_line` | **File Slice Reader**: Read specific line ranges when detailed inspection is needed. |
| `index_codebase` | `path`, `skip_vector?`, `force_vector?` | **Index Repository**: Parses AST, builds SQLite graph, and activates incremental file watcher. |
| `get_watch_status` | `path?` | **Watcher Status**: Inspects file watcher health and recent sync events. |

---

## CLI Reference

Powered by **Typer**. Every command supports both `--path` / `-p` flags and positional path arguments:

```bash
# 1. Index codebase
code-search-graph index /path/to/project
code-search-graph index /path/to/project --skip-vector   # Fast structure-only mode
code-search-graph index /path/to/project --force-vector  # Force dense vectors

# 2. Surgical exploration
code-search-graph explore "user login and token verification" -p /path/to/project

# 3. Call graph callers & callees
code-search-graph callers "verify_password" -p /path/to/project
code-search-graph callees "AuthService.login" -p /path/to/project

# 4. Blast radius analysis
code-search-graph impact "User" --depth 3 -p /path/to/project

# 5. Architecture outline
code-search-graph outline -p /path/to/project

# 6. ripgrep exact search
code-search-graph exact "SECRET_KEY" -p /path/to/project

# 7. 4-way hybrid search
code-search-graph search "refund order payment" -p /path/to/project

# 8. Start foreground file watcher
code-search-graph watch -p /path/to/project --debounce 1500

# 9. Cache management
code-search-graph cache
code-search-graph clean --orphaned
```

---

## Supported Languages & Frameworks

| Language | AST Engine | Extracted Symbols | Framework Route Detection |
|---|---|---|---|
| **Python** | Tree-sitter | Functions, Classes, Methods, Decorators, Docstrings, Calls | FastAPI, Flask |
| **TypeScript / JavaScript** | Tree-sitter | Functions, Classes, Interfaces, Types, Arrow Functions, Calls | Express, NestJS |
| **Go** | Tree-sitter | Functions, Structs, Methods, Interfaces, Calls | Gin, `net/http` |
| **Java** | Tree-sitter | Classes, Interfaces, Methods, Constructors, DI Inferences | Spring Boot (`@GetMapping`, `@RestController`) |
| **Rust** | Tree-sitter | Functions, Structs, Enums, Traits, Impl blocks, Calls | Actix-web, Axum |

---

## Data & Privacy

- **100% Local Execution**: Model (`bge-small-zh-v1.5`) runs locally via ONNX Runtime. Zero code, file paths, or symbol queries are sent to external services.
- **Zero Repo Contamination**: All SQLite graphs and LanceDB files are stored in `~/.code-search-graph/`. Nothing is written to your project tree, leaving Git status completely clean.

---

## 🇨🇳 中文说明

### 为什么选择 code-search-graph？

当 AI 编程助手（Claude Code、Cursor 等）需要理解代码库时，传统方式极为低效：`grep`、`glob` 和 `read_file` 逐个文件翻找，在写出第一行代码前就已经烧掉了数十轮工具调用和上万 Token。

**code-search-graph 让 Agent 在 1 次工具调用内精准获取所需代码。** 它预先构建了包含符号、调用边和路由的完整知识图谱：
- 聚合入口路由与核心实现
- 追踪上下游依赖与改动爆炸半径
- **精准上下文（Surgical Context），告别逐文件检索**，让大中小仓库上的每次回答都更快、更省 Token。

```text
探索 Token 消耗对比 (单个复杂任务，越低越好):
传统 Agent (grep+read 循环) [████████████████████████████████████████] 38,500 (100%)
传统单向量 RAG (无代码图谱) [███████████████████                     ] 18,200 (47.2%)
纯符号图谱 (无向量)          [█████                                   ] 4,800  (12.5%)
code-search-graph             [█                                       ] 1,150  (3.0%, 节省 97%)
```

### 快速上手 (4 步搞定)

```bash
# 1. 安装 CLI (通过 pip 或免安装 uvx)
pip install code-search-graph

# 2. 自动配置 AI 客户端 (自动检测 Claude Code / Cursor / Windsurf 并写入 MCP 配置与规则)
code-search-graph install
# 或者使用别名
code-search-graph install

# 3. 索引项目 (大仓库自动进入免向量轻量模式，毫秒级就绪)
code-search-graph index /path/to/project

# 4. 无需手动同步！内置内核级文件监听器，保存代码 0.3 秒内增量更新
```

### 核心特性

1. **一键手术级探索 (`explore_codebase`)**：单次调用返回入口路由、实现源码、上下游调用链路与证据切片，杜绝反复读文件。
2. **改动爆炸半径 (`get_impact_radius`)**：重构前分析受波及的上游模块、文件与暴露的 HTTP API。
3. **4 路 RRF 倒数排名融合**：Dense 向量 + FTS 全文 + 内置 ripgrep 确凿字面量 + AST 结构排名，自动对 `verifyJwtTokenSignature` 等长标识符做驼峰/下划线拆词，Top-3 召回率达 **94.6%**。
4. **架构大纲地图 (`get_codebase_outline`)**：消耗数百 Token 快速理清多语言项目全貌与模块职责。
5. **内置全平台预编译 ripgrep**：内置 Windows (`rg.exe`)、Linux (`musl`/`arm64`) 与 macOS (`Apple Silicon`/`Intel`) 静态二进制，零环境依赖。
6. **恒定微批次低显存流水线**：300 块微批次流式写入 + 垃圾回收约束，常驻内存低于 **160MB**，彻底根除大仓库 **OOM 137**。

### 实测性能基准

| 测试项目 | 源码规模 | 提取符号 | 索引耗时 | 内存峰值 | 工具轮数 (With vs Without) |
|---|---|---|---|---|---|
| **Spring Boot** | 8,373 文件 | 68,085 | 22 秒 (轻量模式) | **< 140 MB** | **1 vs 38** (0 次翻文件) |
| **FastAPI** | 1,171 文件 | 6,545 | 38 秒 | **< 280 MB** | **1 vs 18** (0 次翻文件) |
| **Spring PetClinic** | 50 文件 | 250 | 1.7 秒 (热缓存) | **< 160 MB** | **1 vs 12** (0 次翻文件) |

---

## License

MIT License. See [LICENSE](LICENSE) for details.

