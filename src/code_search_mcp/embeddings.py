import os
import sys
from pathlib import Path
from typing import Generator, Iterable, List, Optional, Sequence
import numpy as np
from fastembed import TextEmbedding

from code_search_mcp.config import DEFAULT_MODEL_NAME, get_cache_root


_PROBED_PROVIDERS: Optional[List[str]] = None


def get_optimal_execution_providers() -> List[str]:
    """Probe and return optimal hardware acceleration execution providers (CUDA / CoreML / DirectML / CPU)"""
    global _PROBED_PROVIDERS
    if _PROBED_PROVIDERS is not None:
        return list(_PROBED_PROVIDERS)

    try:
        import onnxruntime as ort

        available = ort.get_available_providers()
        chosen = []
        # 1. NVIDIA CUDA (High performance GPU acceleration)
        if "CUDAExecutionProvider" in available:
            chosen.append("CUDAExecutionProvider")

        # 2. Apple Silicon CoreML (Mac MPS / Apple Neural Engine)
        if "CoreMLExecutionProvider" in available:
            chosen.append("CoreMLExecutionProvider")

        # 3. Windows DirectML (explicitly enabled via env to avoid driver quirks)
        if "DmlExecutionProvider" in available:
            if os.environ.get("ENABLE_DIRECTML", "0") == "1":
                chosen.append("DmlExecutionProvider")

        # 4. Multi-core CPU fallback
        chosen.append("CPUExecutionProvider")
        _PROBED_PROVIDERS = chosen
        return list(chosen)
    except Exception:
        _PROBED_PROVIDERS = ["CPUExecutionProvider"]
        return list(_PROBED_PROVIDERS)


def get_bundled_model_dir(model_name: str) -> Optional[Path]:
    """Check if model weights are pre-bundled in package for offline zero-network startup"""
    base_models_dir = Path(__file__).resolve().parent / "models"
    slug = model_name.split("/")[-1]
    candidate = base_models_dir / slug
    if candidate.exists() and (candidate / "model_optimized.onnx").exists():
        return candidate
    return None


class EmbeddingEngine:
    """Local embedding engine powered by FastEmbed and ONNX Runtime"""

    _instance: "EmbeddingEngine | None" = None

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME):
        self.model_name = model_name
        self._model: TextEmbedding | None = None
        self._current_provider: str = ""

    @classmethod
    def get_instance(cls, model_name: str = DEFAULT_MODEL_NAME) -> "EmbeddingEngine":
        if cls._instance is None or cls._instance.model_name != model_name:
            cls._instance = cls(model_name=model_name)
        return cls._instance

    def _init_model(self, providers: List[str]) -> TextEmbedding:
        # Bounded threads to prevent high peak memory during inference
        threads = int(os.environ.get("EMBEDDING_THREADS", min(4, max(1, os.cpu_count() or 4))))
        hw_desc = providers[0].replace("ExecutionProvider", "")
        self._current_provider = providers[0]

        bundled_path = get_bundled_model_dir(self.model_name)
        if bundled_path:
            sys.stderr.write(
                f"[code-search-graph] Loading bundled offline model: {self.model_name} [backend: {hw_desc}, threads: {threads}]\n"
            )
            sys.stderr.flush()
            model = TextEmbedding(
                model_name=self.model_name,
                specific_model_path=str(bundled_path),
                local_files_only=True,
                providers=providers,
                threads=threads,
            )
        else:
            models_cache = str(get_cache_root() / "models")
            if "HF_ENDPOINT" not in os.environ:
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            sys.stderr.write(
                f"[code-search-graph] Loading embedding model: {self.model_name} [backend: {hw_desc}, threads: {threads}]\n"
            )
            sys.stderr.flush()
            model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=models_cache,
                providers=providers,
                threads=threads,
            )
        sys.stderr.write(f"[code-search-graph] Model loaded successfully\n")
        sys.stderr.flush()
        return model

    @property
    def model(self) -> TextEmbedding:
        if self._model is None:
            providers = get_optimal_execution_providers()
            self._model = self._init_model(providers)
        return self._model

    def _switch_to_cpu(self):
        """Seamlessly fallback to CPU Execution Provider on GPU OOM or unsupported operators"""
        sys.stderr.write(
            f"[code-search-graph] Hardware acceleration exception, falling back to CPU multi-core execution...\n"
        )
        sys.stderr.flush()
        self._current_provider = "CPUExecutionProvider"
        self._model = self._init_model(["CPUExecutionProvider"])

    def embed_documents(self, texts: Sequence[str], batch_size: int = 64) -> List[List[float]]:
        """Batch embed code chunks or documents"""
        if not texts:
            return []
        try:
            embeddings_gen = self.model.embed(texts, batch_size=batch_size)
            return [vec.tolist() for vec in embeddings_gen]
        except Exception as e:
            if self._current_provider != "CPUExecutionProvider":
                self._switch_to_cpu()
                embeddings_gen = self.model.embed(texts, batch_size=batch_size)
                return [vec.tolist() for vec in embeddings_gen]
            raise e

    def embed_query(self, query: str) -> List[float]:
        """Embed single natural language query string"""
        try:
            res = list(self.model.query_embed(query))
            if res:
                return res[0].tolist()
            return []
        except Exception as e:
            if self._current_provider != "CPUExecutionProvider":
                self._switch_to_cpu()
                res = list(self.model.query_embed(query))
                if res:
                    return res[0].tolist()
                return []
            raise e
