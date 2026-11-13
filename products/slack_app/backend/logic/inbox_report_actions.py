"""One-click Resolve and Dismiss buttons for an inbox report, posted as a follow-up in its Slack thread."""

import json
from typing import Any

SIGNALS_DISMISS_REPORT_ACTION_ID = "signals_dismiss_report"
SIGNALS_RESOLVE_REPORT_ACTION_ID = "signals_resolve_report"
SIGNALS_REPORT_STATE_ACTION_IDS = (SIGNALS_RESOLVE_REPORT_ACTION_ID, SIGNALS_DISMISS_REPORT_ACTION_ID)

REPORT_STATE_FOLLOWUP_TEXT = "Nothing to build? Close this report out from here."


def report_state_followup_blocks(*, integration_id: int, report_id: str, team_id: int) -> list[dict[str, Any]]:
    """The value carries the report and its project so the click needs no lookup before the access checks.

    The integration lets the cross-region interactivity router claim the click.
    """
    value = json.dumps({"integration_id": integration_id, "report_id": report_id, "team_id": team_id})
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": REPORT_STATE_FOLLOWUP_TEXT}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": SIGNALS_RESOLVE_REPORT_ACTION_ID,
                    "text": {"type": "plain_text", "text": "Mark resolved", "emoji": True},
                    "value": value,
                },
                {
                    "type": "button",
                    "action_id": SIGNALS_DISMISS_REPORT_ACTION_ID,
                    "text": {"type": "plain_text", "text": "Dismiss", "emoji": True},
                    "value": value,
                },
            ],
        },
    ]
