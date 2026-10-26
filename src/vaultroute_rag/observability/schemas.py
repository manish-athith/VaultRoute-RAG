from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class QueryTimings(BaseModel):
    cache_ms: float = 0
    retrieval_ms: float = 0
    generation_ms: float = 0
    total_ms: float = 0


class QueryAuditItem(BaseModel):
    id: str
    request_id: str
    user_id: str | None
    question_hash: str
    outcome: str
    cache_hit: bool
    provider: str | None
    model: str | None
    total_tokens: int
    estimated_cost_usd: float
    total_ms: float
    evidence_count: int
    citation_count: int
    max_retrieval_score: float
    automatic_quality_score: float | None
    error_code: str | None
    created_at: datetime


class ProviderMetric(BaseModel):
    provider: str
    queries: int
    tokens: int
    estimated_cost_usd: float
    average_response_ms: float


class MetricsSummary(BaseModel):
    days: int
    total_queries: int
    generated_answers: int
    cache_hits: int
    cache_hit_rate: float
    refusals: int
    failures: int
    average_response_ms: float
    p95_response_ms: float
    total_tokens: int
    estimated_cost_usd: float
    average_automatic_quality: float | None
    feedback_count: int
    average_feedback_rating: float | None
    providers: tuple[ProviderMetric, ...]


FeedbackIssue = Literal["inaccurate", "incomplete", "wrong_source", "outdated", "access_issue"]


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    query_id: str = Field(min_length=36, max_length=36)
    rating: int = Field(ge=1, le=5)
    issue_codes: tuple[FeedbackIssue, ...] = ()


class FeedbackResponse(BaseModel):
    query_id: str
    rating: int
    issue_codes: tuple[str, ...]
    recorded: bool = True
