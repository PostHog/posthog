import pytest
from unittest.mock import MagicMock, patch

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.github_integration_base import GitHubCommitAuthor
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.user_integration import UserIntegration

from products.signals.backend.report_generation.resolve_reviewers import (
    resolve_org_github_login_to_users,
    resolve_suggested_reviewers,
)


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


def _make_social_auth(user: User, team: Team, login: str) -> None:
    UserSocialAuth.objects.create(user=user, provider="github", uid="github-social-1", extra_data={"login": login})


def _make_user_integration(user: User, team: Team, login: str) -> None:
    UserIntegration.objects.create(
        user=user,
        kind=UserIntegration.IntegrationKind.GITHUB,
        integration_id="user-int-1",
        config={"installation_id": "user-int-1", "github_user": {"login": login}},
        sensitive_config={},
    )


def _make_team_integration(user: User, team: Team, login: str) -> None:
    Integration.objects.create(
        team=team,
        kind="github",
        integration_id="team-int-1",
        config={"installation_id": "team-int-1", "connecting_user_github_login": login},
        sensitive_config={},
        created_by=user,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("identity_source", "create_identity", "stored_login"),
    [
        ("social_auth", _make_social_auth, "OctoCat"),
        ("user_integration", _make_user_integration, "MixedCase"),
        ("team_integration", _make_team_integration, "TeamConnector"),
    ],
)
def test_resolves_login_across_identity_sources(organization, team, identity_source, create_identity, stored_login):
    user = _create_org_member(f"{identity_source}@example.com", organization)
    create_identity(user, team, stored_login)

    lookup = stored_login.lower()
    result = resolve_org_github_login_to_users(team.id, [lookup])

    assert set(result.keys()) == {lookup}
    assert result[lookup].id == user.id


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


@pytest.mark.django_db
def test_resolve_suggested_reviewers_drops_reviewers_without_repo_access(organization, team):
    # Authors come from git history; a past contributor who lost repo access must not be suggested,
    # while collaborators and unknown-access authors (fail open) are kept.
    authors = {
        "sha_keep": GitHubCommitAuthor(login="keeper", name="Keeper", commit_url="https://gh/c/1"),
        "sha_drop": GitHubCommitAuthor(login="departed", name="Departed", commit_url="https://gh/c/2"),
        "sha_unknown": GitHubCommitAuthor(login="mystery", name="Mystery", commit_url="https://gh/c/3"),
    }
    collaborator_by_login = {"keeper": True, "departed": False, "mystery": None}

    github = MagicMock()
    github.get_commit_author_info.side_effect = lambda repository, sha: authors[sha]
    github.is_repository_collaborator.side_effect = lambda repository, login: collaborator_by_login[login]

    with patch(
        "products.signals.backend.report_generation.resolve_reviewers.GitHubIntegration.first_for_team_repository",
        return_value=github,
    ):
        result = resolve_suggested_reviewers(
            team.id,
            "PostHog/posthog",
            {"sha_keep": "reason a", "sha_drop": "reason b", "sha_unknown": "reason c"},
        )

    assert [r.login for r in result] == ["keeper", "mystery"]
