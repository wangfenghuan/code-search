import hashlib
import os
from pathlib import Path

# 默认全局配置与路径管理
DEFAULT_MODEL_NAME = os.getenv("CODE_SEARCH_MODEL", "BAAI/bge-small-zh-v1.5")
MODEL_DIMENSIONS = {
    "BAAI/bge-small-zh-v1.5": 512,
    "BAAI/bge-small-en-v1.5": 384,
    "sentence-transformers/all-MiniLM-L6-v2": 384,
    "nomic-ai/nomic-embed-code": 768,
    "nomic-ai/nomic-embed-text-v1.5": 768,
    "nomic-ai/nomic-embed-text-v1.5-Q": 768,
    "jinaai/jina-embeddings-v2-base-code": 768,
    "jinaai/jina-embeddings-v2-base-zh": 768,
    "ibm-granite/granite-embedding-small-english-r2": 384,
}


def get_vector_dimension(model_name: str = DEFAULT_MODEL_NAME) -> int:
    """获取或动态解析指定模型的向量维度"""
    if model_name in MODEL_DIMENSIONS:
        return MODEL_DIMENSIONS[model_name]
    try:
        from fastembed import TextEmbedding
        for m in TextEmbedding.list_supported_models():
            if m.get("model") == model_name:
                dim = int(m.get("dim", 512))
                MODEL_DIMENSIONS[model_name] = dim
                return dim
    except Exception:
        pass
    return 512


VECTOR_DIMENSION = get_vector_dimension(DEFAULT_MODEL_NAME)
DEFAULT_TOP_K = 5
INDEX_SCHEMA_VERSION = "v2"

# 忽略的目录和文件模式
DEFAULT_IGNORE_DIRS = {
    ".git",
    ".svn",
    ".hg",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "dist",
    "build",
    "target",
    ".gradle",
    ".settings",
    "bin",
    "eggs",
    ".eggs",
    ".idea",
    ".vscode",
    ".tox",
}

DEFAULT_IGNORE_FILES = {
    ".DS_Store",
    "Thumbs.db",
}


def get_cache_root() -> Path:
    """获取用户全局缓存根目录 ~/.code-search-mcp"""
    cache_dir = Path.home() / ".code-search-mcp"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_db_dir() -> Path:
    """获取 LanceDB 存储总目录 ~/.code-search-mcp/dbs"""
    db_dir = get_cache_root() / "dbs"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir


def get_repo_hash(repo_path: str | Path) -> str:
    """根据代码库绝对路径生成唯一哈希标识，用于隔离存储"""
    abs_path = str(Path(repo_path).resolve()).lower()
    return hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:16]


def get_repo_db_path(repo_path: str | Path) -> Path:
    """获取指定代码库对应的 LanceDB 文件夹路径"""
    repo_hash = get_repo_hash(repo_path)
    path = get_db_dir() / repo_hash
    path.mkdir(parents=True, exist_ok=True)
    return path
