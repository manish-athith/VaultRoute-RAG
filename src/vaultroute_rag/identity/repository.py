from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from vaultroute_rag.identity.models import Company, User
from vaultroute_rag.identity.schemas import UserIdentity


class IdentityRepository:
    """Read current user identity and access assignments from PostgreSQL."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_login(self, company_slug: str, email: str) -> tuple[UserIdentity, str] | None:
        statement = (
            select(User)
            .join(User.company)
            .where(Company.slug == company_slug.lower(), User.email == email.lower())
            .options(
                selectinload(User.company),
                selectinload(User.roles),
                selectinload(User.departments),
            )
        )
        user = (await self._session.scalars(statement)).one_or_none()
        if user is None:
            return None
        return self._to_identity(user), user.password_hash

    async def get_by_id(self, user_id: str) -> UserIdentity | None:
        statement = (
            select(User)
            .where(User.id == user_id)
            .options(
                selectinload(User.company),
                selectinload(User.roles),
                selectinload(User.departments),
            )
        )
        user = (await self._session.scalars(statement)).one_or_none()
        return self._to_identity(user) if user else None

    @staticmethod
    def _to_identity(user: User) -> UserIdentity:
        active_roles = tuple(sorted(role.code for role in user.roles if role.is_active))
        active_departments = tuple(
            sorted(department.code for department in user.departments if department.is_active)
        )
        return UserIdentity(
            user_id=user.id,
            company_id=user.company_id,
            company_slug=user.company.slug,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active and user.company.is_active,
            token_version=user.token_version,
            role_codes=active_roles,
            department_codes=active_departments,
            has_global_access=any(role.has_global_access and role.is_active for role in user.roles),
        )
