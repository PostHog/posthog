"""The Slack thread ↔ report link behind "reply in the thread and mention PostHog".

Both notification paths (the inbox reviewer notification and the scout harness delivery) record
the thread they posted, and the Slack mention handler reads it back so the task it starts lands on
the report's own timeline instead of floating free.

Writes are best-effort: a report must still reach Slack when the link cannot be stored.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from django.db import IntegrityError

from products.signals.backend.models import SignalReportSlackThread

logger = logging.getLogger(__name__)


def record_report_slack_thread(
    *, team_id: int, report_id: str, integration_id: int | None, slack_workspace_id: str, channel: str, thread_ts: str
) -> None:
    """Record that `thread_ts` in `channel` is a notification thread for this report."""
    try:
        SignalReportSlackThread.objects.for_team(team_id).get_or_create(
            slack_workspace_id=slack_workspace_id,
            channel=channel,
            thread_ts=thread_ts,
            defaults={"team_id": team_id, "report_id": report_id, "integration_id": integration_id},
        )
    except IntegrityError:
        # The thread is already claimed — by a concurrent delivery of the same message, or by
        # another project connected to the same workspace. Either way the first claim stands.
        pass
    except Exception:
        logger.exception(
            "Failed to record the Slack thread for signal report %s",
            report_id,
            extra={"team_id": team_id, "report_id": report_id},
        )


def report_id_for_slack_thread(*, team_id: int, slack_workspace_id: str, channel: str, thread_ts: str) -> str | None:
    """The report a Slack thread is about, or None when the thread is not a notification thread.

    Scoped to `team_id` rather than to the integration that posted: a workspace can be connected to
    several projects, and a mention routed to a different project must not reach this project's
    report. Reconnecting the workspace writes a new integration row, so keying on it instead would
    lose every link the old row had made.
    """
    try:
        row = (
            SignalReportSlackThread.objects.for_team(team_id)
            .filter(slack_workspace_id=slack_workspace_id, channel=channel, thread_ts=thread_ts)
            .values_list("report_id", flat=True)
            .first()
        )
    except Exception:
        logger.exception(
            "Failed to resolve the signal report for a Slack thread", extra={"team_id": team_id, "channel": channel}
        )
        return None
    return str(row) if row else None


def report_team_id_for_slack_thread(
    *, team_ids: Sequence[int], slack_workspace_id: str, channel: str, thread_ts: str
) -> int | None:
    """Find the report's environment among the caller's accessible Slack integration candidates."""
    try:
        return (
            SignalReportSlackThread.all_teams.filter(
                team_id__in=team_ids, slack_workspace_id=slack_workspace_id, channel=channel, thread_ts=thread_ts
            )
            .values_list("team_id", flat=True)
            .first()
        )
    except Exception:
        logger.exception("Failed to resolve the environment for a Slack report thread", extra={"channel": channel})
        return None
