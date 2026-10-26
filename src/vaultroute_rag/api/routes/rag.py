from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from vaultroute_rag.api.dependencies import (
    get_current_access_profile,
    get_rag_answer_service,
    get_retrieval_service,
)
from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.generation.grounding import UngroundedModelResponse
from vaultroute_rag.generation.providers import ModelProviderError
from vaultroute_rag.generation.router import NoModelProviderAvailable
from vaultroute_rag.generation.schemas import AnswerResponse, AskRequest
from vaultroute_rag.generation.service import RagAnswerService
from vaultroute_rag.retrieval.schemas import SearchRequest, SearchResponse
from vaultroute_rag.retrieval.service import RetrievalService

router = APIRouter(tags=["rag"])


@router.post("/search", response_model=SearchResponse)
async def search_documents(
    request: SearchRequest,
    profile: Annotated[AccessProfile, Depends(get_current_access_profile)],
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> SearchResponse:
    try:
        return await service.search(profile, request)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document retrieval is temporarily unavailable",
        ) from exc


@router.post("/query", response_model=AnswerResponse)
async def answer_question(
    request: AskRequest,
    profile: Annotated[AccessProfile, Depends(get_current_access_profile)],
    service: Annotated[RagAnswerService, Depends(get_rag_answer_service)],
) -> AnswerResponse:
    try:
        return await service.answer(profile, request)
    except NoModelProviderAvailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except (ModelProviderError, UngroundedModelResponse) as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The selected model could not produce a grounded answer",
        ) from exc
