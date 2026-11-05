import json
from collections.abc import Iterator

import pytest
from unittest.mock import MagicMock, patch

from django.core.exceptions import ValidationError

from posthog.models import Organization, OrganizationMembership
from posthog.models.integration import Integration

from products.slack_app.backend.logic.feature_tips.state import get_state
from products.slack_app.backend.logic.onboarding import dispatch
from products.slack_app.backend.logic.onboarding.card import (
    edit_onboarding_message,
    plan_onboarding,
    post_onboarding_message,
)
from products.slack_app.backend.logic.onboarding.interactivity import (
    handle_onboarding_action,
    onboarding_integration_hint,
)
from products.slack_app.backend.models import UntaggedFollowupMode
from products.slack_app.backend.services.slack_settings import (
    resolve_auto_model_choice,
    resolve_onboarding,
    resolve_untagged_followup_mode,
    set_auto_model_choice,
    set_untagged_followup_mode,
    update_onboarding,
)
from products.slack_app.backend.services.workspace_integrations import (
    WorkspaceIntegration,
    require_workspace_integration,
)
from products.slack_app.backend.temporal.slack_app_onboarding import SLACK_APP_ONBOARDING_MAX_PLANS_PER_REFRESH
from products.slack_app.backend.tests.conftest import SLACK_TEAM_ID, SLACK_USER_ID
from products.slack_app.backend.tests.helpers import all_block_text

CARD = "products.slack_app.backend.logic.onboarding.card"
CLICKS = "products.slack_app.backend.logic.onboarding.interactivity"
STEP = "products.slack_app.backend.logic.onboarding.step"
MODEL_STEP = "products.slack_app.backend.logic.onboarding.model_step"
INBOX_STEP = "products.slack_app.backend.logic.onboarding.inbox_channel_step"
LINK_SCOPES = "chat:write,users:read,users:read.email"
ADMIN_SCOPES = f"{LINK_SCOPES},channels:manage,channels:read,groups:read"


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
        if action_id == "slack_onboarding:model"
        else {"action_id": action_id, "value": encoded}
    )
    return {
        "type": "block_actions",
        "team": {"id": SLACK_TEAM_ID},
        "user": {"id": SLACK_USER_ID},
        "response_url": "https://hooks.slack.example/response",
        "actions": [action],
    }


