import json
from collections.abc import Iterator

import pytest
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError

from posthog.models.integration import Integration

from products.slack_app.backend.logic.dm_setup import dispatch
from products.slack_app.backend.logic.dm_setup.card import render_dm_setup_card
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
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID

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


def _block_text(blocks: list[dict]) -> str:
    texts = [block.get("text", {}).get("text", "") for block in blocks]
    texts += [element.get("text", "") for block in blocks for element in block.get("elements", [])]
    return "\n".join(text for text in texts if isinstance(text, str))


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
        client.chat_postMessage.return_value = {"channel": "D1", "ts": "111.1"}
        yield client


@pytest.fixture
def capture() -> Iterator[MagicMock]:
    with patch(f"{CARD}.capture_slack_event") as mock_capture:
        yield mock_capture


@pytest.mark.django_db
def test_first_render_posts_the_card_once_and_later_renders_edit_it(
    org_team_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, _ = org_team_user
    integration = _install(team)

    assert render_dm_setup_card(integration, SLACK_USER_ID) is False
    assert render_dm_setup_card(integration, SLACK_USER_ID) is False

    slack_client.chat_postMessage.assert_called_once()
    posted = slack_client.chat_postMessage.call_args.kwargs
    assert posted["channel"] == SLACK_USER_ID
    assert "step 1 of 3" in _block_text(posted["blocks"])
    assert "Link your PostHog account" in _block_text(posted["blocks"])
    updated = slack_client.chat_update.call_args.kwargs
    assert (updated["channel"], updated["ts"]) == ("D1", "111.1")
    state = resolve_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID)
    assert state is not None and (state.channel, state.ts, state.completed) == ("D1", "111.1", False)
    capture.assert_called_once_with(
        integration,
        "slack app dm setup card shown",
        slack_user_id=SLACK_USER_ID,
        pending_steps=["link_account", "model", "replies_in_threads"],
        step_count=3,
    )


@pytest.mark.django_db
def test_person_with_nothing_to_set_up_gets_no_card(
    org_team_user, link_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    link_user(user)
    set_auto_model_choice(SLACK_TEAM_ID, SLACK_USER_ID, True)
    set_untagged_followup_mode(SLACK_TEAM_ID, SLACK_USER_ID, UntaggedFollowupMode.ASK)

    assert render_dm_setup_card(integration, SLACK_USER_ID) is True

    slack_client.chat_postMessage.assert_not_called()
    state = resolve_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID)
    assert state is not None and state.completed and state.ts is None
    capture.assert_not_called()


@pytest.mark.django_db
def test_card_moves_through_the_steps_and_lists_skipped_ones_when_ready(
    org_team_user, link_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    render_dm_setup_card(integration, SLACK_USER_ID)
    link_user(user)

    render_dm_setup_card(integration, SLACK_USER_ID)
    model_card = _block_text(slack_client.chat_update.call_args.kwargs["blocks"])
    update_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID, skip_step="model")
    set_untagged_followup_mode(SLACK_TEAM_ID, SLACK_USER_ID, UntaggedFollowupMode.AUTO)
    capture.reset_mock()
    finished = render_dm_setup_card(integration, SLACK_USER_ID)

    assert "step 2 of 3" in model_card and "Choose your model" in model_card
    ready_card = _block_text(slack_client.chat_update.call_args.kwargs["blocks"])
    assert finished is True
    assert "You're all set" in ready_card
    assert "You skipped: Your model" in ready_card
    capture.assert_called_once_with(
        integration,
        "slack app dm setup completed",
        slack_user_id=SLACK_USER_ID,
        step_count=3,
        skipped_steps=["model"],
    )
    slack_client.chat_update.reset_mock()
    assert render_dm_setup_card(integration, SLACK_USER_ID) is True
    slack_client.chat_update.assert_not_called()


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
        update_dm_setup_card(SLACK_TEAM_ID, SLACK_USER_ID, channel="D1", ts="111.1", completed=False)
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
