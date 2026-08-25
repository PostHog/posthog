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
import socket
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
from posthog.temporal.common.activity_context import current_activity_attempt
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
    RepartitionAttemptsExhausted,
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
from products.warehouse_sources.backend.temporal.data_imports.workload_report import workload_reporting

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
    # S3 NoSuchKey from an s3fs purge/swap op (`_copy`/`_rm`/`_find`) that raced a concurrent delete —
    # a temp file swept by another attempt, not a bug. A hollow *live* table surfaces the missing file
    # with its path embedded and is routed to a revive inside `repartition_table_in_place` before it
    # ever reaches here, so this bare, pathless variant only ever means a raced object-store operation.
    "the specified key does not exist",
)


# How much of the activity's budget to leave unused when the rewrite gives up, so the failed attempt
# can still be recorded before Temporal kills the activity. Only the bookkeeping needs covering: a
# couple of writes to the schema row and one event.
REWRITE_DEADLINE_MARGIN = dt.timedelta(minutes=5)


def _rewrite_deadline(activity_started: float) -> float | None:
    """Monotonic time by which the rewrite must stop to leave room to record its own failure.

    `activity_started` is the `time.monotonic()` reading taken when the activity began. The deadline
    is anchored to it, not to now: the budget is measured from `start_to_close_timeout`, which Temporal
    counts from the same start, so the pre-rewrite work (job fetch, flag evaluation, the pre-extraction
    Delta-log measurement, temp validation) has to be charged against it too. Anchoring to now instead
    hands the rewrite a deadline later than the activity's own timeout by however long that pre-work
    took, so on the heavily-fragmented tables this path exists to rescue — where reading the log alone
    runs into minutes — Temporal kills the rewrite mid-stream before it can record an outcome, and the
    hard-killed attempt counts toward the give-up cap.

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
    return activity_started + budget


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
    # Anchor the rewrite deadline to when the activity began, so the pre-rewrite work below (job fetch,
    # flag evaluation, pre-extraction Delta-log measurement) is charged against the activity's timeout
    # rather than handed to the rewrite on top of it. See `_rewrite_deadline`.
    activity_started = time.monotonic()
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
    # `max_partition_bytes` here is the last *recorded* value (can be stale); the gate does not trust
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

    # `_handle_failure` also gives up at the cap, but only for an attempt that survives to run it.
    # A rewrite whose worker is OOM-killed never reaches it, so the count has to be read here too.
    # Never while a swap is staged: an interrupted swap may already have deleted live, leaving temp
    # the only intact copy, and `_give_up` clears the marker that points at it. A ready swap has to be
    # completed however many attempts it took to get here.
    if swap is None and _exhausted_attempts(pending):
        _give_up(inputs, schema, pending, trigger_reason, logger)
        return

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

    # Charged before the rewrite and refunded on the stand-down paths below. Charging on failure
    # instead bounds nothing: a worker killed mid-rewrite records no outcome, so the cap never moves.
    # A staged swap runs no rewrite (temp is already complete), so its recovery is not a rewrite
    # attempt and is not charged, the same reason the give-up above exempts it.
    charged_attempts = None if swap is not None else _charge_attempt(schema, pending, logger)

    start = time.monotonic()
    try:
        # HeartbeaterSync heartbeats on a background thread while the (possibly long) rewrite streams,
        # and on worker shutdown, so Temporal reschedules us instead of timing the activity out.
        # The workload reporter makes the rewrite visible to pod co-tenant accounting (see
        # `workload_report.py`): without it a rewrite-heavy pod looks idle to the OOM classifier's
        # culprit rule. The run_id is prefixed because the sync's import activity reports under the
        # bare job id on this same pod, and sharing its key would let a death during that import
        # read this rewrite's report as its own last words.
        with (
            HeartbeaterSync(logger=logger),
            workload_reporting(
                team_id=inputs.team_id,
                schema_id=inputs.schema_id,
                run_id=f"repartition:{inputs.job_id}",
                host=socket.gethostname(),
                initial_phase="repartition",
                attempt=current_activity_attempt(),
            ),
        ):
            result = async_to_sync(repartition_table_in_place)(
                table_ref=table_ref,
                schema=schema,
                target=target,
                logger=logger,
                claim_token=claim_token,
                deadline=_rewrite_deadline(activity_started),
            )
    except RepartitionBudgetExceededError as e:
        # The rewrite didn't fit in one activity's budget. Checkpoint/resume lets a large table
        # converge across runs, so an attempt that advanced the checkpoint is progress, not a failure,
        # and must not burn an attempt (see `_handle_budget_exceeded`); only a stuck one that made no
        # progress counts toward `MAX_REPARTITION_ATTEMPTS` so a doomed rewrite still gives up.
        logger.warning(f"repartition: {e}")
        DELTA_REPARTITION_TOTAL.labels(
            team_id=str(inputs.team_id),
            outcome=_handle_budget_exceeded(
                inputs, schema, pending, trigger_reason, e, claim_token, logger, charged_attempts
            ),
        ).inc()
        return
    except RepartitionSupersededError:
        # A newer attempt claimed the schema and owns the table now. Stop without recording a *failure*
        # (that would burn an attempt and double-report the run the newer claimant is already handling),
        # but still emit the skip: a started event with no terminal event leaves `repartition_pending`
        # set and no way to tell a stood-down attempt from one that vanished.
        logger.info("repartition: superseded by a newer attempt, standing down")
        DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome="superseded").inc()
        _refund_attempt(schema, charged_attempts, logger)
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
        _refund_attempt(schema, charged_attempts, logger)
        raise
    except Exception as e:
        # Do NOT re-raise: a repartition failure must not block the sync — the table is retried on a
        # later run, on the old layout in the meantime.
        if _is_cancellation(e):
            # Some cancellations surface through async_to_sync as an Exception-derived CancelledError.
            # Treat identically to the branch above: propagate, never record it as a failure.
            logger.info("repartition: cancelled mid-run, will be retried")
            _refund_attempt(schema, charged_attempts, logger)
            raise
        if not _still_claimant(schema, claim_token):
            # The error is almost certainly collateral from the newer claimant clobbering our S3 state
            # (e.g. it swept our temp mid-write). It owns the retry; recording our wreckage as a
            # failure would burn an attempt and pollute error tracking with self-inflicted noise.
            logger.info("repartition: failed after being superseded, standing down", exc_info=True)
            DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome="superseded").inc()
            _refund_attempt(schema, charged_attempts, logger)
            _capture_stood_down(schema, inputs, trigger_reason, "superseded_after_error", logger)
            return
        if _is_transient_infra_error(e):
            # Transient infra noise mid-repartition (app-DB pooler drop, S3 rate limit, credential
            # timeout) — not a repartition bug. The rewrite/swap is idempotent via the swap marker, so
            # retrying is always safe. Don't consume an attempt, emit a failure event, or report to
            # error tracking — a condition nobody can act on (e.g. a pgbouncer login-retry cooldown)
            # shouldn't trip an issue there; the log line, the transient metric, and the skipped
            # event's reason="transient_infra_error" already carry the visibility.
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
                _refund_attempt(schema, charged_attempts, logger)
                raise ApplicationError(
                    f"Transient infra error during admin-staged repartition: {e}",
                    type="TransientRepartitionError",
                ) from e
            logger.warning("repartition: transient infra error, will retry on next sync", exc_info=True)
            _refund_attempt(schema, charged_attempts, logger)
            _capture_stood_down(schema, inputs, trigger_reason, "transient_infra_error", logger)
            return
        failure_outcome = _handle_failure(
            inputs, schema, pending, trigger_reason, e, claim_token, logger, charged_attempts
        )
        DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome=failure_outcome).inc()
        return

    duration = time.monotonic() - start
    DELTA_REPARTITION_DURATION_SECONDS.labels(team_id=str(inputs.team_id), schema_id=inputs.schema_id).observe(duration)
    DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome=result.get("outcome", "completed")).inc()

    if result.get("outcome") != "completed":
        # A non-completed result is a skip that ran no rewrite (live unreadable or no delta table on
        # disk), and those paths leave `repartition_pending` set so a later run retries once the table
        # is revived. The attempt was charged up front, so without this refund three such skips would
        # spend the whole cap without a rewrite ever running, and the next run would `_give_up`,
        # discarding the queued rewrite and stamping the cooldown that blocks re-detection. A skip is
        # not a failed attempt, so it must not count. (A completed rewrite clears the marker itself.)
        _refund_attempt(schema, charged_attempts, logger)

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


def _handle_budget_exceeded(
    inputs: RepartitionActivityInputs,
    schema: ExternalDataSchema,
    pending: dict[str, Any] | None,
    trigger_reason: str,
    error: RepartitionBudgetExceededError,
    claim_token: str,
    logger: FilteringBoundLogger,
    charged_attempts: int | None = None,
) -> str:
    """Record a rewrite that ran out of one activity's budget, distinguishing progress from a stall.

    Checkpoint/resume lets a table too large to rewrite in one activity converge across runs (see
    `RepartitionBudgetExceededError`), so an attempt that appended new rows is forward progress, not a
    failure: counting it against the finite `MAX_REPARTITION_ATTEMPTS` would abandon a table that simply
    needs more than three budgets mid-convergence and leave it un-repartitioned. Only an attempt that
    appended nothing this run is stuck; that one falls through to `_handle_failure` so a rewrite which
    genuinely can't advance in one budget still gives up.

    Progress means this attempt left the rewrite further along than it found it. Neither row count
    alone can say that. A cumulative temp size against a stored high-water mark is not monotonic,
    because the rewrite restarts from row 0 whenever its checkpoint is discarded (the source's Delta
    version moved between runs), so a fresh rebuild reading back below an earlier attempt's mark was
    charged a spurious failure. But the rows written this attempt cannot say it either: a rewrite that
    restarts every run writes hundreds of millions of rows each time, clears any `> 0` test, and ends
    exactly where it began. Three schemas sat in that loop for six weeks, each burning a full budget per
    run and finishing nothing, because the cap could never count to three.

    Two shapes count as progress. A resumed attempt that appended rows extended what it inherited. And
    a genuine first attempt — one with no prior checkpoint to inherit — that persisted a checkpoint the
    next run resumes from broke new ground, even though `resumed_from` is 0. `had_prior_checkpoint`
    keeps that first attempt apart from a restart that inherited nothing because it discarded an
    existing checkpoint: the restart re-covered ground the last attempt already covered, however much it
    wrote, so only it (and an attempt that saved no checkpoint at all) falls through to `_handle_failure`.

    Returns the metric outcome: "superseded" when a newer attempt owns the claim, "progressing" when
    the rewrite broke new ground, otherwise whatever `_handle_failure` returns.
    """
    schema.refresh_from_db(fields=["sync_type_config"])
    claim = schema.repartition_claim
    if not (claim and claim.get("token") == claim_token):
        logger.info("repartition: superseded (claim changed under us), standing down without recording failure")
        _refund_attempt(schema, charged_attempts, logger)
        return "superseded"

    pending = schema.repartition_pending or pending or {}
    resumed_and_advanced = error.resumed_from > 0 and error.rows_written > 0
    # A first attempt inherits nothing, so `resumed_from` is 0, but saving a fresh checkpoint the next
    # run resumes from is still forward progress. Only a restart that discarded an existing checkpoint
    # (`had_prior_checkpoint`) re-covered ground already covered — that one is the treadmill to stop.
    fresh_and_checkpointed = not error.had_prior_checkpoint and error.checkpoint_saved
    if resumed_and_advanced or fresh_and_checkpointed:
        # Forward progress this attempt: keep the checkpoint and reset the failure counter — a rewrite
        # still advancing is not the doomed one the cap exists to stop. The next run resumes from the
        # checkpoint rather than giving up.
        schema.set_repartition_pending({**pending, "attempts": 0})
        logger.info(
            f"repartition: over budget but rewrite advanced {error.rows_written} rows past the "
            f"{error.resumed_from} it inherited, resuming next run",
            rows_written=error.rows_written,
            resumed_from=error.resumed_from,
        )
        _capture_stood_down(schema, inputs, trigger_reason, "rewrite_progressing", logger)
        return "progressing"

    # Either this attempt inherited nothing (so it re-streamed ground already covered) or it inherited
    # a checkpoint and appended nothing. Both mean the rewrite can't converge on the budget it has, so
    # count a real failed attempt and let `MAX_REPARTITION_ATTEMPTS` eventually give up on it.
    logger.info(
        f"repartition: over budget without converging (resumed_from={error.resumed_from} "
        f"rows_written={error.rows_written})",
        rows_written=error.rows_written,
        resumed_from=error.resumed_from,
    )
    return _handle_failure(inputs, schema, pending, trigger_reason, error, claim_token, logger, charged_attempts)


def _exhausted_attempts(pending: dict[str, Any] | None) -> bool:
    return pending is not None and int(pending.get("attempts", 0)) >= MAX_REPARTITION_ATTEMPTS


def _give_up(
    inputs: RepartitionActivityInputs,
    schema: ExternalDataSchema,
    pending: dict[str, Any] | None,
    trigger_reason: str,
    logger: FilteringBoundLogger,
) -> None:
    """Abandon a rewrite whose attempts are spent, clearing the markers that would re-arm it.

    Stamps the cooldown as well, or detection re-flags the table on the next sync and the attempts
    start over — same reason `_handle_failure` does.
    """
    logger.warning(
        f"repartition: giving up after {MAX_REPARTITION_ATTEMPTS} attempts that did not survive to "
        f"record an outcome schema_id={inputs.schema_id}",
        schema_id=inputs.schema_id,
    )
    # Stake a fresh claim before clearing anything. This runs before the activity mints its own, so a
    # timed-out predecessor may still be running and still hold the old token; leaving it valid would
    # let it pass `ensure_claim` and go on mutating live after we declared the rewrite abandoned.
    schema.set_repartition_claim(
        {"token": str(uuid.uuid4()), "job_id": inputs.job_id, "claimed_at": timezone.now().isoformat()}
    )
    schema.clear_repartition_pending()
    schema.clear_repartition_swap()
    schema.clear_repartition_rewrite()
    schema.stamp_last_repartition_at()
    error = RepartitionAttemptsExhausted(
        f"repartition gave up after {MAX_REPARTITION_ATTEMPTS} attempts that did not survive to record "
        f"an outcome (trigger_reason={trigger_reason})"
    )
    props = base_event_props(schema, schema.source, inputs.job_id)
    props.update(
        {
            "trigger_reason": trigger_reason,
            "attempts": int((pending or {}).get("attempts", 0)),
            "final": True,
            "error_type": type(error).__name__,
            "error_message": str(error),
        }
    )
    capture_repartition_event("warehouse_repartition_failed", props)
    # Terminal, and the only terminal path that did not already report to error tracking: every attempt
    # was hard-killed before it could run `_handle_failure` (which captures). Capture here too so a table
    # the controller has abandoned surfaces as an issue instead of only a metric — the sync context is
    # already bound (bind_job_context) so the issue is attributed to the connector and table.
    capture_exception(error)
    DELTA_REPARTITION_TOTAL.labels(team_id=str(inputs.team_id), outcome="failed").inc()


def _charge_attempt(
    schema: ExternalDataSchema, pending: dict[str, Any] | None, logger: FilteringBoundLogger
) -> int | None:
    """Record this attempt against the retry cap before the rewrite runs; return the prior count.

    `_refund_attempt` restores that count. None means nothing was charged (no pending marker, or a DB
    failure) — bookkeeping must never block the rewrite.
    """
    if pending is None:
        return None
    prior = int(pending.get("attempts", 0))
    try:
        schema.set_repartition_pending({**pending, "attempts": prior + 1})
    except Exception:
        logger.warning("repartition: could not charge attempt, proceeding uncharged", exc_info=True)
        return None
    return prior


def _refund_attempt(schema: ExternalDataSchema, prior: int | None, logger: FilteringBoundLogger) -> None:
    """Undo `_charge_attempt` for a stand-down that must not count against the retry cap.

    Supersession, transient infra and a checkpoint that advanced are noise or progress, not evidence
    the rewrite is doomed. Refunds only when the persisted count is still the one this attempt wrote:
    overlapping attempts otherwise let each refund erase the other's charge, and a cap that never
    counts up is the loop this whole change exists to stop.
    """
    if prior is None:
        return
    try:
        schema.refresh_from_db(fields=["sync_type_config"])
        pending = schema.repartition_pending
        if pending is not None and int(pending.get("attempts", 0)) == prior + 1:
            schema.set_repartition_pending({**pending, "attempts": prior})
    except Exception:
        logger.warning("repartition: could not refund attempt", exc_info=True)


def _handle_failure(
    inputs: RepartitionActivityInputs,
    schema: ExternalDataSchema,
    pending: dict[str, Any] | None,
    trigger_reason: str,
    error: Exception,
    claim_token: str,
    logger: FilteringBoundLogger,
    charged_attempts: int | None = None,
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
        _refund_attempt(schema, charged_attempts, logger)
        return "superseded"
    pending = schema.repartition_pending or pending or {}
    # Use the charge this attempt made rather than re-reading it: the persisted value is only visible
    # after a round trip, and the count must not depend on that landing. Falls back to incrementing
    # what was read when nothing was charged.
    attempts = (charged_attempts + 1) if charged_attempts is not None else int(pending.get("attempts", 0)) + 1

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
