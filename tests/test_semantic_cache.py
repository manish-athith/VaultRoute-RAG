from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from vaultroute_rag.authorization.access_profile import build_access_profile
from vaultroute_rag.cache.service import SemanticAnswerCache
from vaultroute_rag.cache.vector_store import QdrantSemanticCacheStore
from vaultroute_rag.documents.models import Document
from vaultroute_rag.documents.repository import DocumentRepository
from vaultroute_rag.generation.router import ModelRouter
from vaultroute_rag.generation.schemas import (
    AnswerCitation,
    AnswerResponse,
    AskRequest,
    ModelResult,
    ModelUsage,
    RouteDecision,
)
from vaultroute_rag.generation.service import RagAnswerService
from vaultroute_rag.identity.models import Department
from vaultroute_rag.identity.schemas import UserIdentity
from vaultroute_rag.retrieval.schemas import RetrievedEvidence, SearchResponse


def profile(department: str = "engineering"):
    return build_access_profile(
        UserIdentity(
            user_id=f"user-{department}",
            company_id="company-1",
            company_slug="acme",
            email=f"user-{department}@acme.example.com",
            full_name="Cache User",
            is_active=True,
            token_version=1,
            role_codes=("employee",),
            department_codes=(department,),
        )
    )


def document(*, department: str = "engineering", version: int = 1) -> Document:
    item = Document(
        id="doc-1",
        company_id="company-1",
        uploaded_by_user_id="uploader-1",
        title="API Standards",
        source_filename="api.md",
        media_type="text/markdown",
        checksum="a" * 64,
        classification="internal",
        status="indexed",
        version=version,
        is_company_wide=False,
        text_length=100,
        chunk_count=1,
    )
    item.departments = [
        Department(
            id=f"dept-{department}",
            company_id="company-1",
            code=department,
            name=department,
        )
    ]
    item.roles = []
    item.user_permissions = []
    return item


def answer() -> AnswerResponse:
    evidence = RetrievedEvidence(
        source_id="S1",
        document_id="doc-1",
        document_version=1,
        title="API Standards",
        source_filename="api.md",
        classification="internal",
        departments=("engineering",),
        chunk_index=0,
        text="API logs must exclude passwords and tokens.",
        semantic_score=0.9,
        lexical_score=1.0,
        final_score=0.91,
    )
    return AnswerResponse(
        question="What must API logs exclude?",
        answer="API logs must exclude passwords and tokens [S1].",
        citations=(
            AnswerCitation(
                source_id="S1",
                document_id="doc-1",
                document_version=1,
                title="API Standards",
                source_filename="api.md",
                departments=("engineering",),
                excerpt=evidence.text,
            ),
        ),
        route=RouteDecision(provider="groq", model="small", reason="simple question"),
        usage=ModelUsage(input_tokens=100, output_tokens=12, total_tokens=112),
        retrieval=SearchResponse(
            question="What must API logs exclude?",
            evidence=(evidence,),
            candidates_considered=1,
            max_score=0.91,
            conflict_detected=False,
        ),
    )


class FakeRepository:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents

    async def get_by_ids(self, company_id: str, document_ids: set[str]):
        assert company_id == "company-1"
        return [item for item in self.documents if item.id in document_ids]

    @staticmethod
    def access_rule(item: Document):
        return DocumentRepository.access_rule(item)


@dataclass
class FakeCachePoint:
    id: str
    score: float
    payload: dict


class FakeCacheStore:
    def __init__(self, points: list[FakeCachePoint] | None = None) -> None:
        self.points = points or []
        self.deleted: list[str] = []
        self.stored: list[dict] = []

    async def search(self, **kwargs):
        self.search_kwargs = kwargs
        return self.points

    async def delete(self, point_id: str) -> None:
        self.deleted.append(point_id)

    async def upsert(self, **kwargs) -> str:
        self.stored.append(kwargs)
        return "new-cache-point"


def cached_point(*, version: int = 1) -> FakeCachePoint:
    return FakeCachePoint(
        id="cache-1",
        score=0.97234,
        payload={
            "cache_schema_version": 1,
            "company_id": "company-1",
            "access_scope_key": profile().access_scope_key,
            "source_versions": [{"document_id": "doc-1", "version": version}],
            "response": answer().model_dump(mode="json"),
        },
    )


