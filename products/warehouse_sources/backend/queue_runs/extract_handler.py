"""The `sync.extract` handler: one extraction run of one schema, on the queue.

The handler does what `ExternalDataJobWorkflow` does for a V3 run up to the loader handoff. It
creates the job row, runs the extraction body, and hands the run to the loader. The pipeline
sends a final marker for a run without batches, so the loader finalizes every run that reaches
the pipeline. When the queue engine fails the queue job without the handler, `on_engine_failed`
fails the run's job row.

Job row identity: `workflow_run_id` on the job row is the queue job id, so every attempt of one
queue job finds the same job row. `workflow_id` comes from the payload.

Sync lock: each attempt takes the V3 sync lock with its own token, "<queue job id>:<attempt>", so
Temporal runs and queue runs of one schema exclude each other, and so do two attempts of one queue
job. A later attempt takes the lock over from an earlier attempt only when the earlier attempt's
group lease is no longer live. An attempt that finds a later attempt of its job in the lock stops.
The loader releases the lock with the job row's `workflow_run_id`, the queue job id, which also
releases an attempt token of that job. The run keeps the lock across its own retries, and
releases it itself whenever it ends without handing batches to the loader.
"""

from __future__ import annotations

import time
import socket
import asyncio
import datetime as dt
import contextlib
import dataclasses
from collections.abc import Callable, Iterator
from enum import StrEnum
from typing import Any, cast

from django.db import InterfaceError, InternalError, OperationalError, close_old_connections, transaction

import psycopg
import structlog
from structlog.types import FilteringBoundLogger

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.exceptions_capture import capture_exception
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.queue_runs.budgets import (
    RETRY_WINDOW_MARGIN,
    RunShape,
    claim_deadline,
    run_budget,
)
from products.warehouse_sources.backend.queue_runs.metrics import (
    ROWS_EXTRACTED_TOTAL,
    RUN_DURATION_SECONDS,
    RUNS_FINISHED_TOTAL,
    RUNS_SKIPPED_TOTAL,
    RunOutcome,
    SkipReason,
)
from products.warehouse_sources.backend.queue_runs.payloads import (
    EXTERNAL_DATA_JOB_WORKFLOW_TYPE,
    EXTRACT_LANE,
    SYNC_EXTRACT_KIND,
    SyncExtractPayload,
    SyncTrigger,
)
from products.warehouse_sources.backend.queue_runs.post_extraction import (
    TemporalClientFactory,
    TemporalStarter,
    start_post_extraction_work,
    start_post_import,
)
from products.warehouse_sources.backend.queue_runs.stop_watch import RunStopWatch, StopReason
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
    CANCELLED_RUN_MESSAGE,
    SYNC_RUN_STALLED_MESSAGE,
    SYNC_RUN_TOO_LONG_MESSAGE,
    FailureKind,
    UpdateExternalDataJobStatusInputs,
    _update_job_status,
    classify_failure,
)
from products.warehouse_sources.backend.temporal.data_imports.metrics import TERMINAL_JOB_STATUSES
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller import (
    repartition_import_hold_reason,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.typings import PipelineResult
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    QUEUE_RUNNER,
    LockAcquireResult,
    get_v3_pipeline_lock_holder,
    get_v3_pipeline_lock_meta,
    lock_token_run_id,
    queue_attempt_token,
    release_v3_pipeline_lock,
    try_acquire_v3_pipeline_lock,
    write_v3_pipeline_lock_meta,
)
from products.warehouse_sources.backend.temporal.data_imports.run_control import (
    EventShutdownMonitor,
    RunControl,
    no_heartbeat,
)
from products.warehouse_sources.backend.temporal.data_imports.util import PostHogInternalDatabaseError
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.acquire_v3_lock import (
    failing_schema_deferral,
    take_over_v3_lock_if_holder_finished,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    CreateExternalDataJobModelActivityOutputs,
    V3PipelineLockLostError,
    prepare_run,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
    run_extraction,
)
from products.warehouse_sources.backend.temporal.data_imports.workload_report import aworkload_reporting
from products.warehouse_sources_queue.backend.sdk import Fail, Job, JobContext, JobsTable, Outcome, Retry, Success

LOGGER = get_logger(__name__)

# The tag on a retry that a shutdown caused. Those retries do not count against the run's cap.
SHUTDOWN_RETRY_TAG = "shutdown"
# The tag on a retry because the sync lock store did not answer. It says nothing about the source.
LOCK_UNAVAILABLE_RETRY_TAG = "lock_unavailable"
# The tag on a retry because an earlier attempt of the same run may still run. The source gave no answer.
EARLIER_ATTEMPT_RETRY_TAG = "earlier_attempt_live"
UNCOUNTED_RETRY_TAGS = frozenset({SHUTDOWN_RETRY_TAG, LOCK_UNAVAILABLE_RETRY_TAG, EARLIER_ATTEMPT_RETRY_TAG})
# The key in `ExternalDataJob.schema_snapshot` that keeps the pre-extraction answers, so a later
# attempt of the same queue job reads them instead of creating another job row.
RUN_PLAN_SNAPSHOT_KEY = "queue_run_plan"
EXTRACTION_RESULT_SNAPSHOT_KEY = "queue_extraction_result"
POST_EXTRACTION_DONE_SNAPSHOT_KEY = "queue_post_extraction_done"
POST_IMPORT_DONE_SNAPSHOT_KEY = "queue_post_import_done"
RESULT_WRITE_ATTEMPTS = 3


