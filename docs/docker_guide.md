# 🐳 Docker 部署与 AI 客户端接入指南

通过 Docker 容器化运行 `code-search-mcp`，无需在宿主机安装任何 Python、Tree-sitter 或 Rust 工具链。镜像内部已**预置官方 ripgrep 引擎与 BAAI 中文向量模型权重**，启动即用，100% 离线支持。

---

## 🚀 1. 构建 Docker 镜像

在项目根目录下执行：

```bash
docker build -t code-search-mcp:latest .
```

> 💡 **构建预热设计**：在镜像构建过程中，会自动预下载 `BAAI/bge-small-zh-v1.5`（~90MB）并缓存至镜像中。容器启动时**无需等待模型下载，0.5 秒极速冷启动**。

---

## 🔌 2. 配置到主流 AI 编程助手

### A. 配置到 Claude Code (通过 Docker)

在你的代码项目根目录下执行：

```bash
claude mcp add code-search -- docker run -i --rm -v "$(pwd):/workspace:ro" -v "code-search-cache:/root/.code-search-mcp" code-search-mcp:latest serve
```

或在 `~/.claude.json` 中配置：

```json
{
  "mcpServers": {
    "code-search": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-v", "${workspaceFolder}:/workspace:ro",
        "-v", "code-search-cache:/root/.code-search-mcp",
        "code-search-mcp:latest",
        "serve"
      ]
    }
  }
}
```

---

### B. 配置到 Cursor (通过 Docker)

打开 Cursor：**Settings -> Features -> MCP Servers -> Add New MCP Server**：

- **Name**: `code-search`
- **Type**: `command`
- **Command**:
  ```bash
  docker run -i --rm -v /绝对路径/你的代码库:/workspace:ro -v code-search-cache:/root/.code-search-mcp code-search-mcp:latest serve
  ```

> ⚠️ **关键参数说明**：
> - `-i`（Interactive）：保持标准输入（STDIN）开启，这是 MCP JSON-RPC 协议通信的必备参数。
> - `--rm`：容器退出时自动清理容器实例。
> - `-v /path:/workspace:ro`：将待分析的代码库以只读形式挂载至容器。容器会自动优先推断 `/workspace` 作为分析目标。
> - `-v code-search-cache:/root/.code-search-mcp`：持久化索引数据库，避免每次重启重复建库。

---

## 💻 3. 本地命令行通过 Docker 使用

无需启动 MCP 客户端，直接使用 Docker 容器执行代码搜索与图谱分析：

```bash
# 1. 对代码库建立索引
docker run --rm -v "$(pwd):/workspace" -v "code-search-cache:/root/.code-search-mcp" code-search-mcp:latest index /workspace

# 2. 查看架构大纲地图 (超省 Token)
docker run --rm -v "$(pwd):/workspace" -v "code-search-cache:/root/.code-search-mcp" code-search-mcp:latest outline

# 3. 一键手术级全链路业务探索 (CodeGraph 模式)
docker run --rm -v "$(pwd):/workspace" -v "code-search-cache:/root/.code-search-mcp" code-search-mcp:latest explore "用户登录认证与密码校验流程"

# 4. 改动影响面 / 爆炸半径分析
docker run --rm -v "$(pwd):/workspace" -v "code-search-cache:/root/.code-search-mcp" code-search-mcp:latest impact "hash_password"

# 5. 上游调用追踪
docker run --rm -v "$(pwd):/workspace" -v "code-search-cache:/root/.code-search-mcp" code-search-mcp:latest callers "verify_password"
```

---

## 🛠️ 4. 使用一键脚本

仓库内置了跨平台快捷启动脚本：

- **Linux / macOS**:
  ```bash
  ./scripts/docker-run.sh /path/to/your/project
  ```
- **Windows (PowerShell)**:
  ```powershell
  .\scripts\docker-run.ps1 -TargetDir D:\your\project
  ```
