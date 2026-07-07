import json

import pytest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.conf import settings

from social_django.models import UserSocialAuth

from posthog.models import Organization, Team, User
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership

from products.signals.backend.models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalTeamConfig,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.research import ActionabilityChoice
from products.signals.backend.slack_inbox_notifications import (
    _MAX_THREAD_SIGNALS,
    _build_message_blocks,
    _build_signal_thread_blocks,
    _meets_min_priority,
    _resolve_reviewer_mentions,
    _signal_source_line,
    _summary_excerpt,
    dispatch_inbox_item_notifications,
)
from products.signals.backend.task_run_artefacts import record_implementation_task


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


def _plain_text_block_texts(blocks: list[dict]) -> list[str]:
    """Every plain_text string in the message — mentions here would render as raw `<@…>`."""
    texts: list[str] = []
    for block in blocks:
        text = block.get("text")
        if isinstance(text, dict) and text.get("type") == "plain_text":
            texts.append(text["text"])
        for element in block.get("elements", []):
            el_text = element.get("text") if isinstance(element, dict) else None
            if isinstance(el_text, dict) and el_text.get("type") == "plain_text":
                texts.append(el_text["text"])
    return texts


def test_build_message_blocks_includes_recipient_and_open_in_posthog_button() -> None:
    report = SignalReport(
        id="report-uuid",
        team_id=42,
        title="Checkout errors spiked",
        summary="Error rate rose after deploy.\nIgnored second line.",
        signal_count=12,
    )
    blocks, text = _build_message_blocks(
        report,
        priority="P1",
        source_products=["error_tracking"],
        reviewer_mentions=["<@U123>"],
    )

    assert blocks[0]["text"]["text"] == "Checkout errors spiked"
    section_text = blocks[1]["text"]["text"]
    assert section_text.startswith("*❗ P1 · Error tracking*")
    assert "Error rate rose after deploy." in section_text
    assert "Ignored second line." not in section_text
    # A mention in plain_text would render as the raw token, never pinging anyone.
    assert all("<@" not in t for t in _plain_text_block_texts(blocks))
    context_text = blocks[2]["elements"][0]["text"]
    assert "12 signals" in context_text
    assert "👤 Suggested reviewers: <@U123>" in context_text
    assert "Inbox" not in context_text
    button = blocks[3]["elements"][0]
    assert button["text"]["text"] == "Open in PostHog"
    assert button["url"] == f"{settings.SITE_URL}/project/42/inbox/reports/report-uuid"
    assert text == "Inbox item (P1): Checkout errors spiked"


def test_build_message_blocks_mentions_every_routed_reviewer() -> None:
    report = SignalReport(id="report-uuid", title="Shared channel")
    blocks, _ = _build_message_blocks(
        report,
        priority="P2",
        source_products=[],
        reviewer_mentions=["<@U1>", "<@U2>"],
    )

    assert blocks[1]["text"]["text"] == "*🟠 P2*"
    assert blocks[2]["elements"][0]["text"] == "👤 Suggested reviewers: <@U1> <@U2>"


def test_build_message_blocks_includes_repository_in_metadata_line() -> None:
    report = SignalReport(id="report-uuid", title="Repo test")
    blocks, _ = _build_message_blocks(
        report,
        priority="P2",
        source_products=["error_tracking"],
        reviewer_mentions=[],
        repository="PostHog/posthog",
    )

    assert blocks[1]["text"]["text"] == "*🟠 P2 · Error tracking · PostHog/posthog*"


def test_build_message_blocks_escapes_mrkdwn_in_llm_derived_fields() -> None:
    # A crafted summary/repository must not inject Slack mentions (<!here>, <@U…>) into mrkdwn.
    report = SignalReport(
        id="report-uuid",
        title="Injection test",
        summary="<!here> everyone & <@U999> look",
        signal_count=1,
    )
    blocks, _ = _build_message_blocks(
        report,
        priority="P2",
        source_products=[],
        reviewer_mentions=[],
        repository="<!channel>/repo",
    )

    section_text = blocks[1]["text"]["text"]
    assert "<!here>" not in section_text
    assert "<@U999>" not in section_text
    assert "<!channel>" not in section_text
    assert "&lt;!here&gt;" in section_text
    assert "&amp;" in section_text


