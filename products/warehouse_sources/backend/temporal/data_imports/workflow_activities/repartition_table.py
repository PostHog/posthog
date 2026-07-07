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

from asgiref.sync import async_to_sync
from structlog.contextvars import bind_contextvars
from structlog.types import FilteringBoundLogger
from temporalio import activity

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger

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
    WAREHOUSE_AUTO_REPARTITION_FLAG,
    base_event_props,
    capture_repartition_event,
    is_auto_repartition_enabled,
    maybe_flag_for_repartition,
    target_partition_bytes,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    DELTA_REPARTITION_DURATION_SECONDS,
    DELTA_REPARTITION_TOTAL,
)

LOGGER = get_logger(__name__)


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


def _needs_pre_extraction_detection(schema: ExternalDataSchema, enabled: bool) -> bool:
    """Whether to read the live on-disk partition sizes to decide if a repartition is needed.

    We deliberately do NOT gate on the recorded `max_partition_bytes`. That value is only refreshed by
    post-load detection, so for a table whose merge OOMs before post-load it goes stale and can sit far
    below the true partition size — precisely the tables this path exists to rescue (e.g. a partition
    that has since grown to many GB while the recorded value still reads a few hundred MB). Instead,
    whenever the rollout flag is on (a targeted set of schemas) and the table isn't CDC-excluded, we
    read the live partition sizes from the Delta log each run and let `maybe_flag_for_repartition` judge
    against the real, current size. The cost is one metadata-only Delta-log read per sync, bounded to
    flagged schemas; a disabled flag still short-circuits to a zero-I/O no-op.
    """
    if not enabled:
        return False
    if schema.sync_type == ExternalDataSchema.SyncType.CDC:
        return False
    return True


def _maybe_flag_pre_extraction(
    schema: ExternalDataSchema,
    job: ExternalDataJob,
    helper: DeltaTableHelper,
    logger: FilteringBoundLogger,
    enabled: bool,
) -> dict[str, Any] | None:
    """Measure the on-disk table before extraction and flag a repartition if it's over budget.

    The post-load detector (`maybe_flag_for_repartition`) only runs after a merge completes, so a table
    whose merge OOMs every run can never flag itself for repair — the classic chicken-and-egg. Running
    the same detection (same feature-flag, budget, and cooldown gating) here, pre-extraction, closes
    that gap: the on-disk table already reflects the over-budget layout, so we can flag and — in this
    same run — rewrite it before the merge that would OOM. Returns the pending target set by detection,
    or None if nothing was flagged (or the table couldn't be measured). Never raises.

    `enabled` is the already-evaluated rollout-flag verdict, threaded through so detection reuses it
    instead of paying for a second flag evaluation.
    """
    try:
        delta_table = async_to_sync(helper.get_delta_table)()
        if delta_table is None:
            logger.debug("repartition: no delta table on disk, cannot measure for repartition")
            return None
        async_to_sync(maybe_flag_for_repartition)(schema, schema.source, job, delta_table, logger, enabled=enabled)
    except Exception as e:
        # Detection is best-effort; a failure here must not block the sync.
        logger.warning("repartition: pre-extraction detection failed", exc_info=True)
        capture_exception(e)
        return None
    return schema.repartition_pending


@activity.defn
def maybe_repartition_table_activity(inputs: RepartitionActivityInputs) -> None:
    # Sync activity (runs in the worker's thread pool) so its ORM access is safe off the event loop;
    # the async repartition primitive is driven via async_to_sync, like import_data_activity_sync.
    bind_contextvars(team_id=inputs.team_id, schema_id=inputs.schema_id)
    logger = LOGGER.bind()
    close_old_connections()

    # Always bracket the run with start/finish INFO lines so the Syncs UI shows the activity ran even
    # on the healthy no-op path (which otherwise only logs at DEBUG). The finally guarantees the finish
    # line regardless of which branch returns, including swallowed failures.
    logger.info(
        f"repartition: activity started job_id={inputs.job_id} source_id={inputs.source_id}",
        job_id=inputs.job_id,
        source_id=inputs.source_id,
    )
    try:
        _maybe_repartition_table(inputs, logger)
    finally:
        logger.info("repartition: activity finished")


