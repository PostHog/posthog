"""Reusable analytics helpers for the Slack app.

Uses ``ph_background_capture`` (not ``posthoganalytics.capture``) so events survive being emitted
from a Temporal worker, where the global client's background flush may never run before the worker
exits. Unlike ``ph_scoped_capture`` it doesn't block on a per-call flush, so the same helper is
safe on the Slack webhook request path and its 3-second ack budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from posthog.event_usage import groups
from posthog.models.integration import Integration
from posthog.ph_client import ph_background_capture

if TYPE_CHECKING:
    from posthog.models.user import User

logger = structlog.get_logger(__name__)


def slack_event_props(integration: Integration, *, slack_user_id: str | None = None, **extra: object) -> dict:
    """The standard property bundle attached to every Slack app event, plus any ``extra`` props."""
    props: dict = {
        "integration_id": integration.id,
        "slack_team_id": integration.integration_id,
        "team_id": integration.team_id,
        "organization_id": str(integration.team.organization_id),
    }
    if slack_user_id:
        props["slack_user_id"] = slack_user_id
    props.update(extra)
    return props


def capture_slack_event(
    integration: Integration,
    event: str,
    *,
    slack_user_id: str | None = None,
    posthog_user: User | None = None,
    **props: object,
) -> None:
    """Capture a Slack app event with org/team groups. Best-effort: analytics never breaks the flow.

    ``distinct_id`` ladder: a resolved PostHog user's distinct id, else a stable Slack-derived id
    (``slack:{team}:{user}``) when the acting Slack user is known, else the team uuid — matching
    the mention funnel's attribution so per-user analysis works across every Slack app event.
    """
    try:
        team = integration.team
        if posthog_user is not None:
            distinct_id = posthog_user.distinct_id
        elif slack_user_id:
            distinct_id = f"slack:{integration.integration_id}:{slack_user_id}"
        else:
            distinct_id = str(team.uuid)
        properties = slack_event_props(integration, slack_user_id=slack_user_id, **props)
        properties["posthog_user_identified"] = posthog_user is not None
        if posthog_user is not None:
            properties["$set"] = posthog_user.get_analytics_metadata()
        capture = ph_background_capture()
        capture(
            distinct_id=distinct_id,
            event=event,
            properties=properties,
            groups=groups(team.organization, team),
        )
    except Exception:
        # NB: structlog's first positional arg is named ``event``, so pass the Slack event under a
        # different key — otherwise this best-effort handler itself raises and defeats the swallow.
        logger.warning("slack_analytics_capture_failed", slack_event=event, exc_info=True)
