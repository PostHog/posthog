"""Clicks save at once and only signal the workflow, to answer Slack within 3 seconds."""

from typing import Any

from django.http import HttpResponse

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.onboarding.actions import (
    CONTINUE_ACTION_ID,
    SKIP_ACTION_ID,
    SOURCES_ACTION_ID,
    SOURCES_BLOCK_PREFIX,
    is_onboarding_action,
    read_action_value,
)
from products.slack_app.backend.logic.onboarding.dispatch import request_onboarding
from products.slack_app.backend.logic.onboarding.step import OnboardingContext, StepClick
from products.slack_app.backend.logic.onboarding.steps import ONBOARDING_STEPS, STEPS_BY_KEY
from products.slack_app.backend.services.inbox_interactivity import post_response_url
from products.slack_app.backend.services.slack_settings import update_onboarding
from products.slack_app.backend.services.workspace_integrations import get_workspace_integration

# pinned: analytics event name, renaming breaks dashboards
STEP_SKIPPED_EVENT = "slack app onboarding step skipped"


def _sources_value(action: dict[str, Any]) -> dict[str, Any] | None:
    prefix, _, integration_id = str(action.get("block_id") or "").partition(":")
    if prefix != SOURCES_BLOCK_PREFIX or not integration_id.isdigit():
        return None
    selected = [str(option.get("value")) for option in action.get("selected_options") or []]
    return {"integration_id": int(integration_id), "selected": selected}


def _clicked_action(payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for action in payload.get("actions") or []:
        action_id = action.get("action_id")
        if is_onboarding_action(action_id):
            value = _sources_value(action) if action_id == SOURCES_ACTION_ID else read_action_value(action)
            if value is not None:
                return action_id, value
    return None


def onboarding_integration_hint(payload: dict[str, Any]) -> int | None:
    clicked = _clicked_action(payload)
    integration_id = clicked[1].get("integration_id") if clicked else None
    return integration_id if isinstance(integration_id, int) else None


def _apply(ctx: OnboardingContext, action_id: str, value: dict[str, Any]) -> StepClick:
    if action_id in (SKIP_ACTION_ID, CONTINUE_ACTION_ID):
        step = STEPS_BY_KEY.get(str(value.get("step")))
        if step is None or not step.skippable:
            return StepClick(refresh=False)
        # Continue closes the step. When the person did nothing in it, that counts as a skip.
        if action_id == SKIP_ACTION_ID or not step.is_done(ctx):
            update_onboarding(ctx.integration.integration_id, ctx.slack_user_id, skip_step=step.key)
            capture_slack_event(ctx.integration, STEP_SKIPPED_EVENT, slack_user_id=ctx.slack_user_id, step=step.key)
        return StepClick()
    for step in ONBOARDING_STEPS:
        if step.handles(action_id):
            return step.apply_action(ctx, action_id, value)
    return StepClick(refresh=False)


def handle_onboarding_action(payload: dict[str, Any]) -> HttpResponse:
    clicked = _clicked_action(payload)
    integration_id = clicked[1].get("integration_id") if clicked else None
    slack_team_id = (payload.get("team") or {}).get("id", "")
    # The card sits in the person's own DM with PostHog, so the clicker is the person it is for.
    slack_user_id = (payload.get("user") or {}).get("id", "")
    integration = get_workspace_integration(integration_id, slack_team_id) if integration_id else None
    if clicked is None or integration is None or not slack_user_id:
        return HttpResponse(status=200)

    result = _apply(OnboardingContext(integration=integration, slack_user_id=slack_user_id), *clicked)
    if result.message is not None:
        post_response_url(
            payload.get("response_url") or "",
            {"response_type": "ephemeral", "replace_original": False, "text": result.message},
        )
    if result.refresh:
        request_onboarding(integration, slack_user_id, may_start=False)
    return HttpResponse(status=200)
