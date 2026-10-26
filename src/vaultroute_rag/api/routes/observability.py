from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from vaultroute_rag.api.dependencies import (
    get_current_access_profile,
    get_observability_service,
)
from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.observability.schemas import (
    FeedbackRequest,
    FeedbackResponse,
    MetricsSummary,
    QueryAuditItem,
)
from vaultroute_rag.observability.service import (
    FeedbackNotAllowedError,
    ObservabilityPermissionError,
    ObservabilityService,
)

router = APIRouter(tags=["observability"])


@router.get("/metrics/summary", response_model=MetricsSummary)
async def metrics_summary(
    profile: Annotated[AccessProfile, Depends(get_current_access_profile)],
    service: Annotated[ObservabilityService, Depends(get_observability_service)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> MetricsSummary:
    try:
        return await service.summary(profile, days)
    except ObservabilityPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.get("/audit/queries", response_model=tuple[QueryAuditItem, ...])
async def query_audit(
    profile: Annotated[AccessProfile, Depends(get_current_access_profile)],
    service: Annotated[ObservabilityService, Depends(get_observability_service)],
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> tuple[QueryAuditItem, ...]:
    try:
        return await service.audit(profile, days, limit)
    except ObservabilityPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    profile: Annotated[AccessProfile, Depends(get_current_access_profile)],
    service: Annotated[ObservabilityService, Depends(get_observability_service)],
) -> FeedbackResponse:
    try:
        return await service.feedback(profile, request)
    except FeedbackNotAllowedError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
