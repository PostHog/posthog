import pytest

from posthog.models import Organization, Team, User
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserIntegration

from products.signals.backend.temporal.agentic import resolve_acting_user_id_for_team, resolve_user_id_for_team


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-resolve-user-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-resolve-user-team")


def _create_user(
    email: str,
    organization: Organization,
    *,
    is_active: bool = True,
    level: OrganizationMembership.Level = OrganizationMembership.Level.OWNER,
) -> User:
    user = User.objects.create(email=email, is_active=is_active)
    OrganizationMembership.objects.create(user=user, organization=organization, level=level)
    return user


def _create_github_integration(team: Team, created_by: User | None = None) -> Integration:
    return Integration.objects.create(
        team=team,
        kind="github",
        config={"installation_id": "12345"},
        sensitive_config={},
        created_by=created_by,
    )


def _create_user_github_integration(user: User, *, integration_id: str = "67890") -> UserIntegration:
    return UserIntegration.objects.create(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id=integration_id,
        config={"installation_id": integration_id},
        sensitive_config={},
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


@pytest.mark.django_db
def test_uses_user_integration_owner_when_no_team_integration(organization, team):
    other = _create_user("other@example.com", organization)
    user_integration_owner = _create_user("posthog-code@example.com", organization)
    _create_user_github_integration(user_integration_owner)

    result = resolve_user_id_for_team(team.id)

    assert result == user_integration_owner.id
    assert result != other.id


@pytest.mark.django_db
def test_prefers_team_integration_creator_over_user_integration_owner(organization, team):
    creator = _create_user("creator@example.com", organization)
    user_integration_owner = _create_user("posthog-code@example.com", organization)
    _create_user_github_integration(user_integration_owner)
    _create_github_integration(team, created_by=creator)

    result = resolve_user_id_for_team(team.id)

    assert result == creator.id


@pytest.mark.django_db
def test_raises_when_team_has_no_github_source_at_all(organization, team):
    # No Integration, no UserIntegration. Picking an arbitrary org member without GitHub
    # credentials would just paper over the bug; the caller has to short-circuit instead.
    _create_user("first@example.com", organization)

    with pytest.raises(RuntimeError, match="No GitHub integration"):
        resolve_user_id_for_team(team.id)


@pytest.mark.django_db
def test_acting_user_falls_back_to_active_member_without_github(organization, team):
    # The scout path has no repo to clone, so it must NOT require GitHub: a team with an active
    # org member but no integration resolves that member instead of failing. This is the fix for
    # the teams that were crashing every scheduled run on the GitHub precondition.
    member = _create_user("member@example.com", organization)

    assert resolve_acting_user_id_for_team(team.id) == member.id


@pytest.mark.django_db
def test_acting_user_returns_none_when_no_active_member(organization, team):
    # The only genuine "can't run" case — no active user to act as. Returning None (not raising)
    # is what lets the scheduled caller short-circuit to a skip instead of a bogus failed run.
    _create_user("inactive@example.com", organization, is_active=False)

    assert resolve_acting_user_id_for_team(team.id) is None


@pytest.mark.django_db
def test_acting_user_prefers_github_creator_when_present(organization, team):
    # When GitHub IS connected, keep the existing attribution: act as the integration creator,
    # not an arbitrary member — so the decoupling doesn't change behavior for set-up teams.
    _create_user("member@example.com", organization)
    creator = _create_user("creator@example.com", organization)
    _create_github_integration(team, created_by=creator)

    assert resolve_acting_user_id_for_team(team.id) == creator.id
