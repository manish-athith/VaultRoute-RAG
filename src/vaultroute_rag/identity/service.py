from typing import Protocol

from vaultroute_rag.authorization.access_profile import AccessProfile, build_access_profile
from vaultroute_rag.core.security import PasswordService
from vaultroute_rag.identity.jwt import JwtService, TokenValidationError
from vaultroute_rag.identity.responses import TokenResponse
from vaultroute_rag.identity.schemas import LoginRequest, UserIdentity


class AuthenticationError(ValueError):
    """Safe authentication failure without revealing which check failed."""


class IdentityReader(Protocol):
    async def get_by_login(
        self, company_slug: str, email: str
    ) -> tuple[UserIdentity, str] | None: ...

    async def get_by_id(self, user_id: str) -> UserIdentity | None: ...


class IdentityService:
    def __init__(
        self,
        repository: IdentityReader,
        password_service: PasswordService,
        jwt_service: JwtService,
    ) -> None:
        self._repository = repository
        self._passwords = password_service
        self._jwt = jwt_service

    async def login(self, request: LoginRequest) -> TokenResponse:
        result = await self._repository.get_by_login(request.company_slug, str(request.email))
        if result is None:
            raise AuthenticationError("Invalid company, email, or password")

        identity, password_hash = result
        if not identity.is_active or not self._passwords.verify(request.password, password_hash):
            raise AuthenticationError("Invalid company, email, or password")

        profile = build_access_profile(identity)
        return TokenResponse(
            access_token=self._jwt.create_access_token(profile),
            expires_in=self._jwt.access_token_seconds,
            user=profile,
        )

    async def authenticate_token(self, token: str) -> AccessProfile:
        try:
            claims = self._jwt.decode_access_token(token)
        except TokenValidationError as exc:
            raise AuthenticationError(str(exc)) from exc

        identity = await self._repository.get_by_id(claims.sub)
        if (
            identity is None
            or not identity.is_active
            or identity.company_id != claims.company_id
            or identity.token_version != claims.token_version
        ):
            raise AuthenticationError("Access token is no longer valid")

        return build_access_profile(identity)
