"""Post-sync Temporal workflow that upserts staged warehouse rows onto person properties.

Started fire-and-forget by ``ExternalDataJobWorkflow`` after a sync when the schema feeds at least
one enabled person-target Customer analytics source. Runs on the VIDEO_EXPORT_TASK_QUEUE (the same
worker the signals emission uses) so a large first sync's Kafka production never competes with the
data-warehouse sync workers; ``start_temporal_worker`` registers it via the facade's
``PERSON_PROPERTY_SYNC_WORKFLOWS``/``PERSON_PROPERTY_SYNC_ACTIVITIES``.
"""

import json
from datetime import timedelta
from typing import Any

import structlog
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertySyncActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.person_property_sync import (
    run_person_property_sync,
)

logger = structlog.get_logger(__name__)


@activity.defn
async def sync_warehouse_person_properties_activity(inputs: PersonPropertySyncActivityInputs) -> dict[str, Any]:
    """Read the rows a sync staged and upsert them onto person properties via Kafka."""
    log = logger.bind(**inputs.properties_to_log)
    log.info(f"Starting person-property sync for {inputs.source_type}/{inputs.schema_name}")
    async with Heartbeater():
        result = await run_person_property_sync(
            team_id=inputs.team_id, schema_id=str(inputs.schema_id), job_id=inputs.job_id
        )
    log.info(
        "Person-property sync finished",
        sources=result.sources,
        rows_read=result.rows_read,
        changed=result.changed,
        existing=result.existing,
        produced=result.produced,
    )
    return {
        "sources": result.sources,
        "rows_read": result.rows_read,
        "changed": result.changed,
        "existing": result.existing,
        "produced": result.produced,
    }


@workflow.defn(name="sync-warehouse-person-properties")
class SyncWarehousePersonPropertiesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PersonPropertySyncActivityInputs:
        loaded = json.loads(inputs[0])
        return PersonPropertySyncActivityInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PersonPropertySyncActivityInputs) -> None:
        await workflow.execute_activity(
            sync_warehouse_person_properties_activity,
            inputs,
            start_to_close_timeout=timedelta(hours=6),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )


PERSON_PROPERTY_SYNC_WORKFLOWS = [SyncWarehousePersonPropertiesWorkflow]
PERSON_PROPERTY_SYNC_ACTIVITIES = [sync_warehouse_person_properties_activity]