@pytest.mark.asyncio
async def test_valid_cache_hit_is_reauthorized_and_has_zero_request_tokens() -> None:
    store = FakeCacheStore([cached_point()])
    cache = SemanticAnswerCache(
        repository=FakeRepository([document()]),
        store=store,
        similarity_threshold=0.93,
        candidate_limit=5,
    )

    result = await cache.lookup(
        profile=profile(),
        question="Which secrets are forbidden in API logs?",
        question_vector=[0.1, 0.2, 0.3],
    )

    assert result is not None
    assert result.cache_hit is True
    assert result.cache_similarity == 0.9723
    assert result.question == "Which secrets are forbidden in API logs?"
    assert result.usage.total_tokens == 0
    assert "semantic cache hit" in result.route.reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cached_version", "current_document"),
    [(1, document(version=2)), (1, document(department="hr"))],
)
async def test_stale_or_unauthorized_cache_hit_is_deleted(
    cached_version: int, current_document: Document
) -> None:
    store = FakeCacheStore([cached_point(version=cached_version)])
    cache = SemanticAnswerCache(
        repository=FakeRepository([current_document]),
        store=store,
        similarity_threshold=0.93,
        candidate_limit=5,
    )

    result = await cache.lookup(
        profile=profile(),
        question="Which secrets are forbidden in API logs?",
        question_vector=[0.1, 0.2, 0.3],
    )

    assert result is None
    assert store.deleted == ["cache-1"]


@pytest.mark.asyncio
async def test_generated_answer_is_cached_only_with_current_authorized_sources() -> None:
    store = FakeCacheStore()
    cache = SemanticAnswerCache(
        repository=FakeRepository([document()]),
        store=store,
        similarity_threshold=0.93,
        candidate_limit=5,
    )

    saved = await cache.store(
        profile=profile(),
        question="What must API logs exclude?",
        question_vector=[0.1, 0.2, 0.3],
        response=answer(),
    )

    assert saved is True
    assert store.stored[0]["profile"].access_scope_key == profile().access_scope_key


class CapturingQdrantClient:
    async def delete(self, **kwargs):
        self.delete_kwargs = kwargs

    async def query_points(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(points=[])


@pytest.mark.asyncio
async def test_qdrant_cache_search_filters_company_scope_and_expiry() -> None:
    store = QdrantSemanticCacheStore(
        url="http://unused",
        collection_name="cache",
        dimension=3,
        ttl_seconds=60,
    )
    client = CapturingQdrantClient()
    store._client = client
    store._ready = True
    access = profile()

    await store.search(
        profile=access,
        query_vector=[0.1, 0.2, 0.3],
        score_threshold=0.93,
        limit=5,
    )

    conditions = client.kwargs["query_filter"].must
    matches = {
        condition.key: condition.match.value
        for condition in conditions
        if condition.match is not None
    }
    assert matches == {
        "company_id": "company-1",
        "access_scope_key": access.access_scope_key,
    }
    expiry = next(condition for condition in conditions if condition.key == "expires_at")
    assert expiry.range.gte is not None


class CacheHitRetrieval:
    def __init__(self) -> None:
        self.embeddings = 0

    async def embed_question(self, question: str):
        self.embeddings += 1
        return [0.1, 0.2, 0.3]

    async def search(self, *args, **kwargs):
        raise AssertionError("retrieval must not run after a valid cache hit")


class ReturningCache:
    async def lookup(self, **kwargs):
        return answer().model_copy(update={"cache_hit": True, "cache_similarity": 0.98})

    async def store(self, **kwargs):
        raise AssertionError("an existing cache hit must not be stored again")


@pytest.mark.asyncio
async def test_rag_answer_short_circuits_retrieval_and_model_on_cache_hit() -> None:
    retrieval = CacheHitRetrieval()
    service = RagAnswerService(
        retrieval=retrieval,
        router=None,
        answer_minimum_score=0.5,
        cache=ReturningCache(),
    )

    result = await service.answer(
        profile(),
        AskRequest(question="Which secrets are forbidden in API logs?"),
    )

    assert result.cache_hit is True
    assert retrieval.embeddings == 1


class WorkingRetrieval:
    async def embed_question(self, question: str):
        return [0.1, 0.2, 0.3]

    async def search(self, profile, request, query_vector=None):
        assert query_vector == [0.1, 0.2, 0.3]
        return answer().retrieval


class WorkingProvider:
    provider_name = "groq"
    model_name = "small"
    available = True

    async def generate(self, system_prompt: str, user_prompt: str):
        return ModelResult(
            text="API logs must exclude passwords and tokens [S1].",
            provider=self.provider_name,
            model=self.model_name,
            usage=ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )


class FailingCache:
    async def lookup(self, **kwargs):
        raise RuntimeError("cache unavailable")

    async def store(self, **kwargs):
        raise RuntimeError("cache unavailable")


@pytest.mark.asyncio
async def test_cache_outage_fails_open_to_normal_secure_generation() -> None:
    provider = WorkingProvider()
    service = RagAnswerService(
        retrieval=WorkingRetrieval(),
        router=ModelRouter(provider, provider),
        answer_minimum_score=0.5,
        cache=FailingCache(),
    )

    result = await service.answer(profile(), AskRequest(question="What must API logs exclude?"))

    assert result.cache_hit is False
    assert result.route.provider == "groq"
    assert result.usage.total_tokens == 15
