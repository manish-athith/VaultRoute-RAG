from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from vaultroute_rag.api.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from vaultroute_rag.api.routes.auth import router as auth_router
from vaultroute_rag.api.routes.documents import router as documents_router
from vaultroute_rag.api.routes.health import router as health_router
from vaultroute_rag.api.routes.observability import router as observability_router
from vaultroute_rag.api.routes.rag import router as rag_router
from vaultroute_rag.api.routes.ui import WEB_ROOT
from vaultroute_rag.api.routes.ui import router as ui_router
from vaultroute_rag.cache.vector_store import QdrantSemanticCacheStore
from vaultroute_rag.core.config import Settings, get_settings
from vaultroute_rag.core.logging import configure_logging
from vaultroute_rag.core.security import PasswordService
from vaultroute_rag.database.session import Database
from vaultroute_rag.documents.chunker import OverlappingWordChunker
from vaultroute_rag.documents.embeddings import FastEmbedProvider
from vaultroute_rag.documents.extractor import DocumentTextExtractor
from vaultroute_rag.documents.vector_store import QdrantChunkStore
from vaultroute_rag.generation.providers import GroqChatProvider, OpenAIResponsesProvider
from vaultroute_rag.generation.router import ModelRouter
from vaultroute_rag.identity.jwt import JwtService
from vaultroute_rag.infrastructure.health import HealthService
from vaultroute_rag.infrastructure.metrics import RuntimeMetrics


def create_app(
    settings: Settings | None = None,
    health_service: HealthService | None = None,
    database: Database | None = None,
) -> FastAPI:
    """Application factory used by Uvicorn and tests."""

    resolved_settings = settings or get_settings()
    resolved_database = database or Database(resolved_settings)
    resolved_health_service = health_service or HealthService(
        resolved_settings, engine=resolved_database.engine
    )
    document_chunk_store = QdrantChunkStore(
        url=resolved_settings.qdrant_url,
        collection_name=resolved_settings.qdrant_document_collection,
        dimension=resolved_settings.embedding_dimension,
    )
    semantic_cache_store = QdrantSemanticCacheStore(
        url=resolved_settings.qdrant_url,
        collection_name=resolved_settings.qdrant_cache_collection,
        dimension=resolved_settings.embedding_dimension,
        ttl_seconds=resolved_settings.cache_ttl_seconds,
    )
    groq_key = (
        resolved_settings.groq_api_key.get_secret_value()
        if resolved_settings.groq_api_key
        else None
    )
    openai_key = (
        resolved_settings.openai_api_key.get_secret_value()
        if resolved_settings.openai_api_key
        else None
    )
    model_router = ModelRouter(
        small=GroqChatProvider(
            api_key=groq_key,
            base_url=resolved_settings.groq_base_url,
            model_name=resolved_settings.groq_model,
            timeout_seconds=resolved_settings.model_request_timeout_seconds,
            max_output_tokens=resolved_settings.model_max_output_tokens,
        ),
        large=OpenAIResponsesProvider(
            api_key=openai_key,
            base_url=resolved_settings.openai_base_url,
            model_name=resolved_settings.openai_model,
            timeout_seconds=resolved_settings.model_request_timeout_seconds,
            max_output_tokens=resolved_settings.model_max_output_tokens,
        ),
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved_settings.log_level)
        application.state.settings = resolved_settings
        application.state.database = resolved_database
        application.state.health_service = resolved_health_service
        application.state.password_service = PasswordService()
        application.state.jwt_service = JwtService(resolved_settings)
        application.state.document_extractor = DocumentTextExtractor()
        application.state.document_chunker = OverlappingWordChunker(
            chunk_size_words=resolved_settings.document_chunk_size_words,
            overlap_words=resolved_settings.document_chunk_overlap_words,
        )
        application.state.embedding_provider = FastEmbedProvider(
            model_name=resolved_settings.embedding_model_name,
            dimension=resolved_settings.embedding_dimension,
            cache_dir=resolved_settings.embedding_cache_dir,
        )
        application.state.document_chunk_store = document_chunk_store
        application.state.semantic_cache_store = semantic_cache_store
        application.state.model_router = model_router
        application.state.runtime_metrics = RuntimeMetrics()
        yield
        await semantic_cache_store.close()
        await document_chunk_store.close()
        await resolved_health_service.close()
        await resolved_database.close()

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description="Secure, permission-aware enterprise RAG.",
        lifespan=lifespan,
        docs_url="/docs" if resolved_settings.enable_api_docs else None,
        redoc_url="/redoc" if resolved_settings.enable_api_docs else None,
        openapi_url="/openapi.json" if resolved_settings.enable_api_docs else None,
    )
    application.add_middleware(
        TrustedHostMiddleware, allowed_hosts=resolved_settings.allowed_host_list
    )
    application.add_middleware(
        RateLimitMiddleware,
        default_limit=resolved_settings.rate_limit_requests_per_minute,
        login_limit=resolved_settings.rate_limit_login_per_minute,
        query_limit=resolved_settings.rate_limit_query_per_minute,
        upload_limit=resolved_settings.rate_limit_upload_per_minute,
    )
    application.add_middleware(SecurityHeadersMiddleware)
    application.add_middleware(RequestContextMiddleware)
    application.mount("/assets", StaticFiles(directory=WEB_ROOT), name="assets")
    application.include_router(ui_router)
    application.include_router(auth_router)
    application.include_router(documents_router)
    application.include_router(rag_router)
    application.include_router(observability_router)
    application.include_router(health_router)
    return application


app = create_app()