@frozen
class ExtractHandlerConfig:
    cancel_probe_interval_seconds: float = 30.0
    # Time a cancelled run gets to stop by itself before the handler cancels its task.
    cancel_grace_seconds: float = 30.0
    # Time a run gets after a shutdown to stop by itself. Keep it below the consumer's drain
    # timeout, so the handler still returns its shutdown retry before the engine cancels it.
    shutdown_grace_seconds: float = 540.0


@frozen
class _HandlerResult:
    outcome: Outcome
    run_outcome: RunOutcome
    source_type: str | None = None


class _LockOutcome(StrEnum):
    ACQUIRED = "acquired"
    # Another run holds the lock and keeps it.
    HELD = "held"
    # Redis could not answer, so nobody can tell whether another run holds the lock.
    UNAVAILABLE = "unavailable"
    # An earlier attempt of this queue job holds the lock, and its consumer may still run it.
    EARLIER_ATTEMPT_LIVE = "earlier_attempt_live"


class _RunEligibilityChanged(Exception):
    def __init__(self, eligibility: str) -> None:
        self.eligibility = eligibility
        super().__init__(eligibility)


@frozen
class _Attempt:
    """The facts about one attempt that its failure paths need."""

    job: Job
    ctx: JobContext
    payload: SyncExtractPayload
    number: int
    lock_token: str
    plan: CreateExternalDataJobModelActivityOutputs
    # Counted retries before this attempt, and the most this run may count.
    counted_retries: int
    max_counted_attempts: int
    on_resumable_retry_budget: bool
    deadline: dt.datetime


