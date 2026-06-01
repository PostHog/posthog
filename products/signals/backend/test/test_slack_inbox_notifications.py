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
    SignalReportTask,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.research import ActionabilityChoice
from products.signals.backend.slack_inbox_notifications import (
    _build_message_blocks,
    _meets_min_priority,
    _recipient_presentation,
    _RecipientPresentation,
    _summary_excerpt,
    dispatch_inbox_item_notifications,
)
from products.tasks.backend.models import Task, TaskRun


@pytest.mark.parametrize(
    ("report_priority", "min_priority", "expected"),
    [
        # No threshold → always notify
        ("P0", None, True),
        ("P4", None, True),
        # Report without a priority never notifies
        (None, None, False),
        (None, AutonomyPriority.P0, False),
        # P0 is highest — P1 with min P0 should NOT notify
        ("P1", AutonomyPriority.P0, False),
        # P0 with min P2 notifies
        ("P0", AutonomyPriority.P2, True),
        # P2 with min P2 notifies (at threshold)
        ("P2", AutonomyPriority.P2, True),
        # P3 with min P2 does not
        ("P3", AutonomyPriority.P2, False),
        # Unknown priority value → skip until a valid priority judgment is persisted
        ("XX", AutonomyPriority.P1, False),
    ],
)
def test_meets_min_priority(report_priority: str | None, min_priority: str | None, expected: bool) -> None:
    assert _meets_min_priority(report_priority, min_priority) is expected


def test_summary_excerpt_uses_first_line_only() -> None:
    assert _summary_excerpt("First line.\nSecond line should not appear.") == "First line."


def test_summary_excerpt_truncates_first_line_at_600_chars() -> None:
    long_line = "x" * 650
    assert len(_summary_excerpt(long_line)) == 600
    assert _summary_excerpt(long_line).endswith("...")


def test_build_message_blocks_includes_recipient_and_posthog_code_button() -> None:
    report = SignalReport(
        id="report-uuid",
        title="Checkout errors spiked",
        summary="Error rate rose after deploy.\nIgnored second line.",
        signal_count=12,
    )
    recipient = _RecipientPresentation(slack_mention="<@U123>", plain_name="Marcus Twix")
    blocks, text = _build_message_blocks(
        report,
        priority="P1",
        source_products=["error_tracking"],
        recipients=[recipient],
    )

    assert blocks[0]["text"]["text"] == "📬 Checkout errors spiked"
    section_text = blocks[1]["text"]["text"]
    assert "Suggested for" not in section_text
    # Mention belongs in the mrkdwn section so Slack actually pings the user.
    assert section_text.startswith("*‼️ P1 • Matched to <@U123> per code*")
    assert "*Checkout errors spiked*" not in section_text
    assert "Error rate rose after deploy." in section_text
    assert "Ignored second line." not in section_text
    context_text = blocks[2]["elements"][0]["text"]
    assert "12 signals" in context_text
    assert "Error tracking" in context_text
    assert "Inbox" in context_text
    button = blocks[3]["elements"][0]
    assert button["text"]["text"] == "Open in PostHog Code"
    assert button["url"] == "posthog-code://inbox/report-uuid"
    assert text == "Inbox for Marcus Twix (P1): Checkout errors spiked"


def test_build_message_blocks_tags_all_recipients() -> None:
    report = SignalReport(id="report-uuid", title="Shared channel report")
    recipients = [
        _RecipientPresentation(slack_mention="<@U123>", plain_name="Marcus Twix"),
        _RecipientPresentation(slack_mention=None, plain_name="Dana Snickers"),
    ]
    blocks, text = _build_message_blocks(report, priority="P2", source_products=[], recipients=recipients)

    assert blocks[1]["text"]["text"].startswith("*❗ P2 • Matched to <@U123>, Dana Snickers per code*")
    assert text == "Inbox for Marcus Twix, Dana Snickers (P2): Shared channel report"


def test_build_message_blocks_includes_github_pr_button_when_pr_url_provided() -> None:
    report = SignalReport(
        id="report-uuid",
        title="Checkout errors spiked",
        summary="Error rate rose after deploy.",
        signal_count=12,
    )
    recipient = _RecipientPresentation(slack_mention="<@U123>", plain_name="Marcus Twix")
    pr_url = "https://github.com/org/repo/pull/42"
    blocks, _ = _build_message_blocks(
        report,
        priority="P1",
        source_products=["error_tracking"],
        recipients=[recipient],
        implementation_pr_url=pr_url,
    )

    buttons = blocks[3]["elements"]
    assert len(buttons) == 2
    assert buttons[0]["text"]["text"] == "Open in PostHog Code"
    assert buttons[1]["text"]["text"] == "Review PR in GitHub"
    assert buttons[1]["url"] == pr_url


