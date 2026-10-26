import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.core.logging import request_id_context
from vaultroute_rag.generation.schemas import AnswerResponse
from vaultroute_rag.observability.models import QueryEvent
from vaultroute_rag.observability.repository import ObservabilityRepository
from vaultroute_rag.observability.schemas import (
    FeedbackRequest,
    FeedbackResponse,
    MetricsSummary,
    ProviderMetric,
    QueryAuditItem,
    QueryTimings,
)

logger = logging.getLogger(__name__)
OBSERVABILITY_ROLES = frozenset({"founder", "ceo", "cto", "director"})


class ObservabilityPermissionError(PermissionError):
    pass


class FeedbackNotAllowedError(PermissionError):
    pass


class CostCalculator:
    def __init__(
        self,
        *,
        groq_input_per_million: float,
        groq_output_per_million: float,
        openai_input_per_million: float,
        openai_output_per_million: float,
    ) -> None:
        self._prices = {
            "groq": (Decimal(str(groq_input_per_million)), Decimal(str(groq_output_per_million))),
            "openai": (
                Decimal(str(openai_input_per_million)),
                Decimal(str(openai_output_per_million)),
            ),
        }

    def estimate(self, provider: str | None, input_tokens: int, output_tokens: int) -> Decimal:
        rates = self._prices.get(provider or "")
        if rates is None:
            return Decimal("0")
        cost = (Decimal(input_tokens) * rates[0] + Decimal(output_tokens) * rates[1]) / Decimal(
            1_000_000
        )
        return cost.quantize(Decimal("0.00000001"))


class QueryRecorder:
    def __init__(self, repository: ObservabilityRepository, costs: CostCalculator) -> None:
        self._repository = repository
        self._costs = costs

    async def record(
        self,
        *,
        profile: AccessProfile,
        question: str,
        outcome: str,
        timings: QueryTimings,
        response: AnswerResponse | None = None,
        error_code: str | None = None,
    ) -> str:
        usage = response.usage if response else None
        retrieval = response.retrieval if response else None
        provider = (
            response.route.provider if response and response.route.provider != "none" else None
        )
        event = QueryEvent(
            company_id=profile.company_id,
            user_id=profile.user_id,
            request_id=request_id_context.get(),
            question_hash=self._question_hash(profile.company_id, question),
            outcome=outcome,
            cache_hit=bool(response and response.cache_hit),
            cache_similarity=response.cache_similarity if response else None,
            provider=provider,
            model=response.route.model if provider and response else None,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            estimated_cost_usd=self._costs.estimate(
                provider,
                usage.input_tokens if usage else 0,
                usage.output_tokens if usage else 0,
            ),
            cache_ms=round(timings.cache_ms, 2),
            retrieval_ms=round(timings.retrieval_ms, 2),
            generation_ms=round(timings.generation_ms, 2),
            total_ms=round(timings.total_ms, 2),
            candidates_considered=retrieval.candidates_considered if retrieval else 0,
            evidence_count=len(retrieval.evidence) if retrieval else 0,
            citation_count=len(response.citations) if response else 0,
            max_retrieval_score=retrieval.max_score if retrieval else 0,
            conflict_detected=retrieval.conflict_detected if retrieval else False,
            automatic_quality_score=self._quality_score(response),
            error_code=error_code,
        )
        await self._repository.add_query_event(event)
        logger.info(
            "rag_query_audited",
            extra={
                "query_id": event.id,
                "company_id": profile.company_id,
                "user_id": profile.user_id,
                "outcome": outcome,
                "cache_hit": event.cache_hit,
                "total_ms": event.total_ms,
                "estimated_cost_usd": str(event.estimated_cost_usd),
            },
        )
        return event.id

    @staticmethod
    def _question_hash(company_id: str, question: str) -> str:
        normalized = " ".join(re.findall(r"[a-z0-9]+", question.lower()))
        return hashlib.sha256(f"{company_id}|{normalized}".encode()).hexdigest()

    @staticmethod
    def _quality_score(response: AnswerResponse | None) -> float | None:
        if response is None or response.route.provider == "none":
            return None
        retrieval = response.retrieval
        citation_factor = 1.0 if response.citations else 0.0
        conflict_factor = (
            1.0 if not retrieval.conflict_detected or len(response.citations) >= 2 else 0.5
        )
        score = (0.45 * retrieval.max_score) + (0.35 * citation_factor) + (0.20 * conflict_factor)
        return round(max(0.0, min(1.0, score)), 4)