class SyncExtractHandler:
    def __init__(
        self,
        *,
        config: ExtractHandlerConfig | None = None,
        temporal_client_factory: TemporalClientFactory = async_connect,
        clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
    ) -> None:
        self._config = config or ExtractHandlerConfig()
        self._starter = TemporalStarter(temporal_client_factory)
        self._clock = clock

    async def handle(self, job: Job, ctx: JobContext) -> Outcome:
        payload = SyncExtractPayload.from_json(job.payload)
        attempt = job.latest_attempt + 1
        started = time.monotonic()
        with _job_log_context(payload, job, attempt):
            tag_queries(team_id=payload.team_id, product=Product.WAREHOUSE, feature=Feature.IMPORT_PIPELINE)
            result = await self._handle(job, ctx, payload, attempt, LOGGER.bind())
        RUNS_FINISHED_TOTAL.labels(source_type=result.source_type or "unknown", outcome=result.run_outcome).inc()
        RUN_DURATION_SECONDS.labels(outcome=result.run_outcome).observe(time.monotonic() - started)
        return result.outcome

    async def on_engine_failed(self, job: Job, reason: str) -> None:
        """Fail the run's job row when the engine failed the queue job without this handler.

        Otherwise the row stays Running with no run behind it. The finalizer's terminal states
        absorb later writes, so a race with a real terminal write is safe.
        """
        payload = SyncExtractPayload.from_json(job.payload)
        with _job_log_context(payload, job, job.latest_attempt):
            logger = LOGGER.bind()
            existing = await database_sync_to_async_pool(_find_run_job)(payload.team_id, job.id)
            if existing is None:
                # An attempt may have taken the lock and died before it created the row.
                await _release_sync_lock(payload, job.id)
                return
            if existing.status in TERMINAL_JOB_STATUSES:
                return
            structlog.contextvars.bind_contextvars(external_data_job_id=str(existing.id))
            await logger.awarning("The queue engine failed the run's job, so the run fails", reason=reason)
            await self._finalize(
                payload,
                job.id,
                job_id=str(existing.id),
                status=ExternalDataJob.Status.FAILED,
                internal_error=f"The queue engine failed the job: {reason}"[:1000],
                latest_error=SYNC_RUN_STALLED_MESSAGE,
                logger=logger,
                platform_fault=True,
            )
            # After an extraction the loader may still write this run's batches, and it releases
            # the lock when it finishes them.
            if _load_extraction_result(existing) is None:
                await _release_sync_lock(payload, job.id)
            plan = _load_run_plan(existing)
            RUNS_FINISHED_TOTAL.labels(
                source_type=plan.source_type if plan is not None else "unknown", outcome=RunOutcome.FAILED
            ).inc()

    async def _handle(
        self, job: Job, ctx: JobContext, payload: SyncExtractPayload, attempt: int, logger: FilteringBoundLogger
    ) -> _HandlerResult:
        if job.team_id != payload.team_id or job.group_key != payload.group_key:
            await logger.aerror("Rejecting queue run: its queue identity does not match its payload")
            return _HandlerResult(
                outcome=Fail(reason="queue identity does not match payload"), run_outcome=RunOutcome.FAILED
            )

        eligibility = await database_sync_to_async_pool(_validate_payload_and_eligibility)(payload)
        if eligibility == "invalid":
            await logger.aerror("Rejecting queue run: schema, source, and team do not match")
            return _HandlerResult(
                outcome=Fail(reason="schema, source, and team do not match"), run_outcome=RunOutcome.FAILED
            )
        if eligibility == "disabled":
            await logger.ainfo("Skipping queue run: schema or source is disabled")
            return _skipped(SkipReason.DISABLED)

        existing = await database_sync_to_async_pool(_find_run_job)(payload.team_id, job.id)

        # Only before the run starts: a later attempt continues a run that already went ahead.
        if existing is None and await database_sync_to_async_pool(failing_schema_deferral)(
            payload.team_id, payload.schema_id, reset_requested=payload.reset_pipeline is True, logger=logger
        ):
            await logger.ainfo("Skipping queue run: this sync keeps failing, so the run is deferred")
            return _skipped(SkipReason.DEFERRED)

        token = queue_attempt_token(job.id, attempt)
        lock = await database_sync_to_async_pool(_acquire_sync_lock)(payload, job, token, ctx, logger)
        if lock == _LockOutcome.UNAVAILABLE:
            # Without the lock store nobody can tell whether another run writes this table.
            await logger.awarning("Queue run waits: the sync lock store is unavailable")
            return _HandlerResult(
                outcome=Retry(reason="sync lock unavailable", tag=LOCK_UNAVAILABLE_RETRY_TAG),
                run_outcome=RunOutcome.RETRY,
            )
        if lock == _LockOutcome.EARLIER_ATTEMPT_LIVE:
            # The job row belongs to that attempt too, so this attempt leaves it alone.
            await logger.awarning("Queue run waits: an earlier attempt of this run may still run")
            return _HandlerResult(
                outcome=Retry(reason="an earlier attempt holds the sync lock", tag=EARLIER_ATTEMPT_RETRY_TAG),
                run_outcome=RunOutcome.RETRY,
            )
        if lock == _LockOutcome.HELD:
            await logger.ainfo("Skipping queue run: another run of this schema holds its sync lock")
            if existing is not None and existing.status == ExternalDataJob.Status.RUNNING:
                # This run's own job row is left from an earlier attempt, and the other run replaces it.
                await self._finalize(
                    payload,
                    job.id,
                    job_id=str(existing.id),
                    status=ExternalDataJob.Status.FAILED,
                    latest_error=CANCELLED_RUN_MESSAGE,
                    logger=logger,
                )
            return _skipped(SkipReason.OVERLAP)

        result = await self._run_with_lock(job, ctx, payload, attempt, token, existing, logger)
        # The loader releases the lock when it finishes a run it was handed. A run whose row was
        # already terminal before this attempt has no loader left to do that.
        loader_releases = result.run_outcome == RunOutcome.HANDED_TO_LOADER and not (
            existing is not None and existing.status in TERMINAL_JOB_STATUSES
        )
        if not isinstance(result.outcome, Retry) and not loader_releases:
            await _release_sync_lock(payload, token)
        return result

    async def _run_with_lock(
        self,
        job: Job,
        ctx: JobContext,
        payload: SyncExtractPayload,
        attempt: int,
        token: str,
        existing: ExternalDataJob | None,
        logger: FilteringBoundLogger,
    ) -> _HandlerResult:
        if existing is not None and existing.status in TERMINAL_JOB_STATUSES:
            plan = _load_run_plan(existing)
            result = _load_extraction_result(existing)
            # Only a completed run has follow-up work left. A failed or cancelled run stopped on
            # purpose, and its staged output must not feed the CDP or person-property workflows.
            if existing.status == ExternalDataJob.Status.COMPLETED and plan is not None and result is not None:
                structlog.contextvars.bind_contextvars(external_data_job_id=plan.job_id)
                await logger.ainfo("Resuming post-extraction work for a terminal run", status=existing.status)
                return await self._finish_extraction(job, payload, plan, result, logger)
            await logger.ainfo("Skipping queue run: its job is already terminal", status=existing.status)
            return _skipped(SkipReason.ALREADY_TERMINAL)

        if existing is None:
            if await database_sync_to_async_pool(_held_for_repartition)(payload, logger):
                # Queue runs never run the repartition step, which is what ends the hold.
                await logger.ainfo("Skipping queue run: a repartition holds this schema's import")
                return _skipped(SkipReason.REPARTITION_HOLD)
            prepared = await self._prepare(job, payload, token, logger)
            if isinstance(prepared, _HandlerResult):
                return prepared
            plan = prepared
            if plan.hit_billing_limit:
                await self._finalize(
                    payload,
                    job.id,
                    job_id=plan.job_id,
                    status=ExternalDataJob.Status.BILLING_LIMIT_REACHED,
                    logger=logger,
                )
                return _HandlerResult(
                    outcome=Success(), run_outcome=RunOutcome.BILLING_LIMIT_REACHED, source_type=plan.source_type
                )
        else:
            loaded = _load_run_plan(existing)
            if loaded is None:
                # Only a crash between the job insert and the plan stamp leaves a row without a plan.
                await logger.awarning("Queue run plan is missing from the job row", job_id=str(existing.id))
                await self._finalize(
                    payload,
                    job.id,
                    job_id=str(existing.id),
                    status=ExternalDataJob.Status.FAILED,
                    latest_error=SYNC_RUN_STALLED_MESSAGE,
                    logger=logger,
                    platform_fault=True,
                )
                return _HandlerResult(outcome=Fail(reason="queue run plan missing"), run_outcome=RunOutcome.FAILED)
            plan = loaded
            result = _load_extraction_result(existing)
            if result is not None:
                structlog.contextvars.bind_contextvars(external_data_job_id=plan.job_id)
                await logger.ainfo("Resuming post-extraction work from the persisted extraction result")
                return await self._finish_extraction(job, payload, plan, result, logger)

        structlog.contextvars.bind_contextvars(external_data_job_id=plan.job_id)
        budget = run_budget(
            source_type=plan.source_type,
            incremental_or_append=plan.incremental_or_append,
            schema_name=plan.schema_name,
            failed_runs_in_a_row=plan.failed_runs_in_a_row,
        )
        history = await ctx.retry_history(job, uncounted_tags=UNCOUNTED_RETRY_TAGS)
        run = _Attempt(
            job=job,
            ctx=ctx,
            payload=payload,
            number=attempt,
            lock_token=token,
            plan=plan,
            counted_retries=history.counted_retries,
            max_counted_attempts=budget.max_attempts,
            on_resumable_retry_budget=budget.shape == RunShape.RESUMABLE,
            deadline=claim_deadline(job.created_at),
        )

        if history.counted_retries >= budget.max_attempts:
            # Only an attempt that died without an answer (an OOM, a lost pod) gets here: the
            # handler fails a run itself when an attempt it saw end reaches the cap.
            await self._finalize(
                payload,
                job.id,
                job_id=plan.job_id,
                status=ExternalDataJob.Status.FAILED,
                internal_error=history.last_error or "The run used all of its attempts",
                latest_error=SYNC_RUN_STALLED_MESSAGE,
                logger=logger,
            )
            return _HandlerResult(
                outcome=Fail(reason="attempts exhausted"), run_outcome=RunOutcome.FAILED, source_type=plan.source_type
            )

        timeout = min(budget.timeout, run.deadline - self._clock())
        if timeout <= dt.timedelta(0):
            return await self._fail_too_long(run, logger)

        return await self._extract_and_hand_off(run, timeout, logger)

    async def _prepare(
        self, job: Job, payload: SyncExtractPayload, token: str, logger: FilteringBoundLogger
    ) -> CreateExternalDataJobModelActivityOutputs | _HandlerResult:
        inputs = CreateExternalDataJobModelActivityInputs(
            team_id=payload.team_id,
            schema_id=payload.schema_id,
            source_id=payload.source_id,
            billable=payload.billable,
            # The loader handoff exists only for V3, so every queue run is a V3 run.
            is_v3=True,
            started_by_schedule=payload.trigger == SyncTrigger.SCHEDULE,
        )
        try:
            plan = await database_sync_to_async_pool(_prepare_run_and_stamp)(inputs, payload, job.id, token)
        except V3PipelineLockLostError:
            # The same check as the Temporal path: another run took the lock before the job row existed.
            await logger.awarning("Skipping queue run: another run took the sync lock before preparation")
            return _skipped(SkipReason.LOCK_LOST)
        except _RunEligibilityChanged as e:
            if e.eligibility == "disabled":
                await logger.ainfo("Skipping queue run: schema or source was disabled before preparation")
                return _skipped(SkipReason.DISABLED)
            await logger.aerror("Rejecting queue run: schema, source, and team changed before preparation")
            return _HandlerResult(
                outcome=Fail(reason="schema, source, and team do not match"), run_outcome=RunOutcome.FAILED
            )
        except (OperationalError, InterfaceError, InternalError, PostHogInternalDatabaseError) as e:
            # The transaction rolled back both the row and its plan, so a transient database
            # failure is safe to retry from scratch.
            await logger.awarning("Queue run preparation failed transiently, will retry", error=str(e))
            return _HandlerResult(outcome=Retry(reason=str(e)[:1000]), run_outcome=RunOutcome.RETRY)
        except Exception as e:
            # The workflow gives job creation one attempt, so a non-transient failure ends the run.
            failure = classify_failure(e, is_v3=True)
            await self._finalize(
                payload,
                job.id,
                job_id=None,
                status=failure.status or ExternalDataJob.Status.FAILED,
                internal_error=failure.internal_error,
                latest_error=failure.latest_error,
                logger=logger,
            )
            return _HandlerResult(
                outcome=Fail(reason=f"job creation failed: {e}"[:1000]), run_outcome=RunOutcome.FAILED
            )
        return plan

    async def _extract_and_hand_off(
        self, run: _Attempt, timeout: dt.timedelta, logger: FilteringBoundLogger
    ) -> _HandlerResult:
        payload, plan = run.payload, run.plan
        stop_watch = RunStopWatch(
            shutdown_event=run.ctx.shutdown_event,
            is_run_cancelled=lambda: database_sync_to_async_pool(_run_is_cancelled)(payload.team_id, plan.job_id),
            is_lock_lost=lambda: asyncio.to_thread(_lock_taken_by_another_attempt, payload, run.lock_token),
            probe_interval_seconds=self._config.cancel_probe_interval_seconds,
            shutdown_grace_seconds=self._config.shutdown_grace_seconds,
            cancel_grace_seconds=self._config.cancel_grace_seconds,
        )
        control = RunControl(
            # The engine renews the queue lease on its own cadence, which is the liveness signal.
            heartbeat=no_heartbeat,
            shutdown_monitor=EventShutdownMonitor(
                stop_watch.stop_event,
                activity_id=run.job.id,
                activity_type=SYNC_EXTRACT_KIND,
                task_queue=EXTRACT_LANE,
                attempt=run.number,
                workflow_id=payload.workflow_id,
                workflow_type=EXTERNAL_DATA_JOB_WORKFLOW_TYPE,
            ),
            attempt=run.number,
            workflow_id=payload.workflow_id,
            workflow_run_id=run.job.id,
            on_rows_extracted=ROWS_EXTRACTED_TOTAL.labels(source_type=plan.source_type).inc,
            always_final_marker=True,
        )
        inputs = ImportDataActivityInputs(
            team_id=payload.team_id,
            run_id=plan.job_id,
            schema_id=payload.schema_id,
            source_id=payload.source_id,
            reset_pipeline=payload.reset_pipeline,
            fast_return_eligible=plan.fast_return_eligible,
            scheduled_full_refresh=plan.scheduled_full_refresh,
            on_resumable_retry_budget=run.on_resumable_retry_budget,
        )

        work = asyncio.create_task(_extract(inputs, logger, control))
        watcher = asyncio.create_task(stop_watch.watch(work))
        deadline_ctx = asyncio.timeout(timeout.total_seconds())
        try:
            async with deadline_ctx:
                result = await work
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if not stop_watch.cancelled_work or (current is not None and current.cancelling()):
                raise
            return await self._on_stopped(run, stop_watch.reason, logger)
        except TimeoutError as e:
            if deadline_ctx.expired():
                return await self._fail_too_long(run, logger)
            return await self._on_failure(run, e, logger)
        except Exception as e:
            if stop_watch.reason is not None:
                return await self._on_stopped(run, stop_watch.reason, logger)
            return await self._on_failure(run, e, logger)
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)

        # A full refresh may finish naturally during the cancellation grace period. The terminal
        # cancellation still wins; never hand its output to the loader or start follow-up work.
        if stop_watch.reason == StopReason.CANCELLED:
            return await self._on_stopped(run, stop_watch.reason, logger)
        # A later attempt that took the run over writes the result and hands the run to the loader.
        if stop_watch.reason == StopReason.LOCK_LOST or await asyncio.to_thread(
            _lock_taken_by_another_attempt, payload, run.lock_token
        ):
            return await self._on_stopped(run, StopReason.LOCK_LOST, logger)

        # Persist the extraction result before any follow-up side effect. A retry can then resume
        # idempotent post-extraction starts even if the loader has already made the run terminal.
        await _persist_extraction_result(payload.team_id, plan.job_id, result, logger)
        return await self._finish_extraction(run.job, payload, plan, result, logger)

    async def _finish_extraction(
        self,
        job: Job,
        payload: SyncExtractPayload,
        plan: CreateExternalDataJobModelActivityOutputs,
        result: PipelineResult,
        logger: FilteringBoundLogger,
    ) -> _HandlerResult:
        if result.get("consumer_manages_job_status", False):
            await database_sync_to_async_pool(_set_phase)(payload.team_id, plan.job_id, ExternalDataJob.Phase.LOADING)

        if not await database_sync_to_async_pool(_snapshot_flag)(
            payload.team_id, plan.job_id, POST_EXTRACTION_DONE_SNAPSHOT_KEY
        ):
            await start_post_extraction_work(self._starter, payload=payload, plan=plan, result=result, logger=logger)
            await database_sync_to_async_pool(_update_run_snapshot)(
                payload.team_id, plan.job_id, POST_EXTRACTION_DONE_SNAPSHOT_KEY, True
            )

        if result.get("consumer_manages_job_status", False):
            await logger.ainfo("Queue run handed to the loader")
            return _HandlerResult(
                outcome=Success(), run_outcome=RunOutcome.HANDED_TO_LOADER, source_type=plan.source_type
            )

        # Only a run that returned before the pipeline gets here (a fast return or repartition
        # hold) reaches this path. No marker exists for it, so the handler finalizes it.
        await self._finalize(
            payload, job.id, job_id=plan.job_id, status=ExternalDataJob.Status.COMPLETED, logger=logger
        )
        if not result.get("skip_post_import_activities", False) and not await database_sync_to_async_pool(
            _snapshot_flag
        )(payload.team_id, plan.job_id, POST_IMPORT_DONE_SNAPSHOT_KEY):
            await start_post_import(self._starter, payload=payload, job_id=plan.job_id, logger=logger)
            await database_sync_to_async_pool(_update_run_snapshot)(
                payload.team_id, plan.job_id, POST_IMPORT_DONE_SNAPSHOT_KEY, True
            )
        return _HandlerResult(outcome=Success(), run_outcome=RunOutcome.COMPLETED, source_type=plan.source_type)

    async def _on_stopped(
        self, run: _Attempt, reason: StopReason | None, logger: FilteringBoundLogger
    ) -> _HandlerResult:
        if reason == StopReason.CANCELLED:
            # The cancel wrote the terminal status first, and a terminal status absorbs later writes.
            await logger.ainfo("Queue run stopped: the run was cancelled")
            return _HandlerResult(
                outcome=Fail(reason="run cancelled"), run_outcome=RunOutcome.CANCELLED, source_type=run.plan.source_type
            )
        if reason == StopReason.LOCK_LOST:
            # The later attempt owns the job row and the lock now, so this attempt writes neither.
            await logger.awarning("Queue run stopped: a later attempt of this run took its sync lock")
            return _skipped(SkipReason.LOCK_LOST)
        return await self._on_shutdown(run, logger)

    async def _on_shutdown(self, run: _Attempt, logger: FilteringBoundLogger) -> _HandlerResult:
        if self._retry_is_possible(run):
            # The job stays Running: the next attempt continues it under the same job row.
            await logger.ainfo("Queue run stopped by a shutdown, requeued")
            return _HandlerResult(
                outcome=Retry(reason="worker shutdown", tag=SHUTDOWN_RETRY_TAG),
                run_outcome=RunOutcome.SHUTDOWN_RETRY,
                source_type=run.plan.source_type,
            )
        cause = WorkerShuttingDownError(
            run.job.id,
            SYNC_EXTRACT_KIND,
            EXTRACT_LANE,
            run.number,
            run.payload.workflow_id,
            EXTERNAL_DATA_JOB_WORKFLOW_TYPE,
        )
        return await self._fail(run, cause, logger)

    async def _on_failure(self, run: _Attempt, error: Exception, logger: FilteringBoundLogger) -> _HandlerResult:
        failure = classify_failure(error, is_v3=True)
        if failure.kind == FailureKind.WORKER_SHUTDOWN:
            return await self._on_shutdown(run, logger)
        # The workflow never retries these two: its retry policy lists them as non-retryable.
        final = failure.kind in (FailureKind.NON_RETRYABLE, FailureKind.BILLING_LIMIT_TOO_LOW)
        if not final and run.counted_retries + 1 < run.max_counted_attempts and self._retry_is_possible(run):
            await logger.awarning("Queue run failed, will retry", error=str(error))
            return _HandlerResult(
                outcome=Retry(reason=str(error)[:1000]), run_outcome=RunOutcome.RETRY, source_type=run.plan.source_type
            )
        return await self._fail(run, error, logger)

    async def _fail(self, run: _Attempt, error: BaseException, logger: FilteringBoundLogger) -> _HandlerResult:
        failure = classify_failure(error, is_v3=True)
        status = failure.status or ExternalDataJob.Status.FAILED
        await self._finalize(
            run.payload,
            run.job.id,
            job_id=run.plan.job_id,
            status=status,
            internal_error=failure.internal_error,
            latest_error=failure.latest_error,
            logger=logger,
        )
        return _HandlerResult(
            outcome=Fail(reason=str(error)[:1000] or type(error).__name__),
            run_outcome=RunOutcome.FAILED,
            source_type=run.plan.source_type,
        )

    async def _fail_too_long(self, run: _Attempt, logger: FilteringBoundLogger) -> _HandlerResult:
        await self._finalize(
            run.payload,
            run.job.id,
            job_id=run.plan.job_id,
            status=ExternalDataJob.Status.FAILED,
            internal_error="The extraction ran past its time budget",
            latest_error=SYNC_RUN_TOO_LONG_MESSAGE,
            logger=logger,
        )
        return _HandlerResult(
            outcome=Fail(reason="time budget exceeded"), run_outcome=RunOutcome.FAILED, source_type=run.plan.source_type
        )

    def _retry_is_possible(self, run: _Attempt) -> bool:
        # Past the engine's attempt cap the engine fails the job without calling the handler, and
        # past the claim window nothing claims it. Either way the job row would stay Running.
        return run.number < run.ctx.max_attempts and self._clock() < run.deadline - RETRY_WINDOW_MARGIN

    async def _finalize(
        self,
        payload: SyncExtractPayload,
        queue_job_id: str,
        *,
        job_id: str | None,
        status: str,
        logger: FilteringBoundLogger,
        internal_error: str | None = None,
        latest_error: str | None = None,
        platform_fault: bool = False,
    ) -> None:
        """Write the run's final status through the workflow's own finalizer."""
        await _update_job_status(
            UpdateExternalDataJobStatusInputs(
                team_id=payload.team_id,
                job_id=job_id,
                schema_id=str(payload.schema_id),
                source_id=str(payload.source_id),
                status=status,
                internal_error=internal_error,
                latest_error=latest_error,
                workflow_run_id=queue_job_id,
            ),
            logger,
            # An automatic disable must not try to cancel this run through Temporal.
            exclude_workflow_id=payload.workflow_id,
            platform_fault=platform_fault,
        )