def test_build_message_blocks_omits_github_pr_button_without_pr_url() -> None:
    report = SignalReport(id="report-uuid", title="No PR yet")
    recipient = _RecipientPresentation(slack_mention=None, plain_name="Marcus Twix")
    blocks, _ = _build_message_blocks(
        report,
        priority=None,
        source_products=[],
        recipients=[recipient],
        implementation_pr_url=None,
    )

    assert blocks[1]["text"]["text"] == "*Matched to Marcus Twix per code*"
    assert len(blocks[3]["elements"]) == 1


@pytest.mark.parametrize(
    ("priority", "expected_priority_label"),
    [
        (AutonomyPriority.P0, "🆘 P0"),
        (AutonomyPriority.P1, "‼️ P1"),
        (AutonomyPriority.P2, "❗ P2"),
        (AutonomyPriority.P3, "⚠️ P3"),
        (AutonomyPriority.P4, "👀 P4"),
    ],
)
def test_build_message_blocks_prefixes_priority_with_emoji(priority: str, expected_priority_label: str) -> None:
    report = SignalReport(id="report-uuid", title="Priority test")
    recipient = _RecipientPresentation(slack_mention="<@U123>", plain_name="Marcus Twix")
    blocks, _ = _build_message_blocks(
        report,
        priority=priority,
        source_products=[],
        recipients=[recipient],
    )

    assert blocks[1]["text"]["text"] == f"*{expected_priority_label} • Matched to <@U123> per code*"


def test_recipient_presentation_uses_slack_mention_when_lookup_succeeds() -> None:
    user = User(first_name="Marcus", last_name="Twix", email="marcus@example.com")
    slack = MagicMock()
    integration = MagicMock()

    with patch(
        "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
        return_value="U_SLACK",
    ):
        presentation = _recipient_presentation(user, slack, integration)

    assert presentation.slack_mention == "<@U_SLACK>"
    assert presentation.plain_name == "Marcus Twix"


def test_recipient_presentation_falls_back_to_name_when_slack_user_not_found() -> None:
    user = User(first_name="Marcus", last_name="Twix", email="marcus@example.com")
    slack = MagicMock()
    integration = MagicMock()

    with patch(
        "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
        return_value=None,
    ):
        presentation = _recipient_presentation(user, slack, integration)

    assert presentation.slack_mention is None
    assert presentation.plain_name == "Marcus Twix"


@pytest.fixture
def org_and_team():
    org = Organization.objects.create(name="slack-notif-org")
    team = Team.objects.create(organization=org, name="slack-notif-team")
    yield org, team
    team.delete()
    org.delete()


def _make_reviewer_user(org: Organization, email: str, login: str) -> User:
    user = User.objects.create(email=email, first_name="Reviewer", last_name="Bot")
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
    actionability: str | None = ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
    suggested_logins: list[str] | None = None,
) -> SignalReport:
    report = SignalReport.objects.create(
        team=team, status=SignalReport.Status.READY, title=title, summary=summary, signal_count=3, total_weight=1.0
    )
    if actionability:
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type=SignalReportArtefact.ArtefactType.ACTIONABILITY_JUDGMENT,
            content=json.dumps({"actionability": actionability}),
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


def _create_implementation_task_with_run(
    team: Team,
    report: SignalReport,
    *,
    pr_url: str | None = None,
) -> None:
    task = Task.objects.create(
        team=team,
        title="Implementation task",
        description="Fix the bug",
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
    )
    SignalReportTask.objects.create(
        team=team,
        report=report,
        task=task,
        relationship=SignalReportTask.Relationship.IMPLEMENTATION,
    )
    TaskRun.objects.create(
        team=team,
        task=task,
        status=TaskRun.Status.COMPLETED,
        output={"pr_url": pr_url},
    )