def test_build_message_blocks_includes_github_pr_button_when_pr_url_provided() -> None:
    report = SignalReport(
        id="report-uuid",
        team_id=42,
        title="Checkout errors spiked",
        summary="Error rate rose after deploy.",
        signal_count=12,
    )
    pr_url = "https://github.com/org/repo/pull/42"
    blocks, _ = _build_message_blocks(
        report,
        priority="P1",
        source_products=["error_tracking"],
        reviewer_mentions=["<@U123>"],
        implementation_pr_url=pr_url,
    )

    buttons = blocks[3]["elements"]
    assert len(buttons) == 2
    assert buttons[0]["text"]["text"] == "Review PR"
    assert buttons[0]["url"] == pr_url
    assert buttons[1]["text"]["text"] == "Open in PostHog"
    assert buttons[1]["url"] == f"{settings.SITE_URL}/project/42/inbox/reports/report-uuid"


def test_build_message_blocks_omits_github_pr_button_without_pr_url() -> None:
    report = SignalReport(id="report-uuid", title="No PR yet")
    blocks, _ = _build_message_blocks(
        report,
        priority=None,
        source_products=[],
        reviewer_mentions=["Marcus Twix"],
        implementation_pr_url=None,
    )

    assert blocks[1]["text"]["text"] == "*No PR yet*"
    assert blocks[2]["elements"][0]["text"] == "👤 Suggested reviewers: Marcus Twix"
    assert len(blocks[3]["elements"]) == 1


def test_build_message_blocks_appends_dismiss_button_last_with_action_id() -> None:
    report = SignalReport(id="report-uuid", title="Dismissable")
    dismiss_value = '{"integration_id": 2, "report_id": "report-uuid", "team_id": 1}'
    blocks, _ = _build_message_blocks(
        report,
        priority="P2",
        source_products=[],
        reviewer_mentions=["<@U123>"],
        implementation_pr_url="https://github.com/org/repo/pull/42",
        dismiss_button_value=dismiss_value,
    )

    buttons = blocks[3]["elements"]
    assert [b["text"]["text"] for b in buttons] == ["Review PR", "Open in PostHog", "Dismiss"]
    dismiss = buttons[-1]
    assert dismiss["action_id"] == "signals_dismiss_report"
    assert dismiss["value"] == dismiss_value
    assert "url" not in dismiss
    assert dismiss["confirm"]["confirm"]["text"] == "Dismiss"
    assert dismiss["confirm"]["deny"]["text"] == "Cancel"


@pytest.mark.parametrize(
    ("priority", "expected_priority_label"),
    [
        (AutonomyPriority.P0, "‼️ P0"),
        (AutonomyPriority.P1, "❗ P1"),
        (AutonomyPriority.P2, "🟠 P2"),
        (AutonomyPriority.P3, "🟡 P3"),
        (AutonomyPriority.P4, "🔵 P4"),
    ],
)
def test_build_message_blocks_prefixes_priority_with_emoji(priority: str, expected_priority_label: str) -> None:
    report = SignalReport(id="report-uuid", title="Priority test")
    blocks, _ = _build_message_blocks(
        report,
        priority=priority,
        source_products=[],
        reviewer_mentions=["<@U123>"],
    )

    assert blocks[1]["text"]["text"] == f"*{expected_priority_label}*"
    assert blocks[2]["elements"][0]["text"] == "👤 Suggested reviewers: <@U123>"


def test_resolve_reviewer_mentions_uses_slack_mention_when_lookup_succeeds() -> None:
    user = User(first_name="Marcus", last_name="Twix", email="marcus@example.com")
    slack = MagicMock()
    with patch(
        "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
        return_value="U_SLACK",
    ):
        assert _resolve_reviewer_mentions(slack, [user]) == ["<@U_SLACK>"]


def test_resolve_reviewer_mentions_falls_back_to_name_when_slack_user_not_found() -> None:
    user = User(first_name="Marcus", last_name="Twix", email="marcus@example.com")
    slack = MagicMock()
    with patch(
        "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
        return_value=None,
    ):
        assert _resolve_reviewer_mentions(slack, [user]) == ["Marcus Twix"]


def test_resolve_reviewer_mentions_caps_at_five() -> None:
    users = [User(first_name=f"U{i}", email=f"u{i}@example.com") for i in range(8)]
    slack = MagicMock()
    with patch(
        "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
        return_value=None,
    ):
        assert len(_resolve_reviewer_mentions(slack, users)) == 5


