import json
import datetime as dt

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.prune_snapshots import (
    PruneSnapshotsActivityInputs,
    PruneSnapshotsWorkflowInputs,
    UnpauseScheduleActivityInputs,
    prune_snapshots_activity,
    unpause_schedule_activity,
)


@workflow.defn(name="prune-snapshots")
class PruneSnapshotsWorkflow(PostHogWorkflow):
    """Ad-hoc, source-free prune of a full-refresh-append schema's expired snapshots.

    Triggered from the Django admin to reclaim storage from orphaned snapshots without waiting for the
    next scheduled sync. The admin pauses the schema's schedule before starting this workflow so a
    scheduled sync can't begin mid-prune; the workflow unpauses it again on completion (whether or not
    the prune itself succeeded) when the admin was the one that paused it.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> PruneSnapshotsWorkflowInputs:
        loaded = json.loads(inputs[0])
        return PruneSnapshotsWorkflowInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PruneSnapshotsWorkflowInputs) -> None:
        try:
            await workflow.execute_activity(
                prune_snapshots_activity,
                PruneSnapshotsActivityInputs(team_id=inputs.team_id, schema_id=inputs.schema_id),
                start_to_close_timeout=dt.timedelta(minutes=30),
                retry_policy=RetryPolicy(
                    initial_interval=dt.timedelta(seconds=10),
                    maximum_interval=dt.timedelta(seconds=60),
                    maximum_attempts=3,
                ),
            )
        finally:
            # Always hand the schedule back if we were the one that paused it, even if the prune failed —
            # otherwise a failed prune would leave the schema's syncs paused indefinitely.
            if inputs.unpause_schedule_after:
                await workflow.execute_activity(
                    unpause_schedule_activity,
                    UnpauseScheduleActivityInputs(schema_id=inputs.schema_id),
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
