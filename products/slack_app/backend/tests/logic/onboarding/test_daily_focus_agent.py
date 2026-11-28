from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

import pytest
import time_machine
from unittest.mock import AsyncMock, MagicMock, patch

from posthog.models.integration import Integration

from products.slack_app.backend.logic.onboarding.daily_focus_agent import (
    AgentSuggestion,
    AgentSummaryItem,
    DailyFocusAgentOutput,
    agent_owner_id,
    run_daily_focus_agent,
    to_work_focus,
)
from products.slack_app.backend.logic.onboarding.work_focus import (
    WorkFocus,
    WorkFocusSummaryItem,
    find_and_send_daily_focus,
    work_focus_blocks,
)
from products.slack_app.backend.models import SlackDailyFocus, SlackUserProfileCache
from products.slack_app.backend.services.workspace_integrations import (
    WorkspaceIntegration,
    require_workspace_integration,
)
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID
from products.slack_app.backend.tests.helpers import all_block_text
from products.tasks.backend.facade.profiles import GithubAccess

AGENT = "products.slack_app.backend.logic.onboarding.daily_focus_agent"
WORK_FOCUS = "products.slack_app.backend.logic.onboarding.work_focus"
SINCE = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)
RUN_AT = datetime(2026, 11, 9, 8, 0, tzinfo=UTC)
PRAGUE = ZoneInfo("Europe/Prague")
HOST = "example.slack.com"
LINK = f"https://{HOST}/archives/C1/p1"


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


def _offer(
    n: int,
    author: str = "U_ANA",
    resolved: bool = False,
    has_reaction: bool = False,
    link: str = LINK,
    channel: str | None = None,
) -> AgentSuggestion:
    return AgentSuggestion(
        offer=f"Offer {n}. Want me to look?",
        request=f"Look into {n}.",
        source_permalink=link,
        source_author_id=author,
        source_channel_name=channel,
        resolved=resolved,
        has_reaction=has_reaction,
    )


def _item(
    text: str,
    kind: str = "news",
    channel_id: str = "C1",
    permalink: str | None = LINK,
    resolved: bool = False,
    seen: bool = False,
) -> AgentSummaryItem:
    return AgentSummaryItem(
        text=text,
        kind=kind,
        channel_id=channel_id,
        permalink=permalink,
        resolved=resolved,
        seen_by_person=seen,
    )


def test_the_agent_answer_keeps_only_what_is_new_to_the_person() -> None:
    output = DailyFocusAgentOutput(
        intro="👀 A busy day.",
        summary=[
            # News comes first in the answer, but what is for the person still leads the DM.
            *(_item(f"<@U_BEN> launched {n}") for n in range(4)),
            _item("<@U_ANA> asked you about the pricing page", kind="for_you", permalink="https://evil.example/x"),
            _item("<@U_BEN> linked elsewhere", kind="for_you", permalink="https://other.slack.com/archives/C1/p1"),
            _item("<@U_ANA> spoofed a channel", kind="for_you", channel_id="C1> <https://evil.example|Sign in> <#C1"),
            _item("<@U_ANA> pinged you about trial length", kind="for_you", seen=True),
            _item("<@U_BEN> fixed the export, merged", kind="for_you", resolved=True),
            _item("a DM is not a channel", kind="for_you", channel_id="D1"),
            _item("  ", kind="for_you"),
            *(_item(f"<@U_ANA> asked you {n}", kind="for_you") for n in range(3)),
        ],
        suggestions=[
            _offer(0, author=SLACK_USER_ID),
            _offer(8, resolved=True),
            _offer(9, has_reaction=True),
            _offer(1, link=f"{LINK}> <https://evil.example|Sign in>", channel="growth"),
            _offer(2, link="https://slack.com.evil.example/archives/C1/p1", author="U1> <https://evil.example|x>"),
            _offer(3, link="https://u:p@example.slack.com/archives/C1/p1", channel="x> <https://evil.example|x>"),
            *(_offer(n) for n in range(4, 6)),
        ],
    )

    focus = to_work_focus(output, SLACK_USER_ID, workspace_host=HOST)

    assert [(item.section, item.text) for item in focus.summary] == [
        ("for_you", "<@U_ANA> asked you about the pricing page"),
        ("for_you", "<@U_BEN> linked elsewhere"),
        ("for_you", "<@U_ANA> asked you 0"),
        ("news", "<@U_BEN> launched 0"),
        ("news", "<@U_BEN> launched 1"),
        ("news", "<@U_BEN> launched 2"),
    ]
    # A link off Slack, or to a thread in another workspace, never renders as a link.
    assert [item.permalink for item in focus.summary[:3]] == [None, None, LINK]
    # Work someone already reacted to, resolved work and the person's own message never become offers. What a
    # message could smuggle into the DM's mrkdwn through a link, an author or a channel name is dropped.
    assert [(s.offer, s.source_permalink, s.source_author_id, s.source_channel_name) for s in focus.suggestions] == [
        ("Offer 1. Want me to look?", None, "U_ANA", "growth"),
        ("Offer 2. Want me to look?", None, None, None),
        ("Offer 3. Want me to look?", None, "U_ANA", None),
    ]


