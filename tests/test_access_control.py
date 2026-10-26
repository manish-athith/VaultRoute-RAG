from vaultroute_rag.authorization.access_profile import ALL_DEPARTMENTS, build_access_profile
from vaultroute_rag.authorization.evaluator import AccessRule, is_authorized
from vaultroute_rag.identity.schemas import UserIdentity


def identity(
    *,
    user_id: str = "user-1",
    roles: tuple[str, ...] = ("junior_developer",),
    departments: tuple[str, ...] = ("engineering",),
    global_access: bool = False,
    active: bool = True,
) -> UserIdentity:
    return UserIdentity(
        user_id=user_id,
        company_id="company-1",
        company_slug="acme",
        email="person@acme.example.com",
        full_name="Test Person",
        is_active=active,
        token_version=1,
        role_codes=roles,
        department_codes=departments,
        has_global_access=global_access,
    )


def test_engineering_user_gets_only_engineering_scope() -> None:
    profile = build_access_profile(identity())

    assert profile.scopes == ("company_general", "engineering")
    assert "department:engineering" in profile.principal_ids
    assert "role:junior_developer" in profile.principal_ids


def test_cto_combines_founding_and_engineering() -> None:
    profile = build_access_profile(
        identity(roles=("cto",), departments=("founding", "engineering"))
    )

    assert profile.departments == ("engineering", "founding")
    assert profile.scopes == ("company_general", "engineering", "founding")


def test_global_user_gets_all_departments() -> None:
    profile = build_access_profile(
        identity(roles=("ceo",), departments=("founding",), global_access=True)
    )

    assert profile.has_global_access is True
    assert set(ALL_DEPARTMENTS).issubset(profile.scopes)


def test_scope_key_is_stable_for_the_same_permission_profile() -> None:
    first = build_access_profile(identity(user_id="user-1"))
    second = build_access_profile(identity(user_id="user-2"))

    assert first.access_scope_key == second.access_scope_key


def test_department_access_and_cross_department_denial() -> None:
    profile = build_access_profile(identity())

    engineering = AccessRule(company_id="company-1", allowed_departments=frozenset({"engineering"}))
    human_resources = AccessRule(company_id="company-1", allowed_departments=frozenset({"hr"}))

    assert is_authorized(profile, engineering) is True
    assert is_authorized(profile, human_resources) is False


def test_explicit_deny_wins_even_for_global_access() -> None:
    profile = build_access_profile(
        identity(roles=("founder",), global_access=True, user_id="founder-1")
    )
    rule = AccessRule(company_id="company-1", denied_user_ids=frozenset({"founder-1"}))

    assert is_authorized(profile, rule) is False


def test_inactive_and_other_company_users_are_denied() -> None:
    inactive = build_access_profile(identity(active=False))
    rule = AccessRule(company_id="company-1", is_company_wide=True)
    other_company_rule = AccessRule(company_id="company-2", is_company_wide=True)

    assert is_authorized(inactive, rule) is False
    assert is_authorized(build_access_profile(identity()), other_company_rule) is False
