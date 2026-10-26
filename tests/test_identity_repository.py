import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from vaultroute_rag.core.config import Settings
from vaultroute_rag.core.security import PasswordService
from vaultroute_rag.database.base import Base
from vaultroute_rag.database.session import Database
from vaultroute_rag.identity.models import Company, Department, Role, User
from vaultroute_rag.identity.repository import IdentityRepository


@pytest.mark.asyncio
async def test_repository_returns_current_roles_and_departments() -> None:
    database = Database(Settings(database_url="sqlite+aiosqlite:///:memory:"))
    try:
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with database.session() as session:
            await create_user(session)

        async with database.session() as session:
            result = await IdentityRepository(session).get_by_login(
                "acme", "priya@acme.example.com"
            )

        assert result is not None
        identity, password_hash = result
        assert identity.role_codes == ("junior_developer",)
        assert identity.department_codes == ("engineering",)
        assert PasswordService().verify("ChangeMe123!", password_hash)
    finally:
        await database.close()


async def create_user(session: AsyncSession) -> None:
    company = Company(slug="acme", name="Acme Corporation")
    department = Department(code="engineering", name="Engineering", company=company)
    role = Role(code="junior_developer", name="Junior Developer", company=company)
    user = User(
        company=company,
        email="priya@acme.example.com",
        full_name="Priya Junior",
        password_hash=PasswordService().hash("ChangeMe123!"),
        departments=[department],
        roles=[role],
    )
    session.add(user)
    await session.commit()