@pytest.fixture
def org_and_team():
    org = Organization.objects.create(name="slack-notif-org")
    team = Team.objects.create(organization=org, name="slack-notif-team")
    yield org, team
    team.delete()
    org.delete()


def _set_team_channel(team: Team, channel: str) -> None:
    # SignalTeamConfig is auto-created per team via register_team_extension_signal.
    SignalTeamConfig.objects.filter(team=team).update(default_slack_notification_channel=channel)


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
    Task = apps.get_model("tasks", "Task")
    TaskRun = apps.get_model("tasks", "TaskRun")
    task = Task.objects.create(
        team=team,
        title="Implementation task",
        description="Fix the bug",
        origin_product=Task.OriginProduct.SIGNAL_REPORT,
    )
    record_implementation_task(
        team_id=team.id,
        report_id=str(report.id),
        task_id=str(task.id),
    )
    TaskRun.objects.create(
        team=team,
        task=task,
        status=TaskRun.Status.COMPLETED,
        output={"pr_url": pr_url},
    )


@pytest.mark.django_db
def test_dispatch_no_notification_without_team_channel_or_user_config(org_and_team):
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
    assert "Inbox item (P1)" in call_kwargs["text"]
    blocks = call_kwargs["blocks"]
    assert blocks[0]["text"]["text"] == "Test report"
    assert blocks[1]["text"]["text"].startswith("*❗ P1 · Error tracking*")
    assert "👤 Suggested reviewers: <@U_REVIEWER>" in blocks[2]["elements"][0]["text"]
    assert all("<@" not in t for t in _plain_text_block_texts(blocks))
    assert blocks[3]["elements"][0]["url"] == f"{settings.SITE_URL}/project/{team.id}/inbox/reports/{report.id}"


@pytest.mark.django_db
def test_dispatch_posts_to_team_channel_without_per_user_config(org_and_team):
    org, team = org_and_team
    reviewer = _make_reviewer_user(org, "team-reviewer@example.com", "team-bot")
    _make_slack_integration(team, reviewer)
    _set_team_channel(team, "CTEAM|#posthog-signals")
    report = _make_ready_report(team, priority=AutonomyPriority.P2, suggested_logins=["team-bot"])

    fake_client = MagicMock()
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            return_value="U_TEAM",
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 1
    call_kwargs = fake_client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == "CTEAM"
    assert "<@U_TEAM>" in call_kwargs["blocks"][2]["elements"][0]["text"]


@pytest.mark.django_db
def test_dispatch_falls_back_to_team_channel_when_no_reviewer_has_connected_github(org_and_team):
    # Suggested reviewers exist but none resolve to an org member with a connected GitHub account.
    # The actionable report should still reach the team default channel (with no reviewer mention)
    # rather than notifying nobody.
    org, team = org_and_team
    creator = _make_reviewer_user(org, "creator@example.com", "creator-bot")
    _make_slack_integration(team, creator)
    _set_team_channel(team, "CTEAM|#posthog-signals")
    # "ghost-bot" matches no org member, so it resolves to no connected user.
    report = _make_ready_report(team, priority=AutonomyPriority.P2, suggested_logins=["ghost-bot"])

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 1
    call_kwargs = fake_client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == "CTEAM"
    # No reviewer resolved, so the message carries no "Suggested reviewers" mention line.
    assert "Suggested reviewers" not in json.dumps(call_kwargs["blocks"])


@pytest.mark.django_db
def test_dispatch_posts_nothing_without_reviewers_or_team_channel(org_and_team):
    org, team = org_and_team
    _make_reviewer_user(org, "creator@example.com", "creator-bot")
    report = _make_ready_report(team, priority=AutonomyPriority.P2)  # no reviewers, no team channel

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    # No destination at all → nothing sent.
    assert sent == 0
    assert fake_client.chat_postMessage.call_count == 0


@pytest.mark.django_db
def test_dispatch_skips_non_actionable_report(org_and_team):
    org, team = org_and_team
    creator = _make_reviewer_user(org, "creator@example.com", "creator-bot")
    _make_slack_integration(team, creator)
    _set_team_channel(team, "CTEAM|#posthog-signals")
    # Not in the inbox Reports tab → must not notify, even with a team channel.
    report = _make_ready_report(team, actionability=ActionabilityChoice.NOT_ACTIONABLE)

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 0
    assert fake_client.chat_postMessage.call_count == 0


