import json
from collections.abc import Iterator
from datetime import UTC, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import time_machine
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from rest_framework.test import APIClient

from posthog.llm.system_one import NoulAnswer, NoulQuestion, SystemOneResult
from posthog.models import Organization, OrganizationMembership
from posthog.models.integration import Integration
from posthog.token_bucket import BucketDecision

from products.slack_app.backend.logic.daily_focus import (
    DAILY_FOCUS_OFF_ACTION_ID,
    daily_focus_footer_block,
    resolve_daily_focus,
)
from products.slack_app.backend.logic.onboarding.work_focus import (
    WorkFocus,
    WorkFocusRateLimited,
    WorkFocusSuggestion,
    WorkFocusTransientError,
    find_and_send_daily_focus,
    find_and_send_work_focus,
    work_focus_blocks,
)
from products.slack_app.backend.models import SlackDailyFocus, SlackSettings, SlackUserProfileCache
from products.slack_app.backend.services.slack_settings import resolve_onboarding
from products.slack_app.backend.services.workspace_integrations import (
    WorkspaceIntegration,
    require_workspace_integration,
)
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID
from products.slack_app.backend.tests.helpers import action_ids, all_block_text, sign_slack_request

WORK_FOCUS = "products.slack_app.backend.logic.onboarding.work_focus"
SECRET_MESSAGE = "the churn numbers for the enterprise plan look wrong again"
SIGNUP_MESSAGE = "can someone check why signups dropped after the release"
CHATTER = "lunch at noon?"
REQUEST = "Find out why churn by plan looks wrong for the enterprise plan, and fix the query."


def _install(team) -> WorkspaceIntegration:
    row = Integration.objects.create(
        team=team,
        kind="slack",
        integration_id=SLACK_TEAM_ID,
        config={"scope": "chat:write"},
        sensitive_config={"access_token": "xoxb-test"},
    )
    return require_workspace_integration(row.id, SLACK_TEAM_ID)


def _messages(contents: list[str], *, prefix: str, author: str = SLACK_USER_ID) -> list[dict[str, Any]]:
    return [
        {
            "channel_id": "C1",
            "channel_name": "product",
            "message_ts": f"{prefix}.{index}",
            "content": content,
            "permalink": f"https://example.slack.com/archives/C1/p{prefix}{index}",
            "author_user_id": author,
            "is_author_bot": False,
        }
        for index, content in enumerate(contents)
    ]


def _search(found: int) -> Any:
    """Two pages for each search: the first carries a cursor, the second ends the search."""

    def api_call(_method: str, *, params: dict[str, Any]) -> dict[str, Any]:
        query_key = "mine" if params["query"].startswith("from:") else "mentions"
        if found < 5:
            # Both searches find the same few messages, so they count once.
            return {"ok": True, "results": {"messages": _messages([CHATTER] * found, prefix="few")}}
        if not params.get("cursor"):
            first = [SECRET_MESSAGE, CHATTER, CHATTER] if query_key == "mine" else [SIGNUP_MESSAGE, CHATTER]
            bots = [{"channel_id": "C1", "message_ts": "9", "content": "bot noise", "is_author_bot": True}]
            return {
                "ok": True,
                "results": {
                    "messages": [
                        *_messages(first, prefix=query_key, author=SLACK_USER_ID if query_key == "mine" else "U_ANDY"),
                        *bots,
                    ]
                },
                "response_metadata": {"next_cursor": "page-2"},
            }
        return {"ok": True, "results": {"messages": _messages([CHATTER], prefix=f"{query_key}-2")}}

    return api_call


def _rank(*, state: dict[str, Any], questions: dict[str, NoulQuestion]) -> SystemOneResult:
    def probability(content: str) -> float:
        return {SECRET_MESSAGE: 0.9, SIGNUP_MESSAGE: 0.7}.get(content, 0.1)

    messages = state["messages"]
    return SystemOneResult(
        model="jev",
        answers={key: NoulAnswer(probability=probability(messages[key])) for key in questions},
        input_tokens=None,
    )


