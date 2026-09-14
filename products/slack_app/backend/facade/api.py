"""Facade for slack_app.

The ONLY module other products are allowed to import. Keep the surface narrow:
every function here lives behind a tach contract check, so each addition has a
cost in cross-product coupling.

Today the facade exists for two jobs: letting core's OAuth callback invalidate
the per-integration auth-state cache when a Slack install is reconnected, and
answering whether a channel has been approved for PostHog to speak in. Both are
stable re-exports so the implementations can move around inside slack_app
without breaking their callers.
"""

from __future__ import annotations

from posthog.helpers.slack_scopes import has_scopes
from posthog.models.integration import Integration

from products.slack_app.backend.models import SlackChannel
from products.slack_app.backend.services.slack_auth import invalidate_auth_state
from products.slack_app.backend.services.slack_user_info import invalidate_workspace_bot_user_id

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


def slack_stream_verbosity(integration_id: int, slack_user_id: str | None) -> str:
    """The stream-verbosity preference of one Slack user, as its stored value.

    Read by the tasks product when a run turn starts, keyed on the person whose
    mention started the run. Returns ``"full"`` when the integration is gone or
    nothing is stored — live streaming is the default.
    """
    from products.slack_app.backend.services.slack_settings import (  # noqa: PLC0415 — keeps service imports off the facade import path
        resolve_stream_verbosity,
    )

    integration = Integration.objects.filter(
        id=integration_id, kind="slack"
    ).first()  # nosemgrep: idor-lookup-without-team — id comes from the run's recorded Slack thread context, not user input; only the preference row keyed on it is read
    if integration is None:
        from products.slack_app.backend.models import (
            StreamVerbosity,  # noqa: PLC0415 — matches the deferred-import pattern above
        )

        return StreamVerbosity.FULL.value
    return resolve_stream_verbosity(integration, slack_user_id).value
