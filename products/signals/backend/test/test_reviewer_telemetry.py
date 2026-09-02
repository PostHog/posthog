import pytest
from unittest.mock import patch

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.organization import OrganizationMembership

from products.signals.backend.report_generation.reviewer_telemetry import capture_suggested_reviewers_resolved


@pytest.fixture
def organization():
    org = Organization.objects.create(name="test-reviewer-telemetry-org")
    yield org
    org.delete()


@pytest.fixture
def team(organization):
    return Team.objects.create(organization=organization, name="test-reviewer-telemetry-team")


@pytest.mark.django_db
def test_captures_linkable_unlinkable_split(organization, team):
    user = User.objects.create(email="linked@example.com")
    OrganizationMembership.objects.create(user=user, organization=organization)
    UserSocialAuth.objects.create(user=user, provider="github", uid="gh-1", extra_data={"login": "octocat"})

    with patch(
        "products.signals.backend.report_generation.reviewer_telemetry.posthoganalytics.capture"
    ) as mock_capture:
        capture_suggested_reviewers_resolved(
            team_id=team.id,
            report_id="report-1",
            github_logins=["OctoCat", "ghost-contrib", " ", "octocat"],
            source="pipeline",
        )

    assert mock_capture.call_count == 1
    kwargs = mock_capture.call_args.kwargs
    assert kwargs["event"] == "signals_suggested_reviewers_resolved"
    props = kwargs["properties"]
    assert props["team_id"] == team.id
    assert props["report_id"] == "report-1"
    assert props["source"] == "pipeline"
    assert props["suggested_count"] == 2
    assert props["linkable_logins"] == ["octocat"]
    assert props["unlinkable_logins"] == ["ghost-contrib"]
    assert props["linkable_count"] == 1
    assert props["unlinkable_count"] == 1
    assert props["all_unlinkable"] is False


@pytest.mark.django_db
def test_never_raises_on_missing_team():
    with patch(
        "products.signals.backend.report_generation.reviewer_telemetry.posthoganalytics.capture"
    ) as mock_capture:
        capture_suggested_reviewers_resolved(
            team_id=-1,
            report_id="report-1",
            github_logins=["octocat"],
            source="scout",
        )

    mock_capture.assert_not_called()
