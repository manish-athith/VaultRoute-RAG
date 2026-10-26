from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from vaultroute_rag.api.dependencies import (
    get_current_access_profile,
    get_document_service,
)
from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.documents.extractor import DocumentExtractionError
from vaultroute_rag.documents.repository import DocumentMetadataError
from vaultroute_rag.documents.schemas import DocumentAccessInput, DocumentResponse
from vaultroute_rag.documents.service import (
    DocumentIndexingError,
    DocumentIngestionError,
    DocumentPermissionError,
    DocumentService,
    DuplicateDocumentError,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    profile: Annotated[AccessProfile, Depends(get_current_access_profile)],
    service: Annotated[DocumentService, Depends(get_document_service)],
    file: Annotated[UploadFile, File(description="TXT, Markdown, HTML, PDF, or DOCX")],
    access_json: Annotated[
        str,
        Form(
            description=(
                'JSON access rules, e.g. {"department_codes":["engineering"],'
                '"classification":"internal"}'
            )
        ),
    ],
    title: Annotated[str | None, Form(max_length=240)] = None,
) -> DocumentResponse:
    try:
        access = DocumentAccessInput.model_validate_json(access_json)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=exc.errors(include_context=False),
        ) from exc

    content = await file.read(service.max_upload_bytes + 1)
    await file.close()
    try:
        return await service.ingest(
            profile=profile,
            filename=file.filename or "",
            content=content,
            access=access,
            title=title,
        )
    except DocumentPermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except DuplicateDocumentError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DocumentIndexingError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except (DocumentMetadataError, DocumentExtractionError, DocumentIngestionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("", response_model=list[DocumentResponse])
async def list_documents(
    profile: Annotated[AccessProfile, Depends(get_current_access_profile)],
    service: Annotated[DocumentService, Depends(get_document_service)],
) -> list[DocumentResponse]:
    return await service.list_visible(profile)