class ObservabilityService:
    def __init__(self, repository: ObservabilityRepository) -> None:
        self._repository = repository

    async def summary(self, profile: AccessProfile, days: int) -> MetricsSummary:
        self._require_reader(profile)
        since = datetime.now(UTC) - timedelta(days=days)
        rows = await self._repository.metrics_rows(profile.company_id, since=since)
        total = len(rows)
        latencies = sorted(item.total_ms for item in rows)
        p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0
        quality = [
            item.automatic_quality_score
            for item in rows
            if item.automatic_quality_score is not None
        ]
        feedback_count, feedback_average = await self._repository.feedback_stats(
            profile.company_id, since=since
        )
        providers = tuple(
            ProviderMetric(
                provider=str(provider),
                queries=int(queries),
                tokens=int(tokens),
                estimated_cost_usd=float(cost),
                average_response_ms=round(float(avg_ms), 2),
            )
            for provider, queries, tokens, cost, avg_ms in await self._repository.provider_rows(
                profile.company_id, since=since
            )
        )
        cache_hits = sum(item.cache_hit for item in rows)
        return MetricsSummary(
            days=days,
            total_queries=total,
            generated_answers=sum(item.outcome == "generated" for item in rows),
            cache_hits=cache_hits,
            cache_hit_rate=round(cache_hits / total, 4) if total else 0,
            refusals=sum(item.outcome == "refused" for item in rows),
            failures=sum(item.outcome == "failed" for item in rows),
            average_response_ms=(
                round(sum(item.total_ms for item in rows) / total, 2) if total else 0
            ),
            p95_response_ms=round(p95, 2),
            total_tokens=sum(item.total_tokens for item in rows),
            estimated_cost_usd=round(sum(float(item.estimated_cost_usd) for item in rows), 8),
            average_automatic_quality=(round(sum(quality) / len(quality), 4) if quality else None),
            feedback_count=feedback_count,
            average_feedback_rating=(round(feedback_average, 2) if feedback_average else None),
            providers=providers,
        )

    async def audit(
        self, profile: AccessProfile, days: int, limit: int
    ) -> tuple[QueryAuditItem, ...]:
        self._require_reader(profile)
        since = datetime.now(UTC) - timedelta(days=days)
        rows = await self._repository.list_query_events(
            profile.company_id, since=since, limit=limit
        )
        return tuple(
            QueryAuditItem(
                id=item.id,
                request_id=item.request_id,
                user_id=item.user_id,
                question_hash=item.question_hash,
                outcome=item.outcome,
                cache_hit=item.cache_hit,
                provider=item.provider,
                model=item.model,
                total_tokens=item.total_tokens,
                estimated_cost_usd=float(item.estimated_cost_usd),
                total_ms=item.total_ms,
                evidence_count=item.evidence_count,
                citation_count=item.citation_count,
                max_retrieval_score=item.max_retrieval_score,
                automatic_quality_score=item.automatic_quality_score,
                error_code=item.error_code,
                created_at=item.created_at,
            )
            for item in rows
        )

    async def feedback(self, profile: AccessProfile, request: FeedbackRequest) -> FeedbackResponse:
        event = await self._repository.get_owned_query_event(
            profile.company_id, profile.user_id, request.query_id
        )
        if event is None:
            raise FeedbackNotAllowedError("Query not found for the current user")
        issue_codes = tuple(sorted(set(request.issue_codes)))
        await self._repository.upsert_feedback(
            company_id=profile.company_id,
            user_id=profile.user_id,
            query_event_id=request.query_id,
            rating=request.rating,
            issue_codes=issue_codes,
        )
        return FeedbackResponse(
            query_id=request.query_id,
            rating=request.rating,
            issue_codes=issue_codes,
        )

    @staticmethod
    def _require_reader(profile: AccessProfile) -> None:
        if profile.has_global_access or set(profile.roles).intersection(OBSERVABILITY_ROLES):
            return
        raise ObservabilityPermissionError("Metrics and audit access requires executive access")
