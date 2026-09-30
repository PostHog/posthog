"""The `sync.extract` handler: one extraction run of one schema, on the queue.

The handler does what `ExternalDataJobWorkflow` does for a V3 run up to the loader handoff. It
creates the job row, runs the extraction body, and hands the run to the loader. A run with no
batch never reaches the loader, so the handler completes that run itself.

Job row identity: `workflow_run_id` on the job row is the queue job id, so every attempt of one
queue job finds the same job row. `workflow_id` comes from the payload.
"""

from __future__ import annotations

import time
import socket
import asyncio
import datetime as dt
import dataclasses
from collections.abc import Callable
from typing import Any

from django.db import InterfaceError, InternalError, OperationalError

import structlog
from structlog.types import FilteringBoundLogger

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async_pool
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.logger import get_logger
from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.queue_runs.budgets import RETRY_WINDOW_MARGIN, claim_deadline, run_budget
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
from products.warehouse_sources.backend.temporal.data_imports.run_control import (
    EventShutdownMonitor,
    RunControl,
    no_heartbeat,
)
from products.warehouse_sources.backend.temporal.data_imports.util import PostHogInternalDatabaseError
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model import (
    CreateExternalDataJobModelActivityInputs,
    CreateExternalDataJobModelActivityOutputs,
    prepare_run,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
    raise_setup_app_db_error,
    run_extraction,
)
from products.warehouse_sources.backend.temporal.data_imports.workload_report import aworkload_reporting
from products.warehouse_sources_queue.backend.sdk import Fail, Job, JobContext, Outcome, Retry, Success

LOGGER = get_logger(__name__)

# The tag on a retry that a shutdown caused. Those retries do not count against the run's cap.
SHUTDOWN_RETRY_TAG = "shutdown"
# The key in `ExternalDataJob.schema_snapshot` that keeps the pre-extraction answers, so a later
# attempt of the same queue job reads them instead of creating another job row.
RUN_PLAN_SNAPSHOT_KEY = "queue_run_plan"


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