@pytest.fixture(autouse=True)
def slack_workspace_admin() -> Iterator[MagicMock]:
    with patch(f"{STEP}.is_slack_workspace_admin", return_value=False) as admin:
        yield admin


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
    for _ in range(SLACK_APP_ONBOARDING_MAX_PLANS_PER_REFRESH):
        plan = plan_onboarding(integration, SLACK_USER_ID)
        for edit in plan.edits:
            edit_onboarding_message(integration, SLACK_USER_ID, edit)
        if plan.post is not None:
            post_onboarding_message(integration, SLACK_USER_ID, plan.post)
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
    assert "1. :arrow_right: *Link your PostHog account*" in all_block_text(root["blocks"])
    assert (step["channel"], step["thread_ts"]) == ("D1", "100.1")
    assert f"<@{SLACK_USER_ID}> Step 1 of 3" in all_block_text(step["blocks"])
    assert "Link your PostHog account" in all_block_text(step["blocks"])
    # The second refresh only renders the shown step again, which keeps its link fresh.
    assert list(_edits(slack_client)) == ["100.2"]
    assert [call.args[1] for call in capture.call_args_list] == [
        "slack app onboarding started",
        "slack app onboarding step shown",
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
    state = resolve_onboarding(SLACK_TEAM_ID, SLACK_USER_ID)
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
    update_onboarding(SLACK_TEAM_ID, SLACK_USER_ID, skip_step="model")
    assert plan_onboarding(integration, SLACK_USER_ID).status == (
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
    assert "Hey, I'm PostHog" in edits["100.1"] and "Setup done" in edits["100.1"]
    capture.assert_called_once_with(
        integration, "slack app onboarding completed", slack_user_id=SLACK_USER_ID, skipped_steps=["model"]
    )
    posts_before = slack_client.chat_postMessage.call_count
    assert _refresh(integration) is True
    assert slack_client.chat_postMessage.call_count == posts_before


@pytest.mark.django_db
@pytest.mark.parametrize(
    "action_id, value, check",
    [
        ("slack_onboarding:auto_model", {}, lambda: resolve_auto_model_choice(SLACK_TEAM_ID, SLACK_USER_ID)),
        (
            "slack_onboarding:replies:never",
            {"mode": "never"},
            lambda: resolve_untagged_followup_mode_for_test() == UntaggedFollowupMode.NEVER,
        ),
        ("slack_onboarding:skip", {"step": "model"}, lambda: _skipped() == ("model",)),
    ],
)
def test_card_clicks_save_the_choice_and_refresh_the_card(action_id: str, value: dict, check, org_team_user) -> None:
    _, team, _ = org_team_user
    integration = _install(team)

    with patch(f"{CLICKS}.request_onboarding") as refresh, patch(f"{CLICKS}.capture_slack_event"):
        response = handle_onboarding_action(_click(integration, action_id, **value))

    assert response.status_code == 200
    assert check()
    refresh.assert_called_once_with(integration, SLACK_USER_ID, may_start=False)


@pytest.mark.django_db
def test_the_link_step_cannot_be_skipped(org_team_user) -> None:
    _, team, _ = org_team_user
    integration = _install(team)

    with patch(f"{CLICKS}.request_onboarding"):
        handle_onboarding_action(_click(integration, "slack_onboarding:skip", step="link_account"))

    assert resolve_onboarding(SLACK_TEAM_ID, SLACK_USER_ID) is None


@pytest.mark.django_db
def test_a_model_that_cannot_be_saved_tells_the_person_why(org_team_user) -> None:
    _, team, _ = org_team_user
    integration = _install(team)
    model = "claude-opus-example"

    with (
        patch(f"{MODEL_STEP}.offered_model_choices", return_value=[MagicMock(model=model)]),
        patch(f"{MODEL_STEP}.set_personal_model", side_effect=ValidationError("Link your PostHog account first.")),
        patch(f"{CLICKS}.request_onboarding") as refresh,
        patch(f"{CLICKS}.post_response_url") as reply,
    ):
        payload = _click(integration, "slack_onboarding:model", model=model)
        assert onboarding_integration_hint(payload) == integration.id
        handle_onboarding_action(payload)

    assert reply.call_args.args[1]["text"] == "Link your PostHog account first."
    assert reply.call_args.args[1]["response_type"] == "ephemeral"
    refresh.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "stored, may_start, flag_on, starts",
    [
        ("none", True, True, True),
        ("none", True, False, False),
        ("none", False, True, False),
        ("open", False, False, True),
        ("completed", True, True, False),
    ],
)
def test_only_people_with_onboarding_left_start_the_workflow(
    stored: str, may_start: bool, flag_on: bool, starts: bool, org_team_user
) -> None:
    _, team, _ = org_team_user
    integration = _install(team)
    if stored == "open":
        update_onboarding(SLACK_TEAM_ID, SLACK_USER_ID, root=("D1", "100.1"))
    elif stored == "completed":
        update_onboarding(SLACK_TEAM_ID, SLACK_USER_ID, completed_reason="finished")

    with (
        patch.object(dispatch, "is_slack_app_onboarding_enabled", return_value=flag_on),
        patch.object(dispatch, "_signal_with_start") as start,
    ):
        dispatch.request_onboarding(integration, SLACK_USER_ID, may_start=may_start)

    assert start.called is starts
    if stored == "none":
        state = resolve_onboarding(SLACK_TEAM_ID, SLACK_USER_ID)
        assert (state is not None and state.started_at is not None) is starts


@pytest.mark.django_db
def test_a_burst_of_new_members_spreads_the_starts_over_time(org_team_user) -> None:
    _, team, _ = org_team_user
    integration = _install(team)
    people = [f"U{index}" for index in range(dispatch.BURST_STARTS_PER_MINUTE + 1)]

    with (
        patch.object(dispatch, "is_slack_app_onboarding_enabled", return_value=True),
        patch.object(dispatch, "_signal_with_start") as start,
    ):
        for person in people:
            dispatch.request_onboarding(integration, person, may_start=True, spread_burst=True)
        dispatch.request_onboarding(integration, "U_OPENED_THE_DM", may_start=True)

    delays = [call.kwargs["start_delay_seconds"] for call in start.call_args_list]
    assert delays == [*[0] * dispatch.BURST_STARTS_PER_MINUTE, 60, 0]


def resolve_untagged_followup_mode_for_test() -> UntaggedFollowupMode:
    integration = require_workspace_integration(Integration.objects.get(integration_id=SLACK_TEAM_ID).id, SLACK_TEAM_ID)
    return resolve_untagged_followup_mode(integration, SLACK_USER_ID)


def _skipped() -> tuple[str, ...]:
    state = resolve_onboarding(SLACK_TEAM_ID, SLACK_USER_ID)
    return state.skipped if state else ()


@pytest.mark.django_db
def test_a_workspace_admin_also_gets_the_workspace_steps_after_linking(
    org_team_user, link_user, slack_workspace_admin: MagicMock, slack_client: MagicMock, capture: MagicMock
) -> None:
    org, team, user = org_team_user
    OrganizationMembership.objects.filter(user=user, organization=org).update(level=OrganizationMembership.Level.ADMIN)
    Organization.objects.filter(id=org.id).update(is_ai_data_processing_approved=False)
    integration = _install(team, scope=ADMIN_SCOPES)
    slack_workspace_admin.return_value = True

    _refresh(integration)
    link_user(user)
    _refresh(integration)

    assert plan_onboarding(integration, SLACK_USER_ID).status == (
        "1 of 7 steps done · current step: ai_consent · skipped: none"
    )
    second_step = all_block_text(_posts(slack_client)[-1]["blocks"])
    assert f"<@{SLACK_USER_ID}> Step 2 of 7" in second_step and "Allow AI data processing" in second_step


@pytest.mark.django_db
def test_steps_done_before_the_thread_are_left_out_of_the_numbering(
    org_team_user, link_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, user = org_team_user
    integration = _install(team)
    set_auto_model_choice(SLACK_TEAM_ID, SLACK_USER_ID, True)
    set_untagged_followup_mode(SLACK_TEAM_ID, SLACK_USER_ID, UntaggedFollowupMode.ASK)

    _refresh(integration)
    link_user(user)
    finished = _refresh(integration)

    root, link_step, ready = _posts(slack_client)
    assert "0 of 1 step done" in all_block_text(root["blocks"])
    assert f"<@{SLACK_USER_ID}> Step 1 of 1" in all_block_text(link_step["blocks"])
    assert finished is True and ready["thread_ts"] == "100.1"
    assert "Setup done" in _edits(slack_client)["100.1"]


@pytest.mark.django_db
def test_a_step_set_elsewhere_keeps_its_number_and_says_it_is_already_set(
    org_team_user, link_user, slack_client: MagicMock, capture: MagicMock
) -> None:
    _, team, user = org_team_user
    integration = _install(team)

    _refresh(integration)
    link_user(user)
    set_auto_model_choice(SLACK_TEAM_ID, SLACK_USER_ID, True)
    _refresh(integration)

    replies_step = all_block_text(_posts(slack_client)[-1]["blocks"])
    assert f"<@{SLACK_USER_ID}> Step 3 of 3" in replies_step
    assert "Step 2, Your model, is already set, so I skipped it." in replies_step
    root = _edits(slack_client)["100.1"]
    assert "2 of 3 steps done" in root and "2. :white_check_mark: Your model: already set" in root


@pytest.mark.django_db
@pytest.mark.parametrize(
    "action, org_admin, refreshes, message",
    [
        ("ai_consent", True, True, None),
        ("ai_consent", False, False, "Only an organization admin can allow AI data processing."),
        ("inbox_join", True, True, None),
        ("inbox_join_fails", True, False, "I couldn't add you to #posthog-inbox."),
        ("sources", True, False, None),
        ("continue", True, True, None),
    ],
)
def test_workspace_step_clicks(
    action: str, org_admin: bool, refreshes: bool, message: str | None, org_team_user, link_user
) -> None:
    org, team, user = org_team_user
    Organization.objects.filter(id=org.id).update(is_ai_data_processing_approved=False)
    if org_admin:
        OrganizationMembership.objects.filter(user=user, organization=org).update(
            level=OrganizationMembership.Level.ADMIN
        )
    link_user(user)
    integration = _install(team, scope=ADMIN_SCOPES)
    if action == "sources":
        payload = _click(integration, "slack_onboarding:sources")
        payload["actions"] = [
            {
                "action_id": "slack_onboarding:sources",
                "block_id": f"slack_onboarding_sources:{integration.id}",
                "selected_options": [{"value": "session_replay"}],
            }
        ]
    else:
        payload = _click(integration, f"slack_onboarding:{action.removesuffix('_fails')}", step="sources")

    with (
        patch(f"{CLICKS}.request_onboarding") as refresh,
        patch(f"{CLICKS}.post_response_url") as reply,
        patch(f"{CLICKS}.capture_slack_event"),
        patch(f"{STEP}.capture_slack_event"),
        patch(f"{INBOX_STEP}.ensure_inbox_channel", return_value=("C_INBOX", "#posthog-inbox")),
        patch(f"{INBOX_STEP}.invite_user_to_inbox", return_value=action != "inbox_join_fails") as invite,
        patch("products.signals.backend.facade.api.set_sources") as set_sources,
    ):
        handle_onboarding_action(payload)

    assert refresh.called is refreshes
    assert (reply.call_args.args[1]["text"].split(" Create")[0] if reply.called else None) == message
    if action == "ai_consent":
        org.refresh_from_db()
        assert org.is_ai_data_processing_approved is org_admin
    if action == "inbox_join":
        invite.assert_called_once_with(integration, "C_INBOX", SLACK_USER_ID)
        assert "inbox_channel" in get_state(SLACK_TEAM_ID, SLACK_USER_ID).used
    if action == "sources":
        set_sources.assert_called_once_with(team.id, user.id, ["session_replay"])
    if action == "continue":
        # Continue with no signal ticked closes the step, so the thread moves on.
        assert _skipped() == ("sources",)
