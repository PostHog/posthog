import datetime

import pytest

from django.utils import timezone

from posthog.models import Organization, Team, User
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, GitHubIntegration, Integration
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


_REPO_CACHE_ENTRY = {"full_name": "PostHog/posthog", "id": 1}


def _create_team_integration(
    team: Team,
    *,
    integration_id: str = "team-1",
    account_type: str | None = None,
    repository_cache: list[dict] | None = None,
    cache_synced: bool = True,
) -> Integration:
    config: dict = {"installation_id": integration_id}
    if account_type is not None:
        config["account"] = {"type": account_type}
    integration = Integration.objects.create(
        team=team,
        kind="github",
        integration_id=integration_id,
        config=config,
        sensitive_config={},
        repository_cache=[_REPO_CACHE_ENTRY] if repository_cache is None else repository_cache,
    )
    if cache_synced:
        Integration.objects.filter(pk=integration.pk).update(repository_cache_updated_at=timezone.now())
        integration.refresh_from_db()
    return integration


def _create_user_integration(
    user: User,
    *,
    integration_id: str = "user-1",
    account_type: str | None = None,
    repository_cache: list[dict] | None = None,
    cache_synced: bool = True,
) -> UserIntegration:
    config: dict = {"installation_id": integration_id}
    if account_type is not None:
        config["account"] = {"type": account_type}
    integration = UserIntegration.objects.create(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id=integration_id,
        config=config,
        sensitive_config={},
        repository_cache=[_REPO_CACHE_ENTRY] if repository_cache is None else repository_cache,
    )
    if cache_synced:
        UserIntegration.objects.filter(pk=integration.pk).update(repository_cache_updated_at=timezone.now())
        integration.refresh_from_db()
    return integration


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
def test_picks_newest_user_integration_among_owners(organization, team):
    first_owner = _create_user("first@example.com", organization)
    second_owner = _create_user("second@example.com", organization)
    older_int = _create_user_integration(first_owner, integration_id="older")
    # Backdate `older_int` so the other one is unambiguously newer regardless of
    # auto_now_add resolution between the two creates.
    UserIntegration.objects.filter(pk=older_int.pk).update(
        created_at=older_int.created_at - datetime.timedelta(hours=1)
    )
    newer_int = _create_user_integration(second_owner, integration_id="newer")

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == newer_int.id


@pytest.mark.django_db
def test_ignores_non_owner_member_personal_github(organization, team):
    # The bug: an org member's personal GitHub leaked into another team's report. A plain
    # member (not an owner) must never have their personal repos borrowed for the team.
    member = _create_user("member@example.com", organization, level=OrganizationMembership.Level.MEMBER)
    _create_user_integration(member, integration_id="member-int")

    assert resolve_team_github_integration(team.id) is None


@pytest.mark.django_db
def test_prefers_owner_integration_over_member_integration(organization, team):
    owner = _create_user("owner@example.com", organization)
    member = _create_user("member@example.com", organization, level=OrganizationMembership.Level.MEMBER)
    # Member connected first; pre-fix this would have won by `created_at`.
    member_int = _create_user_integration(member, integration_id="member-int")
    UserIntegration.objects.filter(pk=member_int.pk).update(
        created_at=member_int.created_at - datetime.timedelta(hours=1)
    )
    owner_int = _create_user_integration(owner, integration_id="owner-int")

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == owner_int.id


@pytest.mark.django_db
def test_prefers_owner_personal_account_over_org_account(organization, team):
    # An owner who belongs to a big GitHub org (e.g. `posthog`) must not have that org's repos
    # outrank their own personal account where the team's project actually lives.
    owner = _create_user("owner@example.com", organization)
    org_int = _create_user_integration(owner, integration_id="owner-org", account_type="Organization")
    # Backdate the personal one so the win is from the account-type preference, not recency.
    personal_int = _create_user_integration(owner, integration_id="owner-personal", account_type="User")
    UserIntegration.objects.filter(pk=personal_int.pk).update(
        created_at=org_int.created_at - datetime.timedelta(hours=1)
    )

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == personal_int.id


@pytest.mark.django_db
def test_requester_own_integration_used_when_not_an_owner(organization, team):
    # User-initiated path: a non-owner requester referencing their own connected repo must still
    # resolve their own integration (their own credentials — not the cross-account leak the
    # owner-only fallback guards against). Without `requester_user_id` this returns None.
    member = _create_user("member@example.com", organization, level=OrganizationMembership.Level.MEMBER)
    member_int = _create_user_integration(member, integration_id="member-int")

    assert resolve_team_github_integration(team.id) is None

    resolved = resolve_team_github_integration(team.id, requester_user_id=member.id)
    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == member_int.id


