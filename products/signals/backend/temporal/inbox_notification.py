"""Decides when to send a report's inbox Slack notification.

A report that auto-starts an implementation task waits for the PR to open (so the card can
carry a "Review PR" button), bounded by a timeout. A report with no auto-start task notifies
immediately. Posting itself stays in `dispatch_inbox_item_notifications`; this governs timing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings

import structlog
import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.scoped import scoped_temporal

from products.signals.backend.implementation_pr import fetch_implementation_pr_urls_for_reports
from products.signals.backend.models import SignalReport, SignalReportTask
from products.signals.backend.temporal.signal_queries import fetch_signals_for_report_sync
from products.tasks.backend.models import TaskRun

logger = structlog.get_logger(__name__)


@dataclass
class InboxNotificationInput:
    team_id: int
    report_id: str


@dataclass
class InboxNotificationState:
    has_implementation_task: bool
    pr_available: bool
    task_terminal: bool


def _compute_inbox_notification_state(team_id: int, report_id: str) -> InboxNotificationState:
    has_task = SignalReportTask.objects.filter(
        team_id=team_id,
        report_id=report_id,
        relationship=SignalReportTask.Relationship.IMPLEMENTATION,
    ).exists()
    if not has_task:
        return InboxNotificationState(has_implementation_task=False, pr_available=False, task_terminal=False)

    pr_available = bool(fetch_implementation_pr_urls_for_reports([report_id]))
    latest_run = (
        TaskRun.objects.filter(
            task__signal_report_tasks__report_id=report_id,
            task__signal_report_tasks__relationship=SignalReportTask.Relationship.IMPLEMENTATION,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    task_terminal = bool(latest_run and latest_run.is_terminal) and not pr_available
    return InboxNotificationState(has_implementation_task=True, pr_available=pr_available, task_terminal=task_terminal)


@temporalio.activity.defn
@scoped_temporal()
async def get_inbox_notification_state_activity(input: InboxNotificationInput) -> InboxNotificationState:
    return await database_sync_to_async(_compute_inbox_notification_state, thread_sensitive=False)(
        input.team_id, input.report_id
    )


def _send_report_inbox_notifications(team_id: int, report_id: str) -> int:
    # Guard on status: a deferred wait can outlast the READY state (suppressed/deleted/re-promoted).
    report = SignalReport.objects.filter(id=report_id, team_id=team_id).only("status").first()
    if report is None or report.status != SignalReport.Status.READY:
        logger.info(
            "inbox notification skipped: report not READY",
            report_id=report_id,
            team_id=team_id,
            status=report.status if report else None,
        )
        return 0

    from products.signals.backend.slack_inbox_notifications import dispatch_inbox_item_notifications

    # Re-derive source products at send time so a deferred notification reflects the current signals.
    team = Team.objects.get(id=team_id)
    signals = fetch_signals_for_report_sync(team, report_id)
    source_products = sorted({s["source_product"] for s in signals if s.get("source_product")})
    return dispatch_inbox_item_notifications(report_id=report_id, team_id=team_id, source_products=source_products)


@temporalio.activity.defn
@scoped_temporal()
async def send_report_inbox_notifications_activity(input: InboxNotificationInput) -> int:
    return await database_sync_to_async(_send_report_inbox_notifications, thread_sensitive=False)(
        input.team_id, input.report_id
    )


@temporalio.workflow.defn(name="signal-report-inbox-notification")
class SignalReportInboxNotificationWorkflow:
    @staticmethod
    def workflow_id_for(team_id: int, report_id: str) -> str:
        return f"signals-inbox-notify:{team_id}:{report_id}"

    @temporalio.workflow.run
    async def run(self, inputs: InboxNotificationInput) -> int:
        timeout_seconds = settings.SIGNALS_INBOX_PR_NOTIFICATION_TIMEOUT_SECONDS
        poll_seconds = max(1, settings.SIGNALS_INBOX_PR_NOTIFICATION_POLL_SECONDS)

        state = await self._fetch_state(inputs)
        if state.has_implementation_task and not state.pr_available and not state.task_terminal:
            elapsed = 0
            while elapsed < timeout_seconds:
                await workflow.sleep(timedelta(seconds=poll_seconds))
                elapsed += poll_seconds
                state = await self._fetch_state(inputs)
                if state.pr_available or state.task_terminal:
                    break

        return await workflow.execute_activity(
            send_report_inbox_notifications_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

    async def _fetch_state(self, inputs: InboxNotificationInput) -> InboxNotificationState:
        return await workflow.execute_activity(
            get_inbox_notification_state_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
