"""Pre-extraction Temporal activity that performs a pending in-place repartition.

Runs inside `ExternalDataJobWorkflow` after the pipeline lock is held and before extraction, so it is
the sole writer for the schema (the schedule's OnlyOne overlap policy + the v3 pipeline lock guarantee
no concurrent sync). Acting on a pending target *before* the merge means the merge that follows in the
same run uses the new, memory-safe layout. A repartition failure never fails the workflow — the sync
just proceeds on the old layout (status quo) and the table is retried on a later run. The one nuance:
a transient infra error during an admin-staged rewrite re-raises retryable so the activity's retry
policy re-runs it in this run (the workflow swallows the failure if retries exhaust).
"""

import time
import uuid
import asyncio
import datetime as dt
import dataclasses
from typing import Any

from django.db import InterfaceError, OperationalError, close_old_connections
from django.utils import timezone

from asgiref.sync import async_to_sync
from structlog.contextvars import bind_contextvars
from structlog.types import FilteringBoundLogger
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.exceptions_capture import capture_exception
from posthog.temporal.common.heartbeat_sync import HeartbeaterSync
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.utils import retry_on_db_connection_drop

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.errors import (
    is_transient_maintenance_error,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.delta.table import DeltaTableRef
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition import (
    RepartitionBudgetExceededError,
    RepartitionSupersededError,
    RepartitionTarget,
    RepartitionUnpartitionableError,
    repartition_table_in_place,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller import (
    MAX_REPARTITION_ATTEMPTS,
    WAREHOUSE_AUTO_REPARTITION_FLAG,
    base_event_props,
    capture_repartition_event,
    is_auto_coarsen_enabled,
    is_auto_repartition_enabled,
    maybe_flag_for_repartition,
    target_partition_bytes,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.metrics import (
    DELTA_REPARTITION_DURATION_SECONDS,
    DELTA_REPARTITION_TOTAL,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.job_context import bind_job_context

LOGGER = get_logger(__name__)


@dataclasses.dataclass
class RepartitionActivityInputs:
    team_id: int
    schema_id: str
    job_id: str
    source_id: str


def _is_cancellation(error: BaseException) -> bool:
    """Whether `error` is an activity cancellation, however it surfaced.

    `async_to_sync` can wrap a worker-shutdown `asyncio.CancelledError` (a `BaseException` since 3.8) so
    it arrives Exception-derived; match on the type name too so it's never mistaken for a real failure.
    """
    return isinstance(error, asyncio.CancelledError) or type(error).__name__ == "CancelledError"


# Infra noise observed escaping the rewrite as generic OSError/HTTPClientError — none of these are
# repartition bugs, and the marker-idempotent swap means the next sync simply retries.
_TRANSIENT_ERROR_SNIPPETS = (
    "reduce your request rate",  # S3 503 SlowDown surfaced by the delta kernel as OSError
    "error occurred while loading credentials",  # IMDS/credential-provider timeout inside the kernel
    "event loop is closed",  # s3fs client bound to an already-completed async_to_sync loop
)


# How much of the activity's budget to leave unused when the rewrite gives up, so the failed attempt
# can still be recorded before Temporal kills the activity. Only the bookkeeping needs covering: a
# couple of writes to the schema row and one event.
REWRITE_DEADLINE_MARGIN = dt.timedelta(minutes=5)


def _rewrite_deadline() -> float | None:
    """Monotonic time by which the rewrite must stop to leave room to record its own failure.

    None when there is no budget to derive one from: outside an activity context (direct calls from
    tests), when the activity declares no `start_to_close_timeout`, or when that timeout is shorter
    than the margin. In each case the rewrite runs unbounded, which is the behavior that predates
    this deadline rather than an instant give-up.
    """
    try:
        info = activity.info()
    except RuntimeError:
        return None
    if info.start_to_close_timeout is None:
        return None
    budget = (info.start_to_close_timeout - REWRITE_DEADLINE_MARGIN).total_seconds()
    if budget <= 0:
        return None
    return time.monotonic() + budget


def _is_transient_infra_error(error: Exception) -> bool:
    if isinstance(error, OperationalError | InterfaceError):
        return True
    message = str(error).lower()
    return any(snippet in message for snippet in _TRANSIENT_ERROR_SNIPPETS)


def _still_claimant(schema: ExternalDataSchema, claim_token: str) -> bool:
    """Whether this attempt still holds the schema's repartition claim.

    Conservative on doubt: if the claim can't be read (DB blip), report True so a real failure is
    never silently dropped.
    """
    try:
        schema.refresh_from_db(fields=["sync_type_config"])
        claim = schema.repartition_claim
        return bool(claim and claim.get("token") == claim_token)
    except Exception:
        return True


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

    A table nominated for coarsening is measured whether or not the rollout flag covers it, since the
    nomination is the operator asking for exactly this measurement. CDC stays excluded either way.
    """
    if schema.sync_type == ExternalDataSchema.SyncType.CDC:
        return False
    if schema.coarsen_requested is not None:
        return True
    return enabled


def _maybe_flag_pre_extraction(
    schema: ExternalDataSchema,
    job: ExternalDataJob,
    table_ref: DeltaTableRef,
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
        delta_table = async_to_sync(table_ref.get_delta_table)()
        if delta_table is None:
            logger.debug("repartition: no delta table on disk, cannot measure for repartition")
            return None
        async_to_sync(maybe_flag_for_repartition)(schema, schema.source, job, delta_table, logger, enabled=enabled)
    except Exception as e:
        # Detection is best-effort; a failure here must not block the sync. `get_delta_table` re-raises
        # transient object-store blips (S3/credential-provider timeouts) rather than swallowing them —
        # see its own docstring — and resolving `job.folder_path()` on a pooled app-DB connection can
        # raise OperationalError/InterfaceError the same way. `is_transient_maintenance_error` covers
        # both, so this is the layer that must apply it before reporting, same as the other best-effort
        # call sites around this table.
        if is_transient_maintenance_error(e):
            logger.warning("repartition: pre-extraction detection failed with a transient infra error")
        else:
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
        schema = retry_on_db_connection_drop(
            lambda: ExternalDataSchema.objects.select_related("source").get(id=inputs.schema_id)
        )
    except ExternalDataSchema.DoesNotExist:
        logger.warning(
            f"repartition: schema not found, skipping activity schema_id={inputs.schema_id}",
            schema_id=inputs.schema_id,
        )
        return

    # A table with a pending corruption revive must heal first — the extract activity resets it and
    # rebuilds from source. Repartitioning it here would interleave with that heal and re-hollow the
    # table, re-arming the revive marker every run (a non-billable revive loop). Skip until the revive
    # clears the marker; the healed table is repartitioned normally on a later run.
    if schema.delta_revive_required is not None:
        logger.info(
            f"repartition: skipped, table pending corruption revive schema_id={schema.id}",
            schema_id=str(schema.id),
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

    # The flag has to stop a queued rewrite too, not only detection. Once a table is flagged, the
    # rewrite runs ahead of extraction on every sync, so a rewrite that can't finish delays the sync
    # by the full activity budget indefinitely; the flag is the only lever support has to release
    # such a table, and it does nothing here if it only gates detection. Each auto-staged trigger
    # family answers to the flag that staged it, and any other reason fails open: operator-staged
    # work (admin, coarsening nominations) was queued knowing that syncing on the old layout is the
    # worse option, so it must never dead-end on a rollout flag. A staged swap is always driven to
    # completion because temp is the source of truth in that window and live may already be deleted.
    if pending is not None and swap is None:
        reason = pending.get("trigger_reason")
        if reason in ("proactive_threshold", "oom_history"):
            release = not enabled
        elif reason == "coarsening":
            release = not is_auto_coarsen_enabled(schema)
        else:
            release = False
        if release:
            logger.info(
                f"repartition: queued rewrite skipped, controller disabled by feature flag schema_id={schema.id}",
                schema_id=str(schema.id),
                trigger_reason=reason,
            )
            return

    # Fast no-op path: nothing queued and the gate says no on-disk measurement is needed (flag off, or
    # CDC). Return here — before fetching the job and reading the delta log — so the common healthy
    # invocation avoids all on-disk I/O. Flagged tables fall through and measure the live size below.
    if pending is None and swap is None and not _needs_pre_extraction_detection(schema, enabled):
        logger.info("repartition: nothing queued and no detection needed, nothing to do")
        return

    try:
        job = retry_on_db_connection_drop(lambda: ExternalDataJob.objects.get(id=inputs.job_id))
    except ExternalDataJob.DoesNotExist:
        logger.warning(
            f"repartition: job not found, skipping activity job_id={inputs.job_id}",
            job_id=inputs.job_id,
        )
        return

    # Attach the same source/schema identity the import activity does, so an exception captured
    # anywhere below (budget exhaustion, an unexpected rewrite failure) can be attributed to a
    # connector and table instead of landing in error tracking with no sync context.
    bind_job_context(
        team_id=inputs.team_id,
        source_type=schema.source.source_type,
        external_data_source_id=inputs.source_id,
        external_data_schema_id=inputs.schema_id,
        external_data_job_id=inputs.job_id,
        schema_name=schema.name,
        sync_type=schema.sync_type,
        pipeline_version=job.pipeline_version,
    )

    # `resolved_s3_folder_name` is authoritative for the Delta folder, not the row's own name: a row
    # renamed during the multi-schema migration keeps its folder pinned to the original path (name
    # `public.users`, folder `users`), and the pipeline writes there too. Deriving the folder from
    # `name` alone probes a path that was never written and the repartition skips as `no_delta_table`.
    resource_name = schema.resolved_s3_folder_name or schema.name
    table_ref = DeltaTableRef(resource_name=resource_name, job=job, logger=logger)

    if pending is None and swap is None:
        # Nothing was queued by a prior run's post-load detection, but the gate flagged the table for an
        # on-disk measurement. Measure now and self-flag if it's over budget — the only path that can
        # rescue a table which OOMs its merge every run (and so never reaches post-load detection).
        pending = _maybe_flag_pre_extraction(schema, job, table_ref, logger, enabled)
        if pending is None:
            logger.debug("repartition: pre-extraction measurement found no repartition needed")
            return

    target = RepartitionTarget.from_dict(pending) if pending is not None else _target_from_schema(schema)
    trigger_reason = (pending or {}).get("trigger_reason", "resume")

    started_props = base_event_props(schema, schema.source, inputs.job_id)
    started_props["trigger_reason"] = trigger_reason
    capture_repartition_event("warehouse_repartition_started", started_props)
    logger.info(f"repartition: starting trigger_reason={trigger_reason}", trigger_reason=trigger_reason)

    # Fencing claim: if we get heartbeat-timed-out mid-rewrite, this activity keeps running as a
    # zombie (heartbeat failures are swallowed) while Temporal starts a retry. The retry's newer claim
    # makes every claim re-check inside the rewrite/swap raise RepartitionSupersededError in the
    # zombie, so exactly one writer ever touches the table's S3 state.
    claim_token = str(uuid.uuid4())
    schema.set_repartition_claim(
        {"token": claim_token, "job_id": inputs.job_id, "claimed_at": timezone.now().isoformat()}
    )

    start = time.monotonic()
    try:
        # HeartbeaterSync heartbeats on a background thread while the (possibly long) rewrite streams,
        # and on worker shutdown, so Temporal reschedules us instead of timing the activity out.
        with HeartbeaterSync(logger=logger):
            result = async_to_sync(repartition_table_in_place)(
                table_ref=table_ref,
                schema=schema,
                target=target,
                logger=logger,
                claim_token=claim_token,
                deadline=_rewrite_deadline(),
            )
    except RepartitionBudgetExceededError as e:
        # The table is telling us its rewrite doesn't fit in one activity. Record it as a real failed
        # attempt so `MAX_REPARTITION_ATTEMPTS` is reachable and the table eventually gives up,
        # instead of restarting the same doomed rewrite in front of every sync forever.
        logger.warning(f"repartition: {e}")
        DELTA_REPARTITION_TOTAL.labels(
            team_id=str(inputs.team_id),
            outcome=_handle_failure(inputs, schema, pending, trigger_reason, e, claim_token, logger),
        ).inc()
        return
    except RepartitionSupersededError:
        # A newer attempt claimed the schema and owns the table now. Stop without recording a *failure*
        # (that would burn an attempt and double-report the run the newer claimant is already handling),
        # but still emit the skip: a started event with no terminal event leaves `repartition_pending`
        # set and no way to tell a stood-down attempt from one that vanished.
        logger.info("repartition: superseded by a newer attempt, standing down")
        DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome="superseded").inc()
        _capture_stood_down(schema, inputs, trigger_reason, "superseded", logger)
        return
    except RepartitionUnpartitionableError as e:
        # Terminal: the table can't be partitioned on its keys. Clear the flag AND engage the cooldown —
        # clearing `repartition_pending` alone re-arms the loop, because detection re-flags on the very
        # next sync (the OOM/size trigger is still true and the table's scheme is unchanged), so the
        # table churns flag → start → skip every 5 minutes forever. The cooldown re-evaluates at most
        # daily instead.
        schema.refresh_from_db(fields=["sync_type_config"])
        schema.clear_repartition_pending()
        schema.clear_repartition_rewrite()
        schema.stamp_last_repartition_at()
        props = base_event_props(schema, schema.source, inputs.job_id)
        props.update({"trigger_reason": trigger_reason, "reason": str(e)})
        capture_repartition_event("warehouse_repartition_skipped", props)
        DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome="skipped").inc()
        capture_exception(e)
        return
    except asyncio.CancelledError:
        # Worker shutdown / deploy interrupted the (possibly long) rewrite. Not a repartition failure —
        # Temporal reschedules the activity — so propagate rather than record it, else every deploy fills
        # error tracking with `warehouse_repartition_failed` noise and burns a repartition attempt.
        logger.info("repartition: cancelled mid-run, will be retried")
        raise
    except Exception as e:
        # Do NOT re-raise: a repartition failure must not block the sync — the table is retried on a
        # later run, on the old layout in the meantime.
        if _is_cancellation(e):
            # Some cancellations surface through async_to_sync as an Exception-derived CancelledError.
            # Treat identically to the branch above: propagate, never record it as a failure.
            logger.info("repartition: cancelled mid-run, will be retried")
            raise
        if not _still_claimant(schema, claim_token):
            # The error is almost certainly collateral from the newer claimant clobbering our S3 state
            # (e.g. it swept our temp mid-write). It owns the retry; recording our wreckage as a
            # failure would burn an attempt and pollute error tracking with self-inflicted noise.
            logger.info("repartition: failed after being superseded, standing down", exc_info=True)
            DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome="superseded").inc()
            _capture_stood_down(schema, inputs, trigger_reason, "superseded_after_error", logger)
            return
        if _is_transient_infra_error(e):
            # Transient infra noise mid-repartition (app-DB pooler drop, S3 rate limit, credential
            # timeout) — not a repartition bug. The rewrite/swap is idempotent via the swap marker, so
            # retrying is always safe. Don't consume an attempt or emit a failure event.
            DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome="transient").inc()
            if trigger_reason == "admin":
                # An operator staged this rewrite precisely because syncing on the old layout is
                # pathological (e.g. a badly over-partitioned table merging one commit per partition
                # for hours). Deferring to the next sync would run that crawl first, so re-raise
                # retryable and let the activity's retry policy re-run the rewrite now; the claim
                # fencing handles any zombie, and if attempts exhaust the workflow still swallows the
                # failure and syncs on the old layout. No capture_exception here and the error type is
                # exempted in EXPECTED_CONTROL_FLOW_ERROR_TYPES: retries are expected control flow,
                # and error-tracking events here would spam (and can trigger automated remediation);
                # the log line and the transient metric carry the visibility.
                logger.warning("repartition: transient infra error, re-raising for activity retry", exc_info=True)
                raise ApplicationError(
                    f"Transient infra error during admin-staged repartition: {e}",
                    type="TransientRepartitionError",
                ) from e
            logger.warning("repartition: transient infra error, will retry on next sync", exc_info=True)
            capture_exception(e)
            _capture_stood_down(schema, inputs, trigger_reason, "transient_infra_error", logger)
            return
        failure_outcome = _handle_failure(inputs, schema, pending, trigger_reason, e, claim_token, logger)
        DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome=failure_outcome).inc()
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


def _capture_stood_down(
    schema: ExternalDataSchema,
    inputs: RepartitionActivityInputs,
    trigger_reason: str,
    reason: str,
    logger: FilteringBoundLogger,
) -> None:
    """Emit the closing event for an attempt that stopped without finishing or failing.

    These paths deliberately record no failure, but without a closing event a rewrite that stood down
    is indistinguishable from one that disappeared mid-flight — both leave `repartition_pending` set
    and a lone `warehouse_repartition_started`. Reported as skipped so failure dashboards stay clean,
    and `terminal=False` because the pending marker survives: a later run retries the rewrite, unlike
    the skips that clear it.
    """
    props = base_event_props(schema, schema.source, inputs.job_id)
    props.update({"trigger_reason": trigger_reason, "reason": reason, "terminal": False})
    try:
        capture_repartition_event("warehouse_repartition_skipped", props)
    except Exception:
        # Every caller is an except-handler whose contract is to swallow, so a telemetry failure must
        # not escape: it would fail an activity that deliberately stood down and trigger a retry.
        logger.warning("repartition: failed to capture stand-down event", exc_info=True)


def _handle_failure(
    inputs: RepartitionActivityInputs,
    schema: ExternalDataSchema,
    pending: dict[str, Any] | None,
    trigger_reason: str,
    error: Exception,
    claim_token: str,
    logger: FilteringBoundLogger,
) -> str:
    """Record a failed attempt; give up (and clear the flag) after MAX_REPARTITION_ATTEMPTS.

    Returns the metric outcome: "failed" normally, or "superseded" when the authoritative post-refresh
    read shows a newer attempt now owns the claim. `_still_claimant` is conservative and reports True on
    a transient DB blip, so a zombie could reach here after a newer claimant already finished; the
    refresh below is the authoritative read (the DB is reachable again), so re-checking the claim here
    stops us recording a spurious failure and re-queueing `repartition_pending` the newer attempt cleared.
    """
    schema.refresh_from_db(fields=["sync_type_config"])
    claim = schema.repartition_claim
    if not (claim and claim.get("token") == claim_token):
        logger.info("repartition: superseded (claim changed under us), standing down without recording failure")
        return "superseded"
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
        # Drop any partial-rewrite checkpoint too: leaving it set would make the next flag cycle
        # resume the same doomed temp instead of giving up, so the give-up would never take effect.
        schema.clear_repartition_rewrite()
        # Engage the cooldown as well, or the give-up never takes effect: the trigger that queued
        # this rewrite (the largest partition is over budget) is just as true on the next sync and
        # the layout is unchanged, so detection re-flags the table immediately with `attempts` back
        # at 0 and the three attempts start over. The cooldown re-evaluates at most daily instead.
        schema.stamp_last_repartition_at()
    else:
        updated = {**pending, "attempts": attempts}
        schema.set_repartition_pending(updated)

    capture_repartition_event("warehouse_repartition_failed", props)
    capture_exception(error)
    return "failed"
