"""Per-scanner ClickHouse read metering and the sweep throttle it drives.

An hourly workflow aggregates `system.query_log` read bytes by the `scanner_id` query tag into
hourly buckets on each scanner row. The sweep consults the trailing-24h sum before querying and
stretches its effective cadence when a scanner exceeds its read budget (see `sweep_throttle_factor`).
"""

from typing import TYPE_CHECKING

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.replay_vision.backend.temporal.constants import (
    METER_SCANNER_READS_TIMEOUT,
    READ_METER_EXECUTION_TIMEOUT,
    READ_METER_INTERVAL,
    READ_METER_SCHEDULE_ID,
    READ_METER_WORKFLOW_ID,
    READ_METER_WORKFLOW_NAME,
)
from products.replay_vision.backend.temporal.read_meter_types import MeterScannerReadsInputs, MeterScannerReadsResult

if TYPE_CHECKING:
    from temporalio.client import Client

with workflow.unsafe.imports_passed_through():
    from products.replay_vision.backend.temporal.activities import meter_scanner_read_bytes_activity


@workflow.defn(name=READ_METER_WORKFLOW_NAME)
class MeterScannerReadsWorkflow(PostHogWorkflow):
    inputs_cls = MeterScannerReadsInputs
    inputs_optional = True

    @workflow.run
    async def run(self, inputs: MeterScannerReadsInputs) -> MeterScannerReadsResult:
        return await workflow.execute_activity(
            meter_scanner_read_bytes_activity,
            start_to_close_timeout=METER_SCANNER_READS_TIMEOUT,
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


async def create_replay_vision_read_meter_schedule(client: "Client") -> None:
    """Upsert the hourly read-meter schedule. Called on worker startup."""
    # Function-local: with `@workflow.defn` above, the Temporal sandbox can't
    # re-import the helper's Django/temporalio.client dependencies at workflow load.
    from products.replay_vision.backend.temporal.schedule import upsert_interval_schedule  # noqa: PLC0415

    await upsert_interval_schedule(
        client,
        schedule_id=READ_METER_SCHEDULE_ID,
        workflow_name=READ_METER_WORKFLOW_NAME,
        workflow_id=READ_METER_WORKFLOW_ID,
        inputs=MeterScannerReadsInputs(),
        interval=READ_METER_INTERVAL,
        execution_timeout=READ_METER_EXECUTION_TIMEOUT,
    )
