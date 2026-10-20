# code-search-mcp

Fast, local code search and symbol graph for AI coding agents.

Turn any repository into an indexed knowledge graph with Tree-sitter, SQLite, LanceDB, and ripgrep. Runs entirely on your machine via the Model Context Protocol (MCP).

---

## 为什么写这个工具 (The Problem)

当 Claude Code、Cursor 或其他 AI 编程助手面对一个陌生的大型代码库时，它们通常会陷入这种死循环：

1. `grep` 搜一个函数名，命中了 40 个结果；
2. 随便挑两个文件读，发现不是定义，只是调用点；
3. 接着 `grep`、接着 `read_file`，几轮下来消耗了几万 Token，上下文窗口被无关代码塞满；
4. 问它“改动这个方法会影响哪些接口”，它只能凭记忆猜测，或者再次全盘扫描。

**`code-search-mcp` 的目的很简单：把代码库的结构预先索引好，让 Agent 在 1 次工具调用内拿到准确的上下文，不再盲目翻找文件。**

---

## 它是怎么工作的 (How It Works)

- **Tree-sitter 符号提取**：解析 Python、TypeScript、JavaScript、Go、Java、Rust 源码，提取函数、类、接口、结构体和路由注解。
- **调用图与影响面 (Call Graph & Impact)**：基于 SQLite 构建符号关系拓扑。回答“谁调用了 X”（`callers`）和“修改 X 会波及哪些上游与 API 路由”（`impact`），毫秒级响应，无需依赖向量模型。
- **4 路 RRF 混合检索**：结合 Dense 向量（bge-small-zh）、LanceDB 词法检索（FTS）、内置 ripgrep 精确匹配和 AST 符号结构匹配，自动做驼峰/下划线分词（例如 `verifyJwtToken` 拆解为自然语言），大幅提高代码搜索召回率。
- **架构大纲 (Outline)**：生成全局多语言模块骨架地图，仅消耗数百 Token 即可让 Agent 快速理清项目全貌。
- **实时热更新 (Watcher)**：基于操作系统的内核文件事件（`ReadDirectoryChangesW` / `inotify` / `FSEvents`），保存代码时 0.3 秒内增量更新，无需手动重新索引。
- **低内存流式设计**：采用 300 块微批次流式写入与垃圾回收，常驻内存保持在 150MB 以下，避免大仓库向量化时 OOM。对于超过 2,000 文件的超大仓库，支持自动降级为免向量结构图模式。

---

## 快速上手 (Quickstart)

### 1. 一键安装并配置客户端（推荐）

通过 `uvx` 直接运行安装向导，它会自动检测你机器上的 AI 客户端并写入 MCP 配置：

```bash
uvx code-search-mcp install
```

或者使用 `pip`：

```bash
pip install code-search-mcp
code-search-mcp install
```

向导会自动识别并配置：
- **Claude Code** (`~/.claude.json`)
- **Cursor** (`.cursor/mcp.json` 与全局配置)
- **Claude Desktop** (`claude_desktop_config.json`)
- **Windsurf** / **VS Code (Cline / Roo Code)**

同时会在项目根目录生成 `CLAUDE.md` 与 `.cursorrules`，指导 Agent 优先使用结构化工具检索，避免全盘读文件。

---

### 2. 手动配置 MCP

如果你习惯手动维护配置，直接在客户端的 `mcpServers` 中添加：

**Claude Code:**
```bash
claude mcp add code-search-mcp -- uvx code-search-mcp serve
```

**Cursor / Claude Desktop / Windsurf (`mcp.json`):**
```json
{
  "mcpServers": {
    "code-search-mcp": {
      "command": "uvx",
      "args": ["code-search-mcp", "serve"]
    }
  }
}
```

---

## MCP 工具列表 (Tools)

服务暴露了以下 MCP 工具供 Agent 调用：

