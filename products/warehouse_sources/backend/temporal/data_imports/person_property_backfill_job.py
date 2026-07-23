"""Temporal workflow that backfills person properties from a warehouse table's full Delta data.

Unlike the incremental sync (which reads only the rows a sync staged), this reads the whole table's
parquet from S3 so a newly-created or changed person mapping populates historical rows it never saw.
It is keyed by schema, not source: one workflow reads the table once and upserts every enabled person
source on it, so mapping several properties from one table runs a single backfill.

Started from the customer_analytics facade (auto on mapping create/enable, or a manual "backfill"
button) with a per-``{team, schema}`` workflow id so concurrent triggers for the same table coalesce.
Runs on the DATA_WAREHOUSE_METADATA_TASK_QUEUE alongside the incremental sync so post-sync processing
never competes with the sync workers. The snapshot diff still skips unchanged values, so a re-run is
cheap and idempotent.
"""

import json
import time
import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from prometheus_client import Counter, Histogram
from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertyBackfillActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.person_property_sync import (
    record_completed_runs,
    record_failed_runs,
    run_person_property_backfill,
)

logger = structlog.get_logger(__name__)

PERSON_PROPERTY_BACKFILL_TOTAL = Counter(
    "warehouse_person_property_backfill_total",
    "Person-property backfill activity attempts by outcome",
    labelnames=["team_id", "outcome"],
)

PERSON_PROPERTY_BACKFILL_DURATION_SECONDS = Histogram(
    "warehouse_person_property_backfill_duration_seconds",
    "Duration of one person-property backfill activity run",
    buckets=(0.5, 1.0, 2.5, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0, 600.0, 1800.0, 3600.0),
)


@activity.defn
async def backfill_warehouse_person_properties_activity(inputs: PersonPropertyBackfillActivityInputs) -> dict[str, Any]:
    """Read the table's full Delta data and upsert every enabled person source onto person properties."""
    log = logger.bind(**inputs.properties_to_log)
    log.info(f"Starting person-property backfill for {inputs.source_type}/{inputs.schema_name}")
    start = time.monotonic()
    started_at = datetime.now(UTC).isoformat()
    try:
        async with Heartbeater():
            result = await run_person_property_backfill(
                team_id=inputs.team_id, schema_id=str(inputs.schema_id), trigger=inputs.trigger
            )
    except Exception as e:
        PERSON_PROPERTY_BACKFILL_TOTAL.labels(team_id=str(inputs.team_id), outcome="failed").inc()
        log.exception("Person-property backfill failed")
        capture_exception(e)
        await record_failed_runs(
            team_id=inputs.team_id,
            schema_id=str(inputs.schema_id),
            job_id=None,
            trigger=inputs.trigger,
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            error=str(e),
        )
        raise

    await record_completed_runs(
        team_id=inputs.team_id,
        schema_id=str(inputs.schema_id),
        job_id=None,
        trigger=inputs.trigger,
        started_at=started_at,
        finished_at=datetime.now(UTC).isoformat(),
        result=result,
    )
    PERSON_PROPERTY_BACKFILL_TOTAL.labels(team_id=str(inputs.team_id), outcome="completed").inc()
    PERSON_PROPERTY_BACKFILL_DURATION_SECONDS.observe(time.monotonic() - start)

    log.info(
        "Person-property backfill finished",
        sources=result.sources,
        rows_read=result.rows_read,
        changed=result.changed,
        existing=result.existing,
        produced=result.produced,
        skipped_missing_person=result.skipped_missing_person,
    )
    return dataclasses.asdict(result)


@workflow.defn(name="backfill-warehouse-person-properties")
class BackfillWarehousePersonPropertiesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PersonPropertyBackfillActivityInputs:
        loaded = json.loads(inputs[0])
        return PersonPropertyBackfillActivityInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PersonPropertyBackfillActivityInputs) -> None:
        await workflow.execute_activity(
            backfill_warehouse_person_properties_activity,
            inputs,
            start_to_close_timeout=timedelta(hours=6),
            heartbeat_timeout=timedelta(minutes=5),
            # A one-off full-table read: don't silently re-scan the whole table on a transient error.
            retry_policy=RetryPolicy(maximum_attempts=1),
        )


PERSON_PROPERTY_BACKFILL_WORKFLOWS = [BackfillWarehousePersonPropertiesWorkflow]
PERSON_PROPERTY_BACKFILL_ACTIVITIES = [backfill_warehouse_person_properties_activity]