@contextlib.contextmanager
def _job_log_context(payload: SyncExtractPayload, job: Job, attempt: int) -> Iterator[None]:
    # Restores the keys the engine bound for this job on exit.
    with structlog.contextvars.bound_contextvars(
        team_id=payload.team_id,
        external_data_schema_id=str(payload.schema_id),
        external_data_source_id=str(payload.source_id),
        external_data_job_id=None,
        workflow_type=EXTERNAL_DATA_JOB_WORKFLOW_TYPE,
        workflow_id=payload.workflow_id,
        workflow_run_id=job.id,
        log_source_id=str(payload.schema_id),
        attempt=attempt,
        queue_job_id=job.id,
    ):
        yield


def _skipped(reason: SkipReason) -> _HandlerResult:
    RUNS_SKIPPED_TOTAL.labels(reason=reason).inc()
    return _HandlerResult(outcome=Success(), run_outcome=RunOutcome.SKIPPED)


async def _extract(
    inputs: ImportDataActivityInputs, logger: FilteringBoundLogger, control: RunControl
) -> PipelineResult:
    async with aworkload_reporting(
        team_id=inputs.team_id,
        schema_id=str(inputs.schema_id),
        run_id=str(inputs.run_id),
        host=socket.gethostname(),
        attempt=control.attempt,
    ):
        return await run_extraction(inputs, logger, control)


