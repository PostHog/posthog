import json
from collections.abc import Iterator
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

from rest_framework.test import APIClient

from posthog.models.integration import Integration
from posthog.token_bucket import BucketDecision

from products.slack_app.backend.logic.onboarding.work_focus import (
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
from products.slack_app.backend.tests.helpers import action_ids, sign_slack_request

WORK_FOCUS = "products.slack_app.backend.logic.onboarding.work_focus"
SECRET_MESSAGE = "the churn numbers for the enterprise plan look wrong again"


def _install(team) -> WorkspaceIntegration:
    row = Integration.objects.create(
        team=team,
        kind="slack",
        integration_id=SLACK_TEAM_ID,
        config={"scope": "chat:write"},
        sensitive_config={"access_token": "xoxb-test"},
    )
    return require_workspace_integration(row.id, SLACK_TEAM_ID)


def _search_results(count: int) -> dict[str, Any]:
    messages = [
        {
            "channel_id": "C1",
            "message_ts": f"1700000000.{index}",
            "content": SECRET_MESSAGE if index == 0 else f"message {index} about the signup funnel",
            "permalink": f"https://example.slack.com/archives/C1/p{index}",
            "is_author_bot": False,
        }
        for index in range(count)
    ]
    messages.append({"channel_id": "C1", "message_ts": "1", "content": "bot noise", "is_author_bot": True})
    return {"ok": True, "results": {"messages": messages}}


def _model_answer(suggestions: list[dict[str, Any]]) -> MagicMock:
    completion = MagicMock()
    completion.choices[0].message.content = json.dumps({"suggestions": suggestions})
    return completion


@pytest.fixture
def slack(org_team_user) -> Iterator[dict[str, MagicMock]]:
    allowed = BucketDecision(allowed=True, remaining=9, limit=10, retry_after=0, reset=0)
    with (
        patch(f"{WORK_FOCUS}.SlackWebClient") as search_client,
        patch(f"{WORK_FOCUS}.build_ai_gateway_openai_client") as model,
        patch(f"{WORK_FOCUS}.consume", return_value=allowed) as bucket,
        patch(f"{WORK_FOCUS}.capture_slack_event"),
        patch("posthog.models.integration.slack.WebClient") as bot_client,
    ):
        search_client.return_value.api_call.return_value = _search_results(6)
        model.return_value.with_options.return_value.chat.completions.create.return_value = _model_answer(
            [
                {"label": "Check the signup funnel", "prompt": "Why did signups drop last week?", "source": 2},
                {"label": "Find churn by plan", "prompt": "Show churn by plan for the last month", "source": 0},
            ]
        )
        yield {"search": search_client, "model": model, "bucket": bucket, "bot": bot_client.return_value}


@pytest.mark.django_db
def test_sends_suggestions_once_and_keeps_none_of_the_messages(
    org_team_user, link_user, slack: dict[str, MagicMock]
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes="search:read.public search:read.im users:read")

    assert find_and_send_work_focus(integration, SLACK_USER_ID) == "sent"
    assert find_and_send_work_focus(integration, SLACK_USER_ID) == "already_done"

    searches = slack["search"].return_value.api_call.call_args_list
    assert len(searches) == 2
    assert {call.kwargs["params"]["channel_types"] for call in searches} == {"public_channel,im"}
    create = slack["model"].return_value.with_options.return_value.chat.completions.create
    assert create.call_args.kwargs["extra_headers"] == {"X-PostHog-Privacy-Mode": "true"}
    assert "bot noise" not in create.call_args.kwargs["messages"][1]["content"]
    dm = slack["bot"].chat_postMessage.call_args.kwargs
    assert dm["channel"] == SLACK_USER_ID
    assert action_ids(dm["blocks"]).count("slack_onboarding:work_focus_task") == 2
    assert "https://example.slack.com/archives/C1/p1" in json.dumps(dm["blocks"])
    stored = SlackSettings.objects.get(slack_workspace_id=SLACK_TEAM_ID, slack_user_id=SLACK_USER_ID).onboarding
    assert isinstance(stored, dict) and stored["work_focus_outcome"] == "sent"
    assert SECRET_MESSAGE not in json.dumps(stored)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "outcome, scopes, found, model_fails",
    [
        ("no_search_scope", "users:read", 6, False),
        ("not_enough_messages", "search:read.public", 3, False),
        ("model_failed", "search:read.public", 6, True),
    ],
)
def test_sends_nothing_without_a_usable_search_or_answer(
    outcome: str, scopes: str, found: int, model_fails: bool, org_team_user, link_user, slack: dict[str, MagicMock]
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes=scopes)
    slack["search"].return_value.api_call.return_value = _search_results(found)
    if model_fails:
        slack["model"].return_value.with_options.return_value.chat.completions.create.side_effect = TimeoutError()

    assert find_and_send_work_focus(integration, SLACK_USER_ID) == outcome

    slack["bot"].chat_postMessage.assert_not_called()
    state = resolve_onboarding(SLACK_TEAM_ID, SLACK_USER_ID)
    assert state is not None and state.work_focus_at is not None


@pytest.mark.django_db
def test_a_workspace_out_of_search_calls_retries_later(org_team_user, link_user, slack: dict[str, MagicMock]) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user, user_scopes="search:read.public")
    slack["bucket"].return_value = BucketDecision(allowed=False, remaining=0, limit=10, retry_after=6, reset=60)

    with pytest.raises(WorkFocusRateLimited):
        find_and_send_work_focus(integration, SLACK_USER_ID)

    slack["search"].return_value.api_call.assert_not_called()
    assert resolve_onboarding(SLACK_TEAM_ID, SLACK_USER_ID) is None


@pytest.mark.django_db
@override_settings(DEBUG=True)
@patch("products.slack_app.backend.api.SlackIntegration")
def test_a_suggestion_starts_a_task_in_a_new_dm_thread_once(mock_slack_cls: MagicMock, org_team_user) -> None:
    _, team, user = org_team_user
    cache.clear()
    integration = _install(team)
    secret = "work-focus-test-secret"
    mock_slack_cls.slack_config.return_value = {"SLACK_APP_SIGNING_SECRET": secret}
    bot = mock_slack_cls.return_value.client
    bot.chat_postMessage.return_value = {"channel": "D1", "ts": "1700.1"}
    suggestion = WorkFocusSuggestion(
        label="Check the signup funnel", prompt="Why did signups drop?", source_permalink=None
    )
    button = work_focus_blocks(integration, [suggestion])[1]["accessory"]
    payload = {
        "type": "block_actions",
        "team": {"id": SLACK_TEAM_ID},
        "user": {"id": SLACK_USER_ID},
        "container": {"type": "message", "channel_id": "D1", "message_ts": "1690.1"},
        "actions": [{"action_id": button["action_id"], "value": button["value"]}],
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
        "text": "Why did signups drop?",
    }
