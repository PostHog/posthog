import json
from dataclasses import dataclass
from datetime import timedelta

import structlog
import temporalio
from asgiref.sync import sync_to_async
from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.models import Team
from posthog.sync import database_sync_to_async

from products.signals.backend.api import emit_signal
from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.grouping import (
    WaitForClickHouseInput,
    WaitForClickHouseSignal,
    wait_for_signal_in_clickhouse_activity,
)
from products.signals.backend.temporal.summary import (
    FetchSignalsForReportInput,
    FetchSignalsForReportOutput,
    fetch_signals_for_report_activity,
)
from products.signals.backend.temporal.types import SignalData, SignalReportReingestionWorkflowInputs
from products.signals.backend.utils import soft_delete_report_signals

logger = structlog.get_logger(__name__)


@dataclass
class SoftDeleteReportSignalsInput:
    team_id: int
    report_id: str


@temporalio.activity.defn
async def soft_delete_report_signals_activity(input: SoftDeleteReportSignalsInput) -> None:
    """Soft-delete all ClickHouse signals for a report by re-emitting with metadata.deleted=True."""
    team = await Team.objects.aget(pk=input.team_id)
    await sync_to_async(soft_delete_report_signals, thread_sensitive=False)(
        report_id=input.report_id,
        team_id=input.team_id,
        team=team,
    )
    logger.info(
        "Soft-deleted signals for report",
        team_id=input.team_id,
        report_id=input.report_id,
    )


@dataclass
class DeleteReportInput:
    team_id: int
    report_id: str


@temporalio.activity.defn
async def delete_report_activity(input: DeleteReportInput) -> None:
    """Transition a report to DELETED status in Postgres. Idempotent — no-ops if already deleted."""

    def do_delete():
        report = SignalReport.objects.get(id=input.report_id, team_id=input.team_id)
        if report.status == SignalReport.Status.DELETED:
            return  # Already deleted
        updated_fields = report.transition_to(SignalReport.Status.DELETED)
        report.save(update_fields=updated_fields)

    await database_sync_to_async(do_delete, thread_sensitive=False)()
    logger.info(
        "Deleted report",
        team_id=input.team_id,
        report_id=input.report_id,
    )


@dataclass
class ReingestSignalsInput:
    team_id: int
    signals: list[SignalData]


@temporalio.activity.defn
async def reingest_signals_activity(input: ReingestSignalsInput) -> None:
    """
    Re-emit all signals via emit_signal(), which handles org guards and
    signal-with-start into the per-team TeamSignalGroupingWorkflow.
    """
    team = await Team.objects.aget(pk=input.team_id)

    for signal in input.signals:
        await emit_signal(
            team=team,
            source_product=signal.source_product,
            source_type=signal.source_type,
            source_id=signal.source_id,
            description=signal.content,
            weight=signal.weight,
            extra=signal.extra,
        )

    logger.info(
        "Re-ingested signals via emit_signal",
        team_id=input.team_id,
        signal_count=len(input.signals),
    )


@temporalio.workflow.defn(name="signal-report-reingestion")
class SignalReportReingestionWorkflow:
    """
    Workflow that deletes a report and re-ingests its signals through the grouping pipeline.

    Flow:
    1. Fetch all signals for the report from ClickHouse
    2. Soft-delete all signals in ClickHouse (re-emit with metadata.deleted=True)
    3. Delete the report in Postgres (transition to DELETED)
    4. Re-ingest each signal via the TeamSignalGroupingWorkflow

    The signals will be re-processed through the full grouping pipeline and may end up
    in different reports based on the current LLM matching decisions.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SignalReportReingestionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return SignalReportReingestionWorkflowInputs(**loaded)

    @staticmethod
    def workflow_id_for(team_id: int, report_id: str) -> str:
        return f"signal-report-reingestion-{team_id}-{report_id}"

    @temporalio.workflow.run
    async def run(self, inputs: SignalReportReingestionWorkflowInputs) -> None:
        # 1. Fetch all signals for the report from ClickHouse
        fetch_result: FetchSignalsForReportOutput = await workflow.execute_activity(
            fetch_signals_for_report_activity,
            FetchSignalsForReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not fetch_result.signals:
            workflow.logger.warning(f"No signals found for report {inputs.report_id}, deleting report only")
            await workflow.execute_activity(
                delete_report_activity,
                DeleteReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return

        workflow.logger.info(
            f"Fetched {len(fetch_result.signals)} signals for report {inputs.report_id}, proceeding with reingestion"
        )

        # 2. Soft-delete all signals in ClickHouse
        await workflow.execute_activity(
            soft_delete_report_signals_activity,
            SoftDeleteReportSignalsInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 2b. Wait for all soft-deleted signals to land in ClickHouse before re-ingesting
        await workflow.execute_activity(
            wait_for_signal_in_clickhouse_activity,
            WaitForClickHouseInput(
                team_id=inputs.team_id,
                signals=[
                    WaitForClickHouseSignal(
                        signal_id=s.signal_id,
                        timestamp=s.timestamp,
                    )
                    for s in fetch_result.signals
                ],
                max_wait_time_seconds=3600,
            ),
            start_to_close_timeout=timedelta(hours=1, minutes=5),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        # 3. Delete the report in Postgres
        await workflow.execute_activity(
            delete_report_activity,
            DeleteReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 4. Re-ingest all signals via the grouping workflow
        await workflow.execute_activity(
            reingest_signals_activity,
            ReingestSignalsInput(team_id=inputs.team_id, signals=fetch_result.signals),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        workflow.logger.info(
            f"Reingestion complete for report {inputs.report_id}: "
            f"{len(fetch_result.signals)} signals re-submitted to grouping"
        )
