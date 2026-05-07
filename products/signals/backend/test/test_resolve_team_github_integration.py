import datetime

import pytest

from posthog.models import Organization, Team, User
from posthog.models.integration import GitHubIntegration, Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserGitHubIntegration, UserIntegration

from products.signals.backend.report_generation.select_repo import resolve_team_github_integration


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-cascade-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-cascade-team")


def _create_user(email: str, organization: Organization, *, is_active: bool = True) -> User:
    user = User.objects.create(email=email, is_active=is_active)
    OrganizationMembership.objects.create(user=user, organization=organization)
    return user


_REPO_CACHE_ENTRY = {"full_name": "PostHog/posthog", "id": 1}


def _create_team_integration(
    team: Team,
    *,
    integration_id: str = "team-1",
    account_type: str | None = None,
    repository_cache: list[dict] | None = None,
) -> Integration:
    config: dict = {"installation_id": integration_id}
    if account_type is not None:
        config["account"] = {"type": account_type}
    return Integration.objects.create(
        team=team,
        kind="github",
        integration_id=integration_id,
        config=config,
        sensitive_config={},
        repository_cache=[_REPO_CACHE_ENTRY] if repository_cache is None else repository_cache,
    )


def _create_user_integration(
    user: User,
    *,
    integration_id: str = "user-1",
    account_type: str | None = None,
    repository_cache: list[dict] | None = None,
) -> UserIntegration:
    config: dict = {"installation_id": integration_id}
    if account_type is not None:
        config["account"] = {"type": account_type}
    return UserIntegration.objects.create(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id=integration_id,
        config=config,
        sensitive_config={},
        repository_cache=[_REPO_CACHE_ENTRY] if repository_cache is None else repository_cache,
    )


@pytest.mark.django_db
def test_returns_none_when_team_has_no_github_anywhere(team):
    assert resolve_team_github_integration(team.id) is None


@pytest.mark.django_db
def test_prefers_team_integration_over_user_integration(organization, team):
    user = _create_user("a@example.com", organization)
    _create_user_integration(user, integration_id="user-1")
    team_int = _create_team_integration(team, integration_id="team-1")

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, GitHubIntegration)
    assert resolved.integration.id == team_int.id


@pytest.mark.django_db
def test_falls_back_to_user_integration_when_no_team_integration(organization, team):
    user = _create_user("a@example.com", organization)
    user_int = _create_user_integration(user, integration_id="user-1")

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == user_int.id


@pytest.mark.django_db
def test_picks_oldest_user_integration_among_org_members(organization, team):
    first_user = _create_user("first@example.com", organization)
    second_user = _create_user("second@example.com", organization)
    first_user_int = _create_user_integration(first_user, integration_id="first")
    # Backdate `first_user_int` so it sorts first by `created_at` regardless of
    # auto_now_add resolution between the two creates.
    UserIntegration.objects.filter(pk=first_user_int.pk).update(
        created_at=first_user_int.created_at - datetime.timedelta(hours=1)
    )
    _create_user_integration(second_user, integration_id="second")

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == first_user_int.id


@pytest.mark.django_db
def test_skips_user_integration_when_owner_has_no_team_access(organization, team):
    # Owner with no organization membership = no team access via `team.all_users_with_access()`.
    outsider = User.objects.create(email="outsider@example.com")
    _create_user_integration(outsider, integration_id="outsider-int")

    assert resolve_team_github_integration(team.id) is None


@pytest.mark.django_db
def test_skips_team_integration_with_empty_repository_cache(organization, team):
    user = _create_user("a@example.com", organization)
    _create_team_integration(team, integration_id="team-empty", repository_cache=[])
    user_int = _create_user_integration(user, integration_id="user-1")

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == user_int.id


@pytest.mark.django_db
def test_skips_user_integration_with_empty_repository_cache(organization, team):
    empty_user = _create_user("empty@example.com", organization)
    populated_user = _create_user("populated@example.com", organization)
    _create_user_integration(empty_user, integration_id="user-empty", repository_cache=[])
    populated_int = _create_user_integration(populated_user, integration_id="user-populated")

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == populated_int.id


@pytest.mark.django_db
def test_returns_none_when_all_integrations_have_empty_repository_cache(organization, team):
    user = _create_user("a@example.com", organization)
    _create_team_integration(team, integration_id="team-empty", repository_cache=[])
    _create_user_integration(user, integration_id="user-empty", repository_cache=[])

    assert resolve_team_github_integration(team.id) is None


@pytest.mark.django_db
def test_prefers_org_account_over_user_account(organization, team):
    # Org accounts sort before User accounts on `config__account__type` (alphabetical).
    _create_team_integration(team, integration_id="user-acct", account_type="User")
    org_int = _create_team_integration(team, integration_id="org-acct", account_type="Organization")

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, GitHubIntegration)
    assert resolved.integration.id == org_int.id


@pytest.mark.django_db
def test_prefers_oldest_among_same_account_type(organization, team):
    older = _create_team_integration(team, integration_id="org-old", account_type="Organization")
    Integration.objects.filter(pk=older.pk).update(created_at=older.created_at - datetime.timedelta(hours=1))
    _create_team_integration(team, integration_id="org-new", account_type="Organization")

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, GitHubIntegration)
    assert resolved.integration.id == older.id