| 工具名 | 参数 | 功能说明 |
|---|---|---|
| `explore_codebase` | `query`, `path?`, `top_k?` | **全链路业务探索**：单次调用聚合入口路由、核心实现、上下游依赖与关键源码，代替反复读文件。 |
| `get_impact_radius` | `symbol_name`, `path?`, `max_depth?` | **改动爆炸半径**：分析修改指定符号后受波及的上游函数、文件及外部 API 路由，防止改出线上 Bug。 |
| `get_symbol_callers` | `symbol_name`, `path?` | **查找调用方**：追踪谁调用了该函数/类，返回调用位置与代码片段。 |
| `get_symbol_callees` | `symbol_name`, `path?` | **查找下游依赖**：列出指定函数内部调用的所有下级方法/服务。 |
| `get_codebase_outline` | `path?` | **架构大纲**：提取多语言骨架树与模块职责（~500 Token），适合刚进入项目时理清结构。 |
| `exact_search` | `pattern`, `path?`, `is_regex?`, `file_glob?` | **ripgrep 精确搜索**：内置静态编译 ripgrep 二进制，用于查找确切常量、配置项、错误码或正则。 |
| `search_codebase` | `query`, `path?`, `top_k?`, `compact?` | **4 路混合语义搜索**：融合向量相似度、FTS、ripgrep 与 AST 排名，查找业务逻辑实现。 |
| `get_file_content` | `path`, `start_line`, `end_line` | **代码片段读取**：按需查看目标函数的完整实现代码。 |
| `index_codebase` | `path`, `skip_vector?`, `force_vector?` | **索引项目**：解析 AST 并建立 SQLite 图谱与向量库，自动激活后台增量热监听。 |
| `get_watch_status` | `path?` | **监听状态**：查看后台文件热监听器的运行状态与最近更新记录。 |

---

## 命令行工具 (CLI)

除了通过 MCP 给 Agent 使用，`code-search-mcp` 还提供了完整的命令行交互工具（基于 Typer 构建）：

```bash
# 索引代码库（超过 2000 文件自动跳过向量仅建结构图；可用 --force-vector 强制生成向量）
code-search-mcp index /path/to/project

# 架构大纲预览
code-search-mcp outline -p /path/to/project

# 4 路混合搜索
code-search-mcp search "用户登录认证" -p /path/to/project

# ripgrep 精确字面量/正则搜索
code-search-mcp exact "SECRET_KEY" -p /path/to/project

# 追踪函数调用方与下游依赖
code-search-mcp callers "verify_password" -p /path/to/project
code-search-mcp callees "AuthService.login" -p /path/to/project

# 改动影响面分析（改动前评估）
code-search-mcp impact "User" --depth 3 -p /path/to/project

# 一键业务链路探索
code-search-mcp explore "订单退款流程" -p /path/to/project

# 启动前台文件热监听
code-search-mcp watch -p /path/to/project

# 查看与清理索引缓存
code-search-mcp cache
code-search-mcp clean --orphaned
```

---

## 支持语言与框架

| 语言 | 语法引擎 | 提取能力 | 框架路由感知 |
|---|---|---|---|
| **Python** | Tree-sitter | 函数、类、方法、装饰器、Docstring、调用点 | FastAPI, Flask |
| **TypeScript / JavaScript** | Tree-sitter | 函数、类、Interface、Type、Arrow Function、调用点 | Express, NestJS |
| **Go** | Tree-sitter | 函数、结构体、方法、Interface、调用点 | Gin, 标准库 `http` |
| **Java** | Tree-sitter | 类、方法、构造函数、接口、包名、构造注入推断 | Spring Boot (`@GetMapping`, `@RestController` 等) |
| **Rust** | Tree-sitter | 函数、Struct、Enum、Trait、Impl 块、调用点 | Actix-web, Axum |

---

## 实测指标 (Benchmarks)

在标准开发者机器上实测：

- **FastAPI 核心代码库 (1,171 文件 / 6,545 符号)**：
  - 索引耗时：38 秒
  - 内存峰值：< 450 MB（无 OOM）
  - 调用方查询延迟：< 15 ms
- **Spring PetClinic (50 文件 / 250 符号)**：
  - 首次冷启动索引：40 秒（含模型初始化与向量构建）
  - 增量热更新缓存：1.7 秒
  - `OwnerRepository` 调用方：准确定位 11 个跨文件调用点与 HTTP 路由

---

## 数据与隐私

- **100% 本地运行**：模型（`bge-small-zh-v1.5`）通过 ONNX Runtime 在本地运行，代码、向量与图数据均保存在本地机器上。
- **缓存目录隔离**：所有索引数据库统一保存在 `~/.code-search-mcp/` 全局缓存目录下，不会向你的项目目录写入临时文件，对 Git 状态零污染。

---

## 开源协议

MIT License.
