"""One-click Resolve, Dismiss and Remove me buttons for an inbox report, posted as a follow-up in its Slack thread."""

import json
from typing import Any

SIGNALS_DISMISS_REPORT_ACTION_ID = "signals_dismiss_report"
SIGNALS_RESOLVE_REPORT_ACTION_ID = "signals_resolve_report"
SIGNALS_REMOVE_REVIEWER_ACTION_ID = "signals_remove_report_reviewer"
SIGNALS_REPORT_STATE_ACTION_IDS = (
    SIGNALS_RESOLVE_REPORT_ACTION_ID,
    SIGNALS_DISMISS_REPORT_ACTION_ID,
    SIGNALS_REMOVE_REVIEWER_ACTION_ID,
)

REPORT_STATE_FOLLOWUP_TEXT = "Nothing to build? Close this report out from here."
REPORT_STATE_WITH_REVIEWERS_FOLLOWUP_TEXT = "Nothing to build, or not yours? Act on this report from here."


def report_state_followup_blocks(
    *, integration_id: int, report_id: str, team_id: int, offer_remove_reviewer: bool = False
) -> list[dict[str, Any]]:
    """The value carries the report and its project so the click needs no lookup before the access checks.

    The integration lets the cross-region interactivity router claim the click. Remove me is offered
    only when the report has suggested reviewers, since otherwise nobody is on it to step off.
    """
    value = json.dumps({"integration_id": integration_id, "report_id": report_id, "team_id": team_id})
    buttons = [
        (SIGNALS_RESOLVE_REPORT_ACTION_ID, "Mark resolved"),
        (SIGNALS_DISMISS_REPORT_ACTION_ID, "Dismiss"),
    ]
    if offer_remove_reviewer:
        buttons.append((SIGNALS_REMOVE_REVIEWER_ACTION_ID, "Remove me"))
    text = REPORT_STATE_WITH_REVIEWERS_FOLLOWUP_TEXT if offer_remove_reviewer else REPORT_STATE_FOLLOWUP_TEXT
    return [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "action_id": action_id,
                    "text": {"type": "plain_text", "text": label, "emoji": True},
                    "value": value,
                }
                for action_id, label in buttons
            ],
        },
    ]
