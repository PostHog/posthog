"""Pre-extraction Temporal activity that performs a pending in-place repartition.

Runs inside `ExternalDataJobWorkflow` after the pipeline lock is held and before extraction, so it is
the sole writer for the schema (the schedule's OnlyOne overlap policy + the v3 pipeline lock guarantee
no concurrent sync). Acting on a pending target *before* the merge means the merge that follows in the
same run uses the new, memory-safe layout. A repartition failure never fails the workflow — the sync
just proceeds on the old layout (status quo) and the table is retried on a later run.
"""

import time
import dataclasses
from typing import Any

from django.db import close_old_connections

import structlog
from asgiref.sync import async_to_sync
from structlog.contextvars import bind_contextvars
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
    DeltaTableHelper,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.repartition import (
    RepartitionTarget,
    RepartitionUnpartitionableError,
    repartition_table_in_place,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.repartition_controller import (
    MAX_REPARTITION_ATTEMPTS,
    base_event_props,
    capture_repartition_event,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    DELTA_REPARTITION_DURATION_SECONDS,
    DELTA_REPARTITION_TOTAL,
)

LOGGER = structlog.get_logger(__name__)


@dataclasses.dataclass
class RepartitionActivityInputs:
    team_id: int
    schema_id: str
    job_id: str
    source_id: str


def _target_from_schema(schema: ExternalDataSchema) -> RepartitionTarget:
    """Fallback target reconstructed from the schema's current settings (resume-with-no-pending)."""
    return RepartitionTarget(
        partition_keys=schema.partitioning_keys or schema.primary_key_columns or [],
        trigger_reason="resume",
        partition_mode=schema.partition_mode,
        partition_format=schema.partition_format,
        partition_count=schema.partition_count,
        partition_size=schema.partition_size,
    )


@activity.defn
def maybe_repartition_table_activity(inputs: RepartitionActivityInputs) -> None:
    # Sync activity (runs in the worker's thread pool) so its ORM access is safe off the event loop;
    # the async repartition primitive is driven via async_to_sync, like import_data_activity_sync.
    bind_contextvars(team_id=inputs.team_id, schema_id=inputs.schema_id)
    logger = LOGGER.bind()
    close_old_connections()

    try:
        schema = ExternalDataSchema.objects.select_related("source").get(id=inputs.schema_id)
    except ExternalDataSchema.DoesNotExist:
        return

    pending = schema.repartition_pending
    swap = schema.repartition_swap
    if pending is None and swap is None:
        return  # Nothing queued — cheap common path.

    try:
        job = ExternalDataJob.objects.get(id=inputs.job_id)
    except ExternalDataJob.DoesNotExist:
        return

    target = RepartitionTarget.from_dict(pending) if pending is not None else _target_from_schema(schema)
    trigger_reason = (pending or {}).get("trigger_reason", "resume")

    helper = DeltaTableHelper(resource_name=schema.name, job=job, logger=logger)

    started_props = base_event_props(schema, schema.source, inputs.job_id)
    started_props["trigger_reason"] = trigger_reason
    capture_repartition_event("warehouse_repartition_started", started_props)
    logger.info("repartition: starting", trigger_reason=trigger_reason)

    start = time.monotonic()
    try:
        # HeartbeaterSync heartbeats on a background thread while the (possibly long) rewrite streams,
        # and on worker shutdown, so Temporal reschedules us instead of timing the activity out.
        with HeartbeaterSync(logger=logger):
            result = async_to_sync(repartition_table_in_place)(
                helper=helper,
                schema=schema,
                target=target,
                logger=logger,
            )
    except RepartitionUnpartitionableError as e:
        # Terminal: the table can't be partitioned. Clear the flag so we don't retry every run.
        schema.refresh_from_db(fields=["sync_type_config"])
        schema.clear_repartition_pending()
        props = base_event_props(schema, schema.source, inputs.job_id)
        props.update({"trigger_reason": trigger_reason, "reason": str(e)})
        capture_repartition_event("warehouse_repartition_skipped", props)
        DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome="skipped").inc()
        capture_exception(e)
        return
    except Exception as e:
        # Do NOT re-raise: a repartition failure must not block the sync — the table is retried on a
        # later run, on the old layout in the meantime.
        _handle_failure(inputs, schema, pending, trigger_reason, e)
        DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome="failed").inc()
        return

    duration = time.monotonic() - start
    DELTA_REPARTITION_DURATION_SECONDS.labels(team_id=str(inputs.team_id), schema_id=inputs.schema_id).observe(duration)
    DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome=result.get("outcome", "completed")).inc()

    props = base_event_props(schema, schema.source, inputs.job_id)
    props["trigger_reason"] = trigger_reason
    props["duration_seconds"] = duration
    props.update({k: v for k, v in result.items() if k != "outcome"})
    event = (
        "warehouse_repartition_completed" if result.get("outcome") == "completed" else "warehouse_repartition_skipped"
    )
    capture_repartition_event(event, props)
    logger.info("repartition: finished", outcome=result.get("outcome"), duration_seconds=duration)


def _handle_failure(
    inputs: RepartitionActivityInputs,
    schema: ExternalDataSchema,
    pending: dict[str, Any] | None,
    trigger_reason: str,
    error: Exception,
) -> None:
    """Record a failed attempt; give up (and clear the flag) after MAX_REPARTITION_ATTEMPTS."""
    schema.refresh_from_db(fields=["sync_type_config"])
    pending = schema.repartition_pending or pending or {}
    attempts = int(pending.get("attempts", 0)) + 1

    props = base_event_props(schema, schema.source, inputs.job_id)
    props.update(
        {
            "trigger_reason": trigger_reason,
            "attempts": attempts,
            "error_type": type(error).__name__,
            "error_message": str(error)[:1000],
        }
    )

    if attempts >= MAX_REPARTITION_ATTEMPTS:
        props["final"] = True
        schema.clear_repartition_pending()
        schema.clear_repartition_swap()
    else:
        updated = {**pending, "attempts": attempts}
        schema.set_repartition_pending(updated)

    capture_repartition_event("warehouse_repartition_failed", props)
    capture_exception(error)
