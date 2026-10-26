from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vaultroute_rag.observability.models import AnswerFeedback, QueryEvent


class ObservabilityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def add_query_event(self, event: QueryEvent) -> QueryEvent:
        self.session.add(event)
        await self.session.commit()
        return event

    async def list_query_events(
        self, company_id: str, *, since: datetime, limit: int
    ) -> list[QueryEvent]:
        statement = (
            select(QueryEvent)
            .where(QueryEvent.company_id == company_id, QueryEvent.created_at >= since)
            .order_by(QueryEvent.created_at.desc())
            .limit(limit)
        )
        return list((await self.session.scalars(statement)).all())

    async def metrics_rows(self, company_id: str, *, since: datetime) -> list[QueryEvent]:
        statement = select(QueryEvent).where(
            QueryEvent.company_id == company_id, QueryEvent.created_at >= since
        )
        return list((await self.session.scalars(statement)).all())

    async def provider_rows(
        self, company_id: str, *, since: datetime
    ) -> list[tuple[str, int, int, float, float]]:
        statement = (
            select(
                QueryEvent.provider,
                func.count(QueryEvent.id),
                func.coalesce(func.sum(QueryEvent.total_tokens), 0),
                func.coalesce(func.sum(QueryEvent.estimated_cost_usd), 0),
                func.coalesce(func.avg(QueryEvent.total_ms), 0),
            )
            .where(
                QueryEvent.company_id == company_id,
                QueryEvent.created_at >= since,
                QueryEvent.provider.is_not(None),
            )
            .group_by(QueryEvent.provider)
            .order_by(QueryEvent.provider)
        )
        return [tuple(row) for row in (await self.session.execute(statement)).all()]

    async def feedback_stats(self, company_id: str, *, since: datetime) -> tuple[int, float | None]:
        statement = select(func.count(AnswerFeedback.id), func.avg(AnswerFeedback.rating)).where(
            AnswerFeedback.company_id == company_id, AnswerFeedback.created_at >= since
        )
        row = (await self.session.execute(statement)).one()
        return int(row[0] or 0), float(row[1]) if row[1] is not None else None

    async def get_owned_query_event(
        self, company_id: str, user_id: str, query_event_id: str
    ) -> QueryEvent | None:
        return await self.session.scalar(
            select(QueryEvent).where(
                QueryEvent.id == query_event_id,
                QueryEvent.company_id == company_id,
                QueryEvent.user_id == user_id,
            )
        )

    async def upsert_feedback(
        self,
        *,
        company_id: str,
        user_id: str,
        query_event_id: str,
        rating: int,
        issue_codes: tuple[str, ...],
    ) -> AnswerFeedback:
        feedback = await self.session.scalar(
            select(AnswerFeedback).where(
                AnswerFeedback.query_event_id == query_event_id,
                AnswerFeedback.user_id == user_id,
            )
        )
        if feedback is None:
            feedback = AnswerFeedback(
                company_id=company_id,
                user_id=user_id,
                query_event_id=query_event_id,
                rating=rating,
                issue_codes=list(issue_codes),
            )
            self.session.add(feedback)
        else:
            feedback.rating = rating
            feedback.issue_codes = list(issue_codes)
        await self.session.commit()
        return feedback
