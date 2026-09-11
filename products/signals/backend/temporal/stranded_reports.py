"""Scheduled reconciler for signal reports stranded in `in_progress`.

`SignalReportSummaryWorkflow` moves a report to `in_progress` at the start of a research pass and
back out through its own activities at the end. When Temporal closes the workflow without running
that code (execution timeout, termination, a history that no longer replays after a deploy), the
report keeps `in_progress`. No promotion rule in grouping reads that status, so nothing ever moves
it again. This workflow finds such reports and fails them, which is what the summary workflow's own
error handler would have done.

A report counts as stranded only when its summary workflow is verifiably not running: a long pass
is `RUNNING` and is left alone, and a describe that errors for any reason other than NOT_FOUND
proves nothing and is left alone too.
"""

from __future__ import annotations

from dataclasses import field
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

import structlog
import temporalio
from temporalio import workflow
from temporalio.client import WorkflowExecutionStatus
from temporalio.common import RetryPolicy
from temporalio.service import RPCError, RPCStatusCode

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.heartbeat import Heartbeater
from posthog.temporal.common.scoped import scoped_temporal
from posthog.temporal.common.utils import close_db_connections

from products.signals.backend.models import SignalReport
from products.signals.backend.signal_metadata import fetch_source_products_for_reports
from products.signals.backend.temporal import metrics
from products.signals.backend.temporal.summary import (
    FAIL_REPORT_FAILED,
    MarkReportFailedInput,
    SignalReportSummaryWorkflow,
    fail_report,
)

logger = structlog.get_logger(__name__)

WORKFLOW_NAME = "signals-stranded-report-reconciler"
SCHEDULE_ID = "signals-stranded-report-reconciler-schedule"
SCHEDULE_INTERVAL = timedelta(minutes=30)
# `failure_reason` on the `signal_report_completed` event, so stranded passes can be told apart from
# passes the summary workflow failed itself.
STRANDED_FAILURE_REASON = "research_run_stranded"

# A workflow in either of these states is still doing its pass.
_LIVE_WORKFLOW_STATUSES = frozenset({WorkflowExecutionStatus.RUNNING, WorkflowExecutionStatus.CONTINUED_AS_NEW})


@frozen
class StrandedReportReconcilerInput:
    pass


@frozen
class StrandedReport:
    team_id: int
    report_id: str
    run_count: int
    signal_count: int
    # ISO 8601. The value the report carried when it was judged stranded; the failing activity
    # refuses to act if the row has moved on since.
    last_run_at: str
    # The summary workflow's status name, or NOT_FOUND when Temporal no longer has it.
    workflow_status: str


@frozen
class FindStrandedReportsInput:
    older_than_minutes: int | None = None
    limit: int | None = None


@frozen
class FindStrandedReportsOutput:
    stranded: list[StrandedReport] = field(default_factory=list)
    scanned: int = 0
    running: int = 0
    truncated: bool = False


@frozen
class FailStrandedReportInput:
    team_id: int
    report_id: str
    expected_last_run_at: str
    workflow_status: str
    run_count: int
    signal_count: int


@frozen
class FailStrandedReportOutput:
    outcome: str


@frozen
class _InProgressReport:
    team_id: int
    report_id: str
    run_count: int
    signal_count: int
    last_run_at: datetime


def _fetch_old_in_progress_reports(older_than: timedelta, limit: int) -> list[_InProgressReport]:
    cutoff = timezone.now() - older_than
    rows = (
        SignalReport.objects.filter(status=SignalReport.Status.IN_PROGRESS, last_run_at__lt=cutoff)
        .order_by("last_run_at", "id")
        .values_list("team_id", "id", "run_count", "signal_count", "last_run_at")[:limit]
    )
    return [
        _InProgressReport(
            team_id=team_id,
            report_id=str(report_id),
            run_count=run_count,
            signal_count=signal_count,
            last_run_at=last_run_at,
        )
        for team_id, report_id, run_count, signal_count, last_run_at in rows
        # The `__lt` filter already excludes a null clock; this narrows the type.
        if last_run_at is not None
    ]


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def find_stranded_reports_activity(input: FindStrandedReportsInput) -> FindStrandedReportsOutput:
    if not settings.SIGNAL_STRANDED_REPORT_RECONCILER_ENABLED:
        logger.info("signals stranded report reconciler: disabled, skipping scan")
        return FindStrandedReportsOutput()

    older_than_minutes = (
        input.older_than_minutes
        if input.older_than_minutes is not None
        else settings.SIGNAL_STRANDED_REPORT_MIN_AGE_MINUTES
    )
    limit = input.limit if input.limit is not None else settings.SIGNAL_STRANDED_REPORT_MAX_PER_TICK

    candidates = await database_sync_to_async(_fetch_old_in_progress_reports, thread_sensitive=False)(
        timedelta(minutes=older_than_minutes), limit
    )

    stranded: list[StrandedReport] = []
    running = 0
    client = await async_connect()
    async with Heartbeater():
        for candidate in candidates:
            workflow_id = SignalReportSummaryWorkflow.workflow_id_for(candidate.team_id, candidate.report_id)
            try:
                description = await client.get_workflow_handle(workflow_id).describe()
            except RPCError as error:
                if error.status != RPCStatusCode.NOT_FOUND:
                    logger.warning(
                        "signals stranded report reconciler: describe failed, leaving report alone",
                        report_id=candidate.report_id,
                        team_id=candidate.team_id,
                        workflow_id=workflow_id,
                        error=str(error),
                    )
                    continue
                workflow_status = "NOT_FOUND"
            else:
                if description.status in _LIVE_WORKFLOW_STATUSES:
                    running += 1
                    metrics.increment_stranded_report_reconciled(metrics.STRANDED_OUTCOME_SKIPPED_RUNNING)
                    continue
                workflow_status = description.status.name if description.status else "UNKNOWN"
            stranded.append(
                StrandedReport(
                    team_id=candidate.team_id,
                    report_id=candidate.report_id,
                    run_count=candidate.run_count,
                    signal_count=candidate.signal_count,
                    last_run_at=candidate.last_run_at.isoformat(),
                    workflow_status=workflow_status,
                )
            )

    output = FindStrandedReportsOutput(
        stranded=stranded,
        scanned=len(candidates),
        running=running,
        truncated=len(candidates) >= limit,
    )
    logger.info(
        "signals stranded report reconciler: scan",
        scanned=output.scanned,
        running=output.running,
        stranded=len(output.stranded),
        truncated=output.truncated,
    )
    return output


