import logging
import time
from collections.abc import Sequence
from typing import Protocol

from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.generation.grounding import (
    SYSTEM_PROMPT,
    build_user_prompt,
    validate_and_build_citations,
)
from vaultroute_rag.generation.router import ModelRouter
from vaultroute_rag.generation.schemas import (
    AnswerResponse,
    AskRequest,
    ModelUsage,
    RouteDecision,
)
from vaultroute_rag.observability.schemas import QueryTimings
from vaultroute_rag.observability.service import QueryRecorder
from vaultroute_rag.retrieval.schemas import SearchRequest
from vaultroute_rag.retrieval.service import RetrievalService

logger = logging.getLogger(__name__)


class AnswerCache(Protocol):
    async def lookup(
        self,
        *,
        profile: AccessProfile,
        question: str,
        question_vector: Sequence[float],
    ) -> AnswerResponse | None: ...

    async def store(
        self,
        *,
        profile: AccessProfile,
        question: str,
        question_vector: Sequence[float],
        response: AnswerResponse,
    ) -> bool: ...


class RagAnswerService:
    def __init__(
        self,
        retrieval: RetrievalService,
        router: ModelRouter,
        answer_minimum_score: float,
        cache: AnswerCache | None = None,
        recorder: QueryRecorder | None = None,
    ) -> None:
        self._retrieval = retrieval
        self._router = router
        self._answer_minimum_score = answer_minimum_score
        self._cache = cache
        self._recorder = recorder

    async def answer(self, profile: AccessProfile, request: AskRequest) -> AnswerResponse:
        started = time.perf_counter()
        timings = QueryTimings()
        try:
            response, outcome = await self._answer(profile, request, timings)
        except Exception as exc:
            timings.total_ms = self._elapsed_ms(started)
            await self._record(
                profile=profile,
                question=request.question,
                outcome="failed",
                timings=timings,
                error_code=type(exc).__name__,
            )
            raise

        timings.total_ms = self._elapsed_ms(started)
        query_id = await self._record(
            profile=profile,
            question=request.question,
            outcome=outcome,
            timings=timings,
            response=response,
        )
        return response.model_copy(update={"query_id": query_id})

    async def _answer(
        self, profile: AccessProfile, request: AskRequest, timings: QueryTimings
    ) -> tuple[AnswerResponse, str]:
        query_vector: Sequence[float] | None = None
        if self._cache is not None:
            cache_started = time.perf_counter()
            try:
                query_vector = await self._retrieval.embed_question(request.question)
                cached = await self._cache.lookup(
                    profile=profile,
                    question=request.question,
                    question_vector=query_vector,
                )
                if cached is not None:
                    timings.cache_ms += self._elapsed_ms(cache_started)
                    return cached, "cache_hit"
            except Exception:
                logger.warning("semantic_cache_lookup_failed", exc_info=True)
            timings.cache_ms += self._elapsed_ms(cache_started)

        search_request = SearchRequest(question=request.question, top_k=request.top_k)
        retrieval_started = time.perf_counter()
        if query_vector is None:
            retrieval = await self._retrieval.search(profile, search_request)
        else:
            retrieval = await self._retrieval.search(
                profile,
                search_request,
                query_vector=query_vector,
            )
        timings.retrieval_ms = self._elapsed_ms(retrieval_started)
        if not retrieval.evidence or retrieval.max_score < self._answer_minimum_score:
            return (
                AnswerResponse(
                    question=request.question,
                    answer=(
                        "I do not have enough authorized information in the indexed documents "
                        "to answer that question."
                    ),
                    citations=(),
                    route=RouteDecision(
                        provider="none",
                        model="none",
                        reason="retrieval evidence was missing or below the answer threshold",
                    ),
                    usage=ModelUsage(),
                    retrieval=retrieval,
                ),
                "refused",
            )

        generation_started = time.perf_counter()
        provider, decision = self._router.choose(request.question, retrieval)
        result = await provider.generate(
            SYSTEM_PROMPT,
            build_user_prompt(request.question, retrieval),
        )
        citations = validate_and_build_citations(result.text, retrieval.evidence)
        timings.generation_ms = self._elapsed_ms(generation_started)
        response = AnswerResponse(
            question=request.question,
            answer=result.text,
            citations=citations,
            route=decision.model_copy(update={"model": result.model}),
            usage=result.usage,
            retrieval=retrieval,
        )
        if self._cache is not None:
            cache_started = time.perf_counter()
            try:
                resolved_vector = (
                    query_vector
                    if query_vector is not None
                    else await self._retrieval.embed_question(request.question)
                )
                await self._cache.store(
                    profile=profile,
                    question=request.question,
                    question_vector=resolved_vector,
                    response=response,
                )
            except Exception:
                logger.warning("semantic_cache_store_failed", exc_info=True)
            timings.cache_ms += self._elapsed_ms(cache_started)
        return response, "generated"

    async def _record(
        self,
        *,
        profile: AccessProfile,
        question: str,
        outcome: str,
        timings: QueryTimings,
        response: AnswerResponse | None = None,
        error_code: str | None = None,
    ) -> str | None:
        if self._recorder is None:
            return None
        try:
            return await self._recorder.record(
                profile=profile,
                question=question,
                outcome=outcome,
                timings=timings,
                response=response,
                error_code=error_code,
            )
        except Exception:
            logger.warning("query_audit_record_failed", exc_info=True)
            return None

    @staticmethod
    def _elapsed_ms(started: float) -> float:
        return (time.perf_counter() - started) * 1000