async def _persist_extraction_result(
    team_id: int, job_id: str, result: PipelineResult, logger: FilteringBoundLogger
) -> None:
    """Write the extraction result, retrying a transient database error in place.

    A retry of the whole handler cannot recover a lost write once the loader has completed the run:
    it finds a terminal run with no result and skips the follow-up work for good.
    """
    for write in range(1, RESULT_WRITE_ATTEMPTS + 1):
        try:
            await database_sync_to_async_pool(_update_run_snapshot)(
                team_id, job_id, EXTRACTION_RESULT_SNAPSHOT_KEY, dict(result)
            )
            return
        except (OperationalError, InterfaceError, InternalError) as e:
            if write == RESULT_WRITE_ATTEMPTS:
                raise
            await logger.awarning("Persisting the extraction result failed transiently, retrying", error=str(e))
            await asyncio.sleep(write)


def _find_run_job(team_id: int, queue_job_id: str) -> ExternalDataJob | None:
    return (
        ExternalDataJob.objects.filter(team_id=team_id, workflow_run_id=queue_job_id)
        .only("id", "status", "schema_snapshot")
        .order_by("-created_at")
        .first()
    )


def _acquire_sync_lock(
    payload: SyncExtractPayload, job: Job, token: str, ctx: JobContext, logger: FilteringBoundLogger
) -> _LockOutcome:
    """Take the schema's V3 sync lock for this attempt, from a dead holder of either scheduler too.

    The lock, not the job rows, decides whether another run is in flight: a run that died can
    leave its row Running for good, and that row must not stop the schema.
    """
    team_id, schema_id = payload.team_id, str(payload.schema_id)
    result = try_acquire_v3_pipeline_lock(team_id, schema_id, token)
    if result == LockAcquireResult.UNAVAILABLE:
        return _LockOutcome.UNAVAILABLE
    if result == LockAcquireResult.HELD:
        holder = get_v3_pipeline_lock_holder(team_id, schema_id)
        if holder is not None and holder != token and lock_token_run_id(holder) == job.id:
            taken_over = _take_over_from_earlier_attempt(payload, job, holder, token, ctx, logger)
            if taken_over != _LockOutcome.ACQUIRED:
                return taken_over
        elif holder != token and not take_over_v3_lock_if_holder_finished(team_id, payload.schema_id, token, logger):
            return _LockOutcome.HELD
    # Lets a contender see that the holder is a queue attempt and ask the queue whether it still runs.
    write_v3_pipeline_lock_meta(
        team_id,
        schema_id,
        run_id=token,
        workflow_id=payload.workflow_id,
        runner=QUEUE_RUNNER,
        lease_owner=ctx.lease_owner,
    )
    return _LockOutcome.ACQUIRED


