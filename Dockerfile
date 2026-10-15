# ==============================================================================
# code-search-mcp: 全栈代码知识图谱与语义搜索 MCP 服务
# 100% 纯本地运行，预置 Embedding 模型权重与 ripgrep，零外部网络依赖
# ==============================================================================

FROM python:3.10-slim AS base

# 1. 安装基础依赖与系统级 ripgrep (Linux 平台原生运行)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ripgrep \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. 从官方镜像获取极速包管理器 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# 3. 设置工作目录与环境变量
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    CODE_SEARCH_CACHE_DIR=/root/.code-search-mcp

# 4. 利用 Docker 缓存层，优先同步依赖
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 5. 复制项目所有源码
COPY . .

# 6. 【核心加速设计】在构建阶段预下载 FastEmbed 中文模型权重 (BAAI/bge-small-zh-v1.5)
# 彻底消除容器运行时联网下载延迟，实现毫秒级即时启动，支持离线/内网环境
RUN uv run python -c "from fastembed import TextEmbedding; print('[Docker Build] 预热下载本地向量模型...'); TextEmbedding('BAAI/bge-small-zh-v1.5'); print('[Docker Build] 模型预热就绪！')"

# 7. 创建数据卷挂载点：
# /workspace: 挂载待分析的宿主机代码仓库 (只读即可)
# /root/.code-search-mcp: 挂载 LanceDB 向量库与架构索引持久化目录
RUN mkdir -p /workspace /root/.code-search-mcp
VOLUME ["/workspace", "/root/.code-search-mcp"]

# 8. 默认以 MCP stdio 协议运行，对接 Claude Code / Cursor
ENTRYPOINT ["uv", "run", "main.py"]
CMD ["serve"]
