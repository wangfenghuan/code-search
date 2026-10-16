# code-search-mcp

> 🚀 **极简、零服务、超省 Token 的全栈代码库情报 MCP 服务**  
> 融合 **REA 组装成熟工具哲学**：集成 **ripgrep** 工业级精准检索 + **tree-sitter** 全语言统一解析 (Python / TS / JS / Go) + **LanceDB & bge-small-zh** 本地语义向量检索，专为 Claude Code、Cursor、Codex 等 AI 编程助手打造。

---

## 🌟 核心特性与“组装成熟工具”哲学

1. **🌳 组装工业级 `tree-sitter`（全语言调用拓扑与语法解析）**：
   - 彻底摆脱单一语言限制！接入 GitHub / Neovim 底层的统一语法树引擎 **Tree-sitter**。
   - 天然支持 **Python、TypeScript、JavaScript、Go** 等多语言混合大仓库。精准提取类（Class/Struct/Interface）、方法、参数签名、JSDoc/注释文档，并提取函数内部调用边（Call Graph）。
2. **🧭 吸收 CodeGraph 优秀设计：一键手术级探索 (`explore_codebase`)**：
   - **消灭 AI 的“探索税 (Exploration Tax)”**！传统方式 AI 需要反复执行 5~10 轮 `grep` 和 `read_file` 才能理清链路。
   - `explore_codebase` **仅需 1 次工具调用**，自动聚合命中入口、外部 HTTP 路由、上游触发方、下游依赖与关键源码证据，极速节省上下文与 Token。
3. **💥 改动爆炸半径 / 影响面分析 (`get_impact_radius`)**：
   - 在重构或修改核心公共函数前调用，通过有向图 BFS 扩散自动推导受波及的上游模块、代码文件与外部 API 路由，防止改出未预料的线上回归 Bug。
4. **📞 确定性代码图谱调用链追踪 (`get_symbol_callers` / `get_symbol_callees`)**：
   - 毫秒级回答“谁调用了函数 X”与“函数 X 内部调了哪些下级服务”，无需向量模型开销，100% 确定性。
5. **⚡ 组装内置工业级 `ripgrep`（毫秒级精准事实与证据）**：
   - 项目内置官方预编译 `rg.exe` 静态二进制（支持 AVX2 SIMD 硬件加速与 PCRE2 正则）。
   - 面对确切的类名、常量、错误码、URL 路由或环境变量，0 毫秒精确召回，提供 **100% 确凿证据（Exact Match）**，绝无模型幻觉。
6. **🏛️ 全局多语言架构大纲地图（极省 Token 理清大项目）**：
   - 提供 `get_codebase_outline` 工具。面对混合多语言大项目，AI 无需盲目全盘搜索或读入大文件，仅花费数百 Token 即可瞬间获取项目全貌与核心模块职责。
7. **🎯 混合多路召回 + 符号精准加权（中英文友好）**：
   - 自然语言提问中夹带英文类名、方法名或接口路径时，多路符号匹配与启发式加权联动，保证目标代码排在榜首。
8. **🌐 Web 框架与路由装饰器深度感知**：
   - 原生支持 FastAPI / Flask / Express / NestJS / Go Gin 等主流 Web 框架路由解析。自动提取 `@router.post("/login")`、`router.POST(...)` 等路由信息并注入语义向量与图谱拓扑。
9. **🔒 零外部服务与零污染存储**：
   - 嵌入式单文件运行，无需 Docker。数据库统一保存在 `~/.code-search-mcp/` 全局缓存，对被检索项目源码与 Git 状态零污染。
10. **📡 实时热监听与毫秒级增量更新 (File Watcher & Incremental Sync)**：
   - 彻底解决“代码修改后搜索滞后”痛点！基于操作系统原生内核事件通知（Windows `ReadDirectoryChangesW` / Linux `inotify` / macOS `FSEvents`）。
   - 1500ms 智能防抖聚合连续保存，单文件变更 0.3s 内完成 Tree-sitter AST 抽取与 LanceDB 向量增量覆盖，无需全盘重建。
   - 零输出污染，后台热监听日志严格流向 `sys.stderr`，绝不破坏 MCP JSON-RPC 协议通信。