def _take_over_from_earlier_attempt(
    payload: SyncExtractPayload, job: Job, holder: str, token: str, ctx: JobContext, logger: FilteringBoundLogger
) -> _LockOutcome:
    """Take the lock from an earlier attempt of this queue job, but only when that attempt is fenced.

    The engine stops renewing the group lease of an attempt that loses it, but it does not stop
    the attempt. So the lock alone does not prove that the earlier attempt stopped. Its lease does:
    while another consumer holds a live lease on the group, the earlier attempt may still run. One
    consumer never runs two attempts of a group at once, so this consumer's own lease does not count.
    A queue database error fails closed.
    """
    team_id, schema_id = payload.team_id, str(payload.schema_id)
    meta = get_v3_pipeline_lock_meta(team_id, schema_id)
    holder_lease_owner = meta.get("lease_owner") if meta is not None and meta.get("run_id") == holder else None
    try:
        with psycopg.Connection.connect(ctx.database_url, autocommit=True) as conn:
            live_owner = JobsTable.get_live_lease_owner_sync(conn, lane=job.lane, group_key=job.group_key)
    except Exception as e:
        logger.warning("v3_pipeline_lock_earlier_attempt_check_failed", holder_token=holder, error=str(e))
        capture_exception(e)
        return _LockOutcome.EARLIER_ATTEMPT_LIVE
    if live_owner is not None and live_owner != ctx.lease_owner:
        logger.warning(
            "v3_pipeline_lock_takeover_skipped",
            holder_token=holder,
            reason="earlier_attempt_lease_live",
            holder_lease_owner=holder_lease_owner,
            live_lease_owner=live_owner,
        )
        return _LockOutcome.EARLIER_ATTEMPT_LIVE

    logger.warning(
        "v3_pipeline_lock_taking_over",
        holder_token=holder,
        reason="earlier_attempt_lease_gone",
        holder_lease_owner=holder_lease_owner,
    )
    # Compare-and-delete on the earlier token, so a run that took the lock in between keeps it.
    release_v3_pipeline_lock(team_id, schema_id, holder)
    result = try_acquire_v3_pipeline_lock(team_id, schema_id, token)
    if result == LockAcquireResult.UNAVAILABLE:
        return _LockOutcome.UNAVAILABLE
    return _LockOutcome.ACQUIRED if result == LockAcquireResult.ACQUIRED else _LockOutcome.HELD