@frozen
class _Attempt:
    """The facts about one attempt that its failure paths need."""

    job: Job
    ctx: JobContext
    payload: SyncExtractPayload
    number: int
    plan: CreateExternalDataJobModelActivityOutputs
    # Counted retries before this attempt, and the most this run may count.
    counted_retries: int
    max_counted_attempts: int
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
        # Restores the keys the engine bound for this job when the handler returns.
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
            tag_queries(team_id=payload.team_id, product=Product.WAREHOUSE, feature=Feature.IMPORT_PIPELINE)
            result = await self._handle(job, ctx, payload, attempt, LOGGER.bind())
        RUNS_FINISHED_TOTAL.labels(source_type=result.source_type or "unknown", outcome=result.run_outcome).inc()
        RUN_DURATION_SECONDS.labels(outcome=result.run_outcome).observe(time.monotonic() - started)
        return result.outcome

    async def _handle(
        self, job: Job, ctx: JobContext, payload: SyncExtractPayload, attempt: int, logger: FilteringBoundLogger
    ) -> _HandlerResult:
        existing = await database_sync_to_async_pool(_find_run_job)(payload.team_id, job.id)

        if await database_sync_to_async_pool(_other_run_is_running)(
            payload.team_id, payload.schema_id, existing.id if existing is not None else None
        ):
            await logger.ainfo("Skipping queue run: another run of this schema is running")
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

        if existing is not None and existing.status in TERMINAL_JOB_STATUSES:
            await logger.ainfo("Skipping queue run: its job is already terminal", status=existing.status)
            return _skipped(SkipReason.ALREADY_TERMINAL)

        if existing is None:
            if await database_sync_to_async_pool(_held_for_repartition)(payload, logger):
                # Queue runs never run the repartition step, which is what ends the hold.
                await logger.ainfo("Skipping queue run: a repartition holds this schema's import")
                return _skipped(SkipReason.REPARTITION_HOLD)
            prepared = await self._prepare(job, payload, logger)
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
                )
                return _HandlerResult(outcome=Fail(reason="queue run plan missing"), run_outcome=RunOutcome.FAILED)
            plan = loaded

        structlog.contextvars.bind_contextvars(external_data_job_id=plan.job_id)
        budget = run_budget(
            source_type=plan.source_type,
            incremental_or_append=plan.incremental_or_append,
            keyset_full_load_enabled=plan.keyset_full_load_enabled,
        )
        history = await ctx.retry_history(job, uncounted_tag=SHUTDOWN_RETRY_TAG)
        run = _Attempt(
            job=job,
            ctx=ctx,
            payload=payload,
            number=attempt,
            plan=plan,
            counted_retries=history.counted_retries,
            max_counted_attempts=budget.max_attempts,
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
        self, job: Job, payload: SyncExtractPayload, logger: FilteringBoundLogger
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
            plan = await database_sync_to_async_pool(prepare_run)(
                inputs, workflow_id=payload.workflow_id, workflow_run_id=job.id, verify_v3_lock=False
            )
        except Exception as e:
            # The workflow gives job creation one attempt, so a failure here ends the run.
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
        await database_sync_to_async_pool(_stamp_run_plan)(payload.team_id, plan)
        return plan

    async def _extract_and_hand_off(
        self, run: _Attempt, timeout: dt.timedelta, logger: FilteringBoundLogger
    ) -> _HandlerResult:
        payload, plan = run.payload, run.plan
        stop_watch = RunStopWatch(
            shutdown_event=run.ctx.shutdown_event,
            is_run_cancelled=lambda: database_sync_to_async_pool(_run_is_cancelled)(payload.team_id, plan.job_id),
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
            verify_v3_lock=False,
            on_rows_extracted=ROWS_EXTRACTED_TOTAL.labels(source_type=plan.source_type).inc,
        )
        inputs = ImportDataActivityInputs(
            team_id=payload.team_id,
            run_id=plan.job_id,
            schema_id=payload.schema_id,
            source_id=payload.source_id,
            reset_pipeline=payload.reset_pipeline,
            fast_return_eligible=plan.fast_return_eligible,
            scheduled_full_refresh=plan.scheduled_full_refresh,
            keyset_full_load_enabled=plan.keyset_full_load_enabled,
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

        if result.get("consumer_manages_job_status", False):
            await database_sync_to_async_pool(_set_phase)(payload.team_id, plan.job_id, ExternalDataJob.Phase.LOADING)
            await logger.ainfo("Queue run handed to the loader")
            await start_post_extraction_work(self._starter, payload=payload, plan=plan, result=result, logger=logger)
            return _HandlerResult(
                outcome=Success(), run_outcome=RunOutcome.HANDED_TO_LOADER, source_type=plan.source_type
            )

        # No batch reached the loader, so the loader never hears about this run. Finish it the
        # way the workflow does for such a run: the post-extraction work, then the finalizer.
        await start_post_extraction_work(self._starter, payload=payload, plan=plan, result=result, logger=logger)
        await self._finalize(
            payload, run.job.id, job_id=plan.job_id, status=ExternalDataJob.Status.COMPLETED, logger=logger
        )
        if not result.get("skip_post_import_activities", False):
            await start_post_import(self._starter, payload=payload, job_id=plan.job_id, logger=logger)
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
        )


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
        try:
            return await run_extraction(inputs, logger, control)
        except (OperationalError, InterfaceError, InternalError, PostHogInternalDatabaseError) as e:
            await raise_setup_app_db_error(e, logger)


def _find_run_job(team_id: int, queue_job_id: str) -> ExternalDataJob | None:
    return (
        ExternalDataJob.objects.filter(team_id=team_id, workflow_run_id=queue_job_id)
        .only("id", "status", "schema_snapshot")
        .order_by("-created_at")
        .first()
    )


def _other_run_is_running(team_id: int, schema_id: Any, own_job_id: Any | None) -> bool:
    """Whether another run of the schema is live, from either scheduler.

    Temporal skips a run that overlaps a live one, for manual triggers too. A queue run does the
    same, so a Temporal run that is still going after the flag changed keeps the table to itself.
    """
    running = ExternalDataJob.objects.filter(
        team_id=team_id, schema_id=schema_id, status=ExternalDataJob.Status.RUNNING
    )
    if own_job_id is not None:
        running = running.exclude(id=own_job_id)
    return running.exists()


def _held_for_repartition(payload: SyncExtractPayload, logger: FilteringBoundLogger) -> bool:
    schema = ExternalDataSchema.objects.filter(id=payload.schema_id, team_id=payload.team_id).first()
    return schema is not None and repartition_import_hold_reason(schema, logger) is not None


def _stamp_run_plan(team_id: int, plan: CreateExternalDataJobModelActivityOutputs) -> None:
    job = ExternalDataJob.objects.only("schema_snapshot").get(id=plan.job_id, team_id=team_id)
    snapshot = dict(job.schema_snapshot or {})
    snapshot[RUN_PLAN_SNAPSHOT_KEY] = dataclasses.asdict(plan)
    ExternalDataJob.objects.filter(id=plan.job_id, team_id=team_id).update(
        schema_snapshot=snapshot, phase=ExternalDataJob.Phase.EXTRACTING
    )


def _load_run_plan(job: ExternalDataJob) -> CreateExternalDataJobModelActivityOutputs | None:
    stored = (job.schema_snapshot or {}).get(RUN_PLAN_SNAPSHOT_KEY)
    if not isinstance(stored, dict):
        return None
    known = {field.name for field in dataclasses.fields(CreateExternalDataJobModelActivityOutputs)}
    try:
        return CreateExternalDataJobModelActivityOutputs(**{k: v for k, v in stored.items() if k in known})
    except TypeError:
        return None


def _set_phase(team_id: int, job_id: str, phase: str) -> None:
    # The loader can finish the job before this write, so the status is not a filter. The phase
    # filter keeps a later phase that the loader wrote.
    ExternalDataJob.objects.filter(id=job_id, team_id=team_id, phase=ExternalDataJob.Phase.EXTRACTING).update(
        phase=phase
    )


def _run_is_cancelled(team_id: int, job_id: str) -> bool:
    status = ExternalDataJob.objects.filter(id=job_id, team_id=team_id).values_list("status", flat=True).first()
    return status is None or status in TERMINAL_JOB_STATUSES
