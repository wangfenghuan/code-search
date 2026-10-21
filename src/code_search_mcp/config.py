import hashlib
import os
from pathlib import Path

# Default global configurations and path management
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
    """Get or dynamically resolve vector dimension for embedding model"""
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

# Ignored directory patterns
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
    """Get user global cache directory ~/.code-search-graph (with fallback to ~/.code-search-mcp)"""
    new_dir = Path.home() / ".code-search-graph"
    old_dir = Path.home() / ".code-search-mcp"
    if new_dir.exists():
        return new_dir
    if old_dir.exists():
        return old_dir
    new_dir.mkdir(parents=True, exist_ok=True)
    return new_dir


def get_db_dir() -> Path:
    """Get LanceDB database storage directory <cache_root>/dbs"""
    db_dir = get_cache_root() / "dbs"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir


def get_repo_hash(repo_path: str | Path) -> str:
    """Generate unique deterministic hash for target repository"""
    abs_path = str(Path(repo_path).resolve()).lower()
    return hashlib.sha256(abs_path.encode("utf-8")).hexdigest()[:16]


def get_repo_db_path(repo_path: str | Path) -> Path:
    """Get repository LanceDB directory path"""
    repo_hash = get_repo_hash(repo_path)
    path = get_db_dir() / repo_hash
    path.mkdir(parents=True, exist_ok=True)
    return path
