from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.cache.service import SemanticAnswerCache
from vaultroute_rag.documents.repository import DocumentRepository
from vaultroute_rag.documents.service import DocumentService
from vaultroute_rag.generation.service import RagAnswerService
from vaultroute_rag.identity.repository import IdentityRepository
from vaultroute_rag.identity.service import AuthenticationError, IdentityService
from vaultroute_rag.observability.repository import ObservabilityRepository
from vaultroute_rag.observability.service import (
    CostCalculator,
    ObservabilityService,
    QueryRecorder,
)
from vaultroute_rag.retrieval.service import RetrievalService

bearer_scheme = HTTPBearer(auto_error=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.database.session() as session:
        yield session


def get_identity_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> IdentityService:
    return IdentityService(
        repository=IdentityRepository(session),
        password_service=request.app.state.password_service,
        jwt_service=request.app.state.jwt_service,
    )


def get_document_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DocumentService:
    return DocumentService(
        repository=DocumentRepository(session),
        extractor=request.app.state.document_extractor,
        chunker=request.app.state.document_chunker,
        embeddings=request.app.state.embedding_provider,
        chunk_store=request.app.state.document_chunk_store,
        max_upload_bytes=request.app.state.settings.max_upload_bytes,
    )


def get_retrieval_service(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> RetrievalService:
    settings = request.app.state.settings
    return RetrievalService(
        repository=DocumentRepository(session),
        embeddings=request.app.state.embedding_provider,
        chunk_store=request.app.state.document_chunk_store,
        candidate_limit=settings.retrieval_candidate_limit,
        default_top_k=settings.retrieval_top_k,
        minimum_score=settings.retrieval_min_score,
    )


def get_semantic_answer_cache(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SemanticAnswerCache:
    settings = request.app.state.settings
    return SemanticAnswerCache(
        repository=DocumentRepository(session),
        store=request.app.state.semantic_cache_store,
        similarity_threshold=settings.cache_similarity_threshold,
        candidate_limit=settings.cache_candidate_limit,
    )


def get_query_recorder(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> QueryRecorder:
    settings = request.app.state.settings
    return QueryRecorder(
        repository=ObservabilityRepository(session),
        costs=CostCalculator(
            groq_input_per_million=settings.groq_input_cost_per_million,
            groq_output_per_million=settings.groq_output_cost_per_million,
            openai_input_per_million=settings.openai_input_cost_per_million,
            openai_output_per_million=settings.openai_output_cost_per_million,
        ),
    )


def get_observability_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ObservabilityService:
    return ObservabilityService(ObservabilityRepository(session))


def get_rag_answer_service(
    request: Request,
    retrieval: Annotated[RetrievalService, Depends(get_retrieval_service)],
    cache: Annotated[SemanticAnswerCache, Depends(get_semantic_answer_cache)],
    recorder: Annotated[QueryRecorder, Depends(get_query_recorder)],
) -> RagAnswerService:
    return RagAnswerService(
        retrieval=retrieval,
        router=request.app.state.model_router,
        answer_minimum_score=request.app.state.settings.answer_min_score,
        cache=cache,
        recorder=recorder,
    )


async def get_current_access_profile(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> AccessProfile:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer access token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        return await service.authenticate_token(credentials.credentials)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
