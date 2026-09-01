"""SDK for the generic job queue: handlers, outcomes, and the consumer wiring.

A workload registers one ``JobHandler`` per kind and runs a ``JobConsumer``
for its lane. The consumer engine (``core.batch_consumer.BatchConsumer``)
supplies polling, lease heartbeats, retries with backoff, recovery sweeps, and
health/liveness; ``GenericJobAdapter`` maps its protocol onto the generic
tables. Followers returned by a successful handler are enqueued in the same
transaction as the terminal status write.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, cast

import psycopg

from posthog.dataclasses import frozen

from products.warehouse_sources_queue.backend.core.batch_consumer import (
    BatchConsumer,
    BatchConsumerConfig,
    OwnershipLostError,
    PermanentBatchApplyError,
)
from products.warehouse_sources_queue.backend.core.generic_jobs import (
    JOB_LEASE_TTL_SECONDS,
    TERMINAL_JOB_STATES,
    Job,
    JobsTable,
)
from products.warehouse_sources_queue.backend.core.metrics import ConsumerMetrics, make_consumer_metrics

if TYPE_CHECKING:
    from products.warehouse_sources_queue.backend.core.batch_consumer import BatchConsumerAdapter, ProcessBatchFn

logger = logging.getLogger(__name__)


@frozen
class FollowerSpec:
    """One job to enqueue when its parent succeeds."""

    kind: str
    group_key: str
    team_id: int
    payload: dict[str, Any]
    lane: str
    run_id: str | None = None
    sequence: int = 0
    priority: int = 0
    dedup_key: str | None = None


@frozen
class Success:
    followers: tuple[FollowerSpec, ...] = ()


@frozen
class Retry:
    reason: str


@frozen
class Fail:
    reason: str


Outcome = Success | Retry | Fail


class JobRetryRequested(Exception):
    """Raised internally to route a ``Retry`` outcome into the engine's waiting_retry cycle."""


@frozen(slots=False)
class JobContext:
    """What a handler gets besides the job itself."""

    logger: logging.Logger


class JobHandler(Protocol):
    async def handle(self, job: Job, ctx: JobContext) -> Outcome: ...