def _lock_taken_by_another_attempt(payload: SyncExtractPayload, token: str) -> bool:
    """Whether another attempt of this queue job holds the lock now, so this attempt was replaced.

    Only another attempt of the same job counts. Another run gets the lock only after the loader
    or a teardown released it, which ends this run as well. Best-effort, as the check before job
    creation: an unheld lock or an unavailable Redis does not stop the run.
    """
    holder = get_v3_pipeline_lock_holder(payload.team_id, str(payload.schema_id))
    return holder is not None and holder != token and lock_token_run_id(holder) == lock_token_run_id(token)


async def _release_sync_lock(payload: SyncExtractPayload, token: str) -> None:
    # Compare-and-delete on the token, so a lock another run took is never touched. The queue job
    # id also matches an attempt token of that job.
    await asyncio.to_thread(release_v3_pipeline_lock, payload.team_id, str(payload.schema_id), token)


def _held_for_repartition(payload: SyncExtractPayload, logger: FilteringBoundLogger) -> bool:
    schema = ExternalDataSchema.objects.filter(id=payload.schema_id, team_id=payload.team_id).first()
    return schema is not None and repartition_import_hold_reason(schema, logger) is not None


def _validate_payload_and_eligibility(payload: SyncExtractPayload, *, lock: bool = False) -> str:
    schemas = ExternalDataSchema.objects.select_related("source").filter(id=payload.schema_id, team_id=payload.team_id)
    if lock:
        schemas = schemas.select_for_update()
    schema = schemas.first()
    if schema is None or schema.source_id != payload.source_id or schema.source.team_id != payload.team_id:
        return "invalid"
    if schema.deleted or schema.source.deleted or not schema.should_sync:
        return "disabled"
    return "eligible"


