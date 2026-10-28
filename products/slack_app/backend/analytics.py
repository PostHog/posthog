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


def slack_session_id(slack_team_id: str, channel: str, thread_ts: str) -> str:
    """The id of one Slack thread, which joins its mention, reply, and task run events."""
    return f"{slack_team_id}:{channel}:{thread_ts}"


def slack_distinct_id(integration: Integration, slack_user_id: str) -> str:
    """The distinct id of a Slack user that no PostHog user has been resolved for yet."""
    return f"slack:{integration.integration_id}:{slack_user_id}"


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
            distinct_id = slack_distinct_id(integration, slack_user_id)
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


def alias_slack_user(integration: Integration, slack_user_id: str, posthog_user: User) -> None:
    """Merge a Slack user's anonymous person into their PostHog user's person. Best-effort.

    Events captured before the Slack user was linked use ``slack_distinct_id``. After the merge,
    per-user analysis counts that history toward the PostHog user.
    """
    if not posthog_user.distinct_id:
        return
    try:
        ph_background_capture().alias(
            previous_id=posthog_user.distinct_id, distinct_id=slack_distinct_id(integration, slack_user_id)
        )
    except Exception:
        logger.warning("slack_analytics_alias_failed", integration_id=integration.id, exc_info=True)
