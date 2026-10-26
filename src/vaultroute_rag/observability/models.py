import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from vaultroute_rag.database.base import Base, utc_now


def new_id() -> str:
    return str(uuid.uuid4())


class QueryEvent(Base):
    __tablename__ = "query_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('cache_hit', 'generated', 'refused', 'failed')",
            name="ck_query_event_outcome",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    cache_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    cache_similarity: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str | None] = mapped_column(String(50))
    model: Mapped[str | None] = mapped_column(String(160))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    estimated_cost_usd: Mapped[Decimal] = mapped_column(
        Numeric(14, 8), nullable=False, default=Decimal("0")
    )
    cache_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    retrieval_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    generation_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    total_ms: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    candidates_considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    citation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retrieval_score: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    conflict_detected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    automatic_quality_score: Mapped[float | None] = mapped_column(Float)
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False, index=True
    )


class AnswerFeedback(Base):
    __tablename__ = "answer_feedback"
    __table_args__ = (
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_answer_feedback_rating"),
        UniqueConstraint("query_event_id", "user_id", name="uq_feedback_query_user"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    company_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    query_event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("query_events.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    issue_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
