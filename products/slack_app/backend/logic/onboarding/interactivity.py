"""Clicks save at once and only signal the workflow, to answer Slack within 3 seconds."""

from typing import Any

from django.http import HttpResponse

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.logic.onboarding.actions import CONTINUE_ACTION_ID, SKIP_ACTION_ID, is_onboarding_action
from products.slack_app.backend.logic.onboarding.dispatch import request_onboarding
from products.slack_app.backend.logic.onboarding.step import (
    OnboardingContext,
    OnboardingStep,
    StepClick,
    read_action_value,
)
from products.slack_app.backend.logic.onboarding.steps import ONBOARDING_STEPS, STEPS_BY_KEY
from products.slack_app.backend.services.inbox_interactivity import post_response_url
from products.slack_app.backend.services.slack_settings import update_onboarding
from products.slack_app.backend.services.workspace_integrations import get_workspace_integration

# pinned: analytics event name, renaming breaks dashboards
STEP_SKIPPED_EVENT = "slack app onboarding step skipped"


def _handling_step(action_id: str) -> OnboardingStep | None:
    return next((step for step in ONBOARDING_STEPS if step.handles(action_id)), None)


def _clicked_action(payload: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    for action in payload.get("actions") or []:
        action_id = action.get("action_id")
        if is_onboarding_action(action_id):
            step = _handling_step(action_id)
            value = step.read_value(action) if step else read_action_value(action)
            if value is not None:
                return action_id, value
    return None


def _integration_id(clicked: tuple[str, dict[str, Any]] | None) -> int | None:
    integration_id = clicked[1].get("integration_id") if clicked else None
    return integration_id if isinstance(integration_id, int) else None


def onboarding_integration_hint(payload: dict[str, Any]) -> int | None:
    return _integration_id(_clicked_action(payload))


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
    step = _handling_step(action_id)
    return step.apply_action(ctx, action_id, value) if step else StepClick(refresh=False)


def handle_onboarding_action(payload: dict[str, Any]) -> HttpResponse:
    clicked = _clicked_action(payload)
    integration_id = _integration_id(clicked)
    slack_team_id = (payload.get("team") or {}).get("id", "")
    # The thread sits in the person's own DM with PostHog, so the clicker is the person it is for.
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
