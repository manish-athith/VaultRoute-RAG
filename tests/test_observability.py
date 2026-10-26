from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from vaultroute_rag.authorization.access_profile import build_access_profile
from vaultroute_rag.core.logging import request_id_context
from vaultroute_rag.generation.schemas import (
    AnswerCitation,
    AnswerResponse,
    ModelUsage,
    RouteDecision,
)
from vaultroute_rag.identity.schemas import UserIdentity
from vaultroute_rag.observability.schemas import FeedbackRequest, QueryTimings
from vaultroute_rag.observability.service import (
    CostCalculator,
    FeedbackNotAllowedError,
    ObservabilityPermissionError,
    ObservabilityService,
    QueryRecorder,
)
from vaultroute_rag.retrieval.schemas import RetrievedEvidence, SearchResponse


def profile(*, role: str = "employee", global_access: bool = False):
    return build_access_profile(
        UserIdentity(
            user_id=f"user-{role}",
            company_id="company-1",
            company_slug="acme",
            email=f"{role}@acme.example.com",
            full_name="Metrics User",
            is_active=True,
            token_version=1,
            role_codes=(role,),
            department_codes=("engineering",),
            has_global_access=global_access,
        )
    )


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
        text="API logs must exclude tokens.",
        semantic_score=0.9,
        lexical_score=1,
        final_score=0.92,
    )
    return AnswerResponse(
        question="What must API logs exclude?",
        answer="API logs must exclude tokens [S1].",
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
        route=RouteDecision(provider="groq", model="small", reason="simple"),
        usage=ModelUsage(input_tokens=1_000_000, output_tokens=1_000_000, total_tokens=2_000_000),
        retrieval=SearchResponse(
            question="What must API logs exclude?",
            evidence=(evidence,),
            candidates_considered=2,
            max_score=0.92,
            conflict_detected=False,
        ),
    )


class RecordingRepository:
    def __init__(self) -> None:
        self.event = None

    async def add_query_event(self, event):
        event.id = "query-1"
        self.event = event
        return event


@pytest.mark.asyncio
async def test_query_recorder_tracks_cost_quality_timing_without_raw_question() -> None:
    repository = RecordingRepository()
    costs = CostCalculator(
        groq_input_per_million=0.075,
        groq_output_per_million=0.30,
        openai_input_per_million=10,
        openai_output_per_million=50,
    )
    recorder = QueryRecorder(repository, costs)
    token = request_id_context.set("request-123")
    try:
        query_id = await recorder.record(
            profile=profile(),
            question="What must API logs exclude?",
            outcome="generated",
            timings=QueryTimings(cache_ms=2, retrieval_ms=8, generation_ms=20, total_ms=31),
            response=answer(),
        )
    finally:
        request_id_context.reset(token)

    event = repository.event
    assert query_id == "query-1"
    assert event.request_id == "request-123"
    assert event.question_hash != "What must API logs exclude?"
    assert len(event.question_hash) == 64
    assert event.estimated_cost_usd == Decimal("0.37500000")
    assert event.automatic_quality_score == 0.964
    assert event.total_ms == 31


def test_cost_calculator_uses_provider_specific_configurable_rates() -> None:
    costs = CostCalculator(
        groq_input_per_million=0.075,
        groq_output_per_million=0.30,
        openai_input_per_million=10,
        openai_output_per_million=50,
    )
    assert costs.estimate("groq", 1_000_000, 1_000_000) == Decimal("0.37500000")
    assert costs.estimate("openai", 1_000_000, 1_000_000) == Decimal("60.00000000")
    assert costs.estimate("unknown", 1_000_000, 1_000_000) == Decimal("0")


class MetricsRepository:
    def __init__(self) -> None:
        now = datetime.now(UTC)
        self.rows = [
            SimpleNamespace(
                outcome="generated",
                cache_hit=False,
                total_ms=100.0,
                total_tokens=100,
                estimated_cost_usd=Decimal("0.001"),
                automatic_quality_score=0.9,
                created_at=now,
            ),
            SimpleNamespace(
                outcome="cache_hit",
                cache_hit=True,
                total_ms=20.0,
                total_tokens=0,
                estimated_cost_usd=Decimal("0"),
                automatic_quality_score=0.9,
                created_at=now,
            ),
        ]
        self.company_ids = []

    async def metrics_rows(self, company_id, *, since):
        self.company_ids.append(company_id)
        return self.rows

    async def feedback_stats(self, company_id, *, since):
        self.company_ids.append(company_id)
        return 1, 4.0

    async def provider_rows(self, company_id, *, since):
        self.company_ids.append(company_id)
        return [("groq", 1, 100, Decimal("0.001"), 100.0)]


@pytest.mark.asyncio
async def test_metrics_are_company_scoped_and_executive_only() -> None:
    repository = MetricsRepository()
    service = ObservabilityService(repository)

    with pytest.raises(ObservabilityPermissionError):
        await service.summary(profile(), 30)

    result = await service.summary(profile(role="ceo", global_access=True), 30)
    assert result.total_queries == 2
    assert result.cache_hits == 1
    assert result.cache_hit_rate == 0.5
    assert result.average_response_ms == 60
    assert set(repository.company_ids) == {"company-1"}


class FeedbackRepository:
    def __init__(self, owns_event: bool) -> None:
        self.owns_event = owns_event
        self.saved = None

    async def get_owned_query_event(self, company_id, user_id, query_event_id):
        return SimpleNamespace(id=query_event_id) if self.owns_event else None

    async def upsert_feedback(self, **kwargs):
        self.saved = kwargs


@pytest.mark.asyncio
async def test_feedback_can_only_target_callers_own_company_query() -> None:
    denied = ObservabilityService(FeedbackRepository(owns_event=False))
    request = FeedbackRequest(query_id="12345678-1234-1234-1234-123456789012", rating=2)
    with pytest.raises(FeedbackNotAllowedError):
        await denied.feedback(profile(), request)

    repository = FeedbackRepository(owns_event=True)
    result = await ObservabilityService(repository).feedback(
        profile(),
        FeedbackRequest(
            query_id="12345678-1234-1234-1234-123456789012",
            rating=4,
            issue_codes=("incomplete", "incomplete"),
        ),
    )
    assert result.rating == 4
    assert result.issue_codes == ("incomplete",)
    assert repository.saved["company_id"] == "company-1"


def test_observability_routes_require_authentication(client: TestClient) -> None:
    assert client.get("/metrics/summary").status_code == 401
    assert client.get("/audit/queries").status_code == 401
    assert (
        client.post(
            "/feedback",
            json={"query_id": "12345678-1234-1234-1234-123456789012", "rating": 5},
        ).status_code
        == 401
    )
