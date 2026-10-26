from pydantic import BaseModel

from vaultroute_rag.authorization.access_profile import AccessProfile


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AccessProfile
