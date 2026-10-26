from collections.abc import Sequence

from pydantic import ValidationError

from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.authorization.evaluator import is_authorized
from vaultroute_rag.cache.vector_store import QdrantSemanticCacheStore
from vaultroute_rag.documents.repository import DocumentRepository
from vaultroute_rag.generation.schemas import AnswerResponse, ModelUsage


class SemanticAnswerCache:
    """Returns a cached answer only after authoritative source re-authorization."""

    def __init__(
        self,
        *,
        repository: DocumentRepository,
        store: QdrantSemanticCacheStore,
        similarity_threshold: float,
        candidate_limit: int,
    ) -> None:
        self._repository = repository
        self._store = store
        self._similarity_threshold = similarity_threshold
        self._candidate_limit = candidate_limit

    async def lookup(
        self,
        *,
        profile: AccessProfile,
        question: str,
        question_vector: Sequence[float],
    ) -> AnswerResponse | None:
        points = await self._store.search(
            profile=profile,
            query_vector=question_vector,
            score_threshold=self._similarity_threshold,
            limit=self._candidate_limit,
        )
        for point in points:
            payload = point.payload or {}
            point_id = str(point.id)
            try:
                if payload.get("cache_schema_version") != 1:
                    raise ValueError("Unsupported cache schema")
                if payload.get("company_id") != profile.company_id:
                    raise ValueError("Cache company mismatch")
                if payload.get("access_scope_key") != profile.access_scope_key:
                    raise ValueError("Cache access scope mismatch")
                response = AnswerResponse.model_validate(payload["response"])
                source_versions = self._parse_source_versions(payload["source_versions"])
                if self._response_source_versions(response) != source_versions:
                    raise ValueError("Cache response source mismatch")
                self._validate_citations(response)
            except (KeyError, TypeError, ValueError, ValidationError):
                await self._store.delete(point_id)
                continue
            if not await self._sources_are_current_and_allowed(profile, source_versions):
                await self._store.delete(point_id)
                continue

            retrieval = response.retrieval.model_copy(update={"question": question})
            route = response.route.model_copy(
                update={"reason": f"semantic cache hit; {response.route.reason}"}
            )
            return response.model_copy(
                update={
                    "question": question,
                    "retrieval": retrieval,
                    "route": route,
                    "usage": ModelUsage(),
                    "cache_hit": True,
                    "cache_similarity": round(float(point.score), 4),
                }
            )
        return None

    async def store(
        self,
        *,
        profile: AccessProfile,
        question: str,
        question_vector: Sequence[float],
        response: AnswerResponse,
    ) -> bool:
        source_versions = {
            item.document_id: item.document_version for item in response.retrieval.evidence
        }
        if not source_versions:
            return False
        if not await self._sources_are_current_and_allowed(profile, source_versions):
            return False
        await self._store.upsert(
            profile=profile,
            question=question,
            question_vector=question_vector,
            response=response,
        )
        return True

    async def _sources_are_current_and_allowed(
        self,
        profile: AccessProfile,
        source_versions: dict[str, int],
    ) -> bool:
        if not source_versions:
            return False
        documents = await self._repository.get_by_ids(profile.company_id, set(source_versions))
        if len(documents) != len(source_versions):
            return False
        for document in documents:
            if document.status != "indexed":
                return False
            if document.version != source_versions.get(document.id):
                return False
            if not is_authorized(profile, self._repository.access_rule(document)):
                return False
        return True

    @staticmethod
    def _parse_source_versions(value: object) -> dict[str, int]:
        if not isinstance(value, list):
            raise ValueError("Cache source versions must be a list")
        parsed: dict[str, int] = {}
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("Invalid cache source version entry")
            document_id = str(item["document_id"])
            version = int(item["version"])
            if not document_id or version < 1:
                raise ValueError("Invalid cache source version")
            parsed[document_id] = version
        return parsed

    @staticmethod
    def _response_source_versions(response: AnswerResponse) -> dict[str, int]:
        return {item.document_id: item.document_version for item in response.retrieval.evidence}

    @staticmethod
    def _validate_citations(response: AnswerResponse) -> None:
        evidence = {
            item.source_id: (item.document_id, item.document_version)
            for item in response.retrieval.evidence
        }
        for citation in response.citations:
            expected = evidence.get(citation.source_id)
            if expected != (citation.document_id, citation.document_version):
                raise ValueError("Cache citation does not match retrieval evidence")
