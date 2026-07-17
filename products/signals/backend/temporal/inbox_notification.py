"""Decides when to send a report's inbox Slack notification.

Every actionable report notifies; the PR is enrichment, not a gate. With an auto-start task we
wait (bounded by a timeout) for the PR so the card can link it, then notify either way; with no
task we notify immediately. Actionability is enforced downstream (READY status + persisted
priority). Posting lives in `dispatch_inbox_item_notifications`; this workflow governs timing.
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
from products.signals.backend.models import SignalReport
from products.signals.backend.task_run_artefacts import SIGNALS_PRODUCT, TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.temporal.signal_queries import fetch_signals_for_report_sync
from products.tasks.backend.facade import api as tasks_facade

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
    impl_task_ids = [
        run.task_id
        for run in SignalReport.associated_task_runs(
            report_id=report_id, team_id=team_id, product=SIGNALS_PRODUCT, type=TASK_RUN_TYPE_IMPLEMENTATION
        )
    ]
    if not impl_task_ids:
        return InboxNotificationState(has_implementation_task=False, pr_available=False, task_terminal=False)

    pr_available = bool(fetch_implementation_pr_urls_for_reports([report_id]))
    # Most recent run across the report's implementation task(s).
    latest_run = max(
        tasks_facade.get_latest_run_by_task(impl_task_ids).values(),
        key=lambda run: (run.created_at, run.id),
        default=None,
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

    # Team may have been deleted during a long deferred wait — degrade to no-op rather than failing.
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        logger.info("inbox notification skipped: team gone", report_id=report_id, team_id=team_id)
        return 0

    # Re-derive source products at send time so a deferred notification reflects the current signals.
    signals = fetch_signals_for_report_sync(team, report_id)
    source_products = sorted({s["source_product"] for s in signals if s.get("source_product")})
    return dispatch_inbox_item_notifications(
        report_id=report_id,
        team_id=team_id,
        source_products=source_products,
        signals=signals,
    )


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

        log_ctx = {"report_id": inputs.report_id, "team_id": inputs.team_id}

        state = await self._fetch_state(inputs)
        if state.has_implementation_task and not state.pr_available and not state.task_terminal:
            workflow.logger.info(
                "inbox notification: implementation task present, waiting for its PR",
                extra={**log_ctx, "timeout_seconds": timeout_seconds},
            )
            elapsed = 0
            while elapsed < timeout_seconds:
                await workflow.sleep(timedelta(seconds=poll_seconds))
                elapsed += poll_seconds
                state = await self._fetch_state(inputs)
                if state.pr_available or state.task_terminal:
                    break
            if state.pr_available:
                wait_outcome = "pr_opened"
            elif state.task_terminal:
                wait_outcome = "task_ended_without_pr"
            else:
                wait_outcome = "timed_out_without_pr"
            workflow.logger.info(
                "inbox notification: PR wait finished",
                extra={
                    **log_ctx,
                    "outcome": wait_outcome,
                    "elapsed_seconds": elapsed,
                    "pr_available": state.pr_available,
                },
            )
        elif not state.has_implementation_task:
            workflow.logger.info("inbox notification: no implementation task, notifying now", extra=log_ctx)
        else:
            workflow.logger.info(
                "inbox notification: PR already resolved on first check",
                extra={**log_ctx, "pr_available": state.pr_available},
            )

        # Transitional shim: keep replaying the now-removed `signals-inbox-skip-any-no-pr` patch so
        # executions in flight during rollout stay deterministic. Drop once they drain.
        workflow.deprecate_patch("signals-inbox-skip-any-no-pr")

        sent = await workflow.execute_activity(
            send_report_inbox_notifications_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        workflow.logger.info(
            "inbox notification: dispatch complete",
            extra={**log_ctx, "messages_sent": sent, "pr_available": state.pr_available},
        )
        return sent

    async def _fetch_state(self, inputs: InboxNotificationInput) -> InboxNotificationState:
        return await workflow.execute_activity(
            get_inbox_notification_state_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
