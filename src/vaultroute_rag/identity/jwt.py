import uuid
from datetime import UTC, datetime, timedelta

import jwt
from pydantic import BaseModel, ConfigDict

from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.core.config import Settings


class TokenValidationError(ValueError):
    """Raised when a JWT cannot be trusted."""


class TokenClaims(BaseModel):
    model_config = ConfigDict(frozen=True)

    sub: str
    company_id: str
    company_slug: str
    email: str
    roles: tuple[str, ...]
    departments: tuple[str, ...]
    global_access: bool
    token_version: int
    jti: str
    iat: int
    exp: int
    iss: str
    aud: str


class JwtService:
    def __init__(self, settings: Settings) -> None:
        self._secret = settings.jwt_secret_key
        self._algorithm = settings.jwt_algorithm
        self._issuer = settings.jwt_issuer
        self._audience = settings.jwt_audience
        self.access_token_seconds = settings.jwt_access_token_minutes * 60

    def create_access_token(self, profile: AccessProfile) -> str:
        issued_at = datetime.now(UTC)
        expires_at = issued_at + timedelta(seconds=self.access_token_seconds)
        payload = {
            "sub": profile.user_id,
            "company_id": profile.company_id,
            "company_slug": profile.company_slug,
            "email": profile.email,
            "roles": list(profile.roles),
            "departments": list(profile.departments),
            "global_access": profile.has_global_access,
            "token_version": profile.token_version,
            "jti": str(uuid.uuid4()),
            "iat": issued_at,
            "exp": expires_at,
            "iss": self._issuer,
            "aud": self._audience,
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_access_token(self, token: str) -> TokenClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["sub", "exp", "iat", "iss", "aud", "jti"]},
            )
            return TokenClaims.model_validate(payload)
        except (jwt.InvalidTokenError, ValueError) as exc:
            raise TokenValidationError("Invalid or expired access token") from exc
