import pytest

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.auto_start import ReviewerContent, _resolve_autostart_assignee
from products.signals.backend.models import SignalUserAutonomyConfig
from products.signals.backend.report_generation.research import Priority


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-auto-start-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-auto-start-team")


def _create_org_member_with_github(email: str, organization: Organization, login: str) -> User:
    user = User.objects.create(email=email)
    OrganizationMembership.objects.create(user=user, organization=organization)
    UserSocialAuth.objects.create(user=user, provider="github", uid=f"github-{login}", extra_data={"login": login})
    return user


def _reviewer(login: str) -> ReviewerContent:
    return ReviewerContent(github_login=login, github_name=None, relevant_commits=[])


@pytest.mark.django_db
def test_resolves_assignee_for_org_member_on_team(organization, team):
    user = _create_org_member_with_github("octocat@example.com", organization, "OctoCat")
    SignalUserAutonomyConfig.objects.create(user=user, autostart_priority=Priority.P2.value)

    assignee = _resolve_autostart_assignee(
        team_id=team.id,
        report_priority=Priority.P0,
        reviewers_content=[_reviewer("octocat")],
        team_default_priority=Priority.P0,
    )

    assert assignee is not None
    assert assignee.id == user.id


@pytest.mark.django_db
def test_returns_none_when_priority_below_threshold(organization, team):
    user = _create_org_member_with_github("octocat@example.com", organization, "OctoCat")
    SignalUserAutonomyConfig.objects.create(user=user, autostart_priority=Priority.P1.value)

    assignee = _resolve_autostart_assignee(
        team_id=team.id,
        report_priority=Priority.P3,
        reviewers_content=[_reviewer("octocat")],
        team_default_priority=Priority.P0,
    )

    assert assignee is None