@pytest.mark.django_db
def test_dispatch_no_notification_when_user_has_no_slack_config(org_and_team):
    org, team = org_and_team
    user = _make_reviewer_user(org, "reviewer@example.com", "review-bot")
    SignalUserAutonomyConfig.objects.create(user=user)  # no slack config
    report = _make_ready_report(team, priority=AutonomyPriority.P1, suggested_logins=["review-bot"])

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
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            return_value="U_REVIEWER",
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id, source_products=["error_tracking"])

    assert sent == 1
    assert fake_client.chat_postMessage.call_count == 1
    call_kwargs = fake_client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == "C123"
    assert "Inbox for Reviewer Bot (P1)" in call_kwargs["text"]
    blocks = call_kwargs["blocks"]
    assert blocks[0]["text"]["text"] == "📬 Test report"
    assert blocks[1]["text"]["text"].startswith("*‼️ P1 • Matched to <@U_REVIEWER> per code*")
    assert blocks[3]["elements"][0]["url"] == f"posthog-code://inbox/{report.id}"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("priority", "actionability"),
    [
        (None, ActionabilityChoice.IMMEDIATELY_ACTIONABLE),
        (AutonomyPriority.P1, None),
        ("XX", ActionabilityChoice.IMMEDIATELY_ACTIONABLE),
        (AutonomyPriority.P1, ActionabilityChoice.NOT_ACTIONABLE),
    ],
)
def test_dispatch_skips_until_immediately_actionable_with_valid_priority(
    org_and_team: tuple[Organization, Team], priority: str | None, actionability: str | None
) -> None:
    org, team = org_and_team
    user = _make_reviewer_user(org, "reviewer-missing-judgment@example.com", "missing-judgment-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
    )
    report = _make_ready_report(
        team,
        priority=priority,
        actionability=actionability,
        suggested_logins=["missing-judgment-bot"],
    )

    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 0
    assert slack_cls.call_count == 0


@pytest.mark.django_db
def test_dispatch_includes_github_pr_button_when_implementation_task_has_pr(org_and_team):
    org, team = org_and_team
    user = _make_reviewer_user(org, "reviewer-pr@example.com", "pr-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P1, suggested_logins=["pr-bot"])
    _create_implementation_task_with_run(team, report, pr_url="https://github.com/org/repo/pull/99")

    fake_client = MagicMock()
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            return_value=None,
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 1
    buttons = fake_client.chat_postMessage.call_args.kwargs["blocks"][3]["elements"]
    assert len(buttons) == 2
    assert buttons[1]["text"]["text"] == "Review PR in GitHub"
    assert buttons[1]["url"] == "https://github.com/org/repo/pull/99"


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
def test_dispatch_ignores_slack_config_from_another_team(org_and_team):
    org, report_team = org_and_team
    other_team = Team.objects.create(organization=org, name="other-slack-team")
    user = _make_reviewer_user(org, "reviewer-other-team@example.com", "other-team-bot")
    integration = _make_slack_integration(other_team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
    )
    report = _make_ready_report(report_team, priority=AutonomyPriority.P1, suggested_logins=["other-team-bot"])

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), report_team.id)

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
    report = _make_ready_report(team, priority=AutonomyPriority.P1, suggested_logins=["alpha-login", "beta-login"])

    fake_client = MagicMock()
    fake_client.chat_postMessage.side_effect = [Exception("slack down"), {"ok": True}]
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            return_value=None,
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 1
    assert fake_client.chat_postMessage.call_count == 2


@pytest.mark.django_db
def test_dispatch_sends_once_per_channel_when_reviewers_share_channel(org_and_team):
    org, team = org_and_team
    user1 = _make_reviewer_user(org, "shared1@example.com", "shared-login-1")
    user2 = _make_reviewer_user(org, "shared2@example.com", "shared-login-2")
    integration = _make_slack_integration(team, user1)
    # Both reviewers point at the same channel id — the display alias differs but the id matches.
    SignalUserAutonomyConfig.objects.create(
        user=user1,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
    )
    SignalUserAutonomyConfig.objects.create(
        user=user2,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox-alias",
    )
    report = _make_ready_report(team, suggested_logins=["shared-login-1", "shared-login-2"])

    mentions = {"shared1@example.com": "U_ONE", "shared2@example.com": "U_TWO"}

    fake_client = MagicMock()
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            side_effect=lambda _slack, email: mentions.get(email),
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 1
    assert fake_client.chat_postMessage.call_count == 1
    call_kwargs = fake_client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == "C123"
    # The single message still tags both reviewers that resolved to the channel.
    section_text = call_kwargs["blocks"][1]["text"]["text"]
    assert "Matched to <@U_ONE>, <@U_TWO> per code" in section_text
