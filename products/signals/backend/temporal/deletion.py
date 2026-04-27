import json
from datetime import timedelta

import structlog
import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from products.signals.backend.temporal.reingestion import (
    DeleteReportInput,
    SoftDeleteReportSignalsInput,
    delete_report_activity,
    soft_delete_report_signals_activity,
)
from products.signals.backend.temporal.signal_queries import (
    FetchSignalsForReportInput,
    FetchSignalsForReportOutput,
    WaitForClickHouseInput,
    WaitForClickHouseSignal,
    fetch_signals_for_report_activity,
    wait_for_signal_in_clickhouse_activity,
)
from products.signals.backend.temporal.types import SignalReportDeletionWorkflowInputs

logger = structlog.get_logger(__name__)


@temporalio.workflow.defn(name="signal-report-deletion")
class SignalReportDeletionWorkflow:
    """
    Workflow that soft-deletes a report and its signals.

    Flow:
    1. Fetch all signals for the report from ClickHouse
    2. Soft-delete all signals in ClickHouse (re-emit with metadata.deleted=True)
    2b. Wait for the last soft-deleted signal to land in ClickHouse
    3. Delete the report in Postgres (transition to DELETED)
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SignalReportDeletionWorkflowInputs:
        loaded = json.loads(inputs[0])
        return SignalReportDeletionWorkflowInputs(**loaded)

    @staticmethod
    def workflow_id_for(team_id: int, report_id: str) -> str:
        return f"signal-report-deletion-{team_id}-{report_id}"

    @temporalio.workflow.run
    async def run(self, inputs: SignalReportDeletionWorkflowInputs) -> None:
        # Bind team_id + report_id so all logs flow to the log_entries sink (the Temporal
        # structlog renderer skips producing when team_id isn't in the event dict).
        log = logger.bind(team_id=inputs.team_id, report_id=inputs.report_id)
        # 1. Fetch all signals for the report from ClickHouse
        fetch_result: FetchSignalsForReportOutput = await workflow.execute_activity(
            fetch_signals_for_report_activity,
            FetchSignalsForReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not fetch_result.signals:
            log.warning("No signals found for report, deleting report only")
            await workflow.execute_activity(
                delete_report_activity,
                DeleteReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
                start_to_close_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            return

        # 2. Soft-delete all signals in ClickHouse
        await workflow.execute_activity(
            soft_delete_report_signals_activity,
            SoftDeleteReportSignalsInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 2b. Wait for all soft-deleted signals to land in ClickHouse
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

        log.info(
            "Deletion complete for report: signals soft-deleted",
            signal_count=len(fetch_result.signals),
        )