def _written(suggestions: list[dict[str, Any]]) -> MagicMock:
    completion = MagicMock()
    completion.choices[0].message.content = json.dumps(
        {"intro": "Looks like your week is about churn and signups.", "suggestions": suggestions}
    )
    return completion


@pytest.fixture
def slack(org_team_user) -> Iterator[dict[str, MagicMock]]:
    allowed = BucketDecision(allowed=True, remaining=9, limit=10, retry_after=0, reset=0)
    with (
        patch(f"{WORK_FOCUS}.SlackWebClient") as search_client,
        patch(f"{WORK_FOCUS}.build_system_one_client") as ranker,
        patch(f"{WORK_FOCUS}.build_ai_gateway_openai_client") as writer,
        patch(f"{WORK_FOCUS}.consume", return_value=allowed) as bucket,
        patch(f"{WORK_FOCUS}.refund") as refunded,
        patch(f"{WORK_FOCUS}.capture_slack_event"),
        patch("posthog.models.integration.slack.WebClient") as bot_client,
    ):
        search_client.return_value.api_call.side_effect = _search(found=6)
        ranker.return_value.decide.side_effect = _rank
        writer.return_value.with_options.return_value.chat.completions.create.return_value = _written(
            [
                {"offer": "Churn by plan looks off in #product. Want me to dig in?", "request": REQUEST, "source": 1},
                {
                    "offer": "Signups dropped after the release. Want me to check?",
                    "request": "Check signups.",
                    "source": 2,
                },
            ]
        )
        yield {
            "search": search_client,
            "ranker": ranker,
            "writer": writer,
            "bucket": bucket,
            "refund": refunded,
            "bot": bot_client.return_value,
        }


