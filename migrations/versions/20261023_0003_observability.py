"""Create query audit, performance, cost, and feedback tables.

Revision ID: 20261023_0003
Revises: 20261023_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261023_0003"
down_revision: str | None = "20261023_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "query_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("question_hash", sa.String(length=64), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("cache_hit", sa.Boolean(), nullable=False),
        sa.Column("cache_similarity", sa.Float(), nullable=True),
        sa.Column("provider", sa.String(length=50), nullable=True),
        sa.Column("model", sa.String(length=160), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("estimated_cost_usd", sa.Numeric(14, 8), nullable=False),
        sa.Column("cache_ms", sa.Float(), nullable=False),
        sa.Column("retrieval_ms", sa.Float(), nullable=False),
        sa.Column("generation_ms", sa.Float(), nullable=False),
        sa.Column("total_ms", sa.Float(), nullable=False),
        sa.Column("candidates_considered", sa.Integer(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("citation_count", sa.Integer(), nullable=False),
        sa.Column("max_retrieval_score", sa.Float(), nullable=False),
        sa.Column("conflict_detected", sa.Boolean(), nullable=False),
        sa.Column("automatic_quality_score", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('cache_hit', 'generated', 'refused', 'failed')",
            name="ck_query_event_outcome",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_query_events_company_id", "query_events", ["company_id"])
    op.create_index("ix_query_events_user_id", "query_events", ["user_id"])
    op.create_index("ix_query_events_request_id", "query_events", ["request_id"])
    op.create_index("ix_query_events_outcome", "query_events", ["outcome"])
    op.create_index("ix_query_events_created_at", "query_events", ["created_at"])

    op.create_table(
        "answer_feedback",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("query_event_id", sa.String(length=36), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("issue_codes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_answer_feedback_rating"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["query_event_id"], ["query_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_event_id", "user_id", name="uq_feedback_query_user"),
    )
    op.create_index("ix_answer_feedback_company_id", "answer_feedback", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_answer_feedback_company_id", table_name="answer_feedback")
    op.drop_table("answer_feedback")
    op.drop_index("ix_query_events_created_at", table_name="query_events")
    op.drop_index("ix_query_events_outcome", table_name="query_events")
    op.drop_index("ix_query_events_request_id", table_name="query_events")
    op.drop_index("ix_query_events_user_id", table_name="query_events")
    op.drop_index("ix_query_events_company_id", table_name="query_events")
    op.drop_table("query_events")
