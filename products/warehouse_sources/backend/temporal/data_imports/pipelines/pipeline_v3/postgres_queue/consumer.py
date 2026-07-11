"""
Postgres-backed batch consumer for warehouse source loading.

This module preserves the Delta consumer import path while delegating the shared
polling, retry, and recovery mechanics to the v3 batch consumer engine.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from datetime import datetime
from typing import Any

from django.db import close_old_connections

import psycopg
import structlog
from asgiref.sync import sync_to_async

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.metrics import TERMINAL_JOB_STATUSES
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.batch_consumer import (
    MAX_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
    RECONCILE_GRACE_SECONDS,
    RECONCILE_INTERVAL_SECONDS,
    RECONCILE_LOOKBACK_SECONDS,
    RECOVERY_INTERVAL_SECONDS,
    RETRY_BACKOFF_BASE_SECONDS,
    BatchConsumer as SharedBatchConsumer,
    BatchConsumerConfig,
    OwnershipLostError,
    ProcessBatchFn,
    _group_by_key,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    FRESHNESS_WINDOW_SECONDS,
    BatchQueue,
    PendingBatch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.metrics import (
    OLDEST_UNCLAIMED_BATCH_SECONDS,
    RUNS_RECONCILED_TOTAL,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.sync_lock import (
    release_v3_pipeline_lock,
)
from products.warehouse_sources_queue.backend.models import SourceBatchStatus

logger = structlog.get_logger(__name__)

ConsumerConfig = BatchConsumerConfig

# Raises OwnershipLostError when this consumer no longer holds the group lease.
VerifyOwnership = Callable[[], None]
# Unlike the engine's ProcessBatchFn, the Delta sink also receives the per-batch ownership check.
DeltaProcessBatchFn = Callable[[PendingBatch, VerifyOwnership | None], Coroutine[Any, Any, None]]

# Ceiling for the queue-freshness probe, deliberately far below the sweep
# timeout so a degraded probe can't starve the reconcile sweep it rides on.
FRESHNESS_PROBE_TIMEOUT_SECONDS = 30.0

# Errors that fail identically on every attempt. Substring-matched because they
# surface as generic exceptions; keep entries specific so transients can't match.
NON_RETRYABLE_ERROR_PATTERNS: tuple[str, ...] = (
    # delta-rs decimal precision overflow — the batch's data cannot fit the column
    "is too large to store in a Decimal128",
    # schema configured as incremental without a primary key — config error
    "Primary key required for incremental syncs",
)


class DeltaBatchConsumerAdapter:
    log_prefix: str = ""
    executing_state: str = SourceBatchStatus.State.EXECUTING.value
    succeeded_state: str = SourceBatchStatus.State.SUCCEEDED.value
    waiting_retry_state: str = SourceBatchStatus.State.WAITING_RETRY.value
    per_group_connections: bool = True

    async def fetch_and_lock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int,
        retry_backoff_base_seconds: int,
        owner_token: str,
        lease_ttl_seconds: int,
    ) -> list[PendingBatch]:
        return await BatchQueue.get_unprocessed_and_lock(
            conn,
            owner_token=owner_token,
            limit=limit,
            retry_backoff_base_seconds=retry_backoff_base_seconds,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    async def unlock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[PendingBatch],
        owner_token: str,
    ) -> None:
        await BatchQueue.unlock_for_batches(conn, batches=batches, owner_token=owner_token)

    async def release_all_owned(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
    ) -> None:
        await BatchQueue.release_all_owned_leases(conn, owner_token=owner_token)

    async def update_status(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int,
        error_response: dict[str, Any] | None = None,
        batch_created_at: datetime | None = None,
    ) -> None:
        await BatchQueue.update_status(
            conn,
            batch_id=batch_id,
            job_state=job_state,
            attempt=attempt,
            error_response=error_response,
            batch_created_at=batch_created_at,
        )

    async def fail_run(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
        reason: str,
    ) -> None:
        """Fail all pending batches in this run and mark the ExternalDataJob as failed.

        Each step is isolated so a failure can't crash the consumer.
        """
        try:
            await BatchQueue.fail_run(conn, run_uuid=batch.run_uuid, reason=reason)
        except Exception as e:
            logger.exception("fail_run_queue_update_failed", batch_id=batch.id, run_uuid=batch.run_uuid)
            capture_exception(e)

        try:
            await sync_to_async(_update_job_status_to_failed)(
                job_id=batch.job_id,
                team_id=batch.team_id,
                error=reason,
            )
        except Exception as e:
            # Leave the job for the reconcile sweep rather than crashing the consumer.
            logger.exception("fail_run_job_status_update_failed", job_id=batch.job_id, run_uuid=batch.run_uuid)
            capture_exception(e)

        workflow_run_id = batch.metadata.get("workflow_run_id")
        if workflow_run_id:
            try:
                await sync_to_async(release_v3_pipeline_lock)(
                    team_id=batch.team_id,
                    schema_id=batch.schema_id,
                    token=workflow_run_id,
                )
            except Exception as e:
                logger.error(
                    "failed_to_release_v3_pipeline_lock",
                    job_id=batch.job_id,
                    schema_id=batch.schema_id,
                    exc_info=True,
                )
                capture_exception(e)

    async def verify_advisory_lock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
    ) -> bool:
        return await BatchQueue.verify_advisory_lock(
            conn, team_id=team_id, schema_id=schema_id, owner_token=owner_token
        )

    async def renew_lease(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
        lease_ttl_seconds: int,
    ) -> bool:
        return await BatchQueue.renew_lease(
            conn,
            team_id=team_id,
            schema_id=schema_id,
            owner_token=owner_token,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    async def get_stale_executing(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int,
        keep_locks: bool = False,
    ) -> list[PendingBatch]:
        # keep_locks is meaningless for the lease sink: get_stale_executing holds
        # no locks and the lease LEFT JOIN already excludes live groups.
        return await BatchQueue.get_stale_executing(conn, grace_seconds=grace_seconds)

    async def reconcile_failed_runs(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int,
        lookback_seconds: int,
        limit: int,
    ) -> None:
        """Mark ExternalDataJobs Failed when their run has a failed queue batch but the app-DB write never landed."""
        # Piggyback the reconcile cadence for the queue-freshness gauge: same
        # connection, same periodicity, and isolated so it can't break the sweep.
        await self._observe_queue_freshness(conn)

        refs = await BatchQueue.get_failed_runs(
            conn,
            grace_seconds=grace_seconds,
            lookback_seconds=lookback_seconds,
            limit=limit,
        )
        for ref in refs:
            # A producer can enqueue a batch into a run after fail_run swept it (the
            # extraction is still in flight when a sibling batch exhausts retries).
            # Such stragglers stay 'pending' forever — unclaimable, but counted by the
            # freshness gauge and the CDC backpressure probe — so re-sweep the run here.
            # No-op (one indexed statement) when the run has no non-terminal batches.
            try:
                stragglers = await BatchQueue.fail_run(
                    conn,
                    run_uuid=ref.run_uuid,
                    reason="enqueued into an already-failed run (reconcile sweep)",
                )
            except Exception as e:
                logger.exception("reconcile_straggler_sweep_failed", run_uuid=ref.run_uuid)
                capture_exception(e)
            else:
                if stragglers:
                    logger.warning(
                        "reconcile_swept_straggler_batches",
                        run_uuid=ref.run_uuid,
                        team_id=ref.team_id,
                        external_data_schema_id=ref.schema_id,
                        batch_count=stragglers,
                    )

            try:
                reconciled = await sync_to_async(mark_job_failed_if_not_terminal)(
                    job_id=ref.job_id,
                    team_id=ref.team_id,
                    error=ref.reason or "run failed (reconciled from queue)",
                )
            except Exception as e:
                logger.exception("reconcile_job_status_update_failed", job_id=ref.job_id, run_uuid=ref.run_uuid)
                capture_exception(e)
                continue

            if not reconciled:
                continue  # job was already terminal — nothing to reconcile

            RUNS_RECONCILED_TOTAL.inc()
            logger.warning(
                "run_reconciled_to_failed",
                job_id=ref.job_id,
                run_uuid=ref.run_uuid,
                team_id=ref.team_id,
                external_data_schema_id=ref.schema_id,
            )

            # Release the V3 pipeline lock too, otherwise it blocks the schema's next sync until its TTL expires.
            if ref.workflow_run_id:
                try:
                    await sync_to_async(release_v3_pipeline_lock)(
                        team_id=ref.team_id,
                        schema_id=ref.schema_id,
                        token=ref.workflow_run_id,
                    )
                except Exception as e:
                    logger.error(
                        "failed_to_release_v3_pipeline_lock",
                        job_id=ref.job_id,
                        schema_id=ref.schema_id,
                        exc_info=True,
                    )
                    capture_exception(e)

    async def _observe_queue_freshness(self, conn: psycopg.AsyncConnection[Any]) -> None:
        """Report the age of the oldest batch no consumer has picked up yet.

        This is the loader's data-freshness signal: it rises whenever loading
        stalls, no matter why — the alert on it fires even when every other
        health signal looks green. The probe has its own timeout so it cannot
        eat the reconcile sweep's budget; on timeout the gauge saturates, since
        a queue DB too degraded to measure freshness must read as stale. Other
        failures are swallowed-with-capture so a broken probe can't take the
        sweep down.
        """
        try:
            async with asyncio.timeout(FRESHNESS_PROBE_TIMEOUT_SECONDS):
                age = await BatchQueue.get_oldest_unclaimed_batch_age_seconds(conn)
        except TimeoutError:
            logger.error(  # noqa: TRY400 — designed degraded path, traceback is noise
                "queue_freshness_probe_timed_out",
                timeout_seconds=FRESHNESS_PROBE_TIMEOUT_SECONDS,
            )
            OLDEST_UNCLAIMED_BATCH_SECONDS.set(FRESHNESS_WINDOW_SECONDS)
            return
        except Exception as e:
            logger.exception("queue_freshness_probe_failed")
            capture_exception(e)
            return
        OLDEST_UNCLAIMED_BATCH_SECONDS.set(age or 0.0)

    async def should_process_batch(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> bool:
        return True

    def is_retryable_error(self, err: Exception) -> bool:
        message = str(err)
        return not any(pattern in message for pattern in NON_RETRYABLE_ERROR_PATTERNS)

    async def after_batch_processed(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> None:
        return None


class BatchConsumer(SharedBatchConsumer):
    def __init__(
        self,
        config: ConsumerConfig,
        process_batch: DeltaProcessBatchFn,
        health_reporter: Callable[[], None] | None = None,
    ) -> None:
        async def process_with_ownership_check(batch: PendingBatch) -> None:
            await process_batch(batch, self._make_verify_ownership(batch))

        super().__init__(
            config=config,
            process_batch=process_with_ownership_check,
            adapter=DeltaBatchConsumerAdapter(),
            health_reporter=health_reporter,
        )

    def _make_verify_ownership(self, batch: PendingBatch) -> Callable[[], None]:
        """Sync ownership check for the worker thread: the engine's lease checks bracket
        the batch but can't see a loss mid-write. Fails closed — an unverified lease is lost."""
        database_url = self._config.database_url
        connect_timeout = self._config.connect_timeout_seconds

        def verify_ownership() -> None:
            try:
                owns = BatchQueue.verify_group_lease_sync(
                    database_url,
                    team_id=batch.team_id,
                    schema_id=batch.schema_id,
                    owner_token=self._owner_token,
                    connect_timeout_seconds=connect_timeout,
                )
            except Exception as e:
                raise OwnershipLostError("pre-commit lease verification query failed") from e
            if not owns:
                raise OwnershipLostError(f"group lease lost before commit for ({batch.team_id}, {batch.schema_id})")

        return verify_ownership