@pytest.mark.django_db
def test_dispatch_notifies_requires_human_input_report_without_priority(org_and_team):
    org, team = org_and_team
    reviewer = _make_reviewer_user(org, "rhi@example.com", "rhi-bot")
    _make_slack_integration(team, reviewer)
    _set_team_channel(team, "CTEAM|#posthog-signals")
    # Actionable (requires_human_input) with no priority but a resolvable reviewer → still notifies.
    report = _make_ready_report(
        team, actionability=ActionabilityChoice.REQUIRES_HUMAN_INPUT, priority=None, suggested_logins=["rhi-bot"]
    )

    fake_client = MagicMock()
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch("products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email", return_value=None),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 1
    assert fake_client.chat_postMessage.call_args.kwargs["channel"] == "CTEAM"


@pytest.mark.django_db
def test_dispatch_groups_own_and_fallback_reviewers_sharing_a_channel(org_and_team):
    # One reviewer's own channel resolves to the same channel as the team default that
    # a second (unconfigured) reviewer falls back to → a single post mentioning both.
    org, team = org_and_team
    own = _make_reviewer_user(org, "own@example.com", "own-bot")
    _make_reviewer_user(org, "fallback@example.com", "fallback-bot")
    integration = _make_slack_integration(team, own)
    SignalUserAutonomyConfig.objects.create(
        user=own,
        slack_notification_integration=integration,
        slack_notification_channel="CSHARED|#signals",
    )
    _set_team_channel(team, "CSHARED|#signals")
    report = _make_ready_report(team, priority=AutonomyPriority.P2, suggested_logins=["own-bot", "fallback-bot"])

    def _slack_id(_slack, email):
        return {"own@example.com": "U_OWN", "fallback@example.com": "U_FALLBACK"}.get(email.strip().lower())

    fake_client = MagicMock()
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            side_effect=_slack_id,
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 1
    assert fake_client.chat_postMessage.call_count == 1
    body = fake_client.chat_postMessage.call_args.kwargs["blocks"][2]["elements"][0]["text"]
    assert "<@U_OWN>" in body and "<@U_FALLBACK>" in body


@pytest.mark.django_db
def test_dispatch_skips_team_channel_when_reviewer_has_own_channel(org_and_team):
    # The only reviewer has their own channel → they are routed there and nobody falls
    # back to the team default, so the team channel is not posted to at all.
    org, team = org_and_team
    user = _make_reviewer_user(org, "own-only@example.com", "own-only-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="CUSER|#me",
    )
    _set_team_channel(team, "CTEAM|#posthog-signals")
    report = _make_ready_report(team, priority=AutonomyPriority.P2, suggested_logins=["own-only-bot"])

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
    channels = {c.kwargs["channel"] for c in fake_client.chat_postMessage.call_args_list}
    assert channels == {"CUSER"}


@pytest.mark.django_db
def test_dispatch_team_channel_tags_only_fallback_reviewers(org_and_team):
    # One reviewer has an own channel, one falls back to the team default. The team
    # post must mention only the fallback reviewer, not the one routed elsewhere.
    org, team = org_and_team
    own = _make_reviewer_user(org, "own@example.com", "own-bot")
    _make_reviewer_user(org, "fallback@example.com", "fallback-bot")
    integration = _make_slack_integration(team, own)
    SignalUserAutonomyConfig.objects.create(
        user=own,
        slack_notification_integration=integration,
        slack_notification_channel="CUSER|#me",
    )
    _set_team_channel(team, "CTEAM|#posthog-signals")
    report = _make_ready_report(team, priority=AutonomyPriority.P2, suggested_logins=["own-bot", "fallback-bot"])

    def _slack_id(_slack, email):
        return {"own@example.com": "U_OWN", "fallback@example.com": "U_FALLBACK"}.get(email.strip().lower())

    fake_client = MagicMock()
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            side_effect=_slack_id,
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 2
    by_channel = {
        c.kwargs["channel"]: c.kwargs["blocks"][2]["elements"][0]["text"]
        for c in fake_client.chat_postMessage.call_args_list
    }
    assert set(by_channel) == {"CUSER", "CTEAM"}
    assert "<@U_OWN>" in by_channel["CUSER"] and "<@U_FALLBACK>" not in by_channel["CUSER"]
    assert "<@U_FALLBACK>" in by_channel["CTEAM"] and "<@U_OWN>" not in by_channel["CTEAM"]


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
    assert [b["text"]["text"] for b in buttons] == ["Review PR", "Open in PostHog", "Dismiss"]
    assert buttons[0]["url"] == "https://github.com/org/repo/pull/99"
    assert buttons[1]["url"] == f"{settings.SITE_URL}/project/{team.id}/inbox/reports/{report.id}"
    assert buttons[-1]["action_id"] == "signals_dismiss_report"


