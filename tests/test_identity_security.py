import pytest

from vaultroute_rag.authorization.access_profile import build_access_profile
from vaultroute_rag.core.config import Settings
from vaultroute_rag.core.security import PasswordService
from vaultroute_rag.identity.jwt import JwtService, TokenValidationError
from vaultroute_rag.identity.schemas import UserIdentity


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
        has_global_access=False,
    )


def jwt_service() -> JwtService:
    return JwtService(
        Settings(
            jwt_secret_key="test-secret-that-is-long-enough-for-tests",
            jwt_issuer="test-issuer",
            jwt_audience="test-audience",
            jwt_access_token_minutes=5,
        )
    )


def test_password_hash_is_not_plaintext_and_verifies() -> None:
    passwords = PasswordService()
    password_hash = passwords.hash("CorrectHorseBatteryStaple!")

    assert password_hash != "CorrectHorseBatteryStaple!"
    assert passwords.verify("CorrectHorseBatteryStaple!", password_hash) is True
    assert passwords.verify("wrong-password", password_hash) is False


def test_jwt_round_trip() -> None:
    service = jwt_service()
    profile = build_access_profile(make_identity())

    claims = service.decode_access_token(service.create_access_token(profile))

    assert claims.sub == profile.user_id
    assert claims.company_id == profile.company_id
    assert claims.roles == profile.roles


def test_tampered_jwt_is_rejected() -> None:
    service = jwt_service()
    token = service.create_access_token(build_access_profile(make_identity()))

    with pytest.raises(TokenValidationError):
        service.decode_access_token(f"{token}tampered")
