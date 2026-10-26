from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from vaultroute_rag.authorization.access_profile import build_access_profile
from vaultroute_rag.documents.models import Document
from vaultroute_rag.generation.grounding import (
    UngroundedModelResponse,
    validate_and_build_citations,
)
from vaultroute_rag.generation.router import ModelRouter
from vaultroute_rag.generation.schemas import (
    AskRequest,
    ModelResult,
    ModelUsage,
)
from vaultroute_rag.generation.service import RagAnswerService
from vaultroute_rag.identity.models import Department
from vaultroute_rag.identity.schemas import UserIdentity
from vaultroute_rag.retrieval.schemas import (
    RetrievedEvidence,
    SearchRequest,
    SearchResponse,
)
from vaultroute_rag.retrieval.service import RetrievalService


def make_profile(departments: tuple[str, ...] = ("engineering",)):
    return build_access_profile(
        UserIdentity(
            user_id="user-1",
            company_id="company-1",
            company_slug="acme",
            email="user@acme.example.com",
            full_name="Test User",
            is_active=True,
            token_version=1,
            role_codes=("junior_developer",),
            department_codes=departments,
        )
    )


def make_document(
    document_id: str,
    *,
    title: str = "API Standards",
    department: str = "engineering",
    version: int = 1,
) -> Document:
    document = Document(
        id=document_id,
        company_id="company-1",
        uploaded_by_user_id="uploader-1",
        title=title,
        source_filename=f"{document_id}.md",
        media_type="text/markdown",
        checksum=document_id.ljust(64, "0"),
        classification="internal",
        status="indexed",
        version=version,
        is_company_wide=False,
        text_length=100,
        chunk_count=1,
    )
    document.departments = [
        Department(
            id=f"dept-{department}", company_id="company-1", code=department, name=department
        )
    ]
    document.roles = []
    document.user_permissions = []
    return document


@dataclass
class FakePoint:
    score: float
    payload: dict


class FakeEmbeddingProvider:
    model_name = "fake-embedding"
    dimension = 3

    async def embed_query(self, text: str) -> list[float]:
        assert text
        return [0.1, 0.2, 0.3]


class FakeChunkStore:
    def __init__(self, points: list[FakePoint]) -> None:
        self.points = points
        self.profile = None

    async def search_authorized(self, **kwargs):
        self.profile = kwargs["profile"]
        return self.points


class FakeDocumentRepository:
    def __init__(self, documents: list[Document]) -> None:
        self.documents = documents

    async def get_by_ids(self, company_id: str, document_ids: set[str]) -> list[Document]:
        assert company_id == "company-1"
        return [document for document in self.documents if document.id in document_ids]

    @staticmethod
    def access_rule(document: Document):
        from vaultroute_rag.documents.repository import DocumentRepository

        return DocumentRepository.access_rule(document)


def point(document_id: str, text: str, *, version: int = 1, score: float = 0.8) -> FakePoint:
    return FakePoint(
        score=score,
        payload={
            "document_id": document_id,
            "document_version": version,
            "chunk_index": 0,
            "chunk_text": text,
        },
    )


@pytest.mark.asyncio
async def test_retrieval_rechecks_permissions_after_vector_filter() -> None:
    service = RetrievalService(
        repository=FakeDocumentRepository(
            [
                make_document("eng", department="engineering"),
                make_document("hr", title="Leave Policy", department="hr"),
            ]
        ),
        embeddings=FakeEmbeddingProvider(),
        chunk_store=FakeChunkStore(
            [
                point("eng", "API requests require authentication and request IDs."),
                point("hr", "Medical details stay private."),
            ]
        ),
        candidate_limit=10,
        default_top_k=5,
        minimum_score=0.3,
    )

    result = await service.search(
        make_profile(), SearchRequest(question="How are API requests authenticated?")
    )

    assert [item.document_id for item in result.evidence] == ["eng"]


@pytest.mark.asyncio
async def test_retrieval_rejects_stale_chunk_versions() -> None:
    service = RetrievalService(
        repository=FakeDocumentRepository([make_document("eng", version=2)]),
        embeddings=FakeEmbeddingProvider(),
        chunk_store=FakeChunkStore([point("eng", "Old API policy", version=1)]),
        candidate_limit=10,
        default_top_k=5,
        minimum_score=0.3,
    )

    result = await service.search(make_profile(), SearchRequest(question="What is the API policy?"))

    assert result.evidence == ()


