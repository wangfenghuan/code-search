import sys
from typing import Generator, Iterable, List, Sequence
import numpy as np
from fastembed import TextEmbedding

from code_search_mcp.config import DEFAULT_MODEL_NAME


class EmbeddingEngine:
    """基于 FastEmbed (ONNX Runtime) 的本地轻量向量化引擎"""

    _instance: "EmbeddingEngine | None" = None

    def __init__(self, model_name: str = DEFAULT_MODEL_NAME):
        self.model_name = model_name
        # 延迟加载，避免启动时耗时过长
        self._model: TextEmbedding | None = None

    @classmethod
    def get_instance(cls, model_name: str = DEFAULT_MODEL_NAME) -> "EmbeddingEngine":
        if cls._instance is None or cls._instance.model_name != model_name:
            cls._instance = cls(model_name=model_name)
        return cls._instance

    @property
    def model(self) -> TextEmbedding:
        if self._model is None:
            # 日志仅允许打在 stderr，防止污染 MCP stdio
            sys.stderr.write(f"[code-search-mcp] 正在加载本地 Embedding 模型: {self.model_name}\n")
            sys.stderr.flush()
            self._model = TextEmbedding(model_name=self.model_name)
            sys.stderr.write(f"[code-search-mcp] 模型加载完成\n")
            sys.stderr.flush()
        return self._model

    def embed_documents(self, texts: Sequence[str], batch_size: int = 32) -> List[List[float]]:
        """批量对代码块或文本生成向量列表"""
        if not texts:
            return []
        embeddings_gen = self.model.embed(texts, batch_size=batch_size)
        return [vec.tolist() for vec in embeddings_gen]

    def embed_query(self, query: str) -> List[float]:
        """对单个自然语言查询生成向量"""
        # fastembed query_embed 返回 generator
        res = list(self.model.query_embed(query))
        if res:
            return res[0].tolist()
        return []
