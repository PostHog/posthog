import json

import pytest
from unittest.mock import MagicMock, patch

from django.apps import apps
from django.conf import settings

from rest_framework.exceptions import ValidationError
from slack_sdk.errors import SlackApiError
from social_django.models import UserSocialAuth

from posthog.constants import AvailableFeature
from posthog.models import Organization, Team, User
from posthog.models.integration import Integration
from posthog.models.organization import OrganizationMembership

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.facade.api import set_default_slack_notification_channel
from products.signals.backend.models import (
    AutonomyPriority,
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalScoutRun,
    SignalUserAutonomyConfig,
)
from products.signals.backend.report_generation.research import ActionabilityChoice
from products.signals.backend.slack_inbox_notifications import (
    _build_message_blocks,
    _meets_min_priority,
    _resolve_reviewer_mentions,
    _summary_excerpt,
    dispatch_inbox_item_notifications,
    dispatch_reviewer_added_notifications,
    resolve_suggested_reviewer_user_ids,
)
from products.signals.backend.slack_report_threads import report_id_for_slack_thread
from products.signals.backend.tasks import send_reviewer_added_slack_notifications


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


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ("First line.\nSecond line should not appear.", "First line."),
        ("First sentence. Second sentence should not appear.", "First sentence."),
        (
            "See [the e.g. chart](https://example.com/a. b) now. Then more.",
            "See [the e.g. chart](https://example.com/a. b) now.",
        ),
    ],
)
def test_summary_excerpt_uses_first_sentence_only(summary: str, expected: str) -> None:
    assert _summary_excerpt(summary) == expected


def test_summary_excerpt_truncates_first_sentence_at_280_chars() -> None:
    long_line = "x" * 650
    assert len(_summary_excerpt(long_line)) == 280
    assert _summary_excerpt(long_line).endswith("...")


def test_summary_excerpt_keeps_links_out_of_the_cut() -> None:
    sql_link = "[the query](https://us.posthog.com/project/2/sql?open_query=" + "SELECT%201%20" * 60 + ")"
    assert _summary_excerpt(f"Errors rose, see {sql_link} for details.") == "Errors rose, see the query for details."


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
        title="fix(checkout): Checkout errors spiked",
        summary=(
            "Error rate rose after deploy. Ignored second sentence.\nIgnored second line.\n\n"
            "## Problem\n\nThe payment form throws.\n\n"
            "## Impact\n\nAbout **300 buyers** could not pay\nin the last hour. Ignored second sentence.\n\n"
            "A second paragraph stays out.\n\n"
            "## Expected impact\n\nFailures should drop to zero."
        ),
        signal_count=12,
    )
    blocks, text = _build_message_blocks(report, reviewer_mentions=["<@U123>"])

    assert blocks[0]["text"]["text"] == "Checkout errors spiked"
    assert blocks[1]["text"] == (
        "Error rate rose after deploy.\n\n**Impact:** About **300 buyers** could not pay in the last hour."
    )
    # A mention in plain_text would render as the raw token, never pinging anyone.
    assert all("<@" not in t for t in _plain_text_block_texts(blocks))
    assert blocks[2]["elements"][0]["text"] == "👤 Suggested owner: <@U123>"
    buttons = blocks[3]["elements"]
    assert len(buttons) == 1
    assert buttons[0]["text"]["text"] == "Review in PostHog"
    assert buttons[0]["url"] == f"{settings.SITE_URL}/project/42/inbox/reports/report-uuid?link_source=slack"
    assert text == "Checkout errors spiked"


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ("Lead.\n\n## Impact\n\nUsers lose data.\n\n## Solution\n\nFix it.", "Users lose data."),
        ("Lead.\n\n## Impact\n\nSee [the chart](chart:errors) here.", "See the chart here."),
        ("Lead.\n\n## Expected impact\n\nFailures drop to zero.", ""),
        ("Lead only, no sections.", ""),
    ],
)
def test_build_message_blocks_shows_only_the_impact_section(summary: str, expected: str) -> None:
    report = SignalReport(id="report-uuid", title="Impact test", summary=summary)
    blocks, _ = _build_message_blocks(report, reviewer_mentions=[])

    body = blocks[1]["text"]
    if expected:
        assert body.endswith(f"**Impact:** {expected}")
    else:
        assert "Impact" not in body


