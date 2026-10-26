from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vaultroute_rag.authorization.evaluator import AccessRule
from vaultroute_rag.documents.models import Document, DocumentUserPermission
from vaultroute_rag.documents.schemas import DocumentAccessInput, DocumentResponse
from vaultroute_rag.identity.models import Department, Role, User


class DocumentMetadataError(ValueError):
    """Raised when document permission metadata refers to unknown identities."""


@dataclass(frozen=True)
class ResolvedDocumentAccess:
    departments: tuple[Department, ...]
    roles: tuple[Role, ...]
    allowed_users: tuple[User, ...]
    denied_users: tuple[User, ...]


class DocumentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_duplicate(self, company_id: str, checksum: str) -> Document | None:
        return await self.session.scalar(
            select(Document).where(Document.company_id == company_id, Document.checksum == checksum)
        )

    async def resolve_access(
        self, company_id: str, access: DocumentAccessInput
    ) -> ResolvedDocumentAccess:
        departments = await self._departments(company_id, access.department_codes)
        roles = await self._roles(company_id, access.role_codes)
        all_emails = tuple(sorted({*access.allowed_user_emails, *access.denied_user_emails}))
        users = await self._users(company_id, all_emails)

        self._require_all(
            "department", access.department_codes, {item.code for item in departments}
        )
        self._require_all("role", access.role_codes, {item.code for item in roles})
        self._require_all("user", all_emails, {item.email for item in users})

        users_by_email = {user.email: user for user in users}
        return ResolvedDocumentAccess(
            departments=tuple(departments),
            roles=tuple(roles),
            allowed_users=tuple(users_by_email[email] for email in access.allowed_user_emails),
            denied_users=tuple(users_by_email[email] for email in access.denied_user_emails),
        )

    async def create(
        self,
        *,
        company_id: str,
        uploaded_by_user_id: str,
        title: str,
        source_filename: str,
        media_type: str,
        checksum: str,
        classification: str,
        is_company_wide: bool,
        text_length: int,
        access: ResolvedDocumentAccess,
    ) -> Document:
        document = Document(
            company_id=company_id,
            uploaded_by_user_id=uploaded_by_user_id,
            title=title,
            source_filename=source_filename,
            media_type=media_type,
            checksum=checksum,
            classification=classification,
            status="processing",
            is_company_wide=is_company_wide,
            text_length=text_length,
            departments=list(access.departments),
            roles=list(access.roles),
            user_permissions=[
                *(
                    DocumentUserPermission(user=user, effect="allow")
                    for user in access.allowed_users
                ),
                *(DocumentUserPermission(user=user, effect="deny") for user in access.denied_users),
            ],
        )
        self.session.add(document)
        await self.session.flush()
        return document

    async def list_for_company(self, company_id: str) -> list[Document]:
        statement = (
            select(Document)
            .where(Document.company_id == company_id)
            .options(
                selectinload(Document.departments),
                selectinload(Document.roles),
                selectinload(Document.user_permissions).selectinload(DocumentUserPermission.user),
            )
            .order_by(Document.created_at.desc())
        )
        return list((await self.session.scalars(statement)).unique().all())

    async def get_by_ids(self, company_id: str, document_ids: set[str]) -> list[Document]:
        if not document_ids:
            return []
        statement = (
            select(Document)
            .where(Document.company_id == company_id, Document.id.in_(document_ids))
            .options(
                selectinload(Document.departments),
                selectinload(Document.roles),
                selectinload(Document.user_permissions).selectinload(DocumentUserPermission.user),
            )
        )
        return list((await self.session.scalars(statement)).unique().all())

    @staticmethod
    def access_rule(document: Document) -> AccessRule:
        return AccessRule(
            company_id=document.company_id,
            is_company_wide=document.is_company_wide,
            allowed_roles=frozenset(role.code for role in document.roles),
            allowed_departments=frozenset(department.code for department in document.departments),
            allowed_user_ids=frozenset(
                item.user_id for item in document.user_permissions if item.effect == "allow"
            ),
            denied_user_ids=frozenset(
                item.user_id for item in document.user_permissions if item.effect == "deny"
            ),
        )

    @staticmethod
    def to_response(document: Document) -> DocumentResponse:
        return DocumentResponse(
            id=document.id,
            title=document.title,
            source_filename=document.source_filename,
            media_type=document.media_type,
            classification=document.classification,
            status=document.status,
            version=document.version,
            is_company_wide=document.is_company_wide,
            departments=tuple(sorted(item.code for item in document.departments)),
            roles=tuple(sorted(item.code for item in document.roles)),
            allowed_users=tuple(
                sorted(
                    item.user.email for item in document.user_permissions if item.effect == "allow"
                )
            ),
            denied_users=tuple(
                sorted(
                    item.user.email for item in document.user_permissions if item.effect == "deny"
                )
            ),
            text_length=document.text_length,
            chunk_count=document.chunk_count,
            embedding_model=document.embedding_model,
            created_at=document.created_at,
            indexed_at=document.indexed_at,
        )

    async def _departments(self, company_id: str, codes: tuple[str, ...]) -> list[Department]:
        if not codes:
            return []
        return list(
            (
                await self.session.scalars(
                    select(Department).where(
                        Department.company_id == company_id,
                        Department.code.in_(codes),
                        Department.is_active.is_(True),
                    )
                )
            ).all()
        )

    async def _roles(self, company_id: str, codes: tuple[str, ...]) -> list[Role]:
        if not codes:
            return []
        return list(
            (
                await self.session.scalars(
                    select(Role).where(
                        Role.company_id == company_id,
                        Role.code.in_(codes),
                        Role.is_active.is_(True),
                    )
                )
            ).all()
        )

    async def _users(self, company_id: str, emails: tuple[str, ...]) -> list[User]:
        if not emails:
            return []
        return list(
            (
                await self.session.scalars(
                    select(User).where(
                        User.company_id == company_id,
                        User.email.in_(emails),
                        User.is_active.is_(True),
                    )
                )
            ).all()
        )

    @staticmethod
    def _require_all(kind: str, requested: tuple[str, ...], found: set[str]) -> None:
        missing = sorted(set(requested).difference(found))
        if missing:
            raise DocumentMetadataError(f"Unknown or inactive {kind}: {', '.join(missing)}")
