#!/usr/bin/env bash
# ==============================================================================
# code-search-mcp Docker 启动脚本 (Linux / macOS)
# 用法:
#   ./scripts/docker-run.sh [/path/to/target/project]
# ==============================================================================

set -e

TARGET_DIR="${1:-$(pwd)}"
TARGET_DIR=$(cd "$TARGET_DIR" && pwd)

echo "[code-search-mcp] 正在启动 Docker MCP 服务..." >&2
echo "[code-search-mcp] 挂载目标代码库: $TARGET_DIR" >&2

# 检查本地是否有 code-search-mcp 镜像，没有则自动构建
if ! docker image inspect code-search-mcp:latest >/dev/null 2>&1; then
    echo "[code-search-mcp] 未检测到镜像，正在自动构建 code-search-mcp:latest..." >&2
    SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
    docker build -t code-search-mcp:latest "$SCRIPT_DIR"
fi

# 以 -i (交互式保持 STDIN) 模式运行，直接输出标准 stdio 协议供 AI 助手消费
exec docker run -i --rm \
  -v "$TARGET_DIR:/workspace:ro" \
  -v "code-search-cache:/root/.code-search-mcp" \
  code-search-mcp:latest \
  serve
