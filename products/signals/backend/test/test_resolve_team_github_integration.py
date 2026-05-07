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


def _create_team_integration(team: Team, *, integration_id: str = "team-1") -> Integration:
    return Integration.objects.create(
        team=team,
        kind="github",
        integration_id=integration_id,
        config={"installation_id": integration_id},
        sensitive_config={},
    )


def _create_user_integration(user: User, *, integration_id: str = "user-1") -> UserIntegration:
    return UserIntegration.objects.create(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id=integration_id,
        config={"installation_id": integration_id},
        sensitive_config={},
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
def test_picks_first_user_integration_by_id(organization, team):
    first_user = _create_user("first@example.com", organization)
    second_user = _create_user("second@example.com", organization)
    first_user_int = _create_user_integration(first_user, integration_id="first")
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