@pytest.mark.django_db
def test_requester_integration_preferred_over_owner_fallback(organization, team):
    # The requester explicitly named a repo only they have connected, so their own integration
    # must outrank an owner's fallback (which lists different repos).
    owner = _create_user("owner@example.com", organization)
    member = _create_user("member@example.com", organization, level=OrganizationMembership.Level.MEMBER)
    _create_user_integration(owner, integration_id="owner-int")
    member_int = _create_user_integration(member, integration_id="member-int")

    resolved = resolve_team_github_integration(team.id, requester_user_id=member.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == member_int.id


@pytest.mark.django_db
def test_requester_path_does_not_borrow_other_members_integration(organization, team):
    # Passing a requester must only surface that requester's own integration — never another
    # member's. A requester with no GitHub falls through to the owner-only fallback.
    requester = _create_user("requester@example.com", organization, level=OrganizationMembership.Level.MEMBER)
    other_member = _create_user("other@example.com", organization, level=OrganizationMembership.Level.MEMBER)
    _create_user_integration(other_member, integration_id="other-int")

    assert resolve_team_github_integration(team.id, requester_user_id=requester.id) is None


@pytest.mark.django_db
def test_requester_falls_back_to_owner_when_requester_has_no_github(organization, team):
    # A requester with no GitHub of their own still benefits from the owner fallback.
    owner = _create_user("owner@example.com", organization)
    requester = _create_user("requester@example.com", organization, level=OrganizationMembership.Level.MEMBER)
    owner_int = _create_user_integration(owner, integration_id="owner-int")

    resolved = resolve_team_github_integration(team.id, requester_user_id=requester.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == owner_int.id


@pytest.mark.django_db
def test_team_integration_still_wins_over_requester(organization, team):
    member = _create_user("member@example.com", organization, level=OrganizationMembership.Level.MEMBER)
    _create_user_integration(member, integration_id="member-int")
    team_int = _create_team_integration(team, integration_id="team-1")

    resolved = resolve_team_github_integration(team.id, requester_user_id=member.id)

    assert isinstance(resolved, GitHubIntegration)
    assert resolved.integration.id == team_int.id


@pytest.mark.django_db
def test_skips_user_integration_when_owner_has_no_org_membership(team):
    # A user with a GitHub integration but no membership in the team's org is not an owner.
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
def test_keeps_team_integration_with_empty_unsynced_repository_cache(team):
    # Freshly installed integration: cache is empty but never synced (updated_at is NULL).
    # We can't yet conclude "0 repos" — keep it so select_repo can lazily sync.
    integration = _create_team_integration(team, integration_id="team-fresh", repository_cache=[], cache_synced=False)

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, GitHubIntegration)
    assert resolved.integration.id == integration.id


@pytest.mark.django_db
def test_keeps_user_integration_with_empty_unsynced_repository_cache(organization, team):
    user = _create_user("fresh@example.com", organization)
    integration = _create_user_integration(user, integration_id="user-fresh", repository_cache=[], cache_synced=False)

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == integration.id


@pytest.mark.django_db
def test_skips_team_integration_whose_token_refresh_permanently_failed(organization, team):
    # An install uninstalled/suspended on GitHub's side keeps `errors=TOKEN_REFRESH_FAILED`.
    # Re-selecting it makes repo discovery storm GitHub with doomed refreshes, so it must be
    # skipped in favour of a healthy fallback.
    user = _create_user("a@example.com", organization)
    errored = _create_team_integration(team, integration_id="team-dead")
    Integration.objects.filter(pk=errored.pk).update(errors=ERROR_TOKEN_REFRESH_FAILED)
    user_int = _create_user_integration(user, integration_id="user-1")

    resolved = resolve_team_github_integration(team.id)

    assert isinstance(resolved, UserGitHubIntegration)
    assert resolved.integration.id == user_int.id


@pytest.mark.django_db
def test_returns_none_when_only_team_github_has_failed_token_refresh(team):
    errored = _create_team_integration(team, integration_id="team-dead")
    Integration.objects.filter(pk=errored.pk).update(errors=ERROR_TOKEN_REFRESH_FAILED)

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