def _maybe_repartition_table(inputs: RepartitionActivityInputs, logger: FilteringBoundLogger) -> None:
    try:
        schema = ExternalDataSchema.objects.select_related("source").get(id=inputs.schema_id)
    except ExternalDataSchema.DoesNotExist:
        logger.warning(
            f"repartition: schema not found, skipping activity schema_id={inputs.schema_id}",
            schema_id=inputs.schema_id,
        )
        return

    # Log the rollout-flag verdict (and the recorded/budget sizes) so it's clear from the Syncs UI why a
    # table does or doesn't repartition — a disabled flag is the most common reason for a no-op. Note
    # `max_partition_bytes` here is the last *recorded* value (can be stale); the gate no longer trusts
    # it, the live size is read below. Evaluate the flag once and thread the result into the
    # pre-extraction detection path so it isn't re-evaluated inside maybe_flag_for_repartition.
    enabled = is_auto_repartition_enabled(schema)
    recorded_max_partition_bytes = schema.max_partition_bytes
    budget = target_partition_bytes()
    logger.info(
        f"repartition: feature flag evaluated flag={WAREHOUSE_AUTO_REPARTITION_FLAG} enabled={enabled} "
        f"max_partition_bytes={recorded_max_partition_bytes} target_partition_bytes={budget}",
        flag=WAREHOUSE_AUTO_REPARTITION_FLAG,
        enabled=enabled,
        max_partition_bytes=recorded_max_partition_bytes,
        target_partition_bytes=budget,
    )

    pending = schema.repartition_pending
    swap = schema.repartition_swap

    # Fast no-op path: nothing queued and the gate says no on-disk measurement is needed (flag off, or
    # CDC). Return here — before fetching the job and reading the delta log — so the common healthy
    # invocation avoids all on-disk I/O. Flagged tables fall through and measure the live size below.
    if pending is None and swap is None and not _needs_pre_extraction_detection(schema, enabled):
        logger.info("repartition: nothing queued and no detection needed, nothing to do")
        return

    try:
        job = ExternalDataJob.objects.get(id=inputs.job_id)
    except ExternalDataJob.DoesNotExist:
        logger.warning(
            f"repartition: job not found, skipping activity job_id={inputs.job_id}",
            job_id=inputs.job_id,
        )
        return

    helper = DeltaTableHelper(resource_name=schema.name, job=job, logger=logger)

    if pending is None and swap is None:
        # Nothing was queued by a prior run's post-load detection, but the gate flagged the table for an
        # on-disk measurement. Measure now and self-flag if it's over budget — the only path that can
        # rescue a table which OOMs its merge every run (and so never reaches post-load detection).
        pending = _maybe_flag_pre_extraction(schema, job, helper, logger, enabled)
        if pending is None:
            logger.debug("repartition: pre-extraction measurement found no repartition needed")
            return

    target = RepartitionTarget.from_dict(pending) if pending is not None else _target_from_schema(schema)
    trigger_reason = (pending or {}).get("trigger_reason", "resume")

    started_props = base_event_props(schema, schema.source, inputs.job_id)
    started_props["trigger_reason"] = trigger_reason
    capture_repartition_event("warehouse_repartition_started", started_props)
    logger.info(f"repartition: starting trigger_reason={trigger_reason}", trigger_reason=trigger_reason)

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
        _handle_failure(inputs, schema, pending, trigger_reason, e, logger)
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
    outcome = result.get("outcome")
    logger.info(
        f"repartition: finished outcome={outcome} duration_seconds={duration}",
        outcome=outcome,
        duration_seconds=duration,
    )


def _handle_failure(
    inputs: RepartitionActivityInputs,
    schema: ExternalDataSchema,
    pending: dict[str, Any] | None,
    trigger_reason: str,
    error: Exception,
    logger: FilteringBoundLogger,
) -> None:
    """Record a failed attempt; give up (and clear the flag) after MAX_REPARTITION_ATTEMPTS.

    This runs from the swallow-all `except` around the rewrite, so it must never raise — the whole
    point of that block is that a repartition failure leaves the table on its old layout and the sync
    proceeds. The original failure and a dead Postgres connection can arrive together (a transient
    infra blip drops both S3 and the DB pooler), so re-establish the connection before the ORM access
    and treat the attempt-bookkeeping writes as best-effort: a residual DB error is logged and
    captured, not re-raised, or it would fail the very activity the outer `except` exists to protect.
    """
    props = base_event_props(schema, schema.source, inputs.job_id)
    props.update(
        {
            "trigger_reason": trigger_reason,
            "error_type": type(error).__name__,
            "error_message": str(error)[:1000],
        }
    )

    try:
        # The pooler connection may have dropped alongside the original failure; recycle it so the ORM
        # access below re-establishes a fresh one instead of raising OperationalError on a dead socket.
        close_old_connections()
        schema.refresh_from_db(fields=["sync_type_config"])
        pending = schema.repartition_pending or pending or {}
        attempts = int(pending.get("attempts", 0)) + 1
        props["attempts"] = attempts

        if attempts >= MAX_REPARTITION_ATTEMPTS:
            props["final"] = True
            schema.clear_repartition_pending()
            schema.clear_repartition_swap()
        else:
            updated = {**pending, "attempts": attempts}
            schema.set_repartition_pending(updated)
    except Exception as db_error:
        # Persisting the attempt is best-effort. If the DB is still unreachable we leave the pending
        # flag untouched (the table simply retries next run) rather than let the error escape.
        logger.warning("repartition: failed to persist repartition failure state", exc_info=True)
        capture_exception(db_error)

    capture_repartition_event("warehouse_repartition_failed", props)
    capture_exception(error)
