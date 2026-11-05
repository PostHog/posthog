"""Clicks save at once and only signal the workflow, to answer Slack within 3 seconds."""

from typing import Any

from django.core.exceptions import ValidationError
from django.http import HttpResponse

from posthog.dataclasses import frozen

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.inbox_channel import ensure_inbox_channel, invite_user_to_inbox
from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.backend.logic.feature_tips.state import record_feature_used
from products.slack_app.backend.logic.onboarding.actions import (
    AI_CONSENT_ACTION_ID,
    AUTO_MODEL_ACTION_ID,
    CONTINUE_ACTION_ID,
    INBOX_JOIN_ACTION_ID,
    MODEL_ACTION_ID,
    REPLIES_ACTION_ID,
    SKIP_ACTION_ID,
    SOURCES_ACTION_ID,
    SOURCES_BLOCK_PREFIX,
    is_onboarding_action,
    read_action_value,
)
from products.slack_app.backend.logic.onboarding.dispatch import request_onboarding
from products.slack_app.backend.logic.onboarding.step import OnboardingStepKey
from products.slack_app.backend.logic.onboarding.steps import ONBOARDING_STEPS
from products.slack_app.backend.models import UntaggedFollowupMode
from products.slack_app.backend.services.inbox_interactivity import post_response_url
from products.slack_app.backend.services.model_catalogue import offered_model_choices
from products.slack_app.backend.services.onboarding_checks import approve_ai_data_processing_for_team, is_org_admin
from products.slack_app.backend.services.slack_app_home import linked_posthog_user, set_personal_model
from products.slack_app.backend.services.slack_settings import (
    set_auto_model_choice,
    set_untagged_followup_mode,
    update_onboarding,
)
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration, get_workspace_integration

SKIPPABLE_STEPS = frozenset(step.key for step in ONBOARDING_STEPS if step.skippable)
# pinned: analytics event names, renaming breaks dashboards
STEP_COMPLETED_EVENT = "slack app onboarding step completed"
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


@frozen
class _ClickResult:
    message: str | None = None
    # A tick on a signal checkbox saves at once but keeps the step open, so the person can tick more.
    refresh: bool = True


def _completed(
    integration: WorkspaceIntegration,
    slack_user_id: str,
    step: OnboardingStepKey,
    *,
    choice: str | None = None,
    model: str | None = None,
) -> None:
    capture_slack_event(
        integration, STEP_COMPLETED_EVENT, slack_user_id=slack_user_id, step=step, choice=choice, model=model
    )


def _apply(
    integration: WorkspaceIntegration, slack_user_id: str, action_id: str, value: dict[str, Any]
) -> _ClickResult:
    slack_workspace_id = integration.integration_id
    if action_id == SKIP_ACTION_ID:
        step = value.get("step")
        if step not in SKIPPABLE_STEPS:
            return _ClickResult(refresh=False)
        update_onboarding(slack_workspace_id, slack_user_id, skip_step=str(step))
        capture_slack_event(integration, STEP_SKIPPED_EVENT, slack_user_id=slack_user_id, step=str(step))
    elif action_id == CONTINUE_ACTION_ID:
        pass
    elif action_id == AI_CONSENT_ACTION_ID:
        user = linked_posthog_user(integration, slack_user_id)
        if user is None or not is_org_admin(user.id, integration.team_id):
            return _ClickResult(message="Only an organization admin can allow AI data processing.", refresh=False)
        approve_ai_data_processing_for_team(integration.team_id)
        _completed(integration, slack_user_id, OnboardingStepKey.AI_CONSENT)
    elif action_id == INBOX_JOIN_ACTION_ID:
        channel = ensure_inbox_channel(integration)
        if channel is None or not invite_user_to_inbox(integration, channel[0], slack_user_id):
            return _ClickResult(
                message="I couldn't add you to #posthog-inbox. Create the channel, then invite me with /invite @PostHog.",
                refresh=False,
            )
        record_feature_used(slack_workspace_id, slack_user_id, SlackFeature.INBOX_CHANNEL)
        _completed(integration, slack_user_id, OnboardingStepKey.INBOX_CHANNEL)
    elif action_id == SOURCES_ACTION_ID:
        from products.signals.backend.facade.api import (  # noqa: PLC0415 — keeps the signals stack off the slack import path
            set_sources,
        )

        user = linked_posthog_user(integration, slack_user_id)
        if user is None:
            return _ClickResult(message="Link your PostHog account first.", refresh=False)
        set_sources(integration.team_id, user.id, value.get("selected") or [])
        return _ClickResult(refresh=False)
    elif action_id == AUTO_MODEL_ACTION_ID:
        set_auto_model_choice(slack_workspace_id, slack_user_id, True)
        record_feature_used(slack_workspace_id, slack_user_id, SlackFeature.AUTO_MODEL_CHOICE)
        _completed(integration, slack_user_id, OnboardingStepKey.MODEL, choice="auto")
    elif action_id == MODEL_ACTION_ID:
        model = value.get("model")
        if model not in {choice.model for choice in offered_model_choices()}:
            return _ClickResult(message="That model is no longer available. Pick another one.", refresh=False)
        try:
            set_personal_model(integration, slack_user_id, str(model))
        except ValidationError as error:
            return _ClickResult(message=error.messages[0], refresh=False)
        _completed(integration, slack_user_id, OnboardingStepKey.MODEL, choice="model", model=str(model))
    elif action_id.startswith(f"{REPLIES_ACTION_ID}:"):
        mode = value.get("mode")
        if mode not in UntaggedFollowupMode.values:
            return _ClickResult(refresh=False)
        set_untagged_followup_mode(slack_workspace_id, slack_user_id, UntaggedFollowupMode(mode))
        _completed(integration, slack_user_id, OnboardingStepKey.REPLIES_IN_THREADS, choice=str(mode))
    return _ClickResult()


def handle_onboarding_action(payload: dict[str, Any]) -> HttpResponse:
    clicked = _clicked_action(payload)
    integration_id = clicked[1].get("integration_id") if clicked else None
    slack_team_id = (payload.get("team") or {}).get("id", "")
    # The card sits in the person's own DM with PostHog, so the clicker is the person it is for.
    slack_user_id = (payload.get("user") or {}).get("id", "")
    integration = get_workspace_integration(integration_id, slack_team_id) if integration_id else None
    if clicked is None or integration is None or not slack_user_id:
        return HttpResponse(status=200)

    result = _apply(integration, slack_user_id, *clicked)
    if result.message is not None:
        post_response_url(
            payload.get("response_url") or "",
            {"response_type": "ephemeral", "replace_original": False, "text": result.message},
        )
    if result.refresh:
        request_onboarding(integration, slack_user_id, may_start=False)
    return HttpResponse(status=200)
