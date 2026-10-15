# code-search-mcp

> 🚀 **极简、零服务、超省 Token 的全栈代码库情报 MCP 服务**  
> 融合 **REA 组装成熟工具哲学**：集成 **ripgrep** 工业级精准检索 + **tree-sitter** 全语言统一解析 (Python / TS / JS / Go) + **LanceDB & bge-small-zh** 本地语义向量检索，专为 Claude Code、Cursor、Codex 等 AI 编程助手打造。

---

## 🌟 核心特性与“组装成熟工具”哲学

1. **🌳 组装工业级 `tree-sitter`（全语言语法解析）**：
   - 彻底摆脱单一语言限制！接入 GitHub / Neovim 底层的统一语法树引擎 **Tree-sitter**。
   - 天然支持 **Python、TypeScript、JavaScript、Go** 等多语言混合大仓库。精准提取类（Class/Struct/Interface）、方法、参数签名与 JSDoc/注释文档。
2. **⚡ 组装工业级 `ripgrep`（毫秒级精准事实与证据）**：
   - 借鉴 REA 模式，接入经过工业界十年打磨的 Rust SIMD `ripgrep`（双轨制：优先系统/IDE内置 `rg`，无环境自动降级为内置引擎）。
   - 面对确切的类名、常量、错误码、URL 路由或环境变量，0 毫秒精确召回，提供 **100% 确凿证据（Exact Match）**，绝无模型幻觉。
3. **🏛️ 全局多语言架构大纲地图（极省 Token 理清大项目）**：
   - 提供 `get_codebase_outline` 工具。面对混合多语言大项目，AI 无需盲目全盘搜索或读入大文件，仅花费数百 Token 即可瞬间获取项目全貌、核心模块职责与包含的类/方法。
4. **🎯 混合多路召回 + 符号精准加权（中英文友好）**：
   - 自然语言提问中夹带英文类名、方法名或接口路径时，多路符号匹配与启发式加权联动，保证目标代码排在榜首。
5. **🌐 Web 框架与路由装饰器深度感知**：
   - 原生支持 FastAPI / Flask / Express / NestJS / Go Gin 等主流 Web 框架路由解析。自动提取 `@router.post("/login")`、`router.POST(...)` 等路由信息并注入语义向量，问“登录接口在哪”直接命中控制器。
6. **📉 渐进式呈现与 Compact 极简模式（节省 75%+ Token）**：
   - `search_codebase` 默认以 `compact=True` 运行，仅返回符号位置、文档说明与前 10 行预览。配合 `get_file_content` 按需精准展开，杜绝上下文爆炸。
7. **🔒 零外部服务与零污染存储**：
   - 嵌入式单文件运行，无需 Docker。数据库统一保存在 `~/.code-search-mcp/` 全局缓存，对被检索项目源码与 Git 状态零污染。

---

## 🏗️ 组装分工架构

```text
┌────────────────────────────────────────────────────────┐
│  AI Agent（Claude Code / Cursor / Codex）               │
│  "帮我看看前端支付组件和后端 Go 订单处理逻辑"          │
└───────────┬────────────────────────────────┬───────────┘
            │ 1. 查大纲 / 查确切字面量       │ 2. 查模糊业务意图
┌───────────▼────────────────────────────────▼───────────┐
│  code-search-mcp (全栈代码情报调度中台)                │
│                                                        │
│  ┌────────────────────┐   ┌────────────────────────┐   │
│  │  ripgrep 工业引擎  │   │  tree-sitter 多语言解析│   │
│  │  精准字面量/错误码 │   │  Python/TS/JS/Go 语法树│   │
│  └─────────┬──────────┘   └───────────┬────────────┘   │
│            │                          │                │
│  ┌─────────▼──────────────────────────▼────────────┐   │
│  │  LanceDB + fastembed 本地语义向量存储与混合打分 │   │
│  └─────────────────────┬───────────────────────────┘   │
│                        │                               │
│  ┌─────────────────────▼───────────────────────────┐   │
│  │  证据提炼与 Token 压缩器（输出 100% 确凿证据卡片）  │   │
│  └─────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────┘
```

---

## 🛠️ 快速安装

本项目使用现代极速包管理工具 [uv](https://github.com/astral-sh/uv)：

```bash
# 克隆代码
git clone https://github.com/wangfenghuan/code-search.git
cd code-search

# 安装依赖（一键同步 ONNX Runtime, LanceDB 与 Tree-sitter 语法包）
uv sync
```

---

## 🔌 配置到 AI 编程助手

### 1. 配置到 Claude Code

运行以下命令一键添加到 Claude Code：

```bash
claude mcp add code-search-mcp -- uv --directory /path/to/code-search-mcp run main.py
```

或手动配置 `~/.claude.json`：

```json
{
  "mcpServers": {
    "code-search": {
      "command": "uv",
      "args": [
        "--directory",
        "/path/to/code-search-mcp",
        "run",
        "main.py"
      ]
    }
  }
}
```

### 2. 配置到 Cursor

进入 Cursor 的 **Settings -> Features -> MCP Servers -> Add New MCP Server**：

- **Name**: `code-search`
- **Type**: `command`
- **Command**: `uv --directory /path/to/code-search-mcp run main.py`

---

## 🧰 提供的 5 个核心 MCP 工具

| 工具名 | 入参 | 适用场景与优势 |
|---|---|---|
| `get_codebase_outline` | `path: str = ""` | **【理清大项目首选】** 全局多语言骨架树与模块职责摘要（仅耗费 ~500 Token），避免盲目全盘搜索。 |
| `exact_search` | `pattern: str`, `path: str = ""`, `is_regex: bool = False`, `file_glob: str = ""` | **【组装 ripgrep 确凿证据】** 0 毫秒精准查找变量、常量、错误码、配置 Key 或正则，返回 100% 确凿事实。 |
| `search_codebase` | `query: str`, `path: str = ""`, `top_k: int = 5`, `compact: bool = True` | **【核心语义检索】** 混合自然语言与符号精准加权，跨 Python/TS/JS/Go 语言召回。默认 `compact=True` 极简预览，节省 75% Token。 |
| `get_file_content` | `path: str`, `start_line: int`, `end_line: int` | **【精准展开】** 配合检索结果，按需深入阅读目标函数完整实现代码。 |
| `index_codebase` | `path: str` | 扫描多语言目标项目，Tree-sitter 提取 AST、解析 Web 路由并构建本地向量库。 |

---

## 💻 本地 CLI 命令行调试

```bash
# 1. 索引多语言代码库 (自动识别 Python/TS/JS/Go)
uv run main.py index /path/to/project

# 2. 打印多语言架构大纲地图 (超省 Token)
uv run main.py outline /path/to/project

# 3. 组装 ripgrep 精准字面量/正则检索 (带确凿证据)
uv run main.py exact "SECRET_KEY" --path /path/to/project
uv run main.py exact "PaymentGateway" --path /path/to/project

# 4. 跨语言语义与符号混合搜索（紧凑模式）
uv run main.py search "在线支付与订单退款" --path /path/to/project

# 5. 作为 MCP stdio 服务启动
uv run main.py serve
```

---

## 🧪 运行测试套件

内置全套多语言 Tree-sitter 切片、跨语言混合检索、ripgrep 精确匹配与 5 大 MCP 工具的端到端测试：

```bash
uv run python tests/test_search.py
```

---

## 📄 开源许可证

Apache License 2.0.
