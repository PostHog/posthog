"""Facade for slack_app.

The ONLY module other products are allowed to import. Keep the surface narrow:
every function here lives behind a tach contract check, so each addition has a
cost in cross-product coupling.

Today the facade exists for five jobs: letting core's OAuth callback invalidate
the per-integration auth-state cache when a Slack install is reconnected,
answering whether a channel has been approved for PostHog to speak in,
telling a product that posts a report whether the bot can answer a follow-up,
turning an agent's tool calls into the progress lines of a streamed Slack
reply, and recording that a Slack user used a feature, so feature tips skip it. All are stable re-exports so the implementations can move around inside
slack_app without breaking their callers.

This module's import graph must not reach ``products.signals``. That product now imports this
facade, and ``products.slack_app`` imports signals' facade in turn, so a module-level edge from
here back into signals closes the loop and breaks Django startup. Reach signals from a function
body instead, the way the handlers under ``backend/`` already do.
"""

from __future__ import annotations

from typing import Any

import structlog

from posthog.integrations import IntegrationRecord
from posthog.models.integration import Integration

from products.slack_app.backend.logic.feature_tips.features import SlackFeature
from products.slack_app.backend.logic.feature_tips.state import record_feature_used
from products.slack_app.backend.logic.progress_phases import (
    ANSWER_LINE_TITLE,
    OTHER_WORK,
    PLAN_TITLE_STOPPED,
    PLAN_TITLE_WORKING,
    PREPARING_LINE_TITLE,
    SLACK_STEP_STATUSES,
    THINKING_LINE_TITLE,
    ProgressPhase,
    agent_plan_steps,
    done_plan_title,
    intent_from_narrative,
    phase_for_key,
    phase_for_tool_call,
    phase_line_title,
    tool_call_from_acp_update,
)
from products.slack_app.backend.models import SlackChannel
from products.slack_app.backend.services.followup_invite import build_followup_invite, build_followup_invite_text
from products.slack_app.backend.services.slack_auth import invalidate_auth_state
from products.slack_app.backend.services.slack_scopes import SLACK_CANVAS_SCOPE, SLACK_FILE_SCOPE, has_scopes
from products.slack_app.backend.services.slack_user_info import invalidate_workspace_bot_user_id

__all__ = [
    "ANSWER_LINE_TITLE",
    "OTHER_WORK",
    "PLAN_TITLE_STOPPED",
    "PLAN_TITLE_WORKING",
    "PREPARING_LINE_TITLE",
    "SLACK_STEP_STATUSES",
    "SlackFeature",
    "THINKING_LINE_TITLE",
    "ProgressPhase",
    "agent_plan_steps",
    "done_plan_title",
    "intent_from_narrative",
    "phase_for_key",
    "phase_for_tool_call",
    "phase_line_title",
    "tool_call_from_acp_update",
    "invalidate_slack_integration_auth_state",
    "record_slack_feature_used",
    "slack_artifact_delivery_state_updates",
    "slack_channel_is_approved",
    "slack_followup_invite",
    "slack_followup_invite_text",
]

logger = structlog.get_logger(__name__)

_SLACK_CANVAS_FILE_ADAPTER_SCOPES = frozenset({SLACK_CANVAS_SCOPE, SLACK_FILE_SCOPE})


def invalidate_slack_integration_auth_state(integration_id: int) -> None:
    """Drop the cached auth verdict for ``integration_id``.

    Call from core's OAuth completion path so a freshly-reconnected Slack
    install doesn't get pinned to the stale ``ok=false`` state we wrote when
    its previous token was revoked. The workspace-level bot id mirror goes with
    it: a reinstall can mint a new bot user, and the reaction router's author
    gate must not keep judging the new bot's replies against the old id.
    """
    invalidate_auth_state(integration_id)
    # Cache invalidation on the caller's own row, id straight from core's OAuth completion
    # path rather than user input; only the Slack workspace id is read off it.
    slack_team_id = (
        Integration.objects.filter(  # nosemgrep: idor-lookup-without-team
            id=integration_id, kind="slack"
        )
        .values_list("integration_id", flat=True)
        .first()
    )
    if slack_team_id:
        invalidate_workspace_bot_user_id(slack_team_id)


def slack_channel_is_approved(slack_workspace_id: str, slack_channel_id: str) -> bool:
    """Whether someone in this channel has approved PostHog answering in it.

    Approval is only required for externally shared channels, where a reply is visible to
    members of another Slack workspace. Callers read that from the ``is_ext_shared_channel``
    flag Slack puts on the event envelope and skip this lookup when it is false.
    """
    return SlackChannel.approval_granted(slack_workspace_id, slack_channel_id)


def slack_artifact_delivery_state_updates(integration: IntegrationRecord) -> dict[str, str | bool]:
    """State that tells a task agent which Slack artifact adapters can deliver, and whether to
    share a chart as an insight link rather than render it through the chart endpoint."""
    mode = "canvas_file" if has_scopes(integration, _SLACK_CANVAS_FILE_ADAPTER_SCOPES) else "message"
    return {
        "slack_artifact_delivery": mode,
        "slack_chart_delivery": True,
        "slack_chart_links": True,
    }


def slack_followup_invite_text(integration: IntegrationRecord | None, *, utm_tags: str, ai_enabled: bool) -> str | None:
    """The mrkdwn line inviting a reader to ask the bot a follow-up about this message.

    Returns ``None`` when there is nothing to invite: no Slack install, or an organization that has
    not approved AI data processing. A workspace whose bot cannot answer a mention gets the setup
    link instead, so a caller never has to check the install itself.

    ``utm_tags`` attributes an install that starts from the setup link, so each caller passes its
    own campaign.
    """
    return build_followup_invite_text(integration, utm_tags=utm_tags, ai_enabled=ai_enabled)


def slack_followup_invite(
    integration: IntegrationRecord | None, *, utm_tags: str, ai_enabled: bool
) -> dict[str, Any] | None:
    """``slack_followup_invite_text`` as a Slack context block, for a caller that appends blocks."""
    return build_followup_invite(integration, utm_tags=utm_tags, ai_enabled=ai_enabled)


def record_slack_feature_used(integration_id: int, slack_user_id: str | None, feature: SlackFeature) -> None:
    """Never raises, so a caller can record use from inside the feature's own code path."""
    try:
        slack_workspace_id = (
            Integration.objects.filter(id=integration_id, kind="slack")  # nosemgrep: idor-lookup-without-team
            .values_list("integration_id", flat=True)
            .first()
        )
    except Exception:
        logger.warning("slack_app_feature_used_lookup_failed", integration_id=integration_id, exc_info=True)
        return
    if slack_workspace_id:
        record_feature_used(slack_workspace_id, slack_user_id, feature)
