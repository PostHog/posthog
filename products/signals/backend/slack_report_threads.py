"""The Slack thread ↔ report link behind "reply in the thread and mention PostHog".

Both notification paths (the inbox reviewer notification and the scout harness delivery) record
the thread they posted, and the Slack mention handler reads it back so the task it starts lands on
the report's own timeline instead of floating free.

Writes are best-effort: a report must still reach Slack when the link cannot be stored.
"""

from __future__ import annotations

import re
import logging
from collections.abc import Sequence
from uuid import NAMESPACE_URL, uuid5

from django.db import IntegrityError
from django.db.models import Func, Q, Value

from slack_sdk.errors import SlackApiError

from posthog.dataclasses import frozen
from posthog.integrations import IntegrationManager, IntegrationRecord
from posthog.models import Team
from posthog.models.integration import SlackIntegration
from posthog.models.user_integration import UserIntegration

from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.assignment_flags import assignment_side_effects_allowed
from products.signals.backend.models import SignalReportSlackThread, SignalReportTask
from products.signals.backend.slack_notification_targets import is_slack_member_target

logger = logging.getLogger(__name__)
MAX_IMPLEMENTATION_PR_NOTIFICATIONS = 50


class ImplementationPRNotificationRetry(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("Slack PR notification needs a retry")
        self.retry_after = retry_after


def _notification_retry_after(error: Exception) -> int | None:
    if not isinstance(error, SlackApiError):
        return 0
    status = error.response.status_code
    transient = error.response.get("error") in {
        "ratelimited",
        "internal_error",
        "request_timeout",
        "service_unavailable",
    }
    if status != 429 and status < 500 and not transient:
        return None
    wait = str(error.response.headers.get("Retry-After", "0"))
    return int(wait) if wait.isdigit() else 0


def _thread_recipient_can_receive_pr(slack: SlackIntegration, thread: SignalReportSlackThread) -> bool:
    target = thread.target or ""
    if not is_slack_member_target(target):
        return not thread.channel.startswith(("D", "U", "W"))
    member = slack.get_user_by_id(target)
    if member is None:
        return False
    linked_users = UserIntegration.objects.filter(
        kind=UserIntegration.IntegrationKind.SLACK,
        integration_id=target,
        config__slack_team_id=thread.slack_workspace_id,
    ).values("user_id")
    identity = Q(id=thread.recipient_user_id) if thread.recipient_user_id is not None else Q(id__in=linked_users)
    team = Team.objects.get(id=thread.team_id)
    return team.all_users_with_access().filter(is_active=True).filter(identity).exists()


def _pr_repository(pr_url: str) -> str | None:
    if len(pr_url) > 2000:
        return None
    parsed = re.fullmatch(r"https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/pull/[1-9][0-9]*/?", pr_url)
    return parsed[1].lower() if parsed else None


def eligible_implementation_pr_urls(*, team_id: int, task_id: str, pr_urls: Sequence[str]) -> list[str]:
    task = (
        SignalReportTask.objects.filter(
            team_id=team_id, task_id=task_id, task__team_id=team_id, relationship=TASK_RUN_TYPE_IMPLEMENTATION
        )
        .values_list("task__repository", "task__repositories")
        .first()
    )
    if task is None:
        return []
    repository, repositories = task
    allowed = {value.lower() for value in [repository, *(repositories or [])] if value}
    urls: list[str] = []
    for url in dict.fromkeys(pr_urls):
        if _pr_repository(url) in allowed:
            urls.append(url)
            if len(urls) == MAX_IMPLEMENTATION_PR_NOTIFICATIONS:
                break
    return urls


def _report_thread_integrations(team_id: int, integration_ids: set[int]) -> dict[int, IntegrationRecord]:
    team = Team.objects.get(id=team_id)
    integrations: dict[int, IntegrationRecord] = {}
    for environment_id in Team.objects.filter(project_id=team.project_id).values_list("id", flat=True):
        integrations.update(IntegrationManager.slack.any.get_many(environment_id, integration_ids))
    return integrations


def dispatch_implementation_pr_notifications(*, team_id: int, task_id: str, pr_url: str) -> int:
    repository = _pr_repository(pr_url)
    if repository is None:
        return 0
    report_ids = (
        SignalReportTask.objects.filter(
            team_id=team_id, task_id=task_id, task__team_id=team_id, relationship=TASK_RUN_TYPE_IMPLEMENTATION
        )
        .filter(Q(task__repository__iexact=repository) | Q(task__repositories__contains=[repository]))
        .values("report_id")
    )
    threads = list(
        SignalReportSlackThread.objects.for_team(team_id)
        .filter(report_id__in=report_ids, report__team_id=team_id, integration_id__isnull=False)
        .exclude(notified_pr_urls__contains=[pr_url])
    )
    if not threads:
        return 0
    integration_ids = {thread.integration_id for thread in threads if thread.integration_id is not None}
    integrations = _report_thread_integrations(team_id, integration_ids)
    sent = 0
    retry_after: int | None = None
    for thread in threads:
        integration = integrations.get(thread.integration_id) if thread.integration_id is not None else None
        if integration is None or integration.integration_id != thread.slack_workspace_id:
            continue
        try:
            if not assignment_side_effects_allowed(team_id=team_id, report_id=str(thread.report_id)):
                continue
            slack = SlackIntegration(integration, source="signals_inbox", timeout_seconds=10)
            if not _thread_recipient_can_receive_pr(slack, thread):
                continue
            slack.client.chat_postMessage(
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
        except Exception as error:
            if (wait := _notification_retry_after(error)) is not None:
                retry_after = max(retry_after or 0, wait)
            logger.exception(
                "Failed to post an implementation PR to a report Slack thread",
                extra={"team_id": team_id, "task_id": task_id, "thread_id": str(thread.id)},
            )
    logger.info(
        "signals_inbox_pr_notifications_complete",
        extra={"team_id": team_id, "task_id": task_id, "messages_sent": sent},
    )
    if retry_after is not None:
        raise ImplementationPRNotificationRetry(retry_after)
    return sent


def dispatch_implementation_pr_notification_batch(*, team_id: int, task_id: str, pr_urls: list[str]) -> None:
    retry_after: int | None = None
    for url in pr_urls[:MAX_IMPLEMENTATION_PR_NOTIFICATIONS]:
        try:
            dispatch_implementation_pr_notifications(team_id=team_id, task_id=task_id, pr_url=url)
        except ImplementationPRNotificationRetry as error:
            retry_after = max(retry_after or 0, error.retry_after)
    if retry_after is not None:
        raise ImplementationPRNotificationRetry(retry_after)


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
    recipient_user_id: int | None = None,
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
                "recipient_user_id": recipient_user_id,
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
