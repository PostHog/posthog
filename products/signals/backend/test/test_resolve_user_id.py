import pytest

from posthog.models import Organization, Team, User
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership

from products.signals.backend.temporal.agentic import resolve_user_id_for_team


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-resolve-user-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-resolve-user-team")


def _create_user(email: str, organization: Organization, *, is_active: bool = True) -> User:
    user = User.objects.create(email=email, is_active=is_active)
    OrganizationMembership.objects.create(user=user, organization=organization)
    return user


def _create_github_integration(team: Team, created_by: User | None = None) -> Integration:
    return Integration.objects.create(
        team=team,
        kind="github",
        config={"installation_id": "12345"},
        sensitive_config={},
        created_by=created_by,
    )


@pytest.mark.django_db
def test_returns_integration_creator_when_active(organization, team):
    first_user = _create_user("first@example.com", organization)
    creator = _create_user("creator@example.com", organization)
    _create_github_integration(team, created_by=creator)

    result = resolve_user_id_for_team(team.id)

    assert result == creator.id
    assert result != first_user.id


@pytest.mark.django_db
def test_falls_back_to_first_active_member_when_creator_inactive(organization, team):
    first_user = _create_user("first@example.com", organization)
    creator = _create_user("creator@example.com", organization, is_active=False)
    _create_github_integration(team, created_by=creator)

    result = resolve_user_id_for_team(team.id)

    assert result == first_user.id


@pytest.mark.django_db
def test_falls_back_to_first_active_member_when_creator_not_set(organization, team):
    first_user = _create_user("first@example.com", organization)
    _create_github_integration(team, created_by=None)

    result = resolve_user_id_for_team(team.id)

    assert result == first_user.id


@pytest.mark.django_db
def test_skips_inactive_members_in_fallback(organization, team):
    _create_user("inactive@example.com", organization, is_active=False)
    active_user = _create_user("active@example.com", organization)
    _create_github_integration(team, created_by=None)

    result = resolve_user_id_for_team(team.id)

    assert result == active_user.id


@pytest.mark.django_db
def test_raises_when_no_active_users(organization, team):
    _create_user("inactive@example.com", organization, is_active=False)
    _create_github_integration(team, created_by=None)

    with pytest.raises(RuntimeError, match="No active users"):
        resolve_user_id_for_team(team.id)