@pytest.mark.django_db
def test_jev_picks_the_messages_and_only_those_reach_the_writer(
    org_team_user, link_user, slack: dict[str, MagicMock]
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes="search:read.public search:read.im users:read")

    assert find_and_send_work_focus(integration, SLACK_USER_ID) == "sent"
    assert find_and_send_work_focus(integration, SLACK_USER_ID) == "already_done"

    searches = slack["search"].return_value.api_call.call_args_list
    assert len(searches) == 4
    # All six calls are reserved at once, and the two the search did not need go back.
    assert slack["bucket"].call_args.kwargs["cost"] == 6
    assert slack["refund"].call_args.args[2] == 2
    assert [call.kwargs["params"].get("cursor") for call in searches] == [None, "page-2", None, "page-2"]
    assert {call.kwargs["params"]["channel_types"] for call in searches} == {"public_channel,im"}
    assert slack["ranker"].call_args.kwargs["privacy_mode"] is True
    # Both calls bill the team's PostHog AI credits, and say which run made them.
    assert slack["ranker"].call_args.kwargs["ai_product"] == "slack_app"
    assert slack["ranker"].call_args.kwargs["properties"]["slack_app_flow"] == "slack_app_onboarding"
    assert slack["writer"].call_args.kwargs["ai_product"] == "slack_app"
    assert slack["writer"].call_args.kwargs["properties"]["slack_app_flow"] == "slack_app_onboarding"
    create = slack["writer"].return_value.with_options.return_value.chat.completions.create
    assert create.call_args.kwargs["extra_headers"] == {"X-PostHog-Privacy-Mode": "true"}
    written_from = create.call_args.kwargs["messages"][1]["content"]
    assert SECRET_MESSAGE in written_from and SIGNUP_MESSAGE in written_from
    assert CHATTER not in written_from and "bot noise" not in written_from
    dm = slack["bot"].chat_postMessage.call_args.kwargs
    assert dm["channel"] == SLACK_USER_ID
    assert action_ids(dm["blocks"]) == ["slack_onboarding:work_focus_task"] * 2
    shown = all_block_text(dm["blocks"])
    assert "Looks like your week is about churn and signups." in shown
    # The DM stays short: no message previews, and the full request rides in the button.
    assert dm["unfurl_links"] is False and dm["unfurl_media"] is False
    assert REQUEST not in shown and REQUEST in json.dumps(dm["blocks"])
    # The suggestion links the message Jev ranked first, which the writer named as its source.
    # Each suggestion links its message as a nested line: the person's own message, or the thread with the author.
    assert "◦ <https://example.slack.com/archives/C1/pmine0|Your message> in #product" in shown
    assert "◦ <https://example.slack.com/archives/C1/pmentions0|Here's the thread> with <@U_ANDY> in #product" in shown
    stored = SlackSettings.objects.get(slack_workspace_id=SLACK_TEAM_ID, slack_user_id=SLACK_USER_ID).onboarding
    assert isinstance(stored, dict) and stored["work_focus_outcome"] == "sent"
    assert SECRET_MESSAGE not in json.dumps(stored)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "outcome, scopes, found, writer_fails",
    [
        ("no_search_scope", "users:read", 6, False),
        ("not_enough_messages", "search:read.public", 3, False),
        ("nothing_actionable", "search:read.public", 5, False),
    ],
)
def test_sends_nothing_without_a_usable_search_or_answer(
    outcome: str, scopes: str, found: int, writer_fails: bool, org_team_user, link_user, slack: dict[str, MagicMock]
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes=scopes)
    slack["search"].return_value.api_call.side_effect = _search(found=found)
    if outcome == "nothing_actionable":
        slack["ranker"].return_value.decide.side_effect = None
        slack["ranker"].return_value.decide.return_value = SystemOneResult(model="jev", answers={}, input_tokens=None)
    if writer_fails:
        slack["writer"].return_value.with_options.return_value.chat.completions.create.side_effect = TimeoutError()

    assert find_and_send_work_focus(integration, SLACK_USER_ID) == outcome

    slack["bot"].chat_postMessage.assert_not_called()
    state = resolve_onboarding(SLACK_TEAM_ID, SLACK_USER_ID)
    assert state is not None and state.work_focus_at is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "reason", ["rate_limited", "no_project_access", "no_ai_consent", "out_of_ai_credits", "model_failed"]
)
def test_runs_that_cannot_finish_yet_store_nothing_so_they_run_later(
    reason: str, org_team_user, link_user, slack: dict[str, MagicMock]
) -> None:
    org, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes="search:read.public")
    if reason == "rate_limited":
        slack["bucket"].return_value = BucketDecision(allowed=False, remaining=0, limit=10, retry_after=6, reset=60)
        with pytest.raises(WorkFocusRateLimited):
            find_and_send_work_focus(integration, SLACK_USER_ID)
    elif reason == "no_project_access":
        OrganizationMembership.objects.filter(user=user).delete()
        assert find_and_send_work_focus(integration, SLACK_USER_ID) == "no_project_access"
    elif reason == "no_ai_consent":
        Organization.objects.filter(id=org.id).update(is_ai_data_processing_approved=False)
        assert find_and_send_work_focus(integration, SLACK_USER_ID) == "no_ai_consent"
    elif reason == "out_of_ai_credits":
        with patch("ee.billing.quota_limiting.is_team_over_ai_credit_budget", return_value=True):
            assert find_and_send_work_focus(integration, SLACK_USER_ID) == "out_of_ai_credits"
    else:
        slack["writer"].return_value.with_options.return_value.chat.completions.create.side_effect = TimeoutError()
        with pytest.raises(WorkFocusTransientError):
            find_and_send_work_focus(integration, SLACK_USER_ID)

    assert slack["search"].return_value.api_call.called is (reason == "model_failed")
    slack["bot"].chat_postMessage.assert_not_called()
    assert resolve_onboarding(SLACK_TEAM_ID, SLACK_USER_ID) is None