def _prepare_run_and_stamp(
    inputs: CreateExternalDataJobModelActivityInputs, payload: SyncExtractPayload, queue_job_id: str, lock_token: str
) -> CreateExternalDataJobModelActivityOutputs:
    # Inside the transaction below this would close the connection the transaction runs on.
    close_old_connections()
    # The plan is part of creating a queue run: either both it and the job row commit, or neither
    # does. A retry can never observe the half-created row the former separate UPDATE allowed.
    with transaction.atomic():
        eligibility = _validate_payload_and_eligibility(payload, lock=True)
        if eligibility != "eligible":
            raise _RunEligibilityChanged(eligibility)
        plan = prepare_run(
            inputs, workflow_id=payload.workflow_id, workflow_run_id=queue_job_id, v3_lock_token=lock_token
        )
        _update_run_snapshot(payload.team_id, plan.job_id, RUN_PLAN_SNAPSHOT_KEY, dataclasses.asdict(plan))
        ExternalDataJob.objects.filter(id=plan.job_id, team_id=payload.team_id).update(
            phase=ExternalDataJob.Phase.EXTRACTING
        )
    return plan


def _update_run_snapshot(team_id: int, job_id: str, key: str, value: Any) -> None:
    with transaction.atomic():
        job = ExternalDataJob.objects.select_for_update().only("schema_snapshot").get(id=job_id, team_id=team_id)
        snapshot = dict(job.schema_snapshot or {})
        snapshot[key] = value
        ExternalDataJob.objects.filter(id=job_id, team_id=team_id).update(schema_snapshot=snapshot)


def _snapshot_flag(team_id: int, job_id: str, key: str) -> bool:
    snapshot = (
        ExternalDataJob.objects.filter(id=job_id, team_id=team_id).values_list("schema_snapshot", flat=True).first()
        or {}
    )
    return snapshot.get(key) is True


def _load_run_plan(job: ExternalDataJob) -> CreateExternalDataJobModelActivityOutputs | None:
    stored = (job.schema_snapshot or {}).get(RUN_PLAN_SNAPSHOT_KEY)
    if not isinstance(stored, dict):
        return None
    known = {field.name for field in dataclasses.fields(CreateExternalDataJobModelActivityOutputs)}
    try:
        return CreateExternalDataJobModelActivityOutputs(**{k: v for k, v in stored.items() if k in known})
    except TypeError:
        return None


def _load_extraction_result(job: ExternalDataJob) -> PipelineResult | None:
    stored = (job.schema_snapshot or {}).get(EXTRACTION_RESULT_SNAPSHOT_KEY)
    return cast(PipelineResult, stored) if isinstance(stored, dict) else None


def _set_phase(team_id: int, job_id: str, phase: str) -> None:
    # The loader can finish the job before this write, so the status is not a filter. The phase
    # filter keeps a later phase that the loader wrote.
    ExternalDataJob.objects.filter(id=job_id, team_id=team_id, phase=ExternalDataJob.Phase.EXTRACTING).update(
        phase=phase
    )


def _run_is_cancelled(team_id: int, job_id: str) -> bool:
    status = ExternalDataJob.objects.filter(id=job_id, team_id=team_id).values_list("status", flat=True).first()
    # The loader completes the job when it loads the final batch, while the extraction may still be
    # closing its source. That is a run finishing, not a cancellation.
    return status is None or (status in TERMINAL_JOB_STATUSES and status != ExternalDataJob.Status.COMPLETED)
