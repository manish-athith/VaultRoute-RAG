import pytest

from vaultroute_rag.core.config import Settings
from vaultroute_rag.core.security import PasswordService
from vaultroute_rag.identity.jwt import JwtService
from vaultroute_rag.identity.schemas import LoginRequest, UserIdentity
from vaultroute_rag.identity.service import AuthenticationError, IdentityService


class FakeIdentityRepository:
    def __init__(self, identity: UserIdentity, password_hash: str) -> None:
        self.identity = identity
        self.password_hash = password_hash

    async def get_by_login(self, company_slug: str, email: str) -> tuple[UserIdentity, str] | None:
        if company_slug == self.identity.company_slug and email == str(self.identity.email):
            return self.identity, self.password_hash
        return None

    async def get_by_id(self, user_id: str) -> UserIdentity | None:
        return self.identity if user_id == self.identity.user_id else None


def make_identity() -> UserIdentity:
    return UserIdentity(
        user_id="user-1",
        company_id="company-1",
        company_slug="acme",
        email="priya@acme.example.com",
        full_name="Priya Junior",
        is_active=True,
        token_version=1,
        role_codes=("junior_developer",),
        department_codes=("engineering",),
    )


def make_service(repository: FakeIdentityRepository) -> IdentityService:
    settings = Settings(
        jwt_secret_key="test-secret-that-is-long-enough-for-tests",
        jwt_issuer="test-issuer",
        jwt_audience="test-audience",
    )
    return IdentityService(repository, PasswordService(), JwtService(settings))


@pytest.mark.asyncio
async def test_login_returns_token_and_server_built_profile() -> None:
    passwords = PasswordService()
    repository = FakeIdentityRepository(make_identity(), passwords.hash("ChangeMe123!"))

    result = await make_service(repository).login(
        LoginRequest(email="priya@acme.example.com", password="ChangeMe123!")
    )

    assert result.access_token
    assert result.user.roles == ("junior_developer",)
    assert result.user.departments == ("engineering",)


@pytest.mark.asyncio
async def test_login_does_not_reveal_which_credential_failed() -> None:
    passwords = PasswordService()
    repository = FakeIdentityRepository(make_identity(), passwords.hash("ChangeMe123!"))

    with pytest.raises(AuthenticationError, match="Invalid company, email, or password"):
        await make_service(repository).login(
            LoginRequest(email="priya@acme.example.com", password="WrongPassword1!")
        )


@pytest.mark.asyncio
async def test_token_uses_fresh_database_permissions() -> None:
    passwords = PasswordService()
    repository = FakeIdentityRepository(make_identity(), passwords.hash("ChangeMe123!"))
    service = make_service(repository)
    login = await service.login(
        LoginRequest(email="priya@acme.example.com", password="ChangeMe123!")
    )

    repository.identity = repository.identity.model_copy(
        update={
            "role_codes": ("product_manager",),
            "department_codes": ("engineering", "design", "business"),
        }
    )
    current = await service.authenticate_token(login.access_token)

    assert current.roles == ("product_manager",)
    assert current.departments == ("business", "design", "engineering")


@pytest.mark.asyncio
async def test_token_version_revokes_existing_tokens() -> None:
    passwords = PasswordService()
    repository = FakeIdentityRepository(make_identity(), passwords.hash("ChangeMe123!"))
    service = make_service(repository)
    login = await service.login(
        LoginRequest(email="priya@acme.example.com", password="ChangeMe123!")
    )

    repository.identity = repository.identity.model_copy(update={"token_version": 2})

    with pytest.raises(AuthenticationError, match="no longer valid"):
        await service.authenticate_token(login.access_token)
