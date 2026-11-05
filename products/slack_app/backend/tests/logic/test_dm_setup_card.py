import json
from collections.abc import Iterator

import pytest
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError

from posthog.models.integration import Integration

from products.slack_app.backend.logic.dm_setup import dispatch
from products.slack_app.backend.logic.dm_setup.card import edit_dm_setup_message, plan_dm_setup, post_dm_setup_message
from products.slack_app.backend.logic.dm_setup.interactivity import dm_setup_integration_hint, handle_dm_setup_action
from products.slack_app.backend.models import UntaggedFollowupMode
from products.slack_app.backend.services.slack_settings import (
    resolve_auto_model_choice,
    resolve_dm_setup_card,
    resolve_untagged_followup_mode,
    set_auto_model_choice,
    set_untagged_followup_mode,
    update_dm_setup_card,
)
from products.slack_app.backend.services.workspace_integrations import (
    WorkspaceIntegration,
    require_workspace_integration,
)
from products.slack_app.backend.temporal.slack_dm_setup import SLACK_DM_SETUP_MAX_PLANS_PER_REFRESH
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID
from products.slack_app.backend.tests.helpers import all_block_text

CARD = "products.slack_app.backend.logic.dm_setup.card"
CLICKS = "products.slack_app.backend.logic.dm_setup.interactivity"
LINK_SCOPES = "chat:write,users:read,users:read.email"


def _install(team, scope: str = LINK_SCOPES) -> WorkspaceIntegration:
    row = Integration.objects.create(
        team=team,
        kind="slack",
        integration_id=SLACK_TEAM_ID,
        config={"scope": scope},
        sensitive_config={"access_token": "xoxb-test"},
    )
    return require_workspace_integration(row.id, SLACK_TEAM_ID)


def _click(integration: WorkspaceIntegration, action_id: str, **value: str) -> dict:
    encoded = json.dumps({"integration_id": integration.id, **value})
    action = (
        {"action_id": action_id, "selected_option": {"value": encoded}}
        if action_id == "slack_dm_setup:model"
        else {"action_id": action_id, "value": encoded}
    )
    return {
        "type": "block_actions",
        "team": {"id": SLACK_TEAM_ID},
        "user": {"id": SLACK_USER_ID},
        "response_url": "https://hooks.slack.example/response",
        "actions": [action],
    }


@pytest.fixture
def slack_client() -> Iterator[MagicMock]:
    with patch("posthog.models.integration.slack.WebClient") as web_client:
        client = web_client.return_value
        posted = iter(range(1, 100))
        client.chat_postMessage.side_effect = lambda **_: {"channel": "D1", "ts": f"100.{next(posted)}"}
        yield client


@pytest.fixture
def capture() -> Iterator[MagicMock]:
    with patch(f"{CARD}.capture_slack_event") as mock_capture:
        yield mock_capture


def _refresh(integration: WorkspaceIntegration) -> bool:
    for _ in range(SLACK_DM_SETUP_MAX_PLANS_PER_REFRESH):
        plan = plan_dm_setup(integration, SLACK_USER_ID)
        for edit in plan.edits:
            edit_dm_setup_message(integration, SLACK_USER_ID, edit)
        if plan.post is not None:
            post_dm_setup_message(integration, SLACK_USER_ID, plan.post)
        if not plan.plan_again:
            return plan.finished
    return False


def _posts(slack_client: MagicMock) -> list[dict]:
    return [call.kwargs for call in slack_client.chat_postMessage.call_args_list]


def _edits(slack_client: MagicMock) -> dict[str, str]:
    return {
        call.kwargs["ts"]: all_block_text(call.kwargs["blocks"]) for call in slack_client.chat_update.call_args_list
    }


@pytest.mark.django_db
def test_first_open_starts_a_thread_with_the_first_step_and_later_refreshes_post_nothing_new(
    org_team_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, _ = org_team_user
    integration = _install(team)

    assert _refresh(integration) is False
    assert _refresh(integration) is False

    root, step = _posts(slack_client)
    assert root["channel"] == SLACK_USER_ID and "thread_ts" not in root
    assert "0 of 3 steps done" in all_block_text(root["blocks"])
    assert (step["channel"], step["thread_ts"]) == ("D1", "100.1")
    assert f"<@{SLACK_USER_ID}> Step 1 of 3" in all_block_text(step["blocks"])
    assert "Link your PostHog account" in all_block_text(step["blocks"])
    # The second refresh only renders the shown step again, which keeps its link fresh.
    assert list(_edits(slack_client)) == ["100.2"]
    assert [call.args[1] for call in capture.call_args_list] == [
        "slack app dm setup started",
        "slack app dm setup step shown",
    ]


@pytest.mark.django_db
def test_person_with_nothing_to_set_up_gets_no_thread(
    org_team_user, link_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user)
    set_auto_model_choice(SLACK_TEAM_ID, SLACK_USER_ID, True)
    set_untagged_followup_mode(SLACK_TEAM_ID, SLACK_USER_ID, UntaggedFollowupMode.ASK)

    assert _refresh(integration) is True

    slack_client.chat_postMessage.assert_not_called()
    state = resolve_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID)
    assert state is not None and state.completed and state.root_ts is None
    capture.assert_not_called()