def _update_job_status_to_failed(*, job_id: str, team_id: int, error: str) -> None:
    from products.data_warehouse.backend.facade.api import update_external_job_status
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    # Drop stale app-DB connections so this write reconnects instead of leaving the job stuck in Running.
    close_old_connections()

    existing = ExternalDataJob.objects.filter(id=job_id, team_id=team_id, status=ExternalDataJob.Status.FAILED).first()
    if existing is not None:
        return

    update_external_job_status(
        job_id=job_id,
        team_id=team_id,
        status=ExternalDataJob.Status.FAILED,
        logger=structlog.get_logger(),
        latest_error=error,
    )


def mark_job_failed_if_not_terminal(*, job_id: str, team_id: int, error: str) -> bool:
    """Mark a non-terminal ExternalDataJob Failed; returns True if it transitioned (terminal jobs are a no-op).

    Public seam shared by the reconcile sweep and the manage_warehouse_queue ops
    command, so both fail paths agree on the terminal-status check.
    """
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

    close_old_connections()

    job = ExternalDataJob.objects.filter(id=job_id, team_id=team_id).only("status").first()
    if job is None or job.status in TERMINAL_JOB_STATUSES:
        return False

    _update_job_status_to_failed(job_id=job_id, team_id=team_id, error=error)
    return True


__all__ = [
    "BatchConsumer",
    "ConsumerConfig",
    "DeltaBatchConsumerAdapter",
    "MAX_ATTEMPTS",
    "POLL_INTERVAL_SECONDS",
    "ProcessBatchFn",
    "RECONCILE_GRACE_SECONDS",
    "RECONCILE_INTERVAL_SECONDS",
    "RECONCILE_LOOKBACK_SECONDS",
    "RECOVERY_INTERVAL_SECONDS",
    "RETRY_BACKOFF_BASE_SECONDS",
    "_group_by_key",
    "mark_job_failed_if_not_terminal",
]
