import json

import pytest
from unittest.mock import MagicMock, patch

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership

from products.signals.backend.models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalUserAutonomyConfig,
)
from products.signals.backend.slack_inbox_notifications import _meets_min_priority, dispatch_inbox_item_notifications


@pytest.mark.parametrize(
    ("report_priority", "min_priority", "expected"),
    [
        # No threshold → always notify
        ("P0", None, True),
        ("P4", None, True),
        (None, None, True),
        # Report without a priority always notifies (we don't silently swallow)
        (None, AutonomyPriority.P0, True),
        # P0 is highest — P1 with min P0 should NOT notify
        ("P1", AutonomyPriority.P0, False),
        # P0 with min P2 notifies
        ("P0", AutonomyPriority.P2, True),
        # P2 with min P2 notifies (at threshold)
        ("P2", AutonomyPriority.P2, True),
        # P3 with min P2 does not
        ("P3", AutonomyPriority.P2, False),
        # Unknown priority value → notify (fallback to "no judgement")
        ("XX", AutonomyPriority.P1, True),
    ],
)
def test_meets_min_priority(report_priority: str | None, min_priority: str | None, expected: bool) -> None:
    assert _meets_min_priority(report_priority, min_priority) is expected


@pytest.fixture
def org_and_team():
    org = Organization.objects.create(name="slack-notif-org")
    team = Team.objects.create(organization=org, name="slack-notif-team")
    yield org, team
    team.delete()
    org.delete()


def _make_reviewer_user(org: Organization, email: str, login: str) -> User:
    user = User.objects.create(email=email)
    OrganizationMembership.objects.create(user=user, organization=org)
    UserSocialAuth.objects.create(user=user, provider="github", uid=f"gh-{login}", extra_data={"login": login})
    return user


def _make_slack_integration(team: Team, created_by: User) -> Integration:
    return Integration.objects.create(
        team=team,
        kind="slack",
        integration_id="T123",
        config={"team": {"id": "T123"}, "authed_user": {"id": "U999"}},
        sensitive_config={"access_token": "xoxb-test"},
        created_by=created_by,
    )


def _make_ready_report(
    team: Team,
    *,
    title: str = "Test report",
    summary: str = "Summary text",
    priority: str | None = None,
    suggested_logins: list[str] | None = None,
) -> SignalReport:
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title=title, summary=summary, signal_count=3, total_weight=1.0
    )
    if priority:
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            content=json.dumps({"priority": priority}),
        )
    if suggested_logins:
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": login} for login in suggested_logins]),
        )
    return report


@pytest.mark.django_db
def test_dispatch_no_notification_when_user_has_no_slack_config(org_and_team):
    org, team = org_and_team
    user = _make_reviewer_user(org, "reviewer@example.com", "review-bot")
    SignalUserAutonomyConfig.objects.create(user=user)  # no slack config
    report = _make_ready_report(team, suggested_logins=["review-bot"])

    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 0
    assert slack_cls.call_count == 0


@pytest.mark.django_db
def test_dispatch_sends_to_configured_reviewer(org_and_team):
    org, team = org_and_team
    user = _make_reviewer_user(org, "reviewer2@example.com", "another-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P1, suggested_logins=["another-bot"])

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id, source_products=["error_tracking"])

    assert sent == 1
    assert fake_client.chat_postMessage.call_count == 1
    call_kwargs = fake_client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == "C123"
    assert "needs your review" in call_kwargs["text"]


@pytest.mark.django_db
def test_dispatch_respects_min_priority_filter(org_and_team):
    org, team = org_and_team
    user = _make_reviewer_user(org, "reviewer3@example.com", "skip-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
        slack_notification_min_priority=AutonomyPriority.P1,
    )
    # P3 < P1 threshold so this should be filtered out
    report = _make_ready_report(team, priority=AutonomyPriority.P3, suggested_logins=["skip-bot"])

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 0
    assert fake_client.chat_postMessage.call_count == 0


@pytest.mark.django_db
def test_dispatch_continues_after_per_user_failure(org_and_team):
    org, team = org_and_team
    user1 = _make_reviewer_user(org, "alpha@example.com", "alpha-login")
    user2 = _make_reviewer_user(org, "beta@example.com", "beta-login")
    integration = _make_slack_integration(team, user1)
    SignalUserAutonomyConfig.objects.create(
        user=user1,
        slack_notification_integration=integration,
        slack_notification_channel="C1|#a",
    )
    SignalUserAutonomyConfig.objects.create(
        user=user2,
        slack_notification_integration=integration,
        slack_notification_channel="C2|#b",
    )
    report = _make_ready_report(team, suggested_logins=["alpha-login", "beta-login"])

    fake_client = MagicMock()
    fake_client.chat_postMessage.side_effect = [Exception("slack down"), {"ok": True}]
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    # One succeeded, one failed silently.
    assert sent == 1
    assert fake_client.chat_postMessage.call_count == 2
