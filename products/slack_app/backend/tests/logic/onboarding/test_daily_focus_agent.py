from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
import time_machine
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models.integration import Integration

from products.slack_app.backend.logic.onboarding.daily_focus_agent import (
    AgentSuggestion,
    AgentSummaryItem,
    DailyFocusAgentOutput,
    run_daily_focus_agent,
    to_work_focus,
)
from products.slack_app.backend.logic.onboarding.work_focus import find_and_send_daily_focus
from products.slack_app.backend.models import SlackDailyFocus, SlackUserProfileCache
from products.slack_app.backend.services.workspace_integrations import (
    WorkspaceIntegration,
    require_workspace_integration,
)
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID
from products.slack_app.backend.tests.helpers import all_block_text

AGENT = "products.slack_app.backend.logic.onboarding.daily_focus_agent"
WORK_FOCUS = "products.slack_app.backend.logic.onboarding.work_focus"
SINCE = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)
RUN_AT = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
PRAGUE = ZoneInfo("Europe/Prague")
LINK = "https://example.slack.com/archives/C1/p1"


def _install(team) -> WorkspaceIntegration:
    row = Integration.objects.create(
        team=team,
        kind="slack",
        integration_id=SLACK_TEAM_ID,
        config={"scope": "chat:write,im:history"},
        sensitive_config={"access_token": "[REDACTED]"},
    )
    return require_workspace_integration(row.id, SLACK_TEAM_ID)


def _turn_on_daily(integration: WorkspaceIntegration) -> None:
    SlackDailyFocus.objects.for_team(integration.team_id).create(
        team_id=integration.team_id,
        slack_workspace_id=SLACK_TEAM_ID,
        slack_user_id=SLACK_USER_ID,
        integration_id=integration.id,
        last_run_at=RUN_AT,
        next_run_at=datetime(2026, 11, 10, 8, 0, tzinfo=UTC),
    )
    SlackUserProfileCache.objects.create(
        integration_id=integration.id,
        slack_user_id=SLACK_USER_ID,
        tz="Europe/Prague",
        refreshed_at=datetime(2026, 11, 9, 8, 30, tzinfo=UTC),
    )


def _offer(n: int, author: str = "U_ANA") -> AgentSuggestion:
    return AgentSuggestion(
        offer=f"Offer {n}. Want me to look?", request=f"Look into {n}.", source_permalink=LINK, source_author_id=author
    )


def test_the_agent_answer_keeps_the_pipeline_limits() -> None:
    output = DailyFocusAgentOutput(
        intro="👀 A busy day.",
        summary=[
            AgentSummaryItem(
                text="<@U_ANA> rolled back the release", channel_id="C1", permalink="https://evil.example/x"
            ),
            AgentSummaryItem(text="a DM is not a channel", channel_id="D1", permalink=LINK),
            AgentSummaryItem(text="  ", channel_id="C1"),
            *(AgentSummaryItem(text=f"<@U_ANA> did {n}", channel_id="C1", permalink=LINK) for n in range(6)),
        ],
        suggestions=[_offer(0, author=SLACK_USER_ID), *(_offer(n) for n in range(1, 6))],
    )

    focus = to_work_focus(output, SLACK_USER_ID)

    assert [item.text for item in focus.summary] == [
        "<@U_ANA> rolled back the release",
        "<@U_ANA> did 0",
        "<@U_ANA> did 1",
        "<@U_ANA> did 2",
        "<@U_ANA> did 3",
    ]
    # A link the model made up off Slack never renders as a link.
    assert focus.summary[0].permalink is None
    # The person's own message is never a source, and at most three offers go out.
    assert [suggestion.offer for suggestion in focus.suggestions] == [
        "Offer 1. Want me to look?",
        "Offer 2. Want me to look?",
        "Offer 3. Want me to look?",
    ]


@pytest.mark.django_db
def test_a_daily_run_hands_an_agent_person_to_the_agent_workflow(org_team_user, link_user) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes="search:read.public")
    _turn_on_daily(integration)

    with (
        patch(f"{WORK_FOCUS}.is_slack_app_daily_work_focus_enabled", return_value=True),
        patch(f"{WORK_FOCUS}.SlackIntegration") as bot,
        patch(f"{WORK_FOCUS}.SlackWebClient") as search,
        patch(f"{AGENT}.agent_owner_id", return_value=user.id),
        # The Temporal client is the boundary: the workflow it starts is what the run hands over.
        patch(f"{AGENT}.start_daily_focus_agent") as started,
        time_machine.travel(datetime(2026, 11, 9, 9, 0, tzinfo=UTC), tick=False),
    ):
        bot.return_value.missing_scopes.return_value = frozenset()
        outcome = find_and_send_daily_focus(integration, SLACK_USER_ID, since=SINCE, run_at=RUN_AT)

    assert outcome == "agent_started"
    assert started.call_args.kwargs == {"since": SINCE, "run_at": RUN_AT}
    # The pipeline's search never runs for a person the agent serves, so the day is not paid for twice.
    assert not search.called


@pytest.mark.parametrize(
    "answer, expected",
    [
        (DailyFocusAgentOutput(intro="👀 Release day.", suggestions=[_offer(1)]), "sent"),
        (DailyFocusAgentOutput(intro="👀 Quiet."), "nothing_actionable"),
    ],
    ids=["sends once", "quiet day"],
)
@pytest.mark.django_db
def test_the_agent_run_sends_one_dm_and_mounts_only_the_slack_mcp(answer, expected, org_team_user, link_user) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes="search:read.public")
    _turn_on_daily(integration)
    session = MagicMock(end=AsyncMock())

    with (
        patch(f"{AGENT}.agent_owner_id", return_value=user.id),
        patch(f"{AGENT}.slack_mcp_installation_id", return_value="slack-installation"),
        patch(f"{AGENT}.MultiTurnSession.start", new=AsyncMock(return_value=(session, answer))) as start,
        patch(f"{WORK_FOCUS}.SlackIntegration") as bot,
        patch(f"{WORK_FOCUS}.capture_slack_event") as captured,
        time_machine.travel(datetime(2026, 11, 9, 9, 0, tzinfo=UTC), tick=False),
    ):
        first = run_daily_focus_agent(integration, SLACK_USER_ID, since=SINCE, run_at=RUN_AT, zone=PRAGUE)
        retry = run_daily_focus_agent(integration, SLACK_USER_ID, since=SINCE, run_at=RUN_AT, zone=PRAGUE)

    assert first == expected
    dispatch_state = start.call_args.kwargs["before_task_dispatch"]("run-id")
    assert dispatch_state == {"config_snapshot": {"connectors": {"mcp_installation_ids": ["slack-installation"]}}}
    assert start.call_args.kwargs["context"].model == "zai-org/glm-5.3-flash"
    posts = bot.return_value.client.chat_postMessage.call_args_list
    if expected == "sent":
        assert retry == "already_sent" and start.call_count == 1 and len(posts) == 1
        shown = all_block_text(posts[0].kwargs["blocks"])
        assert "Offer 1. Want me to look?" in shown
        # The run keeps a transcript, so the DM must not promise that nothing was kept.
        assert "with your access" in shown and "kept nothing" not in shown
        assert captured.call_args.kwargs["engine"] == "agent"
    else:
        assert posts == []
