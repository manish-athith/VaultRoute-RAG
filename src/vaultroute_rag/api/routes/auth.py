from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from vaultroute_rag.api.dependencies import get_current_access_profile, get_identity_service
from vaultroute_rag.authorization.access_profile import AccessProfile
from vaultroute_rag.identity.responses import TokenResponse
from vaultroute_rag.identity.schemas import LoginRequest
from vaultroute_rag.identity.service import AuthenticationError, IdentityService

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> TokenResponse:
    try:
        return await service.login(payload)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


@router.get("/me", response_model=AccessProfile)
async def current_user(
    profile: Annotated[AccessProfile, Depends(get_current_access_profile)],
) -> AccessProfile:
    return profile