---

## 🏗️ 组装分工架构

```text
┌────────────────────────────────────────────────────────┐
│  AI Agent（Claude Code / Cursor / Codex）               │
│  "帮我探索用户登录流程并分析密码哈希改动影响面"        │
└───────────┬────────────────────────────────┬───────────┘
            │ 1. 架构探索 / 影响面 / 图谱    │ 2. 语义搜索 / 确切字面量
┌───────────▼────────────────────────────────▼───────────┐
│  code-search-mcp (全栈代码情报与知识图谱中台)          │
│                                                        │
│  ┌────────────────────┐   ┌────────────────────────┐   │
│  │  ripgrep 工业引擎  │   │  tree-sitter 多语言解析│   │
│  │  内置 SIMD 硬件加速│   │  Python/TS/JS/Go 拓扑图│   │
│  └─────────┬──────────┘   └───────────┬────────────┘   │
│            │                          │                │
│  ┌─────────▼──────────────────────────▼────────────┐   │
│  │  CodeGraph 图谱推理引擎 (Caller/Callee/Impact)   │   │
│  │  LanceDB + fastembed 本地语义向量存储与重排     │   │
│  └─────────────────────┬───────────────────────────┘   │
│                        │                               │
│  ┌─────────────────────▼───────────────────────────┐   │
│  │  手术级上下文聚合器 (1 次 Tool Call 返回完整证据链) │   │
│  └─────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────┘
```

---

## ⚡ 一键极速上手（一条命令自动配置）

无需手动找路径、无需手动手写修改 JSON 配置文件，支持全自动跨客户端配置与最佳实践规范注入：

### 方式 1: `uvx` 免安装一键搞定（最推荐，开箱即用）
```bash
# 自动探测系统内所有 AI 客户端并完成 MCP 挂载与规则初始化
uvx code-search-mcp install
```

### 方式 2: 本地克隆一键安装
```bash
git clone https://github.com/wangfenghuan/code-search.git
cd code-search
python install.py
# 或使用 uv:
uv run code-search-mcp install
```

> **自动化完成全部流程**：
> - ✅ 自动识别并合并写入 **Claude Code** (`~/.claude.json`)
> - ✅ 自动识别并合并写入 **Cursor** (`.cursor/mcp.json` 及用户全局设置)
> - ✅ 自动识别并合并写入 **Claude Desktop** (`claude_desktop_config.json`，Windows/macOS/Linux)
> - ✅ 自动识别并合并写入 **Windsurf** 与 **VS Code (Cline / Roo Code)**
> - ✅ 自动为项目生成 **`CLAUDE.md`** 与 **`.cursorrules`** 最佳实践使用规范（吸收 CodeGraph 规范，防止 AI 泛滥读大文件导致上下文爆炸）

---

## 🛠️ 手动配置参考（可选）

如果你习惯手动维护客户端配置文件，也可自行添加以下配置块：

### 1. 配置到 Claude Code
```bash
claude mcp add code-search-mcp -- uvx code-search-mcp serve
```

### 2. 配置到 Claude Desktop / Cursor
在对应客户端的 `mcpServers` 下追加：
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

### 3. Docker 容器化运行（零环境依赖）
```bash
# 构建镜像
docker build -t code-search-mcp:latest .

# 启动容器
docker run -i --rm -v "$(pwd):/workspace" code-search-mcp:latest serve
```
> 📖 详细 Docker 命令请参阅 [Docker 完整部署指南 (DOCKER_GUIDE.md)](DOCKER_GUIDE.md)。

---

## 🧰 提供的 10 个核心 MCP 工具

