"""Inbox onboarding: what the reader's four answers do (GitHub, sources, reports/channel, AI approval).

``send_onboarding_dm`` delivers the message, the interactivity helpers (called from ``api.py``)
handle each click, and ``run_install_onboarding`` is the install entrypoint. The message itself is
built in ``services/slack_welcome_messages.py`` with the rest of the first-contact copy.
"""

from __future__ import annotations

from enum import StrEnum

import structlog
from slack_sdk.errors import SlackApiError

from posthog.models.integration import SlackIntegration
from posthog.slack.formatting import channel_id_from_target

from products.slack_app.backend.analytics import capture_slack_event
from products.slack_app.backend.feature_flags import is_slack_app_onboarding_enabled
from products.slack_app.backend.inbox_channel import (
    _get_team_channel,
    _is_channel_member,
    ensure_inbox_channel,
    has_inbox_scopes,
    invite_user_to_inbox,
)
from products.slack_app.backend.logic.onboarding.checks import (
    approve_ai_data_processing_for_team,
    has_ai_approval as _has_ai_approval,
    has_enabled_source as _has_enabled_source,
    has_personal_github as _has_personal_github,
    has_team_github as _has_team_github,
    is_org_admin as _is_org_admin,
)
from products.slack_app.backend.logic.onboarding.dispatch import request_onboarding
from products.slack_app.backend.services.slack_messages import context_block
from products.slack_app.backend.services.slack_welcome_messages import (
    INBOX_CREATE_ACTION_ID,
    INBOX_JOIN_ACTION_ID,
    build_onboarding_dm,
)
from products.slack_app.backend.services.workspace_integrations import WorkspaceIntegration

logger = structlog.get_logger(__name__)


class OnboardingStep(StrEnum):
    AI_APPROVAL = "ai_approval"
    CHANNEL = "channel"
    GITHUB = "github"
    SOURCES = "sources"


EVENT_DM_SENT = "slack_onboarding_dm_sent"
EVENT_STEP_COMPLETED = "slack_onboarding_step_completed"
EVENT_COMPLETED = "slack_onboarding_completed"
EVENT_SOURCE_ENABLED = "slack_onboarding_source_enabled"

_REQUIRED_STEPS = (OnboardingStep.AI_APPROVAL, OnboardingStep.CHANNEL, OnboardingStep.GITHUB, OnboardingStep.SOURCES)


# Slack has no disabled buttons; a context block is the idiomatic greyed/done state.
def _replace_actions_with_context(blocks: list[dict], action_ids: set[str], text: str) -> list[dict]:
    return [
        context_block(text)
        if (
            block.get("type") == "actions"
            and any(el.get("action_id") in action_ids for el in block.get("elements", []))
        )
        else block
        for block in blocks
    ]


# =====================================================================
# Status, delivery, completion
# =====================================================================


def _resolve_onboarding_user(
    slack: SlackIntegration, integration: WorkspaceIntegration, slack_user_id: str
) -> int | None:
    """Resolve the Slack user to a PostHog user id (org-member email match), or None."""
    from products.slack_app.backend.api import (
        resolve_slack_user,  # noqa: PLC0415 — api.py imports this module; defer to break the cycle
    )

    context = resolve_slack_user(slack, integration, slack_user_id, "", "", post_feedback=False)
    return context.user.id if context else None


def _onboarding_status(
    integration: WorkspaceIntegration, slack: SlackIntegration, slack_user_id: str, user_id: int | None = None
) -> tuple[int | None, dict[OnboardingStep, bool]]:
    """Resolve the user and evaluate each step's done/not-done — the source of truth for what's left.
    Pass ``user_id`` when the caller already resolved it, to skip the repeat lookup."""
    # GitHub is done only when both the team install and the user's personal GitHub exist.
    if user_id is None:
        user_id = _resolve_onboarding_user(slack, integration, slack_user_id)
    team_id = integration.team_id
    configured = _get_team_channel(team_id)
    in_channel = configured is not None and _is_channel_member(slack, channel_id_from_target(configured), slack_user_id)
    return user_id, {
        OnboardingStep.AI_APPROVAL: _has_ai_approval(team_id),
        OnboardingStep.CHANNEL: in_channel,
        OnboardingStep.GITHUB: (user_id is None or _has_personal_github(user_id)) and _has_team_github(team_id),
        OnboardingStep.SOURCES: _has_enabled_source(team_id),
    }


def _build_from_status(
    integration: WorkspaceIntegration, slack: SlackIntegration, user_id: int | None, status: dict[OnboardingStep, bool]
) -> tuple[str, list[dict]]:
    is_admin = user_id is not None and _is_org_admin(user_id, integration.team_id)
    return build_onboarding_dm(
        integration,
        slack,
        needs_ai_approval=not status[OnboardingStep.AI_APPROVAL],
        ai_approval_is_admin=is_admin,
        needs_github=not status[OnboardingStep.GITHUB],
        already_in_channel=status[OnboardingStep.CHANNEL],
    )


