"""Post-sync Temporal workflow that upserts staged warehouse rows onto person properties.

Started fire-and-forget by ``ExternalDataJobWorkflow`` after a sync when the schema feeds at least
one enabled person-target Customer analytics source. Runs on the DATA_WAREHOUSE_METADATA_TASK_QUEUE
(alongside semantic enrichment and column statistics) so a large first sync's post-processing never
competes with the sync workers themselves; ``start_temporal_worker`` registers it via the facade's
``PERSON_PROPERTY_SYNC_WORKFLOWS``/``PERSON_PROPERTY_SYNC_ACTIVITIES``.

Failure semantics: the activity retries up to 3 times, then the (abandoned) child workflow fails
without affecting the sync. Nothing is lost — staged files are only cleared on success and the
dedup snapshot only advances per produced person, so the next sync's run re-reads and re-diffs.
Every terminal failure is captured to error tracking and counted in the metrics below.
"""

import json
import time
import dataclasses
from datetime import timedelta
from typing import Any

import structlog
from prometheus_client import Counter, Histogram
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertySyncActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.person_property_sync import (
    run_person_property_sync,
)

logger = structlog.get_logger(__name__)

PERSON_PROPERTY_SYNC_TOTAL = Counter(
    "warehouse_person_property_sync_total",
    "Person-property sync activity attempts by outcome",
    labelnames=["team_id", "outcome"],
)

# Funnel stages: rows_read -> changed (survived the snapshot diff) -> existing (distinct_id
# resolved to a person) -> produced (intent on Kafka). A stage dropping to zero pinpoints where
# updates are going missing (nothing staged / nothing changed / no matching persons / produce).
PERSON_PROPERTY_SYNC_ROWS_TOTAL = Counter(
    "warehouse_person_property_sync_rows_total",
    "Rows flowing through each stage of the person-property sync funnel",
    labelnames=["team_id", "stage"],
)

PERSON_PROPERTY_SYNC_DURATION_SECONDS = Histogram(
    "warehouse_person_property_sync_duration_seconds",
    "Duration of one person-property sync activity run",
    buckets=(0.5, 1.0, 2.5, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0),
)


@activity.defn
async def sync_warehouse_person_properties_activity(inputs: PersonPropertySyncActivityInputs) -> dict[str, Any]:
    """Read the rows a sync staged and upsert them onto person properties via Kafka."""
    log = logger.bind(**inputs.properties_to_log)
    log.info(f"Starting person-property sync for {inputs.source_type}/{inputs.schema_name}")
    start = time.monotonic()
    try:
        async with Heartbeater():
            result = await run_person_property_sync(
                team_id=inputs.team_id, schema_id=str(inputs.schema_id), job_id=inputs.job_id
            )
    except Exception as e:
        # Re-raised so Temporal retries; captured so a terminal failure is visible in error
        # tracking rather than dying silently in an abandoned child workflow.
        PERSON_PROPERTY_SYNC_TOTAL.labels(team_id=str(inputs.team_id), outcome="failed").inc()
        log.exception("Person-property sync failed")
        capture_exception(e)
        raise

    PERSON_PROPERTY_SYNC_TOTAL.labels(team_id=str(inputs.team_id), outcome="completed").inc()
    PERSON_PROPERTY_SYNC_DURATION_SECONDS.observe(time.monotonic() - start)
    for stage, count in (
        ("read", result.rows_read),
        ("changed", result.changed),
        ("existing", result.existing),
        ("produced", result.produced),
        ("skipped_missing_person", result.skipped_missing_person),
    ):
        if count:
            PERSON_PROPERTY_SYNC_ROWS_TOTAL.labels(team_id=str(inputs.team_id), stage=stage).inc(count)

    log.info(
        "Person-property sync finished",
        sources=result.sources,
        rows_read=result.rows_read,
        changed=result.changed,
        existing=result.existing,
        produced=result.produced,
        skipped_missing_person=result.skipped_missing_person,
    )
    return dataclasses.asdict(result)


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