@pytest.mark.django_db
def test_a_dm_that_may_have_gone_out_is_never_sent_twice(org_team_user, link_user, slack: dict[str, MagicMock]) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes="search:read.public")
    slack["bot"].chat_postMessage.side_effect = TimeoutError()

    with pytest.raises(TimeoutError):
        find_and_send_work_focus(integration, SLACK_USER_ID)
    assert find_and_send_work_focus(integration, SLACK_USER_ID) == "already_done"

    slack["bot"].chat_postMessage.assert_called_once()


@pytest.mark.django_db
@override_settings(DEBUG=True)
@patch("products.slack_app.backend.api.SlackIntegration")
def test_do_it_shows_the_request_and_only_start_runs_it_once(mock_slack_cls: MagicMock, org_team_user) -> None:
    _, team, user = org_team_user
    cache.clear()
    integration = _install(team)
    secret = "work-focus-test-secret"
    mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": secret}
    bot = mock_slack_cls.return_value.client
    bot.chat_postMessage.return_value = {"channel": "D1", "ts": "1700.1"}
    source = "https://example.slack.com/archives/C1/p1"
    focus = WorkFocus(
        intro="Looks like your week is about churn.",
        suggestions=[
            WorkFocusSuggestion(
                offer="Want me to dig in?",
                request=REQUEST,
                source_permalink=source,
                source_author_id="U_ANDY",
                source_channel_name="product",
            ),
            WorkFocusSuggestion(offer="Want me to check signups?", request="Check signups."),
        ],
    )
    blocks = work_focus_blocks(integration, focus, SLACK_USER_ID)

    def click(message_ts: str, message_blocks: list[dict], button: dict, block_id: str | None = None) -> None:
        payload = {
            "type": "block_actions",
            "team": {"id": SLACK_TEAM_ID},
            "user": {"id": SLACK_USER_ID},
            "container": {"type": "message", "channel_id": "D1", "message_ts": message_ts},
            "message": {"ts": message_ts, "text": "dm", "blocks": message_blocks},
            "actions": [{"action_id": button["action_id"], "block_id": block_id, "value": button["value"]}],
        }
        body = f"payload={json.dumps(payload)}"
        signed = sign_slack_request(body.encode(), secret)
        response = APIClient().post(
            "/slack/interactivity-callback/",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"x-slack-signature": signed.signature, "x-slack-request-timestamp": signed.timestamp},
        )
        assert response.status_code == 200

    with (
        patch("products.slack_app.backend.api._is_org_member", return_value=user),
        patch("products.slack_app.backend.api._can_access_team", return_value=True),
        patch("products.slack_app.backend.api._start_mention_workflow") as start,
        patch("products.slack_app.backend.api.capture_slack_event"),
    ):
        for _ in range(2):
            click("1690.1", blocks, blocks[1]["accessory"], blocks[1]["block_id"])
        # The model writes the request from other people's messages too, so nothing runs before the person reads it.
        start.assert_not_called()
        bot.chat_postMessage.assert_called_once()
        review = bot.chat_postMessage.call_args.kwargs
        shown = all_block_text(review["blocks"])
        assert REQUEST in shown and f"<{source}|Here's the thread> with <@U_ANDY> in #product" in shown
        assert review["unfurl_links"] is False
        opened = bot.chat_update.call_args.kwargs["blocks"]
        assert "accessory" not in opened[1] and "Opened below" in opened[1]["text"]["text"]
        assert "accessory" in opened[2]

        start_button = review["blocks"][-1]["elements"][0]
        for _ in range(2):
            click("1700.1", review["blocks"], start_button, "review_actions")

    start.assert_called_once()
    assert start.call_args.args[0] == {
        "type": "message",
        "user": SLACK_USER_ID,
        "channel": "D1",
        "ts": "1700.1",
        "thread_ts": "1700.1",
        "text": f"{REQUEST}\n\nThe Slack message this came from: {source}",
    }
    started = bot.chat_update.call_args.kwargs["blocks"]
    assert all(block["type"] != "actions" for block in started) and "Started" in all_block_text(started)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "chose_before, quiet, turns_on",
    [
        (None, False, True),
        # A quiet search sends no DM, but the link step promised the daily runs, so they still start.
        (None, True, True),
        (False, False, False),
    ],
)
def test_the_onboarding_turns_the_daily_work_focus_on_unless_the_person_chose(
    chose_before: bool | None, quiet: bool, turns_on: bool, org_team_user, link_user, slack: dict[str, MagicMock]
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes="search:read.public")
    if chose_before is not None:
        SlackDailyFocus.objects.for_team(team.id).create(
            team=team, slack_workspace_id=SLACK_TEAM_ID, slack_user_id=SLACK_USER_ID, integration_id=integration.id
        )

    if quiet:
        slack["ranker"].return_value.decide.side_effect = None
        slack["ranker"].return_value.decide.return_value = SystemOneResult(model="jev", answers={}, input_tokens=None)

    with patch(f"{WORK_FOCUS}.is_slack_app_daily_work_focus_enabled", return_value=True):
        outcome = find_and_send_work_focus(integration, SLACK_USER_ID)

    assert resolve_daily_focus(SLACK_TEAM_ID, SLACK_USER_ID).enabled is turns_on
    if quiet:
        assert outcome == "nothing_actionable"
        slack["bot"].chat_postMessage.assert_not_called()
        return
    assert outcome == "sent"
    dm = slack["bot"].chat_postMessage.call_args.kwargs
    assert (DAILY_FOCUS_OFF_ACTION_ID in action_ids(dm["blocks"])) is turns_on


