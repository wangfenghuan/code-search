# code-search-mcp

> 🚀 **极简、零服务、超省 Token 的 Python 代码语义检索 MCP 服务**  
> 专为 Claude Code、Cursor、Codex 等 AI 编程助手打造，支持大中型代码库快速理清拓扑、高准确度自然语言检索与极简 Token 消耗。

---

## 🌟 进阶核心特性

1. **🏛️ 全局架构大纲地图（极省 Token 理清大项目）**：
   - 提供 `get_codebase_outline` 工具。在大项目接手时，AI 无需盲目全盘搜索或读入大文件，仅花费数百 Token 即可瞬间获取项目全貌、核心模块职责、包含类与函数列表。
2. **🎯 混合多路召回 + 符号精准加权（中英文友好）**：
   - 自然语言提问中夹带英文类名、方法名或接口路径（如“看看 PasswordHasher 怎么初始化的”、“POST /login 接口”）时，触发多路符号匹配与启发式加权，准确率达到 100%。
3. **🌐 Web 框架与路由装饰器深度感知**：
   - 原生支持 FastAPI / Flask / Django / Tornado 框架路由解析。自动提取 `@router.post("/login")` 等路由信息并注入语义向量，问“登录接口在哪”直接命中控制器。
4. **📉 渐进式呈现与 Compact 极简模式（节省 75%+ Token）**：
   - `search_codebase` 默认以 `compact=True` 运行，仅返回符号位置、文档说明与前 10 行预览，避免无脑将大段代码刷入上下文。配合 `get_file_content` 按需精准展开。
5. **⚡ 零外部服务与零污染存储**：
   - 基于 **LanceDB** 嵌入式数据库与 **fastembed / ONNX Runtime**，CPU 毫秒级推理，模型仅 ~90MB，无需 Docker，数据库统一保存在 `~/.code-search-mcp/` 全局缓存，对被检索项目零污染。

---

## 🏗️ 架构设计

```text
┌────────────────────────────────────────────────────────┐
│  Claude Code / Cursor / Codex                           │
│  （用户："项目有哪些模块？登录接口在哪里？"）          │
└───────────┬────────────────────────────────┬───────────┘
            │ 1. 先查架构大纲 (超低 Token)   │ 2. 混合精准检索
┌───────────▼────────────────────────────────▼───────────┐
│  code-search-mcp（本地 Python 进程）                   │
│                                                        │
│  ┌────────────────────┐   ┌────────────────────────┐   │
│  │  Outline Generator │   │  Hybrid Searcher       │   │
│  │  架构大纲树提取    │   │  向量 + 符号 + 路由加权│   │
│  └─────────┬──────────┘   └───────────┬────────────┘   │
│            │                          │                │
│  ┌─────────▼──────────────────────────▼────────────┐   │
│  │  LanceDB 嵌入式向量库 (~/.code-search-mcp/dbs)  │   │
│  └─────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────┘
```

---

## 🛠️ 快速安装

本项目使用现代极速包管理工具 [uv](https://github.com/astral-sh/uv)：

```bash
# 克隆代码
git clone https://github.com/your-username/code-search-mcp.git
cd code-search-mcp

# 安装依赖
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

## 🧰 提供的 4 个核心 MCP 工具

| 工具名 | 入参 | 说明 |
|---|---|---|
| `get_codebase_outline` | `path: str = ""` | **【理清项目首选】** 返回全局架构骨架树与模块职责摘要（仅耗费 ~500 Token），避免盲目全盘搜索。 |
| `index_codebase` | `path: str` | 扫描并索引指定代码库，提取 AST、解析 Web 路由并构建本地向量库。 |
| `search_codebase` | `query: str`, `path: str = ""`, `top_k: int = 5`, `compact: bool = True` | **【核心检索】** 混合语义与符号精准加权检索。默认 `compact=True` 极简预览，大幅节省上下文。 |
| `get_file_content` | `path: str`, `start_line: int`, `end_line: int` | 配合检索结果，精准展开目标文件指定行号范围的代码。 |

---

## 💻 本地 CLI 命令行调试

```bash
# 1. 索引代码库
uv run main.py index /path/to/project

# 2. 打印架构大纲地图
uv run main.py outline /path/to/project

# 3. 语义与符号混合搜索（紧凑模式）
uv run main.py search "用户登录验证接口" --path /path/to/project

# 4. 打印完整代码（非紧凑）
uv run main.py search "PasswordHasher" --path /path/to/project --full

# 5. 作为 MCP stdio 服务启动
uv run main.py serve
```

---

## 🧪 运行测试套件

```bash
uv run python tests/test_search.py
```

---

## 📄 开源许可证

MIT License.
