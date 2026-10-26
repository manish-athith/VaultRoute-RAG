import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from vaultroute_rag.authorization.access_profile import build_access_profile
from vaultroute_rag.documents.chunker import OverlappingWordChunker
from vaultroute_rag.documents.extractor import DocumentExtractionError, DocumentTextExtractor
from vaultroute_rag.documents.schemas import DocumentAccessInput
from vaultroute_rag.documents.service import (
    DocumentIngestionError,
    DocumentPermissionError,
    DocumentService,
)
from vaultroute_rag.identity.schemas import UserIdentity


def profile(*, roles: tuple[str, ...], departments: tuple[str, ...], global_access: bool = False):
    return build_access_profile(
        UserIdentity(
            user_id="user-1",
            company_id="company-1",
            company_slug="acme",
            email="user@acme.example.com",
            full_name="Test User",
            is_active=True,
            token_version=1,
            role_codes=roles,
            department_codes=departments,
            has_global_access=global_access,
        )
    )


def test_chunker_preserves_configured_overlap_and_offsets() -> None:
    text = "one two three four five six seven eight nine ten eleven"
    chunks = OverlappingWordChunker(chunk_size_words=5, overlap_words=2).split(text)

    assert [chunk.text for chunk in chunks] == [
        "one two three four five",
        "four five six seven eight",
        "seven eight nine ten eleven",
    ]
    assert chunks[1].char_start == text.index("four")
    assert chunks[-1].char_end == len(text)


def test_html_extraction_discards_script_content() -> None:
    extracted = DocumentTextExtractor().extract(
        "policy.html",
        b"<h1>Leave policy</h1><script>stealSecrets()</script><p>Employees receive leave.</p>",
    )

    assert "Leave policy" in extracted.text
    assert "Employees receive leave" in extracted.text
    assert "stealSecrets" not in extracted.text


def test_extractor_rejects_disguised_or_unsupported_files() -> None:
    extractor = DocumentTextExtractor()

    with pytest.raises(DocumentExtractionError, match="allowed"):
        extractor.extract("malware.exe", b"not executable")
    with pytest.raises(DocumentExtractionError, match="content is not"):
        extractor.extract("fake.pdf", b"not a pdf")


def test_access_rules_require_an_allow_path_and_no_user_conflict() -> None:
    with pytest.raises(ValidationError, match="At least one allow rule"):
        DocumentAccessInput()
    with pytest.raises(ValidationError, match="both explicitly allowed and denied"):
        DocumentAccessInput(
            allowed_user_emails=("priya@acme.example.com",),
            denied_user_emails=("priya@acme.example.com",),
        )


def test_employee_cannot_upload_documents() -> None:
    access = DocumentAccessInput(department_codes=("engineering",))

    with pytest.raises(DocumentPermissionError, match="cannot upload"):
        DocumentService._authorize_ingestion(
            profile(roles=("junior_developer",), departments=("engineering",)), access
        )


def test_manager_can_upload_only_to_own_department() -> None:
    manager = profile(roles=("engineering_manager",), departments=("engineering",))
    DocumentService._authorize_ingestion(
        manager, DocumentAccessInput(department_codes=("engineering",))
    )

    with pytest.raises(DocumentPermissionError, match="own departments"):
        DocumentService._authorize_ingestion(manager, DocumentAccessInput(department_codes=("hr",)))


def test_global_user_can_define_cross_department_and_role_access() -> None:
    ceo = profile(roles=("ceo",), departments=("founding",), global_access=True)
    access = DocumentAccessInput(
        department_codes=("engineering", "business"),
        role_codes=("cto",),
        denied_user_emails=("priya@acme.example.com",),
    )

    DocumentService._authorize_ingestion(ceo, access)


@pytest.mark.asyncio
async def test_upload_size_is_checked_before_processing() -> None:
    service = DocumentService(
        repository=None,  # type: ignore[arg-type]
        extractor=DocumentTextExtractor(),
        chunker=OverlappingWordChunker(),
        embeddings=None,  # type: ignore[arg-type]
        chunk_store=None,  # type: ignore[arg-type]
        max_upload_bytes=5,
    )

    with pytest.raises(DocumentIngestionError, match="exceeds"):
        await service.ingest(
            profile=profile(roles=("ceo",), departments=("founding",), global_access=True),
            filename="large.txt",
            content=b"too large",
            access=DocumentAccessInput(is_company_wide=True),
        )


def test_document_routes_require_login(client: TestClient) -> None:
    assert client.get("/documents").status_code == 401
    response = client.post(
        "/documents/upload",
        data={"access_json": '{"department_codes":["engineering"]}'},
        files={"file": ("policy.md", b"policy text", "text/markdown")},
    )
    assert response.status_code == 401
