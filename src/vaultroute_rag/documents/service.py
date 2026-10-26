import hashlib
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError

from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.authorization.evaluator import is_authorized
from vaultroute_rag.documents.chunker import OverlappingWordChunker
from vaultroute_rag.documents.embeddings import EmbeddingProvider
from vaultroute_rag.documents.extractor import DocumentTextExtractor
from vaultroute_rag.documents.models import Document
from vaultroute_rag.documents.repository import DocumentRepository
from vaultroute_rag.documents.schemas import DocumentAccessInput, DocumentResponse
from vaultroute_rag.documents.vector_store import QdrantChunkStore

DOCUMENT_MANAGER_ROLES = frozenset(
    {
        "director",
        "cto",
        "engineering_manager",
        "product_manager",
        "hr_manager",
        "senior_designer",
        "business_manager",
    }
)
logger = logging.getLogger(__name__)


class DocumentIngestionError(ValueError):
    """Safe document-ingestion error for API clients."""


class DocumentPermissionError(PermissionError):
    """Raised when a user cannot create the requested document scope."""


class DuplicateDocumentError(DocumentIngestionError):
    """Raised when the same source bytes already exist for the company."""


class DocumentIndexingError(DocumentIngestionError):
    """Raised when an infrastructure failure prevents vector indexing."""


class DocumentService:
    def __init__(
        self,
        repository: DocumentRepository,
        extractor: DocumentTextExtractor,
        chunker: OverlappingWordChunker,
        embeddings: EmbeddingProvider,
        chunk_store: QdrantChunkStore,
        max_upload_bytes: int,
    ) -> None:
        self._repository = repository
        self._extractor = extractor
        self._chunker = chunker
        self._embeddings = embeddings
        self._chunk_store = chunk_store
        self._max_upload_bytes = max_upload_bytes

    @property
    def max_upload_bytes(self) -> int:
        return self._max_upload_bytes

    async def ingest(
        self,
        *,
        profile: AccessProfile,
        filename: str,
        content: bytes,
        access: DocumentAccessInput,
        title: str | None = None,
    ) -> DocumentResponse:
        self._authorize_ingestion(profile, access)
        if len(content) > self._max_upload_bytes:
            raise DocumentIngestionError(
                f"Document exceeds the {self._max_upload_bytes // (1024 * 1024)} MB limit"
            )

        extracted = self._extractor.extract(filename, content)
        chunks = self._chunker.split(extracted.text)
        if not chunks:
            raise DocumentIngestionError("Document produced no indexable chunks")

        checksum = hashlib.sha256(content).hexdigest()
        if await self._repository.find_duplicate(profile.company_id, checksum):
            raise DuplicateDocumentError("This document has already been uploaded")

        resolved_access = await self._repository.resolve_access(profile.company_id, access)
        clean_title = (title or Path(extracted.filename).stem).strip()
        if not clean_title or len(clean_title) > 240:
            raise DocumentIngestionError("Document title must contain 1 to 240 characters")

        document = await self._repository.create(
            company_id=profile.company_id,
            uploaded_by_user_id=profile.user_id,
            title=clean_title,
            source_filename=extracted.filename,
            media_type=extracted.media_type,
            checksum=checksum,
            classification=access.classification.value,
            is_company_wide=access.is_company_wide,
            text_length=len(extracted.text),
            access=resolved_access,
        )
        try:
            await self._repository.session.commit()
        except IntegrityError as exc:
            await self._repository.session.rollback()
            raise DuplicateDocumentError("This document has already been uploaded") from exc

        document_id = document.id
        allowed_user_ids = [user.id for user in resolved_access.allowed_users]
        denied_user_ids = [user.id for user in resolved_access.denied_users]
        department_codes = [item.code for item in resolved_access.departments]
        role_codes = [item.code for item in resolved_access.roles]
        access_principals = [
            *(f"department:{code}" for code in department_codes),
            *(f"role:{code}" for code in role_codes),
            *(f"user:{user_id}" for user_id in allowed_user_ids),
        ]
        if access.is_company_wide:
            access_principals.append(f"company:{profile.company_id}")

        try:
            vectors = await self._embeddings.embed_documents([chunk.text for chunk in chunks])
            await self._chunk_store.index_document(
                document_id=document.id,
                version=document.version,
                chunks=chunks,
                vectors=vectors,
                payload={
                    "company_id": profile.company_id,
                    "title": document.title,
                    "source_filename": document.source_filename,
                    "checksum": document.checksum,
                    "classification": document.classification,
                    "is_company_wide": document.is_company_wide,
                    "department_codes": department_codes,
                    "role_codes": role_codes,
                    "allowed_user_ids": allowed_user_ids,
                    "denied_user_ids": denied_user_ids,
                    "access_principals": access_principals,
                },
            )
            document.status = "indexed"
            document.chunk_count = len(chunks)
            document.embedding_model = self._embeddings.model_name
            document.indexed_at = datetime.now(UTC)
            document.error_message = None
            await self._repository.session.commit()
        except Exception as exc:
            await self._repository.session.rollback()
            try:
                await self._chunk_store.delete_document(document_id)
            except Exception:
                logger.exception(
                    "document_vector_cleanup_failed", extra={"document_id": document_id}
                )
            failed_document = await self._repository.session.get(Document, document_id)
            if failed_document is None:
                raise DocumentIndexingError("Document indexing failed") from exc
            failed_document.status = "failed"
            failed_document.error_message = str(exc)[:1000]
            await self._repository.session.commit()
            raise DocumentIndexingError("Document indexing failed") from exc

        return self._repository.to_response(document)

    async def list_visible(self, profile: AccessProfile) -> list[DocumentResponse]:
        documents = await self._repository.list_for_company(profile.company_id)
        return [
            self._repository.to_response(document)
            for document in documents
            if is_authorized(profile, self._repository.access_rule(document))
        ]

    @staticmethod
    def _authorize_ingestion(profile: AccessProfile, access: DocumentAccessInput) -> None:
        if not profile.is_active:
            raise DocumentPermissionError("Active user required")
        if profile.has_global_access:
            return
        if not set(profile.roles).intersection(DOCUMENT_MANAGER_ROLES):
            raise DocumentPermissionError("Your role cannot upload documents")
        if access.is_company_wide:
            raise DocumentPermissionError(
                "Only global administrators can create company-wide access"
            )
        if access.role_codes or access.allowed_user_emails or access.denied_user_emails:
            raise DocumentPermissionError(
                "Only global administrators can assign role or user-specific access"
            )
        if not set(access.department_codes).issubset(profile.departments):
            raise DocumentPermissionError("You can upload only to your own departments")
