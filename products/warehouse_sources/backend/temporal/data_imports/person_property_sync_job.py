"""Post-sync Temporal workflow that upserts staged warehouse rows onto person properties.

Started fire-and-forget by ``ExternalDataJobWorkflow`` after a sync when the schema feeds at least
one enabled person-target Customer analytics source. Runs on the DATA_WAREHOUSE_METADATA_TASK_QUEUE
(alongside semantic enrichment and column statistics) so a large first sync's post-processing never
competes with the sync workers themselves; ``start_temporal_worker`` registers it via the facade's
``PERSON_PROPERTY_SYNC_WORKFLOWS``/``PERSON_PROPERTY_SYNC_ACTIVITIES``.

Failure semantics: the activity retries up to 3 times, then the (abandoned) child workflow fails
without affecting the sync. Nothing is lost — staged files are only cleared on success and the
dedup snapshot only advances per produced person, so the next sync's run re-reads and re-diffs.
Each failed attempt is captured to error tracking. The workflow then records the run as failed and
counts it once in the metrics below, also when the activity was timed out, cancelled or killed.
"""

import json
import time
import dataclasses
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from prometheus_client import Counter, Histogram
from temporalio import activity, workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.heartbeat import LivenessHeartbeater as Heartbeater

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    PersonPropertyFailedRunInputs,
    PersonPropertySyncActivityInputs,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.person_property_sync import (
    failed_run_error,
    is_worker_interruption,
    record_completed_runs,
    record_failed_runs,
    record_started_runs,
    run_person_property_sync,
)

logger = structlog.get_logger(__name__)

INTERRUPTED_RUN_NEXT_STEP = "Check the source status, then click Sync now to try again."
# Three recorder attempts of up to 5 minutes each.
RECORD_FAILED_RUN_RESERVE = timedelta(minutes=15)
RECORD_FAILED_RUN_PATCH = "person-property-sync-record-failed-run-2026-10"

PERSON_PROPERTY_SYNC_TOTAL = Counter(
    "warehouse_person_property_sync_total",
    "Person-property sync runs by outcome",
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
    """Read the rows a warehouse run staged and upsert them onto person properties via Kafka."""
    log = logger.bind(**inputs.properties_to_log)
    log.info(f"Starting person-property sync for {inputs.source_type}/{inputs.schema_name}")
    start = time.monotonic()
    started_at = datetime.now(UTC).isoformat()
    binding = inputs.binding
    await record_started_runs(
        team_id=inputs.team_id,
        binding=binding,
        job_id=inputs.job_id,
        trigger="scheduled",
        started_at=started_at,
    )
    try:
        async with Heartbeater():
            result = await run_person_property_sync(team_id=inputs.team_id, binding=binding, job_id=inputs.job_id)
    except Exception as e:
        # Re-raised so Temporal retries; captured so a terminal failure is visible in error
        # tracking rather than dying silently in an abandoned child workflow. The failed outcome is
        # counted by the workflow once retries are exhausted, not here per attempt.
        log.exception("Person-property sync failed")
        capture_exception(e, inputs.properties_to_log)
        await record_failed_runs(
            team_id=inputs.team_id,
            binding=binding,
            job_id=inputs.job_id,
            trigger="scheduled",
            started_at=started_at,
            finished_at=datetime.now(UTC).isoformat(),
            error=str(e),
        )
        raise

    await record_completed_runs(
        team_id=inputs.team_id,
        binding=binding,
        job_id=inputs.job_id,
        trigger="scheduled",
        started_at=started_at,
        finished_at=datetime.now(UTC).isoformat(),
        result=result,
    )
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


@activity.defn
async def record_failed_person_property_sync_runs_activity(inputs: PersonPropertyFailedRunInputs) -> None:
    await record_failed_runs(
        team_id=inputs.team_id,
        binding=inputs.binding,
        job_id=inputs.job_id,
        trigger=inputs.trigger,
        started_at=inputs.started_at,
        finished_at=datetime.now(UTC).isoformat(),
        error=inputs.error,
        count_failure=inputs.count_failure,
    )
    PERSON_PROPERTY_SYNC_TOTAL.labels(team_id=str(inputs.team_id), outcome="failed").inc()


@workflow.defn(name="sync-warehouse-person-properties")
class SyncWarehousePersonPropertiesWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> PersonPropertySyncActivityInputs:
        loaded = json.loads(inputs[0])
        return PersonPropertySyncActivityInputs(**loaded)

    @workflow.run
    async def run(self, inputs: PersonPropertySyncActivityInputs) -> None:
        # Temporal terminates the workflow at its own deadline without running the except branch
        # below, so the activity has to give up early enough to leave time to record the failure.
        schedule_to_close_timeout = None
        info = workflow.info()
        if info.execution_timeout is not None:
            elapsed = workflow.now() - info.start_time
            schedule_to_close_timeout = info.execution_timeout - elapsed - RECORD_FAILED_RUN_RESERVE
        try:
            await workflow.execute_activity(
                sync_warehouse_person_properties_activity,
                inputs,
                start_to_close_timeout=timedelta(hours=6),
                schedule_to_close_timeout=schedule_to_close_timeout,
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except ActivityError as e:
            if workflow.patched(RECORD_FAILED_RUN_PATCH):
                try:
                    await workflow.execute_activity(
                        record_failed_person_property_sync_runs_activity,
                        PersonPropertyFailedRunInputs(
                            team_id=inputs.team_id,
                            schema_id=inputs.schema_id,
                            saved_query_id=inputs.saved_query_id,
                            job_id=inputs.job_id,
                            trigger="scheduled",
                            started_at=info.start_time.isoformat(),
                            error=failed_run_error(e, INTERRUPTED_RUN_NEXT_STEP),
                            count_failure=not is_worker_interruption(e),
                        ),
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=RetryPolicy(maximum_attempts=3),
                    )
                except ActivityError:
                    # Fail with the sync's own error, not the recorder's.
                    workflow.logger.exception("Failed to record the failed person-property sync run")
            raise


PERSON_PROPERTY_SYNC_WORKFLOWS = [SyncWarehousePersonPropertiesWorkflow]
PERSON_PROPERTY_SYNC_ACTIVITIES: list[Callable[..., Any]] = [
    sync_warehouse_person_properties_activity,
    record_failed_person_property_sync_runs_activity,
]
