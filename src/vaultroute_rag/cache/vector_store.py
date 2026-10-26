import asyncio
import hashlib
import re
import time
import uuid
from collections.abc import Sequence
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.generation.schemas import AnswerResponse


class QdrantSemanticCacheStore:
    """Stores answer vectors and permission/version metadata in one shared collection."""

    def __init__(
        self,
        *,
        url: str,
        collection_name: str,
        dimension: int,
        ttl_seconds: int,
    ) -> None:
        self.collection_name = collection_name
        self.dimension = dimension
        self.ttl_seconds = ttl_seconds
        self._client = AsyncQdrantClient(url=url, check_compatibility=False)
        self._ready = False
        self._ready_lock = asyncio.Lock()
        self._cleanup_lock = asyncio.Lock()
        self._last_cleanup_at = 0

    async def ensure_collection(self) -> None:
        if self._ready:
            return
        async with self._ready_lock:
            if self._ready:
                return
            if await self._client.collection_exists(self.collection_name):
                collection = await self._client.get_collection(self.collection_name)
                configured_size = getattr(collection.config.params.vectors, "size", None)
                if configured_size != self.dimension:
                    raise ValueError(
                        f"Qdrant cache dimension is {configured_size}; expected {self.dimension}"
                    )
            else:
                await self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=models.VectorParams(
                        size=self.dimension,
                        distance=models.Distance.COSINE,
                    ),
                    on_disk_payload=True,
                )
                for field, schema in (
                    ("company_id", models.PayloadSchemaType.KEYWORD),
                    ("access_scope_key", models.PayloadSchemaType.KEYWORD),
                    ("expires_at", models.PayloadSchemaType.INTEGER),
                ):
                    await self._client.create_payload_index(
                        collection_name=self.collection_name,
                        field_name=field,
                        field_schema=schema,
                        wait=True,
                    )
            self._ready = True

    async def search(
        self,
        *,
        profile: AccessProfile,
        query_vector: Sequence[float],
        score_threshold: float,
        limit: int,
    ):
        await self.ensure_collection()
        await self._cleanup_expired_if_due()
        result = await self._client.query_points(
            collection_name=self.collection_name,
            query=list(query_vector),
            query_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="company_id",
                        match=models.MatchValue(value=profile.company_id),
                    ),
                    models.FieldCondition(
                        key="access_scope_key",
                        match=models.MatchValue(value=profile.access_scope_key),
                    ),
                    models.FieldCondition(
                        key="expires_at",
                        range=models.Range(gte=int(time.time())),
                    ),
                ]
            ),
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        return result.points

    async def upsert(
        self,
        *,
        profile: AccessProfile,
        question: str,
        question_vector: Sequence[float],
        response: AnswerResponse,
    ) -> str:
        await self.ensure_collection()
        await self._cleanup_expired_if_due()
        normalized_question = self._normalize_question(question)
        identity = hashlib.sha256(
            f"{profile.company_id}|{profile.access_scope_key}|{normalized_question}".encode()
        ).hexdigest()
        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"vaultroute-cache:{identity}"))
        now = int(time.time())
        source_versions = self._source_versions(response)
        payload: dict[str, Any] = {
            "cache_schema_version": 1,
            "company_id": profile.company_id,
            "access_scope_key": profile.access_scope_key,
            "question": question,
            "normalized_question": normalized_question,
            "source_versions": source_versions,
            "response": response.model_dump(mode="json"),
            "created_at": now,
            "expires_at": now + self.ttl_seconds,
        }
        await self._client.upsert(
            collection_name=self.collection_name,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector=list(question_vector),
                    payload=payload,
                )
            ],
            wait=True,
        )
        return point_id

    async def delete(self, point_id: str) -> None:
        await self._client.delete(
            collection_name=self.collection_name,
            points_selector=models.PointIdsList(points=[point_id]),
            wait=True,
        )

    async def close(self) -> None:
        await self._client.close()

    async def _cleanup_expired_if_due(self) -> None:
        now = int(time.time())
        if now - self._last_cleanup_at < 3600:
            return
        async with self._cleanup_lock:
            if now - self._last_cleanup_at < 3600:
                return
            await self._client.delete(
                collection_name=self.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(
                                key="expires_at",
                                range=models.Range(lt=now),
                            )
                        ]
                    )
                ),
                wait=False,
            )
            self._last_cleanup_at = now

    @staticmethod
    def _normalize_question(question: str) -> str:
        return " ".join(re.findall(r"[a-z0-9]+", question.lower()))

    @staticmethod
    def _source_versions(response: AnswerResponse) -> list[dict[str, Any]]:
        unique: dict[str, int] = {}
        for evidence in response.retrieval.evidence:
            unique[evidence.document_id] = evidence.document_version
        return [
            {"document_id": document_id, "version": version}
            for document_id, version in sorted(unique.items())
        ]