def test_build_message_blocks_mentions_every_routed_reviewer() -> None:
    report = SignalReport(id="report-uuid", title="Shared channel")
    blocks, _ = _build_message_blocks(report, reviewer_mentions=["<@U1>", "<@U2>"])

    assert blocks[1]["text"] == "**Shared channel**"
    assert blocks[2]["elements"][0]["text"] == "👤 Suggested owners: <@U1> <@U2>"


def test_build_message_blocks_escapes_mrkdwn_in_llm_derived_fields() -> None:
    # A crafted summary must not inject Slack mentions (<!here>, <@U…>) into mrkdwn.
    report = SignalReport(
        id="report-uuid",
        title="Injection test",
        summary="<!here> everyone & <@U999> look\n\n## Impact\n\n<!channel> is affected",
        signal_count=1,
    )
    blocks, _ = _build_message_blocks(report, reviewer_mentions=[])

    section_text = blocks[1]["text"]
    assert "<!here>" not in section_text
    assert "<@U999>" not in section_text
    assert "<!channel>" not in section_text
    assert "&lt;!here&gt;" in section_text
    # `&` is left alone. Slack decodes an entity without re-reading it as a token, so escaping it
    # buys no safety, and it does not decode inside a link destination, where it would corrupt the
    # query string of every link a report carries.
    assert "everyone & " in section_text


def test_resolve_reviewer_mentions_uses_slack_mention_when_lookup_succeeds() -> None:
    user = User(first_name="Marcus", last_name="Twix", email="marcus@example.com")
    slack = MagicMock()
    with patch(
        "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
        return_value="U_SLACK",
    ):
        assert _resolve_reviewer_mentions(slack, [user]) == ["<@U_SLACK>"]


@pytest.mark.parametrize(
    ("lookup_result", "expected_lookups"),
    [
        (None, 2),
        # A lookup error stops the remaining lookups, because each one fails the same way.
        (SlackApiError("missing_scope", {"ok": False, "error": "missing_scope"}), 1),
        (ValidationError({"slack_notification_direct_message": "Slack is unavailable"}), 1),
    ],
    ids=["slack_user_not_found", "missing_scope", "lookup_budget_spent"],
)
def test_resolve_reviewer_mentions_falls_back_to_name(lookup_result: object, expected_lookups: int) -> None:
    users = [
        User(first_name="Marcus", last_name="Twix", email="marcus@example.com"),
        User(first_name="Ada", last_name="Lime", email="ada@example.com"),
    ]
    slack = MagicMock()
    with patch(
        "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
        side_effect=lookup_result if isinstance(lookup_result, Exception) else None,
        return_value=lookup_result,
    ) as lookup:
        assert _resolve_reviewer_mentions(slack, users) == ["Marcus Twix", "Ada Lime"]
    assert lookup.call_count == expected_lookups


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


def _set_team_channel(team: Team, channel: str, integration: Integration | None = None) -> None:
    set_default_slack_notification_channel(team.id, channel, integration_id=integration.id if integration else None)


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


