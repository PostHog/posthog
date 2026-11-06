import json
from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from rest_framework.test import APIClient

from posthog.llm.system_one import NoulAnswer, NoulQuestion, SystemOneResult
from posthog.models import Organization
from posthog.models.integration import Integration
from posthog.token_bucket import BucketDecision

from products.slack_app.backend.logic.onboarding.work_focus import (
    WorkFocus,
    WorkFocusRateLimited,
    WorkFocusSuggestion,
    find_and_send_work_focus,
    work_focus_blocks,
)
from products.slack_app.backend.models import SlackSettings
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


def _messages(contents: list[str], *, prefix: str) -> list[dict[str, Any]]:
    return [
        {
            "channel_id": "C1",
            "channel_name": "product",
            "message_ts": f"{prefix}.{index}",
            "content": content,
            "permalink": f"https://example.slack.com/archives/C1/p{prefix}{index}",
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
                "results": {"messages": [*_messages(first, prefix=query_key), *bots]},
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
        patch(f"{WORK_FOCUS}.capture_slack_event"),
        patch("posthog.models.integration.slack.WebClient") as bot_client,
    ):
        search_client.return_value.api_call.side_effect = _search(found=6)
        ranker.return_value.decide.side_effect = _rank
        writer.return_value.with_options.return_value.chat.completions.create.return_value = _written(
            [{"offer": "Churn by plan looks off in #product. Want me to dig in?", "request": REQUEST, "source": 1}]
        )
        yield {
            "search": search_client,
            "ranker": ranker,
            "writer": writer,
            "bucket": bucket,
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
    assert [call.kwargs["params"].get("cursor") for call in searches] == [None, "page-2", None, "page-2"]
    assert {call.kwargs["params"]["channel_types"] for call in searches} == {"public_channel,im"}
    assert slack["ranker"].call_args.kwargs["privacy_mode"] is True
    create = slack["writer"].return_value.with_options.return_value.chat.completions.create
    assert create.call_args.kwargs["extra_headers"] == {"X-PostHog-Privacy-Mode": "true"}
    written_from = create.call_args.kwargs["messages"][1]["content"]
    assert SECRET_MESSAGE in written_from and SIGNUP_MESSAGE in written_from
    assert CHATTER not in written_from and "bot noise" not in written_from
    dm = slack["bot"].chat_postMessage.call_args.kwargs
    assert dm["channel"] == SLACK_USER_ID
    assert action_ids(dm["blocks"]) == ["slack_onboarding:work_focus_task"]
    shown = all_block_text(dm["blocks"])
    assert "Looks like your week is about churn and signups." in shown
    # The DM stays short: no message previews, and the full request rides in the button.
    assert dm["unfurl_links"] is False and dm["unfurl_media"] is False
    assert REQUEST not in shown and REQUEST in json.dumps(dm["blocks"])
    # The suggestion links the message Jev ranked first, which the writer named as its source.
    assert "<https://example.slack.com/archives/C1/pmine0|↗ message>" in shown
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
        ("model_failed", "search:read.public", 6, True),
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
@pytest.mark.parametrize("rate_limited", [True, False])
def test_runs_that_cannot_start_yet_store_nothing_so_they_run_later(
    rate_limited: bool, org_team_user, link_user, slack: dict[str, MagicMock]
) -> None:
    org, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes="search:read.public")
    if rate_limited:
        slack["bucket"].return_value = BucketDecision(allowed=False, remaining=0, limit=10, retry_after=6, reset=60)
        with pytest.raises(WorkFocusRateLimited):
            find_and_send_work_focus(integration, SLACK_USER_ID)
    else:
        Organization.objects.filter(id=org.id).update(is_ai_data_processing_approved=False)
        assert find_and_send_work_focus(integration, SLACK_USER_ID) == "no_ai_consent"

    slack["search"].return_value.api_call.assert_not_called()
    assert resolve_onboarding(SLACK_TEAM_ID, SLACK_USER_ID) is None


@pytest.mark.django_db
@override_settings(DEBUG=True)
@patch("products.slack_app.backend.api.SlackIntegration")
def test_a_suggestion_starts_its_request_in_a_new_dm_thread_once_and_loses_its_button(
    mock_slack_cls: MagicMock, org_team_user
) -> None:
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
            WorkFocusSuggestion(offer="Want me to dig in?", request=REQUEST, source_permalink=source),
            WorkFocusSuggestion(offer="Want me to check signups?", request="Check signups."),
        ],
    )
    blocks = work_focus_blocks(integration, focus)
    clicked = blocks[1]
    payload = {
        "type": "block_actions",
        "team": {"id": SLACK_TEAM_ID},
        "user": {"id": SLACK_USER_ID},
        "container": {"type": "message", "channel_id": "D1", "message_ts": "1690.1"},
        "message": {"ts": "1690.1", "text": focus.intro, "blocks": blocks},
        "actions": [
            {
                "action_id": clicked["accessory"]["action_id"],
                "block_id": clicked["block_id"],
                "value": clicked["accessory"]["value"],
            }
        ],
    }
    body = f"payload={json.dumps(payload)}"
    signed = sign_slack_request(body.encode(), secret)

    with (
        patch("products.slack_app.backend.api._is_org_member", return_value=user),
        patch("products.slack_app.backend.api._can_access_team", return_value=True),
        patch("products.slack_app.backend.api._start_mention_workflow") as start,
        patch("products.slack_app.backend.api.capture_slack_event"),
    ):
        for _ in range(2):
            response = APIClient().post(
                "/slack/interactivity-callback/",
                data=body,
                content_type="application/x-www-form-urlencoded",
                headers={"x-slack-signature": signed.signature, "x-slack-request-timestamp": signed.timestamp},
            )
            assert response.status_code == 200

    start.assert_called_once()
    assert start.call_args.args[0] == {
        "type": "message",
        "user": SLACK_USER_ID,
        "channel": "D1",
        "ts": "1700.1",
        "thread_ts": "1700.1",
        "text": f"{REQUEST}\n\nThe Slack message this came from: {source}",
    }
    starter = bot.chat_postMessage.call_args.kwargs
    assert REQUEST in starter["text"] and f"<{source}|" in starter["text"] and starter["unfurl_links"] is False
    bot.chat_update.assert_called_once()
    updated = bot.chat_update.call_args.kwargs["blocks"]
    assert "accessory" not in updated[1] and "Started" in updated[1]["text"]["text"]
    assert "accessory" in updated[2]