| 工具名 | 入参 | 适用场景与优势 |
|---|---|---|
| `explore_codebase` | `query: str`, `path: str = ""`, `top_k: int = 2` | **【旗舰级一键探索（启发自 CodeGraph）】** 1 次调用直出全链路业务上下文。聚合入口路由、核心实现、上下游依赖与源码证据，彻底避免多次调用 read/grep 翻找文件。 |
| `get_impact_radius` | `symbol_name: str`, `path: str = ""`, `max_depth: int = 3` | **【改动爆炸半径分析】** 改动函数前调用，分析受波及的上游模块、代码文件与外部 Web/API 路由，防止改漏改错。 |
| `get_symbol_callers` | `symbol_name: str`, `path: str = ""` | **【Call Graph 上游调用追踪】** 查找代码库中谁调用了该函数或类，返回调用位置与代码预览。 |
| `get_symbol_callees` | `symbol_name: str`, `path: str = ""` | **【Call Graph 下游依赖追踪】** 查找指定函数直接调用的下级依赖，标明是否在仓库内定义。 |
| `get_codebase_outline` | `path: str = ""` | **【理清大项目首选】** 全局多语言骨架树与模块职责摘要（仅耗费 ~500 Token），避免盲目全盘搜索。 |
| `exact_search` | `pattern: str`, `path: str = ""`, `is_regex: bool = False`, `file_glob: str = ""` | **【内置 ripgrep 确凿证据】** 0 毫秒精准查找变量、常量、错误码、配置 Key 或正则，返回 100% 确凿事实。 |
| `search_codebase` | `query: str`, `path: str = ""`, `top_k: int = 5`, `compact: bool = True` | **【核心语义检索】** 混合自然语言与符号精准加权，跨 Python/TS/JS/Go 语言召回。默认 `compact=True` 极简预览，节省 75% Token。 |
| `get_watch_status` | `path: str = ""` | **【实时热监听状态与同步历史】** 实时查看当前代码库热更新监控器运行状态、防抖延迟配置与最近 10 次增量更新事件。 |
| `get_file_content` | `path: str`, `start_line: int`, `end_line: int` | **【精准展开】** 配合检索结果，按需深入阅读目标函数完整实现代码。 |
| `index_codebase` | `path: str` | 扫描多语言目标项目，Tree-sitter 提取 AST、调用边、Web 路由并构建本地向量库与知识图，自动激活后台实时热监听。 |

---

## 💻 本地 CLI 命令行调试

```bash
# 1. 索引多语言代码库 (自动识别 Python/TS/JS/Go 并提取调用拓扑)
uv run main.py index /path/to/project

# 2. 一键直达手术级业务全链路探索 (CodeGraph 风格)
uv run main.py explore "用户登录认证与密码加密校验流程" -p /path/to/project

# 3. 改动影响面 / 爆炸半径分析 (重构前必查)
uv run main.py impact "hash_password" -p /path/to/project

# 4. 上下游调用关系追踪
uv run main.py callers "verify_password" -p /path/to/project
uv run main.py callees "AuthService.login" -p /path/to/project

# 5. 打印多语言架构大纲地图 (超省 Token)
uv run main.py outline /path/to/project

# 6. 内置 ripgrep 精准字面量/正则检索 (带确凿证据)
uv run main.py exact "SECRET_KEY" --path /path/to/project
uv run main.py exact "PaymentGateway" --path /path/to/project

# 7. 跨语言语义与符号混合搜索（紧凑模式）
uv run main.py search "在线支付与订单退款" --path /path/to/project

# 8. 启动前台实时热更新文件监控器 (自动防抖增量更新)
uv run main.py watch /path/to/project --debounce 1500

# 9. 作为 MCP stdio 服务启动
uv run main.py serve
```

---

## 🧪 运行测试套件

内置全套多语言 Tree-sitter 切片、调用拓扑提取、爆炸半径分析、一键全链路探索、跨语言混合检索与 9 大 MCP 工具的端到端测试：

```bash
uv run python tests/test_search.py
```

---

## 📄 开源许可证

Apache License 2.0.