@pytest.mark.parametrize(
    ("target", "expected_conversation", "expects_mention"),
    [
        ("C123|#inbox", "C123", True),
        # A member target is delivered as a direct message, which mentions nobody.
        ("U0123ABC456|@reviewer", "U0123ABC456", False),
    ],
)
@pytest.mark.django_db
def test_dispatch_sends_to_configured_reviewer(org_and_team, target, expected_conversation, expects_mention):
    org, team = org_and_team
    user = _make_reviewer_user(org, "reviewer2@example.com", "another-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel=target,
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
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 1
    assert fake_client.chat_postMessage.call_count == 1
    call_kwargs = fake_client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == expected_conversation
    assert call_kwargs["text"] == "Test report"
    blocks = call_kwargs["blocks"]
    assert blocks[0]["text"]["text"] == "Test report"
    context_texts = [block["elements"][0]["text"] for block in blocks if block["type"] == "context"]
    if expects_mention:
        assert "👤 Suggested owner: <@U_REVIEWER>" in context_texts
    else:
        assert not any("Suggested owner" in text for text in context_texts)
    assert all("<@" not in t for t in _plain_text_block_texts(blocks))
    actions = next(block for block in blocks if block["type"] == "actions")
    assert actions["elements"][0]["url"] == (
        f"{settings.SITE_URL}/project/{team.id}/inbox/reports/{report.id}?link_source=slack"
    )


@pytest.mark.django_db
def test_dispatch_skips_a_direct_message_to_an_ineligible_member(org_and_team):
    # Report contents must not follow a member who left the workspace or became a guest.
    org, team = org_and_team
    user = _make_reviewer_user(org, "reviewer-dm@example.com", "dm-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="U0123ABC456|@reviewer",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P1, suggested_logins=["dm-bot"])

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        slack_cls.return_value.get_user_by_id.return_value = None
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 0
    assert fake_client.chat_postMessage.call_count == 0


@pytest.mark.django_db
def test_dispatch_skips_report_authored_by_scout_kept_out_of_inbox(org_and_team):
    org, team = org_and_team
    reviewer = _make_reviewer_user(org, "digest-reviewer@example.com", "digest-bot")
    _make_slack_integration(team, reviewer)
    _set_team_channel(team, "CTEAM|#posthog-signals")
    report = _make_ready_report(team, priority=AutonomyPriority.P2, suggested_logins=["digest-bot"])
    config = SignalScoutConfig.objects.for_team(team.id).create(
        team=team, skill_name="signals-scout-digest", output_destinations={"inbox": False}
    )
    task = apps.get_model("tasks", "Task").objects.create(team=team, title="scout", description="d")
    SignalScoutRun.objects.for_team(team.id).create(
        team=team,
        task_run=apps.get_model("tasks", "TaskRun").objects.create(team=team, task=task),
        scout_config=config,
        skill_name=config.skill_name,
        skill_version=1,
        emitted_report_ids=[str(report.id)],
    )

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 0
    assert fake_client.chat_postMessage.call_count == 0


@pytest.mark.django_db
@pytest.mark.parametrize("ai_approved", [True, False])
def test_dispatch_posts_to_team_channel_without_per_user_config(org_and_team, ai_approved):
    org, team = org_and_team
    if not ai_approved:
        org.is_ai_data_processing_approved = False
        org.save()
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
    # The invite closes the message, and only while the org still approves AI data processing:
    # a reviewer can be added to a retained report after that approval is revoked. Which of the
    # two variants renders is the shared builder's decision, tested in products/slack_app.
    assert ("@PostHog" in call_kwargs["blocks"][-1]["elements"][0]["text"]) is ai_approved


@pytest.mark.django_db
@pytest.mark.parametrize("binding", ["bound", "unbound", "removed"])
def test_dispatch_posts_team_channel_through_the_workspace_that_owns_it(org_and_team, binding):
    org, team = org_and_team
    reviewer = _make_reviewer_user(org, "workspace-reviewer@example.com", "workspace-bot")
    oldest = _make_slack_integration(team, reviewer)
    newer = Integration.objects.create(
        team=team, kind="slack", integration_id="T456", config={}, sensitive_config={"access_token": "xoxb-other"}
    )
    removed = Integration.objects.create(team=team, kind="slack", integration_id="T789", config={})
    _set_team_channel(team, "CTEAM|#posthog-signals", {"bound": newer, "unbound": None, "removed": removed}[binding])
    removed.delete()
    report = _make_ready_report(team, priority=AutonomyPriority.P2, suggested_logins=["workspace-bot"])

    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch("products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email", return_value=None),
    ):
        slack_cls.return_value.client = MagicMock()
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 1
    assert slack_cls.call_args.args[0] == (newer if binding == "bound" else oldest)


@pytest.mark.parametrize(
    ("target", "posted_channel"),
    [
        ("C123|#inbox", "C123"),
        # Posting to a member id opens a direct message, so Slack answers with the `D…`
        # conversation. An inbound mention names that conversation, not the member id.
        ("U0123ABC456|@reviewer", "D0123ABC456"),
    ],
)
@pytest.mark.django_db
def test_dispatch_records_the_notification_thread_for_the_report(org_and_team, target, posted_channel):
    # The message invites a reply mentioning PostHog, which starts a task. Dropping the posted
    # `ts`, or storing the id we sent instead of the one Slack answered with, leaves that task
    # with no way back to the report it discusses.
    org, team = org_and_team
    reviewer = _make_reviewer_user(org, "thread-reviewer@example.com", "thread-bot")
    integration = _make_slack_integration(team, reviewer)
    SignalUserAutonomyConfig.objects.create(
        user=reviewer,
        slack_notification_integration=integration,
        slack_notification_channel=target,
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P1, suggested_logins=["thread-bot"])

    fake_client = MagicMock()
    fake_client.chat_postMessage.return_value = {"ok": True, "ts": "1700000000.000100", "channel": posted_channel}
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        dispatch_inbox_item_notifications(str(report.id), team.id)

    assert report_id_for_slack_thread(
        slack_workspace_id=integration.integration_id,
        team_id=team.id,
        channel=posted_channel,
        thread_ts="1700000000.000100",
    ) == str(report.id)


@pytest.mark.django_db
def test_dispatch_falls_back_to_team_channel_without_suggested_reviewers(org_and_team):
    org, team = org_and_team
    creator = _make_reviewer_user(org, "creator@example.com", "creator-bot")
    _make_slack_integration(team, creator)
    _set_team_channel(team, "CTEAM|#posthog-signals")
    report = _make_ready_report(team, priority=AutonomyPriority.P2)  # no suggested reviewers

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    # No suggested reviewer, but a channel is configured → still delivered, with no reviewers section.
    assert sent == 1
    assert fake_client.chat_postMessage.call_count == 1
    assert fake_client.chat_postMessage.call_args.kwargs["channel"] == "CTEAM"
    assert "Suggested owner" not in json.dumps(fake_client.chat_postMessage.call_args.kwargs["blocks"])


@pytest.mark.django_db
@pytest.mark.parametrize("has_project_access", [True, False])
def test_reviewer_resolution_uses_only_the_latest_reviewer_row(
    org_and_team: tuple[Organization, Team], has_project_access: bool
) -> None:
    org, team = org_and_team
    if not has_project_access:
        org.available_product_features = [
            {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
        ]
        org.save()
        AccessControl.objects.create(team=team, resource="project", resource_id=str(team.id), access_level="none")
    old_reviewer = _make_reviewer_user(org, "old@example.com", "old-reviewer")
    current_reviewer = _make_reviewer_user(org, "current@example.com", "current-reviewer")
    report = _make_ready_report(team, priority=AutonomyPriority.P1)
    SignalReportArtefact.objects.create(
        team=team,
        report=report,
        type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        content=json.dumps([{"user_uuid": str(old_reviewer.uuid)}]),
    )
    SignalReportArtefact.objects.create(
        team=team,
        report=report,
        type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
        content=json.dumps([{"user_uuid": str(current_reviewer.uuid)}]),
    )

    assert resolve_suggested_reviewer_user_ids(report) == ({current_reviewer.id} if has_project_access else set())


@pytest.mark.django_db
def test_dispatch_does_not_use_own_channel_as_fallback_without_reviewers(org_and_team):
    # A per-user own channel is a reviewer notification, not a team catch-all. With no team default
    # channel and no resolvable reviewer, the report is not delivered to the user's own channel.
    org, team = org_and_team
    user = User.objects.create(email="subscriber@example.com")
    OrganizationMembership.objects.create(user=user, organization=org)
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="CMINE|#my-signals",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P2, suggested_logins=["ghost-not-in-org"])

    fake_client = MagicMock()
    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        slack_cls.return_value.client = fake_client
        sent = dispatch_inbox_item_notifications(str(report.id), team.id)

    assert sent == 0
    assert fake_client.chat_postMessage.call_count == 0


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
    capture_context = MagicMock()
    capture = capture_context.__enter__.return_value
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch("products.signals.backend.slack_inbox_notifications.ph_scoped_capture", return_value=capture_context),
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
    assert capture.call_args.kwargs["properties"]["destination"] == "team"


@pytest.mark.django_db
def test_dispatch_posts_team_channel_when_reviewer_has_own_channel(org_and_team):
    # The only reviewer has their own channel. The team channel still gets the report, without
    # mentioning that reviewer a second time.
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

    assert sent == 2
    posts = {c.kwargs["channel"]: c.kwargs["blocks"] for c in fake_client.chat_postMessage.call_args_list}
    assert set(posts) == {"CUSER", "CTEAM"}
    assert "Suggested" not in json.dumps(posts["CTEAM"])


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
def test_dispatch_filtered_own_channel_reviewer_is_not_mentioned_in_team_channel(org_and_team):
    # A reviewer whose own channel is filtered out by their min-priority chose that
    # threshold, so the team channel gets the report without mentioning them.
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
    # P3 is below the user's P1 threshold → no own-channel post.
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

    assert sent == 1
    call_kwargs = fake_client.chat_postMessage.call_args.kwargs
    assert call_kwargs["channel"] == "CTEAM"
    assert "Suggested" not in json.dumps(call_kwargs["blocks"])


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
    assert "👤 Suggested owners: <@U_ONE> <@U_TWO>" in context_text


@pytest.mark.django_db
def test_reviewer_added_notifies_added_reviewer_on_own_channel(org_and_team):
    # Someone manually added to a READY, actionable report is pinged on their own channel,
    # even though they weren't a suggested reviewer when the report first went ready.
    org, team = org_and_team
    user = _make_reviewer_user(org, "added@example.com", "added-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P1)

    fake_client = MagicMock()
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            return_value="U_ADDED",
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_reviewer_added_notifications(str(report.id), team.id, ["added-bot"])

    assert sent == 1
    assert fake_client.chat_postMessage.call_args.kwargs["channel"] == "C123"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("report_ready", "team_channel", "expected_sent"),
    [(False, None, 0), (True, None, 0), (True, "CTEAM", 1)],
)
def test_notification_respects_project_access(
    org_and_team: tuple[Organization, Team], report_ready: bool, team_channel: str | None, expected_sent: int
) -> None:
    # Org membership alone must not leak a private project's report into Slack: a member
    # locked out of the project (project marked private, no explicit access) gets no ping.
    org, team = org_and_team
    org.available_product_features = [{"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}]
    org.save()
    AccessControl.objects.create(team=team, resource="project", resource_id=str(team.id), access_level="none")

    user = _make_reviewer_user(org, "no-access@example.com", "no-access-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C123|#inbox",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P1, suggested_logins=["no-access-bot"])
    if team_channel:
        _set_team_channel(team, team_channel)

    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        if report_ready:
            sent = dispatch_inbox_item_notifications(str(report.id), team.id)
        else:
            sent = dispatch_reviewer_added_notifications(str(report.id), team.id, ["no-access-bot"])

    assert sent == expected_sent
    assert slack_cls.call_count == expected_sent
    if expected_sent:
        post_message = slack_cls.return_value.client.chat_postMessage
        post_message.assert_called_once()
        assert post_message.call_args.kwargs["channel"] == team_channel
        assert "Suggested owner" not in json.dumps(post_message.call_args.kwargs["blocks"])


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("min_priority", "expected_sent"),
    [
        # No threshold: an unprioritized report still pings — the initial path would have
        # delivered it via the team channel, and this personal path has no fallback.
        (None, 1),
        # An explicit threshold keeps filtering unprioritized reports out.
        (AutonomyPriority.P1, 0),
    ],
)
def test_reviewer_added_unprioritized_report(org_and_team, min_priority, expected_sent):
    org, team = org_and_team
    user = _make_reviewer_user(org, "added-noprio@example.com", "added-noprio-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C555|#inbox",
        slack_notification_min_priority=min_priority,
    )
    report = _make_ready_report(team, priority=None)

    fake_client = MagicMock()
    with (
        patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls,
        patch(
            "products.signals.backend.slack_inbox_notifications.lookup_slack_user_id_by_email",
            return_value="U_ADDED",
        ),
    ):
        slack_cls.return_value.client = fake_client
        sent = dispatch_reviewer_added_notifications(str(report.id), team.id, ["added-noprio-bot"])

    assert sent == expected_sent


@pytest.mark.django_db
def test_reviewer_added_skips_when_report_not_ready(org_and_team):
    # The add-time ping mirrors the initial notification's gate: a report that isn't READY
    # (still being generated) must not notify.
    org, team = org_and_team
    user = _make_reviewer_user(org, "added2@example.com", "added-bot2")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C1|#c",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P1)
    SignalReport.objects.filter(id=report.id).update(status=SignalReport.Status.IN_PROGRESS)

    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        sent = dispatch_reviewer_added_notifications(str(report.id), team.id, ["added-bot2"])

    assert sent == 0
    assert slack_cls.call_count == 0


@pytest.mark.django_db
def test_reviewer_added_does_not_fall_back_to_team_channel(org_and_team):
    # A manual add is a personal ping — a reviewer with no own channel gets nothing, rather
    # than broadcasting to the whole team's default channel for a one-person add.
    org, team = org_and_team
    user = _make_reviewer_user(org, "added3@example.com", "added-bot3")
    _make_slack_integration(team, user)
    _set_team_channel(team, "CTEAM|#signals")
    SignalUserAutonomyConfig.objects.create(user=user)  # no personal slack config
    report = _make_ready_report(team, priority=AutonomyPriority.P2)

    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        sent = dispatch_reviewer_added_notifications(str(report.id), team.id, ["added-bot3"])

    assert sent == 0
    assert slack_cls.call_count == 0


@pytest.mark.django_db
def test_reviewer_added_excludes_actor(org_and_team):
    # Adding yourself shouldn't ping you.
    org, team = org_and_team
    user = _make_reviewer_user(org, "self@example.com", "self-bot")
    integration = _make_slack_integration(team, user)
    SignalUserAutonomyConfig.objects.create(
        user=user,
        slack_notification_integration=integration,
        slack_notification_channel="C9|#c",
    )
    report = _make_ready_report(team, priority=AutonomyPriority.P1)

    with patch("products.signals.backend.slack_inbox_notifications.SlackIntegration") as slack_cls:
        sent = dispatch_reviewer_added_notifications(str(report.id), team.id, ["self-bot"], exclude_user_id=user.id)

    assert sent == 0
    assert slack_cls.call_count == 0


@pytest.mark.django_db
def test_reviewer_added_task_decodes_uuid_from_the_legacy_argument(org_and_team):
    _, team = org_and_team
    with patch("products.signals.backend.tasks.dispatch_reviewer_added_notifications") as mock_dispatch:
        send_reviewer_added_slack_notifications(
            report_id="019f0000-0000-7000-8000-000000000000",
            team_id=team.id,
            added_github_logins=["linked-user", "user:019f0000-0000-7000-8000-000000000001"],
        )

    assert mock_dispatch.call_args.kwargs["added_github_logins"] == ["linked-user"]
    assert mock_dispatch.call_args.kwargs["added_user_uuids"] == ["019f0000-0000-7000-8000-000000000001"]