@pytest.mark.django_db
def test_each_step_is_a_new_reply_and_done_steps_shrink_to_one_line(
    org_team_user, link_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    _refresh(integration)

    link_user(user)
    _refresh(integration)
    model_step = _posts(slack_client)[-1]
    edits_after_link = _edits(slack_client)
    update_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID, skip_step="model")
    assert plan_dm_setup(integration, SLACK_USER_ID).status == (
        "2 of 3 steps done · current step: replies_in_threads · skipped: model"
    )
    set_untagged_followup_mode(SLACK_TEAM_ID, SLACK_USER_ID, UntaggedFollowupMode.AUTO)
    capture.reset_mock()
    finished = _refresh(integration)

    assert "Step 2 of 3" in all_block_text(model_step["blocks"]) and model_step["thread_ts"] == "100.1"
    assert ":white_check_mark: PostHog account linked" in edits_after_link["100.2"]
    assert "Link account" not in edits_after_link["100.2"]
    assert "1 of 3 steps done" in edits_after_link["100.1"]
    ready = _posts(slack_client)[-1]
    edits = _edits(slack_client)
    assert finished is True
    assert ready["thread_ts"] == "100.1"
    assert "You skipped: Your model" in all_block_text(ready["blocks"])
    assert "Skipped: Your model" in edits["100.3"] and "Pick a model" not in edits["100.3"]
    assert "PostHog is set up" in edits["100.1"] and "3 of 3 steps done" in edits["100.1"]
    capture.assert_called_once_with(
        integration, "slack app dm setup completed", slack_user_id=SLACK_USER_ID, skipped_steps=["model"]
    )
    posts_before = slack_client.chat_postMessage.call_count
    assert _refresh(integration) is True
    assert slack_client.chat_postMessage.call_count == posts_before


@pytest.mark.django_db
@pytest.mark.parametrize(
    "action_id, value, check",
    [
        ("slack_dm_setup:auto_model", {}, lambda: resolve_auto_model_choice(SLACK_TEAM_ID, SLACK_USER_ID)),
        (
            "slack_dm_setup:replies:never",
            {"mode": "never"},
            lambda: resolve_untagged_followup_mode_for_test() == UntaggedFollowupMode.NEVER,
        ),
        ("slack_dm_setup:skip", {"step": "model"}, lambda: _skipped() == ("model",)),
    ],
)
def test_card_clicks_save_the_choice_and_refresh_the_card(action_id: str, value: dict, check, org_team_user) -> None:
    _, team, _ = org_team_user
    integration = _install(team)

    with patch(f"{CLICKS}.request_dm_setup_card_render") as refresh, patch(f"{CLICKS}.capture_slack_event"):
        response = handle_dm_setup_action(_click(integration, action_id, **value))

    assert response.status_code == 200
    assert check()
    refresh.assert_called_once_with(integration, SLACK_USER_ID, opened_dm=False)


@pytest.mark.django_db
def test_the_link_step_cannot_be_skipped(org_team_user) -> None:
    _, team, _ = org_team_user
    integration = _install(team)

    with patch(f"{CLICKS}.request_dm_setup_card_render"):
        handle_dm_setup_action(_click(integration, "slack_dm_setup:skip", step="link_account"))

    assert resolve_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID) is None


@pytest.mark.django_db
def test_a_model_that_cannot_be_saved_tells_the_person_why(org_team_user) -> None:
    _, team, _ = org_team_user
    integration = _install(team)
    model = "claude-opus-example"

    with (
        patch(f"{CLICKS}.offered_model_choices", return_value=[MagicMock(model=model)]),
        patch(f"{CLICKS}.set_personal_model", side_effect=ValidationError("Link your PostHog account first.")),
        patch(f"{CLICKS}.request_dm_setup_card_render") as refresh,
        patch(f"{CLICKS}.post_response_url") as reply,
    ):
        payload = _click(integration, "slack_dm_setup:model", model=model)
        assert dm_setup_integration_hint(payload) == integration.id
        handle_dm_setup_action(payload)

    assert reply.call_args.args[1]["text"] == "Link your PostHog account first."
    assert reply.call_args.args[1]["response_type"] == "ephemeral"
    refresh.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "stored, opened_dm, flag_on, starts",
    [
        ("none", True, True, True),
        ("none", True, False, False),
        ("none", False, True, False),
        ("open", False, False, True),
        ("completed", True, True, False),
    ],
)
def test_only_people_with_a_card_to_render_start_the_workflow(
    stored: str, opened_dm: bool, flag_on: bool, starts: bool, org_team_user
) -> None:
    _, team, _ = org_team_user
    integration = _install(team)
    if stored == "open":
        update_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID, root=("D1", "100.1"))
    elif stored == "completed":
        update_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID, completed=True)

    with (
        patch.object(dispatch, "is_slack_app_dm_setup_card_enabled", return_value=flag_on),
        patch.object(dispatch, "_signal_with_start") as start,
    ):
        dispatch.request_dm_setup_card_render(integration, SLACK_USER_ID, opened_dm=opened_dm)

    assert start.called is starts


def resolve_untagged_followup_mode_for_test() -> UntaggedFollowupMode:
    integration = require_workspace_integration(Integration.objects.get(integration_id=SLACK_TEAM_ID).id, SLACK_TEAM_ID)
    return resolve_untagged_followup_mode(integration, SLACK_USER_ID)


def _skipped() -> tuple[str, ...]:
    state = resolve_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID)
    return state.skipped if state else ()
