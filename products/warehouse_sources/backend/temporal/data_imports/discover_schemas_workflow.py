import json
import datetime as dt

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.sync_new_schemas import (
    SyncNewSchemasActivityInputs,
    sync_new_schemas_activity,
)


@workflow.defn(name="discover-schemas")
class DiscoverSchemasWorkflow(PostHogWorkflow):
    """Per-source schema discovery workflow.

    Runs `sync_new_schemas_activity` for a single `ExternalDataSource` on a slow
    cadence (every 6h), independently of per-schema sync schedules. This
    keeps the expensive schema-discovery pass out of the per-schema sync hot
    path — see `external_data_job.ExternalDataJobWorkflow.run`, which used to
    fire it on every individual schema sync.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SyncNewSchemasActivityInputs:
        loaded = json.loads(inputs[0])
        return SyncNewSchemasActivityInputs(**loaded)

    @workflow.run
    async def run(self, inputs: SyncNewSchemasActivityInputs) -> None:
        await workflow.execute_activity(
            sync_new_schemas_activity,
            inputs,
            start_to_close_timeout=dt.timedelta(minutes=10),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=10),
                maximum_interval=dt.timedelta(seconds=60),
                maximum_attempts=3,
                non_retryable_error_types=["NotNullViolation", "IntegrityError", "BaseSSHTunnelForwarderError"],
            ),
        )