SINCE = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)


def _turn_on_daily(integration: WorkspaceIntegration) -> None:
    SlackDailyFocus.objects.for_team(integration.team_id).create(
        team_id=integration.team_id,
        slack_workspace_id=SLACK_TEAM_ID,
        slack_user_id=SLACK_USER_ID,
        integration_id=integration.id,
        next_run_at=datetime(2026, 11, 9, 8, 0, tzinfo=UTC),
    )


@pytest.mark.django_db
def test_a_daily_run_reads_since_the_last_run_and_sends_once(
    org_team_user, link_user, slack: dict[str, MagicMock]
) -> None:
    _, team, user = org_team_user
    cache.clear()
    integration = _install(team)
    link_user(user, user_scopes="search:read.public")
    _turn_on_daily(integration)
    # The sweep claimed Monday's run and scheduled Tuesday's with the cached profile, which has no timezone yet.
    SlackDailyFocus.objects.unscoped().update(
        last_run_at=datetime(2026, 11, 9, 8, 0, tzinfo=UTC), next_run_at=datetime(2026, 11, 10, 8, 0, tzinfo=UTC)
    )
    SlackUserProfileCache.objects.create(
        integration_id=integration.id,
        slack_user_id=SLACK_USER_ID,
        tz="",
        refreshed_at=datetime(2026, 11, 9, 8, 30, tzinfo=UTC),
    )
    slack["bot"].users_info.return_value = {"ok": True, "user": {"tz": "America/New_York"}}

    with (
        patch(f"{WORK_FOCUS}.is_slack_app_daily_work_focus_enabled", return_value=True),
        patch(f"{WORK_FOCUS}.SlackIntegration") as bot_integration,
        time_machine.travel(datetime(2026, 11, 9, 9, 0, tzinfo=UTC), tick=False),
    ):
        bot_integration.return_value.missing_scopes.return_value = frozenset()
        assert find_and_send_daily_focus(integration, SLACK_USER_ID, since=SINCE) == "sent"
        assert find_and_send_daily_focus(integration, SLACK_USER_ID, since=SINCE) == "already_sent"

    searches = slack["search"].return_value.api_call.call_args_list
    assert {call.kwargs["params"]["after"] for call in searches} == {int(SINCE.timestamp())}
    bot_integration.return_value.client.chat_postMessage.assert_called_once()
    blocks = bot_integration.return_value.client.chat_postMessage.call_args.kwargs["blocks"]
    assert action_ids(blocks)[-1] == DAILY_FOCUS_OFF_ACTION_ID
    assert "I read your messages since Friday" in all_block_text(blocks)
    assert "(America/New_York)" in all_block_text(blocks)
    assert slack["writer"].call_args.kwargs["properties"]["slack_app_flow"] == "slack_app_daily_focus"
    # The run fetched the timezone again, so Tuesday's run moves to 09:00 in New York.
    assert SlackDailyFocus.objects.unscoped().get().next_run_at == datetime(2026, 11, 10, 14, 0, tzinfo=UTC)


