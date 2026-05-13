import pytest

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserIntegration

from products.signals.backend.report_generation.resolve_reviewers import resolve_org_github_login_to_users


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-resolve-reviewers-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-resolve-reviewers-team")


def _create_org_member(email: str, organization: Organization) -> User:
    user = User.objects.create(email=email)
    OrganizationMembership.objects.create(user=user, organization=organization)
    return user


@pytest.mark.django_db
def test_resolves_login_via_social_auth(organization, team):
    user = _create_org_member("social@example.com", organization)
    UserSocialAuth.objects.create(
        user=user,
        provider="github",
        uid="github-social-1",
        extra_data={"login": "OctoCat"},
    )

    result = resolve_org_github_login_to_users(team.id, ["octocat"])

    assert set(result.keys()) == {"octocat"}
    assert result["octocat"].id == user.id


@pytest.mark.django_db
def test_resolves_login_via_user_integration(organization, team):
    user = _create_org_member("user-int@example.com", organization)
    UserIntegration.objects.create(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id="user-int-1",
        config={"installation_id": "user-int-1", "github_user": {"login": "MixedCase"}},
        sensitive_config={},
    )

    result = resolve_org_github_login_to_users(team.id, ["mixedcase"])

    assert set(result.keys()) == {"mixedcase"}
    assert result["mixedcase"].id == user.id


@pytest.mark.django_db
def test_resolves_login_via_team_integration(organization, team):
    user = _create_org_member("team-int@example.com", organization)
    Integration.objects.create(
        team=team,
        kind="github",
        integration_id="team-int-1",
        config={"installation_id": "team-int-1", "connecting_user_github_login": "TeamConnector"},
        sensitive_config={},
        created_by=user,
    )

    result = resolve_org_github_login_to_users(team.id, ["teamconnector"])

    assert set(result.keys()) == {"teamconnector"}
    assert result["teamconnector"].id == user.id


@pytest.mark.django_db
def test_returns_empty_when_no_match(organization, team):
    user = _create_org_member("nomatch@example.com", organization)
    UserSocialAuth.objects.create(
        user=user,
        provider="github",
        uid="github-nomatch",
        extra_data={"login": "someone"},
    )

    result = resolve_org_github_login_to_users(team.id, ["different-login"])

    assert result == {}


@pytest.mark.django_db
def test_skips_users_outside_organization(organization, team):
    other_org = Organization.objects.create(name="test-resolve-reviewers-other-org")
    try:
        outside_user = User.objects.create(email="outside@example.com")
        OrganizationMembership.objects.create(user=outside_user, organization=other_org)
        UserSocialAuth.objects.create(
            user=outside_user,
            provider="github",
            uid="github-outside",
            extra_data={"login": "outsider"},
        )

        result = resolve_org_github_login_to_users(team.id, ["outsider"])

        assert result == {}
    finally:
        other_org.delete()