@pytest.mark.asyncio
async def test_retrieval_prefers_newer_same_title_and_warns() -> None:
    service = RetrievalService(
        repository=FakeDocumentRepository(
            [
                make_document("old", title="Release Policy", version=1),
                make_document("new", title="Release Policy", version=2),
            ]
        ),
        embeddings=FakeEmbeddingProvider(),
        chunk_store=FakeChunkStore(
            [
                point("old", "Old release policy", version=1, score=0.9),
                point("new", "New release policy", version=2, score=0.8),
            ]
        ),
        candidate_limit=10,
        default_top_k=5,
        minimum_score=0.3,
    )

    result = await service.search(make_profile(), SearchRequest(question="release policy"))

    assert [item.document_id for item in result.evidence] == ["new"]
    assert result.conflict_detected is True
    assert result.warnings


def evidence(source_id: str = "S1", score: float = 0.8) -> RetrievedEvidence:
    return RetrievedEvidence(
        source_id=source_id,
        document_id=f"doc-{source_id}",
        document_version=1,
        title="API Standards",
        source_filename="api.md",
        classification="internal",
        departments=("engineering",),
        chunk_index=0,
        text="Every API request receives a request ID.",
        semantic_score=score,
        lexical_score=1.0,
        final_score=score,
    )


def search_response(*items: RetrievedEvidence, conflict: bool = False) -> SearchResponse:
    return SearchResponse(
        question="question",
        evidence=items,
        candidates_considered=len(items),
        max_score=max((item.final_score for item in items), default=0),
        conflict_detected=conflict,
    )


class FakeProvider:
    def __init__(self, provider: str, model: str, available: bool = True) -> None:
        self.provider_name = provider
        self.model_name = model
        self.available = available
        self.calls = 0

    async def generate(self, system_prompt: str, user_prompt: str) -> ModelResult:
        assert "untrusted data" in system_prompt
        assert "AUTHORIZED EVIDENCE" in user_prompt
        self.calls += 1
        return ModelResult(
            text="Every request receives a request ID [S1].",
            provider=self.provider_name,
            model=self.model_name,
            usage=ModelUsage(input_tokens=100, output_tokens=10, total_tokens=110),
        )


def test_router_uses_groq_for_simple_question_and_openai_for_complex_question() -> None:
    groq = FakeProvider("groq", "small")
    openai = FakeProvider("openai", "large")
    router = ModelRouter(groq, openai)

    simple, _ = router.choose("What is the API rule?", search_response(evidence()))
    complex_provider, decision = router.choose(
        "Compare the strategy, risks, tradeoffs, and implications across all relevant policies.",
        search_response(*(evidence(f"S{i}") for i in range(1, 5))),
    )

    assert simple is groq
    assert complex_provider is openai
    assert decision.provider == "openai"


def test_router_falls_back_to_available_provider() -> None:
    groq = FakeProvider("groq", "small", available=False)
    openai = FakeProvider("openai", "large")

    selected, decision = ModelRouter(groq, openai).choose(
        "What is the API rule?", search_response(evidence())
    )

    assert selected is openai
    assert "fallback" in decision.reason


def test_grounding_validator_accepts_only_known_citations() -> None:
    citations = validate_and_build_citations("The API requires request IDs [S1].", (evidence(),))
    assert citations[0].source_id == "S1"

    with pytest.raises(UngroundedModelResponse, match="unknown"):
        validate_and_build_citations("Unsupported claim [S9].", (evidence(),))
    with pytest.raises(UngroundedModelResponse, match="did not cite"):
        validate_and_build_citations("Unsupported claim.", (evidence(),))


class FakeRetrievalService:
    def __init__(self, result: SearchResponse) -> None:
        self.result = result

    async def search(self, profile, request):
        return self.result


@pytest.mark.asyncio
async def test_answer_refuses_without_strong_authorized_evidence() -> None:
    groq = FakeProvider("groq", "small")
    service = RagAnswerService(
        retrieval=FakeRetrievalService(search_response(evidence(score=0.2))),
        router=ModelRouter(groq, FakeProvider("openai", "large")),
        answer_minimum_score=0.42,
    )

    result = await service.answer(make_profile(), AskRequest(question="What is the API rule?"))

    assert "not have enough authorized information" in result.answer
    assert result.route.provider == "none"
    assert groq.calls == 0


@pytest.mark.asyncio
async def test_answer_uses_routed_model_and_returns_validated_citations() -> None:
    groq = FakeProvider("groq", "small")
    service = RagAnswerService(
        retrieval=FakeRetrievalService(search_response(evidence())),
        router=ModelRouter(groq, FakeProvider("openai", "large")),
        answer_minimum_score=0.42,
    )

    result = await service.answer(make_profile(), AskRequest(question="What is the API rule?"))

    assert result.route.provider == "groq"
    assert result.citations[0].source_id == "S1"
    assert result.usage.total_tokens == 110


def test_search_and_query_routes_require_login(client: TestClient) -> None:
    assert client.post("/search", json={"question": "API rules"}).status_code == 401
    assert client.post("/query", json={"question": "API rules"}).status_code == 401
