# ==============================================================================
# code-search-graph: Full-stack Code Intelligence & FastMCP Engine
# 100% local execution, pre-bundled embedding models & ripgrep, zero network dependency
# ==============================================================================

FROM python:3.10-slim AS base

# 1. Install base dependencies and system ripgrep
RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. Get uv package manager
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 3. Working directory and environment variables
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    CODE_SEARCH_CACHE_DIR=/root/.code-search-graph

# 4. Dependency caching layer
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 5. Copy project source code
COPY . .

# 6. Pre-warm embedding model weights during build to eliminate runtime download delay
RUN uv run python -c "from fastembed import TextEmbedding; print('[Docker Build] Pre-warming embedding model...'); TextEmbedding('BAAI/bge-small-en-v1.5'); print('[Docker Build] Pre-warm complete!')"

# 7. Volume mount points:
# /workspace: Mount host repository (read-only)
# /root/.code-search-graph: LanceDB & cache persistence
RUN mkdir -p /workspace /root/.code-search-graph
VOLUME ["/workspace", "/root/.code-search-graph"]

# 8. FastMCP stdio server entrypoint
ENTRYPOINT ["uv", "run", "main.py"]
CMD ["serve"]
