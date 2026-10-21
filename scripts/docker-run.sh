#!/usr/bin/env bash
# ==============================================================================
# code-search-graph Docker Launcher (Linux / macOS)
# Usage:
#   ./scripts/docker-run.sh [/path/to/target/project]
# ==============================================================================

set -e

TARGET_DIR="${1:-$(pwd)}"
TARGET_DIR=$(cd "$TARGET_DIR" && pwd)

echo "[code-search-graph] Starting Docker MCP service..." >&2
echo "[code-search-graph] Mounting repository: $TARGET_DIR" >&2

# Check if Docker image exists locally
if ! docker image inspect code-search-graph:latest >/dev/null 2>&1; then
    echo "[code-search-graph] Image not found locally, building code-search-graph:latest..." >&2
    SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
    docker build -t code-search-graph:latest "$SCRIPT_DIR"
fi

# Run container with interactive stdio attached for MCP protocol
exec docker run -i --rm \
  -v "$TARGET_DIR:/workspace:ro" \
  -v "code-search-cache:/root/.code-search-graph" \
  code-search-graph:latest \
  serve