@pytest.mark.django_db
def test_dispatch_dismiss_button_carries_routing_ids_and_repository(org_and_team):
    org, team = org_and_team
    user = _make_reviewer_user(org, "reviewer-dismiss@example.com", "dismiss-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P2, suggested_logins=["dismiss-bot"])
    SignalReportArtefact.objects.create(
        team=team,
        report=report,
        type=SignalReportArtefact.ArtefactType.REPO_SELECTION,
        content=json.dumps({"repository": "PostHog/posthog", "reason": "owns the code"}),
    )

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
    blocks = fake_client.chat_postMessage.call_args.kwargs["blocks"]
    assert "PostHog/posthog" in blocks[1]["text"]["text"]
    dismiss = blocks[3]["elements"][-1]
    assert json.loads(dismiss["value"]) == {
        "integration_id": integration.id,
        "report_id": str(report.id),
        "team_id": team.id,
    }


@pytest.mark.django_db
def test_dispatch_respects_per_user_min_priority_filter(org_and_team):
    org, team = org_and_team
    user = _make_reviewer_user(org, "reviewer3@example.com", "skip-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
        slack_notification_min_priority=AutonomyPriority.P1,
    )
    # P3 < P1 threshold so the per-user post is filtered out (and no team channel is set).
    report = _make_ready_report(team, priority=AutonomyPriority.P3, suggested_logins=["skip-bot"])

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 0
    assert fake_client.chat_postMessage.call_count == 0


@pytest.mark.django_db
def test_dispatch_filtered_own_channel_reviewer_does_not_fall_back_to_team(org_and_team):
    # A reviewer whose own channel is filtered out by their min-priority chose that
    # threshold — they are not silently rerouted to the team default channel.
    org, team = org_and_team
    user = _make_reviewer_user(org, "low-pri@example.com", "low-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="CUSER|#me",
        slack_notification_min_priority=AutonomyPriority.P1,
    )
    _set_team_channel(team, "CTEAM|#posthog-signals")
    # P3 is below the user's P1 threshold → no own-channel post and no team fallback.
    report = _make_ready_report(team, priority=AutonomyPriority.P3, suggested_logins=["low-bot"])

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
    report = _make_ready_report(
        team, priority=AutonomyPriority.P1, suggested_logins=["shared-login-1", "shared-login-2"]
    )

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
    context_text = call_kwargs["blocks"][2]["elements"][0]["text"]
    assert "👤 Suggested reviewers: <@U_ONE> <@U_TWO>" in context_text


@pytest.mark.parametrize(
    ("source_product", "source_type", "expected"),
    [
        # Explicit labels mirror the canonical Inbox UI's signalCardSourceLine.
        ("error_tracking", "issue_created", "Error tracking · New issue"),
        ("error_tracking", "issue_spiking", "Error tracking · Volume spike"),
        ("session_replay", "session_problem", "Session replay · Session problem"),
        ("session_replay", "session_analysis_cluster", "Session replay · Session analysis cluster"),
        ("llm_analytics", "evaluation", "AI observability · Evaluation"),
        ("llm_analytics", "evaluation_report", "AI observability · Evaluation report"),
        ("github", "issue", "GitHub · Issue"),
        ("zendesk", "ticket", "Zendesk · Ticket"),
        ("linear", "issue", "Linear · Issue"),
        ("pganalyze", "issue", "pganalyze · Issue"),
        # Unknown error-tracking type falls back to the humanized source type.
        ("error_tracking", "weird_type", "Error tracking · weird type"),
        # No source type → no trailing separator.
        ("error_tracking", "", "Error tracking"),
        # Unknown product/type humanizes both halves.
        ("logs", "alert_state_change", "logs · alert state change"),
        ("unknown_thing", "", "unknown thing"),
    ],
)
def test_signal_source_line(source_product: str, source_type: str, expected: str) -> None:
    assert _signal_source_line(source_product, source_type) == expected


@pytest.mark.parametrize(
    ("skill_name", "expected"),
    [
        # A scout's skill name becomes the label.
        ("signals-scout-error-tracking", "Scout · Error tracking"),
        ("signals-scout-revenue-analytics", "Scout · Revenue analytics"),
        # No usable skill name → generic scout label.
        ("", "Scout · Cross-source issue"),
    ],
)
def test_signal_source_line_scout_uses_skill_name(skill_name: str, expected: str) -> None:
    extra = {"skill_name": skill_name} if skill_name else {}
    assert _signal_source_line("signals_scout", "cross_source_issue", extra) == expected


def test_build_signal_thread_blocks_renders_header_content_and_github_details() -> None:
    signal = {
        "source_product": "github",
        "source_type": "issue",
        "weight": 2.5,
        "content": "Users report the export button does nothing",
        "extra": {
            "number": 42,
            "labels": ["bug", "export"],
            "html_url": "https://github.com/PostHog/posthog/issues/42",
        },
    }
    blocks, fallback = _build_signal_thread_blocks(signal)

    assert blocks[0]["elements"][0]["text"] == "*GitHub · Issue*"
    assert blocks[1]["text"]["text"] == "Users report the export button does nothing"
    detail = blocks[2]["elements"][0]["text"]
    assert "#42" in detail
    assert "bug, export" in detail
    assert "<https://github.com/PostHog/posthog/issues/42|View on GitHub>" in detail
    assert fallback.startswith("GitHub · Issue:")


def test_build_signal_thread_blocks_escapes_content_to_block_mention_injection() -> None:
    signal = {
        "source_product": "logs",
        "source_type": "alert",
        "weight": 1.0,
        "content": "<!here> ping & <@U999>",
        "extra": {},
    }
    blocks, fallback = _build_signal_thread_blocks(signal)
    content_text = blocks[1]["text"]["text"]
    assert "<!here>" not in content_text
    assert "<@U999>" not in content_text
    assert "&lt;!here&gt;" in content_text
    # The fallback `text` also reaches Slack mention parsing, so it must be escaped too.
    assert "<!here>" not in fallback
    assert "<@U999>" not in fallback
    assert "&lt;!here&gt;" in fallback


def test_build_signal_thread_blocks_escapes_source_line_in_header_and_fallback() -> None:
    # An unknown source type flows verbatim into the source line, so it must be escaped both places.
    signal = {
        "source_product": "custom",
        "source_type": "<@U42>",
        "weight": 1.0,
        "content": "body",
        "extra": {},
    }
    blocks, fallback = _build_signal_thread_blocks(signal)
    header_text = blocks[0]["elements"][0]["text"]
    assert "<@U42>" not in header_text
    assert "<@U42>" not in fallback
    assert "&lt;@U42&gt;" in header_text
    assert "&lt;@U42&gt;" in fallback


def test_build_signal_thread_blocks_rejects_unsafe_detail_url() -> None:
    signal = {
        "source_product": "zendesk",
        "source_type": "ticket",
        "weight": 1.0,
        "content": "Ticket body",
        "extra": {"priority": "high", "status": "open", "url": "javascript:alert(1)"},
    }
    blocks, _ = _build_signal_thread_blocks(signal)
    detail = blocks[2]["elements"][0]["text"]
    assert "Priority: high" in detail
    assert "Status: open" in detail
    assert "javascript:" not in detail


def test_build_signal_thread_blocks_renders_markdown_content_as_mrkdwn() -> None:
    # Markdown in the description (headings, bullets, emphasis, links) renders as Slack mrkdwn
    # rather than showing literal `##`, `**`, and `[text](url)` noise.
    signal = {
        "source_product": "github",
        "source_type": "issue",
        "weight": 1.0,
        "content": "## Bug\n**Export** is broken, see [issue](https://example.com/i?a=1&b=2)\n- step one\n- step two",
        "extra": {},
    }
    blocks, _ = _build_signal_thread_blocks(signal)
    content_text = blocks[1]["text"]["text"]
    assert "*Bug*" in content_text
    assert "*Export*" in content_text
    assert "<https://example.com/i?a=1&amp;b=2|issue>" in content_text
    assert "• step one" in content_text
    # No raw markdown syntax should survive the conversion.
    assert "##" not in content_text
    assert "**" not in content_text
    assert "[issue]" not in content_text


def test_build_signal_thread_blocks_neutralizes_injection_in_markdown_content() -> None:
    # Even when converting markdown, raw mention/link syntax in untrusted content stays inert.
    signal = {
        "source_product": "github",
        "source_type": "issue",
        "weight": 1.0,
        "content": "**Heads up** <!here> and <@U999> and a fake <https://evil.com|click here>",
        "extra": {},
    }
    blocks, _ = _build_signal_thread_blocks(signal)
    content_text = blocks[1]["text"]["text"]
    assert "*Heads up*" in content_text  # markdown still rendered
    assert "<!here>" not in content_text
    assert "<@U999>" not in content_text
    assert "<https://evil.com|click here>" not in content_text
    assert "&lt;!here&gt;" in content_text
    assert "&lt;@U999&gt;" in content_text


def test_build_signal_thread_blocks_defangs_mention_injection_via_markdown_links() -> None:
    # `markdown_to_mrkdwn` turns `[text](dest)` into Slack's `<dest|label>` form; an untrusted
    # description could smuggle a broadcast/ping by pointing the link at `!channel` / `@U123`.
    signal = {
        "source_product": "github",
        "source_type": "issue",
        "weight": 1.0,
        "content": "[ping everyone](!channel) and [dm me](@U12345678) but [real](https://example.com) is fine",
        "extra": {},
    }
    blocks, _ = _build_signal_thread_blocks(signal)
    content_text = blocks[1]["text"]["text"]
    # No live mention/broadcast token survives.
    assert "<!channel|" not in content_text
    assert "<@U12345678|" not in content_text
    assert "&lt;!channel|ping everyone&gt;" in content_text
    assert "&lt;@U12345678|dm me&gt;" in content_text
    # A genuine http(s) link is still rendered as a clickable Slack link.
    assert "<https://example.com|real>" in content_text


@pytest.mark.django_db
def test_dispatch_posts_signal_evidence_into_thread(org_and_team):
    org, team = org_and_team
    user = _make_reviewer_user(org, "thread@example.com", "thread-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P1, suggested_logins=["thread-bot"])

    signals = [
        {
            "source_product": "error_tracking",
            "source_type": "issue_created",
            "weight": 3.0,
            "content": "Boom",
            "extra": {"fingerprint": "abc123"},
        },
        {"source_product": "github", "source_type": "issue", "weight": 1.0, "content": "Bug", "extra": {"number": 7}},
    ]

    fake_client = MagicMock()
    fake_client.chat_postMessage.return_value = {"ts": "1700000000.000100"}
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            return_value="U_THREAD",
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id, signals=signals)

    assert sent == 1
    # 1 top-level message + 2 threaded evidence replies.
    assert fake_client.chat_postMessage.call_count == 3
    thread_calls = [c for c in fake_client.chat_postMessage.call_args_list if c.kwargs.get("thread_ts")]
    assert len(thread_calls) == 2
    assert all(c.kwargs["thread_ts"] == "1700000000.000100" for c in thread_calls)
    assert all(c.kwargs["channel"] == "C123" for c in thread_calls)


@pytest.mark.django_db
def test_dispatch_caps_thread_signals_and_posts_overflow_note(org_and_team):
    org, team = org_and_team
    user = _make_reviewer_user(org, "overflow@example.com", "overflow-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P1, suggested_logins=["overflow-bot"])

    extra_count = 5
    signals = [
        {"source_product": "logs", "source_type": "alert", "weight": 1.0, "content": f"signal {i}", "extra": {}}
        for i in range(_MAX_THREAD_SIGNALS + extra_count)
    ]

    fake_client = MagicMock()
    fake_client.chat_postMessage.return_value = {"ts": "1700000000.000100"}
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            return_value="U_OVERFLOW",
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id, signals=signals)

    assert sent == 1
    # 1 top-level + _MAX_THREAD_SIGNALS evidence replies + 1 overflow note.
    assert fake_client.chat_postMessage.call_count == 1 + _MAX_THREAD_SIGNALS + 1
    overflow_call = fake_client.chat_postMessage.call_args_list[-1]
    assert f"+{extra_count} more signals in PostHog" in overflow_call.kwargs["text"]
