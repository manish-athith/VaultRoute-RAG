import asyncio
import uuid
from collections.abc import Sequence
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.documents.schemas import TextChunk


class QdrantChunkStore:
    """Owns the document-chunk collection and its permission payloads."""

    def __init__(self, url: str, collection_name: str, dimension: int) -> None:
        self.collection_name = collection_name
        self.dimension = dimension
        self._client = AsyncQdrantClient(url=url, check_compatibility=False)
        self._ready = False
        self._ready_lock = asyncio.Lock()

    async def ensure_collection(self) -> None:
        if self._ready:
            return
        async with self._ready_lock:
            if self._ready:
                return
            if await self._client.collection_exists(self.collection_name):
                collection = await self._client.get_collection(self.collection_name)
                vectors = collection.config.params.vectors
                configured_size = getattr(vectors, "size", None)
                if configured_size != self.dimension:
                    raise ValueError(
                        f"Qdrant collection dimension is {configured_size}; "
                        f"expected {self.dimension}"
                    )
            else:
                await self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.dimension, distance=models.Distance.COSINE
                    ),
                    on_disk_payload=True,
                )
                for field in (
                    "company_id",
                    "document_id",
                    "department_codes",
                    "role_codes",
                    "allowed_user_ids",
                    "denied_user_ids",
                    "access_principals",
                    "classification",
                ):
                    await self._client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                        wait=True,
                    )
            self._ready = True

    async def index_document(
        self,
        *,
        document_id: str,
        version: int,
        chunks: Sequence[TextChunk],
        vectors: Sequence[Sequence[float]],
        payload: dict[str, Any],
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("Every chunk must have exactly one embedding")
        await self.ensure_collection()
        points = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{document_id}:{version}:{chunk.index}"))
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=list(vector),
                    payload={
                        **payload,
                        "document_id": document_id,
                        "document_version": version,
                        "chunk_index": chunk.index,
                        "chunk_text": chunk.text,
                        "word_count": chunk.word_count,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                    },
                )
            )
        await self._client.upsert(
            collection_name=self.collection_name,
            points=points,
            wait=True,
        )

    async def delete_document(self, document_id: str) -> None:
        if not await self._client.collection_exists(self.collection_name):
            return
        await self._client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id", match=models.MatchValue(value=document_id)
                        )
                    ]
                )
            ),
            wait=True,
        )

    async def search_authorized(
        self,
        *,
        profile: AccessProfile,
        query_vector: Sequence[float],
        limit: int,
        score_threshold: float,
    ):
        await self.ensure_collection()
        must = [
            models.FieldCondition(
                key="company_id", match=models.MatchValue(value=profile.company_id)
            )
        ]
        must_not = [
            models.FieldCondition(
                key="denied_user_ids", match=models.MatchValue(value=profile.user_id)
            )
        ]
        minimum_access = None
        if not profile.has_global_access:
            minimum_access = models.MinShould(
                conditions=[
                    models.FieldCondition(
                        key="access_principals",
                        match=models.MatchAny(any=list(profile.principal_ids)),
                    )
                ],
                min_count=1,
            )
        result = await self._client.query_points(
            collection_name=self.collection_name,
            query=list(query_vector),
            query_filter=models.Filter(
                must=must,
                must_not=must_not,
                min_should=minimum_access,
            ),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        return result.points

    async def close(self) -> None:
        await self._client.close()