@pytest.mark.parametrize("agent", [True, False], ids=["agent DM", "pipeline DM"])
def test_only_the_agent_dm_shows_its_summary_in_two_sections(agent: bool) -> None:
    def item(text: str, section: Literal["for_you", "news"]) -> WorkFocusSummaryItem:
        return WorkFocusSummaryItem(text=text, channel_id="C1", permalink=LINK, section=section if agent else None)

    focus = WorkFocus(
        intro="👀 Hi.",
        suggestions=[],
        summary=[item("<@U_ANA> asked you", "for_you"), item("<@U_BEN> launched", "news")],
    )

    summary_block = work_focus_blocks(MagicMock(id=1), focus, SLACK_USER_ID)[0]

    lines = summary_block["text"]["text"].split("\n")
    expected = (
        [
            "*For you*",
            f"• <@U_ANA> asked you in <#C1>. <{LINK}|[1]>",
            "*In your channels*",
            f"• <@U_BEN> launched in <#C1>. <{LINK}|[2]>",
        ]
        if agent
        else [f"• <@U_ANA> asked you in <#C1>. <{LINK}|[1]>", f"• <@U_BEN> launched in <#C1>. <{LINK}|[2]>"]
    )
    assert lines[1:] == expected


# DeepSeek V4 Flash stays reserved for other products, so the slack_app pin refuses it.
@pytest.mark.parametrize("model, kept", [("deepseek-ai/deepseek-v4-flash-0731", False), ("claude-haiku-4-5", True)])
@pytest.mark.django_db
def test_a_model_the_gateway_refuses_keeps_the_person_on_the_pipeline(model, kept, org_team_user, link_user) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes="search:read.public")

    with (
        patch(f"{AGENT}.AGENT_MODEL", model),
        patch(f"{AGENT}.is_slack_app_daily_focus_agent_enabled", return_value=True),
        patch(f"{AGENT}.slack_mcp_installation_id", return_value="slack-installation") as mcp,
    ):
        owner = agent_owner_id(integration, SLACK_USER_ID)

    # Otherwise the run starts on the default model without a word, at many times the cost.
    assert owner == (user.id if kept else None)
    if kept:
        assert mcp.call_args.kwargs == {"slack_team_id": SLACK_TEAM_ID, "slack_user_id": SLACK_USER_ID}


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
        patch(f"{AGENT}.SlackIntegration") as workspace,
        patch(f"{WORK_FOCUS}.capture_slack_event") as captured,
        time_machine.travel(datetime(2026, 11, 9, 9, 0, tzinfo=UTC), tick=False),
    ):
        workspace.return_value.client.auth_test.return_value = {"url": f"https://{HOST}/"}
        first = run_daily_focus_agent(integration, SLACK_USER_ID, since=SINCE, run_at=RUN_AT, zone=PRAGUE)
        retry = run_daily_focus_agent(integration, SLACK_USER_ID, since=SINCE, run_at=RUN_AT, zone=PRAGUE)

    assert first == expected
    dispatch_state = start.call_args.kwargs["before_task_dispatch"]("run-id")
    # Only the Slack MCP, on a small box instead of the default 4 CPU / 16 GB.
    assert dispatch_state == {
        "config_snapshot": {"connectors": {"mcp_installation_ids": ["slack-installation"]}},
        "sandbox_cpu_cores": 2,
        "sandbox_memory_gb": 4,
    }
    context = start.call_args.kwargs["context"]
    # Slack messages steer the run, so it never holds the person's GitHub credential.
    assert (context.model, context.github_access) == ("zai-org/glm-5.3-flash", GithubAccess.NONE)
    posts = bot.return_value.client.chat_postMessage.call_args_list
    if expected == "sent":
        assert retry == "already_sent" and start.call_count == 1 and len(posts) == 1
        shown = all_block_text(posts[0].kwargs["blocks"])
        assert "Offer 1. Want me to look?" in shown
        # The link to the thread survives, because it is on the workspace Slack names for this integration.
        assert LINK in shown
        # The run keeps a transcript, so the DM must not promise that nothing was kept.
        assert "with your access" in shown and "kept nothing" not in shown
        assert captured.call_args.kwargs["engine"] == "agent"
    else:
        assert posts == []
