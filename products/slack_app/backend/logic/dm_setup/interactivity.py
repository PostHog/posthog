"""Clicks save at once and only signal the workflow, to answer Slack within 3 seconds."""

from typing import Any

from django.core.exceptions import ValidationError
from django.http import HttpResponse

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.dm_setup.actions import (
    AUTO_MODEL_ACTION_ID,
    MODEL_ACTION_ID,
    REPLIES_ACTION_ID,
    SKIP_ACTION_ID,
    is_dm_setup_action,
    read_action_value,
)
from products.slack_app.backend.logic.dm_setup.dispatch import request_dm_setup_card_render
from products.slack_app.backend.logic.dm_setup.step import DmSetupStepKey
from products.slack_app.backend.logic.dm_setup.steps import DM_SETUP_STEPS
from products.slack_app.backend.models import UntaggedFollowupMode
from products.slack_app.backend.services.inbox_interactivity import post_response_url
from products.slack_app.backend.services.model_catalogue import offered_model_choices
from products.slack_app.backend.services.slack_app_home import set_personal_model
from products.slack_app.backend.services.slack_settings import (
    set_auto_model_choice,
    set_untagged_followup_mode,
    update_dm_setup_card,
)
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration, get_workspace_integration

SKIPPABLE_STEPS = frozenset(step.key for step in DM_SETUP_STEPS if step.skippable)
# pinned: analytics event names, renaming breaks dashboards
STEP_COMPLETED_EVENT = "slack app dm setup step completed"
STEP_SKIPPED_EVENT = "slack app dm setup step skipped"


def _clicked_action(payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for action in payload.get("actions") or []:
        action_id = action.get("action_id")
        if is_dm_setup_action(action_id):
            value = read_action_value(action)
            if value is not None:
                return action_id, value
    return None


def dm_setup_integration_hint(payload: dict[str, Any]) -> int | None:
    clicked = _clicked_action(payload)
    integration_id = clicked[1].get("integration_id") if clicked else None
    return integration_id if isinstance(integration_id, int) else None


def _apply(integration: WorkspaceIntegration, slack_user_id: str, action_id: str, value: dict[str, Any]) -> str | None:
    """Returns a message for the person when the choice cannot be saved."""
    slack_workspace_id = integration.integration_id
    if action_id == SKIP_ACTION_ID:
        step = value.get("step")
        if step not in SKIPPABLE_STEPS:
            return None
        update_dm_setup_card(slack_workspace_id, slack_user_id, skip_step=str(step))
        capture_slack_event(integration, STEP_SKIPPED_EVENT, slack_user_id=slack_user_id, step=str(step))
    elif action_id == AUTO_MODEL_ACTION_ID:
        set_auto_model_choice(slack_workspace_id, slack_user_id, True)
        capture_slack_event(
            integration, STEP_COMPLETED_EVENT, slack_user_id=slack_user_id, step=DmSetupStepKey.MODEL, choice="auto"
        )
    elif action_id == MODEL_ACTION_ID:
        model = value.get("model")
        if model not in {choice.model for choice in offered_model_choices()}:
            return "That model is no longer available. Pick another one."
        try:
            set_personal_model(integration, slack_user_id, str(model))
        except ValidationError as error:
            return error.messages[0]
        capture_slack_event(
            integration,
            STEP_COMPLETED_EVENT,
            slack_user_id=slack_user_id,
            step=DmSetupStepKey.MODEL,
            choice="model",
            model=str(model),
        )
    elif action_id.startswith(f"{REPLIES_ACTION_ID}:"):
        mode = value.get("mode")
        if mode not in UntaggedFollowupMode.values:
            return None
        set_untagged_followup_mode(slack_workspace_id, slack_user_id, UntaggedFollowupMode(mode))
        capture_slack_event(
            integration,
            STEP_COMPLETED_EVENT,
            slack_user_id=slack_user_id,
            step=DmSetupStepKey.REPLIES_IN_THREADS,
            choice=str(mode),
        )
    return None


def handle_dm_setup_action(payload: dict[str, Any]) -> HttpResponse:
    clicked = _clicked_action(payload)
    integration_id = clicked[1].get("integration_id") if clicked else None
    slack_team_id = (payload.get("team") or {}).get("id", "")
    # The card sits in the person's own DM with PostHog, so the clicker is the person it is for.
    slack_user_id = (payload.get("user") or {}).get("id", "")
    integration = get_workspace_integration(integration_id, slack_team_id) if integration_id else None
    if clicked is None or integration is None or not slack_user_id:
        return HttpResponse(status=200)

    error = _apply(integration, slack_user_id, *clicked)
    if error is not None:
        post_response_url(
            payload.get("response_url") or "",
            {"response_type": "ephemeral", "replace_original": False, "text": error},
        )
        return HttpResponse(status=200)
    request_dm_setup_card_render(integration, slack_user_id, opened_dm=False)
    return HttpResponse(status=200)
