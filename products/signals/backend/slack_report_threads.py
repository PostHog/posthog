"""The Slack thread ↔ report link behind "reply in the thread and mention PostHog".

Both notification paths (the inbox reviewer notification and the scout harness delivery) record
the thread they posted, and the Slack mention handler reads it back so the task it starts lands on
the report's own timeline instead of floating free.

Writes are best-effort: a report must still reach Slack when the link cannot be stored.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

from django.db import IntegrityError
from django.db.models import Func, Value

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager
from posthog.models.integration import SlackIntegration

from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.models import SignalReportSlackThread, SignalReportTask
from products.signals.backend.slack_formatting import is_safe_slack_http_url

logger = logging.getLogger(__name__)


def dispatch_implementation_pr_notifications(*, team_id: int, task_id: str, pr_url: str) -> int:
    if not is_safe_slack_http_url(pr_url) or len(pr_url) > 2000:
        return 0
    report_ids = SignalReportTask.objects.filter(
        team_id=team_id, task_id=task_id, relationship=TASK_RUN_TYPE_IMPLEMENTATION
    ).values("report_id")
    threads = list(
        SignalReportSlackThread.objects.for_team(team_id)
        .filter(report_id__in=report_ids, report__team_id=team_id, integration_id__isnull=False)
        .exclude(notified_pr_urls__contains=[pr_url])
    )
    if not threads:
        return 0
    integrations = IntegrationManager.slack.any.get_many(
        team_id, {thread.integration_id for thread in threads if thread.integration_id is not None}
    )
    sent = 0
    for thread in threads:
        integration = integrations.get(thread.integration_id) if thread.integration_id is not None else None
        if integration is None or integration.integration_id != thread.slack_workspace_id:
            continue
        try:
            SlackIntegration(integration, source="signals_inbox").client.chat_postMessage(
                channel=thread.channel,
                thread_ts=thread.thread_ts,
                text=f"Pull request opened: <{pr_url}|View pull request>",
                client_msg_id=str(uuid5(NAMESPACE_URL, f"signals-pr:{thread.id}:{pr_url}")),
                unfurl_links=False,
                unfurl_media=False,
            )
            SignalReportSlackThread.objects.for_team(team_id).filter(id=thread.id).exclude(
                notified_pr_urls__contains=[pr_url]
            ).update(notified_pr_urls=Func("notified_pr_urls", Value(pr_url), function="array_append"))
            sent += 1
        except Exception:
            logger.exception(
                "Failed to post an implementation PR to a report Slack thread",
                extra={"team_id": team_id, "task_id": task_id, "thread_id": str(thread.id)},
            )
    logger.info(
        "signals_inbox_pr_notifications_complete",
        extra={"team_id": team_id, "task_id": task_id, "messages_sent": sent},
    )
    return sent


@frozen
class ScoutReportSlackMessage:
    """A scout report message already in Slack, which a later delivery updates in place."""

    channel: str
    thread_ts: str
    reply_ts: list[str]


def record_report_slack_thread(
    *,
    team_id: int,
    report_id: str,
    integration_id: int | None,
    slack_workspace_id: str,
    channel: str,
    thread_ts: str,
    kind: SignalReportSlackThread.Kind,
    target: str | None = None,
) -> None:
    """Record that `thread_ts` in `channel` is a notification thread for this report."""
    try:
        SignalReportSlackThread.objects.for_team(team_id).get_or_create(
            slack_workspace_id=slack_workspace_id,
            channel=channel,
            thread_ts=thread_ts,
            defaults={
                "team_id": team_id,
                "report_id": report_id,
                "integration_id": integration_id,
                "kind": kind,
                "target": target,
            },
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


def scout_report_slack_message(
    *, team_id: int, report_id: str, slack_workspace_id: str, target: str | None = None, thread_ts: str | None = None
) -> ScoutReportSlackMessage | None:
    """The latest scout report message for this report at `target`, or the one rooted at `thread_ts`.

    Fails open: an unreadable link means post, since a duplicate message beats a lost report."""
    filters: dict[str, str] = {}
    if target is not None:
        filters["target"] = target
    if thread_ts is not None:
        filters["thread_ts"] = thread_ts
    try:
        row = (
            SignalReportSlackThread.objects.for_team(team_id)
            .filter(
                report_id=report_id,
                slack_workspace_id=slack_workspace_id,
                kind=SignalReportSlackThread.Kind.SCOUT_REPORT,
                **filters,
            )
            .order_by("-created_at")
            .values_list("channel", "thread_ts", "reply_ts")
            .first()
        )
    except Exception:
        logger.exception(
            "Failed to read the Slack message for signal report %s",
            report_id,
            extra={"team_id": team_id, "report_id": report_id},
        )
        return None
    if row is None:
        return None
    channel, root_ts, reply_ts = row
    return ScoutReportSlackMessage(channel=channel, thread_ts=root_ts, reply_ts=_reply_ts_list(reply_ts))


def record_scout_report_slack_replies(
    *, team_id: int, slack_workspace_id: str, channel: str, thread_ts: str, reply_ts: list[str]
) -> None:
    """Store the `ts` of each threaded reply, so a later delivery can update the replies in place."""
    try:
        SignalReportSlackThread.objects.for_team(team_id).filter(
            slack_workspace_id=slack_workspace_id,
            channel=channel,
            thread_ts=thread_ts,
            kind=SignalReportSlackThread.Kind.SCOUT_REPORT,
        ).update(reply_ts=reply_ts)
    except Exception:
        logger.exception(
            "Failed to record the Slack thread replies for a signal report",
            extra={"team_id": team_id, "channel": channel},
        )


def _reply_ts_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(ts) if ts else "" for ts in value]


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
