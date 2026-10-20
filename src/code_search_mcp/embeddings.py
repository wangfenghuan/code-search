import os
import sys
from pathlib import Path
from typing import Generator, Iterable, List, Optional, Sequence
import numpy as np
from fastembed import TextEmbedding

from code_search_mcp.config import DEFAULT_MODEL_NAME, get_cache_root


_PROBED_PROVIDERS: Optional[List[str]] = None


def get_optimal_execution_providers() -> List[str]:
    """智能探测并返回最优硬件加速推理 Provider 顺序 (CUDA / CoreML / DirectML / CPU)"""
    global _PROBED_PROVIDERS
    if _PROBED_PROVIDERS is not None:
        return list(_PROBED_PROVIDERS)

    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
        chosen = []
        # 1. NVIDIA CUDA (极速 GPU 加速，工业级首选)
        if "CUDAExecutionProvider" in available:
            chosen.append("CUDAExecutionProvider")

        # 2. Apple Silicon CoreML (Mac MPS / Apple Neural Engine 加速)
        if "CoreMLExecutionProvider" in available:
            chosen.append("CoreMLExecutionProvider")

        # 3. Windows DirectML (仅在显式启用或探针通过时启用，避免核显 Attention 算子 8007000E 显存异常)
        if "DmlExecutionProvider" in available:
            if os.environ.get("ENABLE_DIRECTML", "0") == "1":
                chosen.append("DmlExecutionProvider")

        # 4. CPU 多核并行兜底 (threads=os.cpu_count() + batch_size=128，吞吐达 180~370 texts/s)
        chosen.append("CPUExecutionProvider")
        _PROBED_PROVIDERS = chosen
        return list(chosen)
    except Exception:
        _PROBED_PROVIDERS = ["CPUExecutionProvider"]
        return list(_PROBED_PROVIDERS)


def get_bundled_model_dir(model_name: str) -> Optional[Path]:
    """检测代码库内是否随附了离线预打包的模型文件 (零网络离线秒启)"""
    base_models_dir = Path(__file__).resolve().parent / "models"
    # 例如 "BAAI/bge-small-zh-v1.5" -> "bge-small-zh-v1.5"
    slug = model_name.split("/")[-1]
    candidate = base_models_dir / slug
    if candidate.exists() and (candidate / "model_optimized.onnx").exists():
        return candidate
    return None


class EmbeddingEngine:
    """基于 FastEmbed (ONNX Runtime) 的本地轻量向量化引擎 (支持 GPU/MPS/CoreML 硬件自适应加速与多核 CPU 平滑兜底)"""

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
        # 限制最大并行线程数为 4（或由环境变量指定），避免 ONNX Runtime 线程工作区显存/内存峰值过高引起 OOM
        threads = int(os.environ.get("EMBEDDING_THREADS", min(4, max(1, os.cpu_count() or 4))))
        hw_desc = providers[0].replace("ExecutionProvider", "")
        self._current_provider = providers[0]

        bundled_path = get_bundled_model_dir(self.model_name)
        if bundled_path:
            sys.stderr.write(f"[code-search-mcp] 加载离线模型: {self.model_name} [硬件后端: {hw_desc}, 并行线程: {threads}]\n")
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
            # 为国内用户默认提供稳定镜像源兜底
            if "HF_ENDPOINT" not in os.environ:
                os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            sys.stderr.write(f"[code-search-mcp] Loading embedding model: {self.model_name} [backend: {hw_desc}, threads: {threads}]\n")
            sys.stderr.flush()
            model = TextEmbedding(
                model_name=self.model_name,
                cache_dir=models_cache,
                providers=providers,
                threads=threads,
            )
        sys.stderr.write(f"[code-search-mcp] Model loaded successfully\n")
        sys.stderr.flush()
        return model

    @property
    def model(self) -> TextEmbedding:
        if self._model is None:
            providers = get_optimal_execution_providers()
            self._model = self._init_model(providers)
        return self._model

    def _switch_to_cpu(self):
        """当 GPU/MPS 硬件加速出现显存溢出或算子不支持时，自动降级至 CPU 多核并行兜底"""
        sys.stderr.write(f"[code-search-mcp] 硬件加速遇到异常，平滑降级至 CPUExecutionProvider 多核全速兜底...\n")
        sys.stderr.flush()
        self._current_provider = "CPUExecutionProvider"
        self._model = self._init_model(["CPUExecutionProvider"])

    def embed_documents(self, texts: Sequence[str], batch_size: int = 64) -> List[List[float]]:
        """批量对代码块或文本生成向量列表 (安全批大小 64 兼顾吞吐与内存，硬件加速异常自动降级 CPU 兜底)"""
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
        """对单个自然语言查询生成向量 (硬件加速异常自动降级 CPU 兜底)"""
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