def _source_products_for(team: Team, report_id: str) -> list[str]:
    meta = fetch_source_products_for_reports(team, [report_id]).get(report_id)
    return meta.source_products if meta else []


@temporalio.activity.defn
@scoped_temporal()
@close_db_connections
async def fail_stranded_report_activity(input: FailStrandedReportInput) -> FailStrandedReportOutput:
    expected_last_run_at = datetime.fromisoformat(input.expected_last_run_at)

    def still_stranded(report: SignalReport) -> bool:
        # A new pass rewrites `last_run_at` on CANDIDATE -> IN_PROGRESS, and any other move changes
        # the status, so the two together prove the row is the one the scan judged.
        return report.status == SignalReport.Status.IN_PROGRESS and report.last_run_at == expected_last_run_at

    team = await Team.objects.aget(pk=input.team_id)
    try:
        source_products = await database_sync_to_async(_source_products_for, thread_sensitive=False)(
            team, input.report_id
        )
    except Exception:
        logger.warning(
            "signals stranded report reconciler: could not read source products",
            report_id=input.report_id,
            team_id=input.team_id,
            exc_info=True,
        )
        source_products = []

    result = await fail_report(
        MarkReportFailedInput(
            team_id=input.team_id,
            report_id=input.report_id,
            error=f"Research run did not complete (summary workflow {input.workflow_status})",
            failure_reason=STRANDED_FAILURE_REASON,
            signal_count=input.signal_count,
            source_products=source_products,
        ),
        guard=still_stranded,
    )
    outcome = (
        metrics.STRANDED_OUTCOME_FAILED if result == FAIL_REPORT_FAILED else metrics.STRANDED_OUTCOME_SKIPPED_CHANGED
    )
    metrics.increment_stranded_report_reconciled(outcome)
    logger.info(
        "signals stranded report reconciler: reconciled report",
        report_id=input.report_id,
        team_id=input.team_id,
        outcome=outcome,
        workflow_status=input.workflow_status,
        run_count=input.run_count,
    )
    return FailStrandedReportOutput(outcome=outcome)


@temporalio.workflow.defn(name=WORKFLOW_NAME)
class StrandedReportReconcilerWorkflow:
    """One tick: scan for stranded reports, then fail each one in its own activity."""

    @staticmethod
    def parse_inputs(inputs: list[str]) -> StrandedReportReconcilerInput:
        return StrandedReportReconcilerInput()

    @temporalio.workflow.run
    async def run(self, _input: StrandedReportReconcilerInput) -> None:
        found = await workflow.execute_activity(
            find_stranded_reports_activity,
            FindStrandedReportsInput(),
            start_to_close_timeout=timedelta(minutes=10),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        for report in found.stranded:
            # One activity per report, contained, so a row that keeps erroring costs this tick that
            # report and nothing else. Sequential on purpose: a deploy strands tens of reports, not
            # thousands, and the per-report work is two small queries.
            try:
                await workflow.execute_activity(
                    fail_stranded_report_activity,
                    FailStrandedReportInput(
                        team_id=report.team_id,
                        report_id=report.report_id,
                        expected_last_run_at=report.last_run_at,
                        workflow_status=report.workflow_status,
                        run_count=report.run_count,
                        signal_count=report.signal_count,
                    ),
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            except Exception:
                workflow.logger.exception(
                    "signals stranded report reconciler: failing report raised",
                    extra={"team_id": report.team_id, "report_id": report.report_id},
                )