class GenericJobAdapter:
    """``BatchConsumerAdapter`` over the generic job tables.

    The engine's protocol speaks in batch vocabulary (``batch_id``,
    ``schema_id``); this adapter maps those onto jobs and (lane, group_key)
    leases — see ``Job``'s alias properties for the field mapping.
    """

    log_prefix = "generic_jobs"
    executing_state = "executing"
    succeeded_state = "succeeded"
    waiting_retry_state = "waiting_retry"
    # Lease ownership is token-based, so any connection works.
    per_group_connections = True
    # A skip means "already terminal"; the succeeded re-write is absorbed by the
    # unless-failed guard, so recording it is safe.
    record_skip_as_success = True

    def __init__(
        self,
        *,
        lane: str,
        kinds: list[str],
        is_retryable: Callable[[Exception], bool] | None = None,
    ) -> None:
        self._lane = lane
        self._kinds = kinds
        self._is_retryable = is_retryable
        # Followers a handler returned, keyed by job id, consumed by the
        # succeeded status write so both land in one transaction. The engine
        # runs process and the status write on the same group task, so there is
        # no concurrent access per key.
        self._pending_followers: dict[str, tuple[FollowerSpec, ...]] = {}

    def stash_followers(self, job_id: str, followers: tuple[FollowerSpec, ...]) -> None:
        if followers:
            self._pending_followers[job_id] = followers

    async def fetch_and_lock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int,
        retry_backoff_base_seconds: int,
        owner_token: str,
        lease_ttl_seconds: int,
    ) -> list[Job]:
        return await JobsTable.get_unprocessed_and_lock(
            conn,
            owner_token=owner_token,
            lane=self._lane,
            kinds=self._kinds,
            limit=limit,
            retry_backoff_base_seconds=retry_backoff_base_seconds,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    async def unlock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[Job],
        owner_token: str,
    ) -> None:
        await JobsTable.unlock_groups(
            conn,
            lane=self._lane,
            group_keys=sorted({job.group_key for job in batches}),
            owner_token=owner_token,
        )

    async def release_all_owned(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
    ) -> None:
        await JobsTable.release_all_owned(conn, owner_token=owner_token)

    async def update_status(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int,
        error_response: dict[str, Any] | None = None,
        batch_created_at: datetime | None = None,
        expected_state_changed_at: datetime | None = None,
    ) -> None:
        if job_state == self.succeeded_state:
            # Peek rather than pop: if the transaction below raises, the
            # entry must still be there for a subsequent retry to pick up,
            # otherwise a crash mid-commit would silently drop the followers.
            followers = self._pending_followers.get(batch_id, ())
            # Terminal write and follower enqueue commit together: a crash
            # between them cannot complete a job without its followers.
            async with conn.transaction():
                wrote = await JobsTable.update_status_unless_failed(
                    conn,
                    job_id=batch_id,
                    job_state=job_state,
                    attempt=attempt,
                    error_response=error_response,
                    job_created_at=batch_created_at,
                )
                if wrote and followers:
                    await JobsTable.insert_many(
                        conn,
                        [
                            {
                                "kind": f.kind,
                                "lane": f.lane,
                                "group_key": f.group_key,
                                "team_id": f.team_id,
                                "payload": f.payload,
                                "run_id": f.run_id,
                                "sequence": f.sequence,
                                "priority": f.priority,
                                "dedup_key": f.dedup_key,
                            }
                            for f in followers
                        ],
                    )
            # Only drop the stash once the transaction has actually committed
            # (i.e. the block above returned without raising).
            self._pending_followers.pop(batch_id, None)
            return
        # expected_state_changed_at arms a compare-and-swap: the recovery sweep passes
        # the state it observed so a stale re-queue can't clobber a newer terminal write
        # (e.g. a late success) with 'waiting_retry'. update_status_unless_failed also
        # keeps 'failed' absorbing for every write here, not just the succeeded one.
        arm_cas = expected_state_changed_at is not None
        wrote = await JobsTable.update_status_unless_failed(
            conn,
            job_id=batch_id,
            job_state=job_state,
            attempt=attempt,
            error_response=error_response,
            job_created_at=batch_created_at,
            expected_state_changed_at=expected_state_changed_at,
            arm_cas=arm_cas,
        )
        if arm_cas and not wrote:
            raise OwnershipLostError(
                f"job {batch_id} moved under this writer (already failed or state advanced); "
                f"refusing to write '{job_state}' over it"
            )

    async def fail_run(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: Job,
        reason: str,
    ) -> None:
        # Must not raise (the engine calls this from error paths). No run-level
        # fan-out in phase 1: failing the one job is the whole action, and the
        # run gate parks any followers behind the failed sequence.
        try:
            self._pending_followers.pop(batch.id, None)
            await JobsTable.update_status(
                conn,
                job_id=batch.id,
                job_state="failed",
                attempt=batch.latest_attempt,
                error_response={"error": reason},
                job_created_at=batch.created_at,
            )
        except Exception:
            logger.exception("generic_jobs_fail_run_write_failed", extra={"job_id": batch.id})

    async def verify_advisory_lock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
    ) -> bool:
        return await JobsTable.verify_lease(conn, lane=self._lane, group_key=schema_id, owner_token=owner_token)

    async def renew_lease(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
        lease_ttl_seconds: int,
    ) -> bool:
        return await JobsTable.renew_lease(
            conn,
            lane=self._lane,
            group_key=schema_id,
            owner_token=owner_token,
            lease_ttl_seconds=lease_ttl_seconds or JOB_LEASE_TTL_SECONDS,
        )

    async def delete_expired_lease(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
    ) -> None:
        await JobsTable.delete_expired_lease(conn, lane=self._lane, group_key=schema_id)

    async def get_stale_executing(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int,
        keep_locks: bool = False,
    ) -> list[Job]:
        return await JobsTable.get_stale_executing(
            conn, lane=self._lane, kinds=self._kinds, grace_seconds=grace_seconds
        )

    async def reconcile_failed_runs(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int,
        lookback_seconds: int,
        limit: int,
    ) -> None:
        # Nothing to reconcile: generic jobs have no external state machine to
        # repair (the batch queue's reconcile exists for ExternalDataJob rows).
        return

    async def should_process_batch(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: Job,
    ) -> bool:
        state = await JobsTable.get_latest_state(conn, job_id=batch.id)
        return state not in TERMINAL_JOB_STATES

    def is_retryable_error(self, err: Exception) -> bool:
        if isinstance(err, PermanentBatchApplyError):
            return False
        if self._is_retryable is not None:
            return self._is_retryable(err)
        return True

    def is_expected_user_error(self, err: Exception) -> bool:
        return False

    async def after_batch_processed(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: Job,
    ) -> None:
        return