@pytest.mark.django_db
@pytest.mark.parametrize("reason", ["quiet_day", "turned_off", "flag_off", "no_project_access", "out_of_ai_credits"])
def test_a_daily_run_sends_nothing_when_it_cannot_or_need_not_run(
    reason: str, org_team_user, link_user, slack: dict[str, MagicMock]
) -> None:
    _, team, user = org_team_user
    cache.clear()
    integration = _install(team)
    link_user(user, user_scopes="search:read.public")
    _turn_on_daily(integration)
    if reason == "turned_off":
        SlackDailyFocus.objects.unscoped().update(next_run_at=None)
    if reason == "no_project_access":
        OrganizationMembership.objects.filter(user=user).delete()
    if reason == "quiet_day":
        slack["ranker"].return_value.decide.side_effect = None
        slack["ranker"].return_value.decide.return_value = SystemOneResult(model="jev", answers={}, input_tokens=None)

    with (
        patch(f"{WORK_FOCUS}.is_slack_app_daily_work_focus_enabled", return_value=reason != "flag_off"),
        patch("ee.billing.quota_limiting.is_team_over_ai_credit_budget", return_value=reason == "out_of_ai_credits"),
        patch(f"{WORK_FOCUS}.SlackIntegration") as bot_integration,
    ):
        bot_integration.return_value.missing_scopes.return_value = frozenset()
        outcome = find_and_send_daily_focus(integration, SLACK_USER_ID, since=SINCE)

    assert outcome == {"quiet_day": "nothing_actionable"}.get(reason, reason)
    # Only a quiet day got as far as reading Slack. The others spend no search calls and no AI credits.
    assert slack["search"].return_value.api_call.called is (reason == "quiet_day")
    bot_integration.return_value.client.chat_postMessage.assert_not_called()


@pytest.mark.django_db
@override_settings(DEBUG=True)
@patch("products.slack_app.backend.api.SlackIntegration")
def test_turn_off_in_the_dm_stops_the_daily_work_focus_and_says_so(mock_slack_cls: MagicMock, org_team_user) -> None:
    _, team, _ = org_team_user
    integration = _install(team)
    _turn_on_daily(integration)
    secret = "daily-focus-test-secret"
    mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": secret}
    footer = daily_focus_footer_block(integration, time(9, 0), ZoneInfo("Europe/Prague"), first=False)
    payload = {
        "type": "block_actions",
        "team": {"id": SLACK_TEAM_ID},
        "user": {"id": SLACK_USER_ID},
        "container": {"type": "message", "channel_id": "D1", "message_ts": "1700.1"},
        "message": {"ts": "1700.1", "text": "dm", "blocks": [footer]},
        "actions": [{"action_id": DAILY_FOCUS_OFF_ACTION_ID, "value": footer["accessory"]["value"]}],
    }
    body = f"payload={json.dumps(payload)}"
    signed = sign_slack_request(body.encode(), secret)

    with patch("products.slack_app.backend.logic.daily_focus.capture_slack_event"):
        response = APIClient().post(
            "/slack/interactivity-callback/",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers={"x-slack-signature": signed.signature, "x-slack-request-timestamp": signed.timestamp},
        )

    assert response.status_code == 200
    assert resolve_daily_focus(SLACK_TEAM_ID, SLACK_USER_ID).enabled is False
    updated = mock_slack_cls.return_value.client.chat_update.call_args.kwargs["blocks"]
    assert action_ids(updated) == [] and "daily work focus is off" in all_block_text(updated)
