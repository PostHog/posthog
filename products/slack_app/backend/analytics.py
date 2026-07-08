"""Reusable analytics helpers for the Slack app.

Uses ``ph_scoped_capture`` (not ``posthoganalytics.capture``) so events survive being emitted from a
Temporal worker, where the global client's background flush may never run before the worker exits.
"""

from __future__ import annotations

import structlog

from posthog.event_usage import groups
from posthog.models.integration import Integration
from posthog.ph_client import ph_scoped_capture

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


def slack_user_distinct_id(workspace_id: str, slack_user_id: str) -> str:
    """Stable per-Slack-user distinct_id for events that must chain into per-user funnels.
    Deliberately synthetic (not the linked PostHog user's distinct_id): it is computable at
    every capture site — interactivity handlers, home opens before user resolution, Temporal
    activities — so every step of a flow lands on the same person."""
    return f"slack:{workspace_id}:{slack_user_id}"


def capture_slack_event(
    integration: Integration,
    event: str,
    *,
    slack_user_id: str | None = None,
    distinct_id: str | None = None,
    **props: object,
) -> None:
    """Capture a Slack app event with org/team groups. Best-effort: analytics never breaks the flow.

    ``distinct_id`` defaults to the team uuid, which collapses every user in a workspace into one
    person — fine for volume counts, useless for funnels. Flows that need per-user conversion
    tracking must pass ``slack_user_distinct_id(...)``."""
    try:
        team = integration.team
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=distinct_id or str(team.uuid),
                event=event,
                properties=slack_event_props(integration, slack_user_id=slack_user_id, **props),
                groups=groups(team.organization, team),
            )
    except Exception:
        # NB: structlog's first positional arg is named ``event``, so pass the Slack event under a
        # different key — otherwise this best-effort handler itself raises and defeats the swallow.
        logger.warning("slack_analytics_capture_failed", slack_event=event, exc_info=True)