# Module-level singleton: prometheus collectors register globally, so building
# them once keeps repeated JobConsumer construction (tests, reuse) safe.
GENERIC_JOB_METRICS: ConsumerMetrics | None = None


def _generic_job_metrics() -> ConsumerMetrics:
    global GENERIC_JOB_METRICS
    if GENERIC_JOB_METRICS is None:
        GENERIC_JOB_METRICS = make_consumer_metrics("warehouse_jobs")
    return GENERIC_JOB_METRICS


class JobConsumer:
    """Kind-dispatching consumer for one lane, on the shared engine.

    ``handlers`` maps kind -> ``JobHandler``; the consumer claims only those
    kinds. Handler outcomes: ``Success`` records the terminal state and
    enqueues followers atomically; ``Retry`` routes into the engine's
    waiting_retry cycle (attempt caps from ``config.max_attempts``); ``Fail``
    fails the job on first attempt.
    """

    def __init__(
        self,
        *,
        config: BatchConsumerConfig,
        lane: str,
        handlers: dict[str, JobHandler],
        health_reporter: Callable[[], None] | None = None,
        metrics: ConsumerMetrics | None = None,
        is_retryable: Callable[[Exception], bool] | None = None,
    ) -> None:
        self._handlers = handlers
        self._adapter = GenericJobAdapter(lane=lane, kinds=sorted(handlers), is_retryable=is_retryable)
        self._ctx = JobContext(logger=logger)
        # The engine is typed against the batch item; Job satisfies its runtime
        # attribute contract through the documented aliases, so the casts bridge
        # the vocabulary until the engine is generic over its item type.
        self._consumer = BatchConsumer(
            config,
            cast("ProcessBatchFn", self._process),
            cast("BatchConsumerAdapter", self._adapter),
            health_reporter=health_reporter,
            metrics=metrics or _generic_job_metrics(),
        )

    async def _process(self, job: Job) -> None:
        handler = self._handlers.get(job.kind)
        if handler is None:
            raise PermanentBatchApplyError(f"no handler registered for kind {job.kind!r}")
        outcome = await handler.handle(job, self._ctx)
        match outcome:
            case Success(followers=followers):
                self._adapter.stash_followers(job.id, followers)
            case Retry(reason=reason):
                raise JobRetryRequested(reason)
            case Fail(reason=reason):
                raise PermanentBatchApplyError(reason)
            case _:
                raise PermanentBatchApplyError(f"handler for {job.kind!r} returned {outcome!r}, not an Outcome")

    async def run(self) -> None:
        await self._consumer.run()

    def request_shutdown(self) -> None:
        # The engine only arms shutdown from its own SIGTERM/SIGINT handlers;
        # tests and embedders need a programmatic trigger for the same event.
        self._consumer._shutdown.set()
