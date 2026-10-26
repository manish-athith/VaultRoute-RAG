import asyncio
from collections.abc import Sequence
from typing import Protocol


class EmbeddingProvider(Protocol):
    model_name: str
    dimension: int

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...


class FastEmbedProvider:
    """Lazy CPU embeddings through FastEmbed's ONNX runtime."""

    def __init__(self, model_name: str, dimension: int, cache_dir: str) -> None:
        self.model_name = model_name
        self.dimension = dimension
        self.cache_dir = cache_dir
        self._model = None
        self._load_lock = asyncio.Lock()

    async def _get_model(self):
        if self._model is None:
            async with self._load_lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    self._model = await asyncio.to_thread(
                        TextEmbedding,
                        model_name=self.model_name,
                        cache_dir=self.cache_dir,
                        lazy_load=True,
                    )
        return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await self._get_model()
        vectors = await asyncio.to_thread(
            lambda: [vector.tolist() for vector in model.embed(texts)]
        )
        if any(len(vector) != self.dimension for vector in vectors):
            raise ValueError("Embedding model returned an unexpected vector dimension")
        return vectors

    async def embed_query(self, text: str) -> list[float]:
        model = await self._get_model()
        vectors = await asyncio.to_thread(
            lambda: [vector.tolist() for vector in model.query_embed(text)]
        )
        if len(vectors) != 1 or len(vectors[0]) != self.dimension:
            raise ValueError("Embedding model returned an unexpected query vector")
        return vectors[0]
