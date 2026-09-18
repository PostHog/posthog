"""Links a report's Slack notification thread back to the report.

Signals posts a report to Slack and asks the reader to reply in the thread and mention the app.
That mention starts a task, but the event only names a channel and a thread. These two functions
are the record and the read of that link, so the task can be filed against the report it discusses.
"""

import structlog

from products.signals.backend.models import SignalReportSlackThread

logger = structlog.get_logger(__name__)


def record_report_slack_thread(
    *, team_id: int, report_id: str, integration_id: int, channel: str, thread_ts: str
) -> None:
    """Remember which report a delivered Slack thread is about.

    Best-effort: a failure here costs the link, never the notification. The same thread is written
    again when a report is re-delivered, so the report is updated rather than a second row added.
    """
    if not channel or not thread_ts:
        return
    try:
        # `for_team` scopes the lookup; the create still needs `team_id` of its own, because a
        # queryset filter does not propagate into row creation.
        SignalReportSlackThread.objects.for_team(team_id).update_or_create(
            integration_id=integration_id,
            channel=channel,
            thread_ts=thread_ts,
            defaults={"team_id": team_id, "report_id": report_id},
        )
    except Exception:
        logger.warning(
            "signals_report_slack_thread_record_failed",
            report_id=report_id,
            integration_id=integration_id,
            exc_info=True,
        )


def report_id_for_slack_thread(*, team_id: int, integration_id: int, channel: str, thread_ts: str) -> str | None:
    """The report a Slack thread is about, or None when the thread is not a report notification."""
    report_id = (
        SignalReportSlackThread.objects.for_team(team_id)
        .filter(integration_id=integration_id, channel=channel, thread_ts=thread_ts)
        .values_list("report_id", flat=True)
        .first()
    )
    return str(report_id) if report_id else None
