# 🐳 Docker Deployment & AI Client Integration Guide

Run `code-search-graph` inside a lightweight Docker container with zero setup. No need to install Python, Tree-sitter, or Rust toolchains on the host. The container bundles the ripgrep binary and pre-warmed BAAI vector embedding weights for 100% offline support.

---

## 🚀 1. Build Docker Image

From the repository root:

```bash
docker build -t code-search-graph:latest .
```

> 💡 **Build-time Model Pre-warming**: During `docker build`, `BAAI/bge-small-zh-v1.5` (~90MB) is downloaded and cached in the image layer. Container startup requires zero download time, enabling sub-second cold starts.

---

## 🔌 2. Configure AI Coding Clients

### A. Claude Code (via Docker)

Run directly in your project root:

```bash
claude mcp add code-search-graph -- docker run -i --rm -v "$(pwd):/workspace:ro" -v "code-search-cache:/root/.code-search-graph" code-search-graph:latest serve
```

Or configure manually in `~/.claude.json`:

```json
{
  "mcpServers": {
    "code-search-graph": {
      "command": "docker",
      "args": [
        "run",
        "-i",
        "--rm",
        "-v", "${workspaceFolder}:/workspace:ro",
        "-v", "code-search-cache:/root/.code-search-graph",
        "code-search-graph:latest",
        "serve"
      ]
    }
  }
}
```

---

### B. Cursor (via Docker)

In Cursor: **Settings -> Features -> MCP Servers -> Add New MCP Server**:

- **Name**: `code-search-graph`
- **Type**: `command`
- **Command**:
  ```bash
  docker run -i --rm -v /absolute/path/to/your/repo:/workspace:ro -v code-search-cache:/root/.code-search-graph code-search-graph:latest serve
  ```

> ⚠️ **Key Arguments**:
> - `-i` (Interactive): Keeps standard input (STDIN) open, mandatory for MCP JSON-RPC stdio protocol.
> - `--rm`: Automatically removes the container instance on exit.
> - `-v /path:/workspace:ro`: Mounts the repository read-only. The server defaults to `/workspace` if no repository path is supplied.
> - `-v code-search-cache:/root/.code-search-graph`: Persists the LanceDB and SQLite index databases across runs.

---

## 💻 3. Docker CLI Usage

Run searches and graph analysis directly using Docker without an MCP client:

```bash
# 1. Index codebase
docker run --rm -v "$(pwd):/workspace" -v "code-search-cache:/root/.code-search-graph" code-search-graph:latest index /workspace

# 2. View architecture outline
docker run --rm -v "$(pwd):/workspace" -v "code-search-cache:/root/.code-search-graph" code-search-graph:latest outline

# 3. Explore full feature workflow
docker run --rm -v "$(pwd):/workspace" -v "code-search-cache:/root/.code-search-graph" code-search-graph:latest explore "user authentication and login verification flow"

# 4. Impact radius analysis
docker run --rm -v "$(pwd):/workspace" -v "code-search-cache:/root/.code-search-graph" code-search-graph:latest impact "hash_password"

# 5. Upstream caller trace
docker run --rm -v "$(pwd):/workspace" -v "code-search-cache:/root/.code-search-graph" code-search-graph:latest callers "verify_password"
```

---

## 🛠️ 4. Quick Scripts

The repository includes cross-platform launcher scripts:

- **Linux / macOS**:
  ```bash
  ./scripts/docker-run.sh /path/to/your/project
  ```
- **Windows (PowerShell)**:
  ```powershell
  .\scripts\docker-run.ps1 -TargetDir D:\your\project
  ```