def send_onboarding_dm(integration: WorkspaceIntegration, slack_user_id: str) -> bool:
    """DM a user the inbox onboarding. Returns True when sent, False when the post failed.

    Always posts (no dedupe, no all-done shortcut) — the install hook already fires only once.
    """
    if not slack_user_id:
        return False
    slack = SlackIntegration(integration)
    user_id, status = _onboarding_status(integration, slack, slack_user_id)
    text, blocks = _build_from_status(integration, slack, user_id, status)
    try:
        slack.client.chat_postMessage(channel=slack_user_id, text=text, blocks=blocks)
    except SlackApiError as e:
        logger.warning("slack_inbox_onboarding_dm_failed", integration_id=integration.id, error=e.response.get("error"))
        return False
    capture_slack_event(
        integration,
        EVENT_DM_SENT,
        slack_user_id=slack_user_id,
        steps_needed=[str(step) for step, done in status.items() if not done],
        steps_total=len(status),
        is_admin=user_id is not None and _is_org_admin(user_id, integration.team_id),
    )
    # A step done before the DM gets no click, so without this the step funnel never sees it.
    for step, done in status.items():
        if done:
            capture_slack_event(
                integration, EVENT_STEP_COMPLETED, slack_user_id=slack_user_id, step=str(step), completed_before_dm=True
            )
    _capture_completed_if_done(integration, slack_user_id, status)
    return True


def _maybe_complete(integration: WorkspaceIntegration, slack_user_id: str, user_id: int | None = None) -> None:
    """Fire 'completed' once every required step is done. Pass ``user_id`` when already resolved."""
    _, status = _onboarding_status(integration, SlackIntegration(integration), slack_user_id, user_id)
    _capture_completed_if_done(integration, slack_user_id, status)


def _capture_completed_if_done(
    integration: WorkspaceIntegration, slack_user_id: str, status: dict[OnboardingStep, bool]
) -> None:
    if all(status[step] for step in _REQUIRED_STEPS):
        capture_slack_event(integration, EVENT_COMPLETED, slack_user_id=slack_user_id)


# =====================================================================
# Interactivity: click handlers (called from api.py's router)
# =====================================================================


def _chat_update_blocks(
    integration: WorkspaceIntegration, channel: str, message_ts: str, text: str, blocks: list[dict]
) -> None:
    try:
        SlackIntegration(integration).client.chat_update(channel=channel, ts=message_ts, text=text, blocks=blocks)
    except SlackApiError as e:
        logger.warning(
            "slack_inbox_connect_update_failed", integration_id=integration.id, error=e.response.get("error")
        )


def mark_channel_joined(
    integration: WorkspaceIntegration, slack_user_id: str, channel: str, message_ts: str, original_blocks: list[dict]
) -> None:
    """After create/join: flip just the channel block to a '✅' line in place, then record completion."""
    swapped = _replace_actions_with_context(
        original_blocks,
        {INBOX_CREATE_ACTION_ID, INBOX_JOIN_ACTION_ID},
        ":white_check_mark: You're in your #posthog-inbox channel",
    )
    _chat_update_blocks(integration, channel, message_ts, "You're in your #posthog-inbox channel", swapped)
    capture_slack_event(
        integration, EVENT_STEP_COMPLETED, slack_user_id=slack_user_id, step=str(OnboardingStep.CHANNEL)
    )
    _maybe_complete(integration, slack_user_id)


def apply_sources_selection(integration: WorkspaceIntegration, slack_user_id: str, selected_keys: list[str]) -> None:
    """Sync the team's sources to the new selection."""
    from products.signals.backend.facade.api import (
        set_sources,  # noqa: PLC0415 — keeps the signals stack off the slack import path
    )

    user_id = _resolve_onboarding_user(SlackIntegration(integration), integration, slack_user_id)
    if user_id is None:
        # Can't tie the clicker to an org member — don't mutate team state.
        return
    had_sources = _has_enabled_source(integration.team_id)
    set_sources(integration.team_id, user_id, selected_keys)
    capture_slack_event(integration, EVENT_SOURCE_ENABLED, slack_user_id=slack_user_id, selected=list(selected_keys))
    if selected_keys and not had_sources:
        capture_slack_event(
            integration, EVENT_STEP_COMPLETED, slack_user_id=slack_user_id, step=str(OnboardingStep.SOURCES)
        )
    _maybe_complete(integration, slack_user_id, user_id)


def approve_ai_data_processing(integration: WorkspaceIntegration, slack_user_id: str) -> bool:
    """Admin-only approval: re-checks ADMIN+ server-side, sets org consent, records completion.
    Returns False if the clicker isn't an admin."""
    user_id = _resolve_onboarding_user(SlackIntegration(integration), integration, slack_user_id)
    if user_id is None or not _is_org_admin(user_id, integration.team_id):
        return False
    if not approve_ai_data_processing_for_team(integration.team_id):
        return False
    capture_slack_event(
        integration, EVENT_STEP_COMPLETED, slack_user_id=slack_user_id, step=str(OnboardingStep.AI_APPROVAL)
    )
    _maybe_complete(integration, slack_user_id, user_id)
    return True


def installer_slack_user_id(integration: WorkspaceIntegration) -> str | None:
    return ((integration.config or {}).get("authed_user") or {}).get("id")


def run_install_onboarding(integration: WorkspaceIntegration) -> None:
    """On a fresh install: create the inbox channel, invite the installer, and DM them the onboarding.
    Gated on the install having ``channels:manage``; best-effort."""
    if not has_inbox_scopes(integration):
        return
    channel = ensure_inbox_channel(integration)
    installer = installer_slack_user_id(integration)
    if not installer:
        return
    if channel is not None:
        invite_user_to_inbox(integration, channel[0], installer)
    # The DM setup thread takes over the installer's setup, so it starts here in place of the old DM.
    if is_slack_app_onboarding_enabled(integration):
        request_onboarding(integration, installer, may_start=True)
        return
    send_onboarding_dm(integration, installer)
