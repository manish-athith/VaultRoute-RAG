from pydantic import BaseModel, ConfigDict, EmailStr, Field


class LoginRequest(BaseModel):
    company_slug: str = Field(default="acme", min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: str
    company_id: str
    company_slug: str
    email: EmailStr
    full_name: str
    is_active: bool
    token_version: int
    role_codes: tuple[str, ...] = ()
    department_codes: tuple[str, ...] = ()
    has_global_access: bool = False
