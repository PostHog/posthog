"""Facade for slack_app.

The ONLY module other products are allowed to import. Keep the surface narrow:
every function here lives behind a tach contract check, so each addition has a
cost in cross-product coupling.

Today the facade exists for three jobs: letting core's OAuth callback invalidate
the per-integration auth-state cache when a Slack install is reconnected,
answering whether a channel has been approved for PostHog to speak in, and
telling a product that posts a report whether the bot can answer a follow-up.
All are stable re-exports so the implementations can move around inside
slack_app without breaking their callers.

This module's import graph must not reach ``products.signals``. That product now imports this
facade, and ``products.slack_app`` imports signals' facade in turn, so a module-level edge from
here back into signals closes the loop and breaks Django startup. Reach signals from a function
body instead, the way the handlers under ``backend/`` already do.
"""

from __future__ import annotations

from typing import Any

from posthog.models.integration import Integration

from products.slack_app.backend.models import SlackChannel
from products.slack_app.backend.services.followup_invite import build_followup_invite, build_followup_invite_text
from products.slack_app.backend.services.slack_auth import invalidate_auth_state
from products.slack_app.backend.services.slack_scopes import has_scopes
from products.slack_app.backend.services.slack_user_info import invalidate_workspace_bot_user_id

__all__ = [
    "invalidate_slack_integration_auth_state",
    "slack_artifact_delivery_state_updates",
    "slack_channel_is_approved",
    "slack_followup_invite",
    "slack_followup_invite_text",
]

_SLACK_CANVAS_FILE_ADAPTER_SCOPES = frozenset({"canvases:write", "files:write"})


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


def slack_artifact_delivery_state_updates(integration: Integration) -> dict[str, str | bool]:
    """State that tells a task agent which Slack artifact adapters can deliver."""
    mode = "canvas_file" if has_scopes(integration, _SLACK_CANVAS_FILE_ADAPTER_SCOPES) else "message"
    return {"slack_artifact_delivery": mode, "slack_chart_delivery": True}


def slack_followup_invite_text(integration: Integration | None, *, utm_tags: str, ai_enabled: bool) -> str | None:
    """The mrkdwn line inviting a reader to ask the bot a follow-up about this message.

    Returns ``None`` when there is nothing to invite: no Slack install, or an organization that has
    not approved AI data processing. A workspace whose bot cannot answer a mention gets the setup
    link instead, so a caller never has to check the install itself.

    ``utm_tags`` attributes an install that starts from the setup link, so each caller passes its
    own campaign.
    """
    return build_followup_invite_text(integration, utm_tags=utm_tags, ai_enabled=ai_enabled)


def slack_followup_invite(integration: Integration | None, *, utm_tags: str, ai_enabled: bool) -> dict[str, Any] | None:
    """``slack_followup_invite_text`` as a Slack context block, for a caller that appends blocks."""
    return build_followup_invite(integration, utm_tags=utm_tags, ai_enabled=ai_enabled)
