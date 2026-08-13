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

from products.signals.backend.auto_start import implementation_pr_can_be_started
from products.signals.backend.facade.slack_actions import SLACK_CREATE_PR_ACTION_ID
from products.signals.backend.models import SignalReport


def slack_create_pr_button(report: SignalReport, *, integration_id: int) -> dict | None:
    """The "Create PR" action element for a report's Slack message, or ``None`` when a PR can't be
    started for it (it already has one, it's closed, or it has no repository to open one against).

    ``integration_id`` rides on the button so the webhook can settle which region owns the click
    before it authorizes anything — the same routing hint the report's other Slack actions carry.
    """
    if not implementation_pr_can_be_started(report):
        return None
    return {
        "type": "button",
        "text": {"type": "plain_text", "text": "Create PR", "emoji": True},
        "action_id": SLACK_CREATE_PR_ACTION_ID,
        "value": json.dumps({"integration_id": integration_id, "report_id": str(report.id), "team_id": report.team_id}),
    }
