import hashlib
import os
from pathlib import Path

# Default global configurations and path management
def _resolve_default_model() -> str:
    if "CODE_SEARCH_MODEL" in os.environ:
        return os.environ["CODE_SEARCH_MODEL"]
    bundled_en = Path(__file__).resolve().parent / "models" / "bge-small-en-v1.5"
    if bundled_en.exists() and (bundled_en / "model_optimized.onnx").exists():
        return "BAAI/bge-small-en-v1.5"
    return "BAAI/bge-small-zh-v1.5"


DEFAULT_MODEL_NAME = _resolve_default_model()
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


def resolve_repo_path(repo_path: str | Path | None = None) -> Path:
    """Resolve repository path with predictable precedence:
    1. Explicit path argument (if valid and directory exists)
    2. Current working directory Path.cwd() (if it was indexed or is a source/git repository)
    3. Docker container mount priority (/workspace)
    4. Most recently indexed repository (last_repo.txt)
    5. Current working directory Path.cwd()
    """
    if repo_path:
        p = Path(repo_path).resolve()
        if p.exists() and p.is_dir():
            return p

    cwd = Path.cwd().resolve()
    # If cwd has been indexed or is a git repository, ALWAYS respect current working directory!
    cwd_db = get_repo_db_path(cwd)
    if (cwd_db / "meta.json").exists() or (cwd / ".git").exists():
        return cwd

    # If cwd contains common project markers, prefer cwd
    project_markers = (
        "src",
        "lib",
        "app",
        "main",
        "pom.xml",
        "package.json",
        "pyproject.toml",
        "Cargo.toml",
        "go.mod",
        "settings.gradle",
        "build.gradle",
    )
    try:
        if any((cwd / marker).exists() for marker in project_markers):
            return cwd
    except Exception:
        pass

    # Docker container mount priority
    docker_ws = Path("/workspace")
    if docker_ws.exists() and docker_ws.is_dir():
        try:
            if any(docker_ws.iterdir()):
                return docker_ws
        except Exception:
            pass

    last_repo_file = get_db_dir() / "last_repo.txt"
    if last_repo_file.exists():
        try:
            saved_path = last_repo_file.read_text(encoding="utf-8").strip()
            p = Path(saved_path).resolve()
            if p.exists() and p.is_dir():
                return p
        except Exception:
            pass

    return cwd

