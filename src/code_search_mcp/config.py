import hashlib
import os
from pathlib import Path

# 默认全局配置与路径管理
DEFAULT_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
VECTOR_DIMENSION = 512
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
