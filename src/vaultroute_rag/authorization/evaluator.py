from pydantic import BaseModel, ConfigDict

from vaultroute_rag.authorization.access_profile import AccessProfile


class AccessRule(BaseModel):
    """Reusable authorization rule for a future document or resource."""

    model_config = ConfigDict(frozen=True)

    company_id: str
    is_company_wide: bool = False
    allowed_roles: frozenset[str] = frozenset()
    allowed_departments: frozenset[str] = frozenset()
    allowed_user_ids: frozenset[str] = frozenset()
    denied_user_ids: frozenset[str] = frozenset()


def is_authorized(profile: AccessProfile, rule: AccessRule) -> bool:
    """Apply explicit deny, global, user, role, then department access."""

    if not profile.is_active or profile.company_id != rule.company_id:
        return False
    if profile.user_id in rule.denied_user_ids:
        return False
    if profile.has_global_access:
        return True
    if profile.user_id in rule.allowed_user_ids:
        return True
    if rule.is_company_wide:
        return True
    if set(profile.roles).intersection(rule.allowed_roles):
        return True
    return bool(set(profile.departments).intersection(rule.allowed_departments))
