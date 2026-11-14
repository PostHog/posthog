import time
import asyncio
from datetime import timedelta
from uuid import UUID

from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from prometheus_client import Counter
from temporalio.client import WorkflowExecutionStatus
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.client import async_connect

from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.summary import (
    SignalReportSummaryWorkflow,
    revert_report_to_candidate,
    summary_execution_timeout,
)
from products.signals.backend.temporal.types import RESEARCH_DEBOUNCE_SECONDS

logger = structlog.get_logger(__name__)

# A report that is still IN_PROGRESS this long after its run started has outlived the run's
# `execution_timeout`. The margin covers the delay before Temporal enforces the timeout.
STUCK_RESEARCH_CUTOFF = summary_execution_timeout(RESEARCH_DEBOUNCE_SECONDS) + timedelta(minutes=15)
STUCK_RESEARCH_BATCH_SIZE = 100
STUCK_RESEARCH_LOOKUP_CONCURRENCY = 10
STUCK_RESEARCH_LOOKUP_TIMEOUT = 80
STUCK_RESEARCH_SWEEP_TIMEOUT = 110

STUCK_RESEARCH_REPORTS_RECOVERED = Counter(
    "signals_stuck_research_reports_recovered_total",
    "IN_PROGRESS reports with no running research workflow that the sweep returned to CANDIDATE.",
)


def recover_stuck_research_reports() -> int:
    """Return IN_PROGRESS reports that no research workflow still runs to CANDIDATE. Returns how many moved.

    A run that reaches its `execution_timeout`, or that someone terminates, never runs the workflow's
    error handling, and no promotion rule picks up an IN_PROGRESS report. Without this sweep, the
    report stays IN_PROGRESS. As CANDIDATE, it re-promotes on the next matching signal.
    """
    sweep_started = time.monotonic()
    started_before = timezone.now() - STUCK_RESEARCH_CUTOFF
    stale = list(
        SignalReport.objects.filter(status=SignalReport.Status.IN_PROGRESS, last_run_at__lt=started_before)
        .order_by("last_run_at")
        .values_list("team_id", "id")[:STUCK_RESEARCH_BATCH_SIZE]
    )
    if not stale:
        return 0
    lookup_timeout = max(0, STUCK_RESEARCH_LOOKUP_TIMEOUT - (time.monotonic() - sweep_started))
    workflow_statuses = async_to_sync(_research_workflow_statuses)(stale, lookup_timeout)
    recovered = 0
    for team_id, report_id in stale:
        if time.monotonic() - sweep_started >= STUCK_RESEARCH_SWEEP_TIMEOUT:
            break
        if report_id not in workflow_statuses:
            continue
        workflow_status = workflow_statuses[report_id]
        if workflow_status == WorkflowExecutionStatus.RUNNING:
            continue
        if revert_report_to_candidate(team_id, str(report_id), started_before=started_before):
            recovered += 1
            STUCK_RESEARCH_REPORTS_RECOVERED.inc()
            logger.warning(
                "signals.research.stuck_report_recovered",
                team_id=team_id,
                report_id=str(report_id),
                workflow_status=workflow_status.name if workflow_status else "NOT_FOUND",
            )
    return recovered


async def _research_workflow_statuses(
    reports: list[tuple[int, UUID]],
    timeout: float,
) -> dict[UUID, WorkflowExecutionStatus | None]:
    """Map each report to the status of its research workflow, or None when Temporal has no such workflow.

    A report that Temporal could not describe has no entry, so the sweep leaves it for the next run.
    """
    statuses: dict[UUID, WorkflowExecutionStatus | None] = {}

    async def describe_report(team_id: int, report_id: UUID, semaphore: asyncio.Semaphore) -> None:
        async with semaphore:
            workflow_id = SignalReportSummaryWorkflow.workflow_id_for(team_id, str(report_id))
            try:
                description = await client.get_workflow_handle(workflow_id).describe(rpc_timeout=timedelta(seconds=5))
            except RPCError as error:
                if error.status == RPCStatusCode.NOT_FOUND:
                    statuses[report_id] = None
                else:
                    logger.warning(
                        "signals.research.stuck_report_describe_failed",
                        team_id=team_id,
                        report_id=str(report_id),
                        error=str(error),
                    )
                return
            statuses[report_id] = description.status

    try:
        async with asyncio.timeout(timeout):
            client = await async_connect()
            semaphore = asyncio.Semaphore(STUCK_RESEARCH_LOOKUP_CONCURRENCY)
            async with asyncio.TaskGroup() as tasks:
                for team_id, report_id in reports:
                    tasks.create_task(describe_report(team_id, report_id, semaphore))
    except TimeoutError:
        logger.warning("signals.research.stuck_report_lookup_timed_out")
    return statuses
