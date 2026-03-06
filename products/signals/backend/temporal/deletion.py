import json
from datetime import datetime, timedelta

import temporalio
from temporalio import workflow
from temporalio.common import RetryPolicy

from products.signals.backend.temporal.grouping import WaitForClickHouseInput, wait_for_signal_in_clickhouse_activity
from products.signals.backend.temporal.reingestion import (
    DeleteReportInput,
    SoftDeleteReportSignalsInput,
    delete_report_activity,
    soft_delete_report_signals_activity,
)
from products.signals.backend.temporal.summary import (
    FetchSignalsForReportInput,
    FetchSignalsForReportOutput,
    fetch_signals_for_report_activity,
)
from products.signals.backend.temporal.types import SignalReportDeletionWorkflowInputs


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
        # 1. Fetch all signals for the report from ClickHouse
        fetch_result: FetchSignalsForReportOutput = await workflow.execute_activity(
            fetch_signals_for_report_activity,
            FetchSignalsForReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=2),
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

        # 2. Soft-delete all signals in ClickHouse
        await workflow.execute_activity(
            soft_delete_report_signals_activity,
            SoftDeleteReportSignalsInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 2b. Wait for the last soft-deleted signal to land in ClickHouse
        last_signal = fetch_result.signals[-1]
        await workflow.execute_activity(
            wait_for_signal_in_clickhouse_activity,
            WaitForClickHouseInput(
                team_id=inputs.team_id,
                signal_id=last_signal.signal_id,
                timestamp=datetime.fromisoformat(last_signal.timestamp),
            ),
            start_to_close_timeout=timedelta(minutes=2),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # 3. Delete the report in Postgres
        await workflow.execute_activity(
            delete_report_activity,
            DeleteReportInput(team_id=inputs.team_id, report_id=inputs.report_id),
            start_to_close_timeout=timedelta(minutes=1),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        workflow.logger.info(
            f"Deletion complete for report {inputs.report_id}: {len(fetch_result.signals)} signals soft-deleted"
        )
