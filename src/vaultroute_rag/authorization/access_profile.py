import hashlib
import json

from pydantic import BaseModel, ConfigDict

from vaultroute_rag.identity.schemas import UserIdentity

ALL_DEPARTMENTS = ("business", "design", "engineering", "founding", "hr")


class AccessProfile(BaseModel):
    """Current server-calculated permissions for an authenticated user."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    company_id: str
    company_slug: str
    email: str
    full_name: str
    is_active: bool
    roles: tuple[str, ...]
    departments: tuple[str, ...]
    scopes: tuple[str, ...]
    principal_ids: tuple[str, ...]
    has_global_access: bool
    access_scope_key: str
    token_version: int


def build_access_profile(identity: UserIdentity) -> AccessProfile:
    roles = tuple(sorted(set(identity.role_codes)))
    departments = tuple(sorted(set(identity.department_codes)))
    scopes = (
        ("company_general", *ALL_DEPARTMENTS)
        if identity.has_global_access
        else tuple(sorted({"company_general", *departments}))
    )

    scope_material = {
        "company_id": identity.company_id,
        "departments": departments,
        "global": identity.has_global_access,
        "roles": roles,
    }
    scope_hash = hashlib.sha256(
        json.dumps(scope_material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:20]

    principals = {
        f"company:{identity.company_id}",
        f"user:{identity.user_id}",
        *(f"department:{department}" for department in departments),
        *(f"role:{role}" for role in roles),
    }
    if identity.has_global_access:
        principals.add("global")

    return AccessProfile(
        user_id=identity.user_id,
        company_id=identity.company_id,
        company_slug=identity.company_slug,
        email=str(identity.email),
        full_name=identity.full_name,
        is_active=identity.is_active,
        roles=roles,
        departments=departments,
        scopes=scopes,
        principal_ids=tuple(sorted(principals)),
        has_global_access=identity.has_global_access,
        access_scope_key=f"scope:{scope_hash}",
        token_version=identity.token_version,
    )
