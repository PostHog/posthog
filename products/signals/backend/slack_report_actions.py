"""The interactive "Create PR" button PostHog's report Slack messages carry.

Both report surfaces render it — the scout harness's own delivery (`scout_harness/slack_delivery.py`)
and the reviewer notifications (`slack_inbox_notifications.py`) — so the button is built here once.
The click comes back through the Slack app's interactivity webhook, which routes on
`SLACK_CREATE_PR_ACTION_ID` and calls `facade.api.start_report_pr_from_slack`.

Resolved by the code that is about to post (which is already reading the report's artefacts), not
inside the message builders: those stay pure so they can be tested without a database.
"""

from __future__ import annotations

import json

import structlog

from posthog.models.integration import Integration

from products.signals.backend.facade.slack_actions import SLACK_CREATE_PR_ACTION_ID
from products.signals.backend.models import SignalReport

logger = structlog.get_logger(__name__)


def slack_create_pr_button(report: SignalReport, *, integration: Integration) -> dict | None:
    """The "Create PR" action element for a report's Slack message, or ``None`` when the message must
    not offer one.

    Offered only when a PR could still land for the report, and only over a Slack connection the
    click can be authorized against. Scout output is delivered over any connection in the report's
    project, including one owned by another environment, and the webhook authorizes a report action
    against the connection's own team — so a button on a cross-environment message would be dropped
    on every click. The message keeps its link out instead, mirroring how the scout's follow-up reply
    is skipped for the same reason.

    The integration id rides on the button so the webhook can settle which region owns the click
    before it authorizes anything — the same routing hint the report's other Slack actions carry.
    """
    from products.signals.backend.auto_start import (  # noqa: PLC0415 — keeps the tasks facade off the django.setup() path, which reaches this module through signals' Celery tasks
        implementation_pr_can_be_started,
    )

    if integration.team_id != report.team_id:
        logger.info(
            "signals_slack_create_pr_button_skipped_environment_mismatch",
            report_team_id=report.team_id,
            integration_team_id=integration.team_id,
        )
        return None
    if not implementation_pr_can_be_started(report):
        return None
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "Create PR", "emoji": True},
        "action_id": SLACK_CREATE_PR_ACTION_ID,
        "value": json.dumps({"integration_id": integration.id, "report_id": str(report.id), "team_id": report.team_id}),
    }
