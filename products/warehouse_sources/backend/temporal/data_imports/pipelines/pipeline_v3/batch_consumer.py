from __future__ import annotations

import time
import random
import signal
import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

import psycopg
import structlog

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    PendingBatch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.metrics import (
    DELTA_CONSUMER_METRICS,
    ConsumerMetrics,
)

logger = structlog.get_logger(__name__)

MAX_ATTEMPTS = 3
POLL_INTERVAL_SECONDS = 2.0
RECOVERY_INTERVAL_SECONDS = 30.0
RETRY_BACKOFF_BASE_SECONDS = 15
HEARTBEAT_INTERVAL_SECONDS = 5.0
RECOVERY_GRACE_SECONDS = 300

# Reconcile sweep: catch runs whose queue batch failed but whose ExternalDataJob was left non-terminal.
RECONCILE_INTERVAL_SECONDS = 300.0
RECONCILE_GRACE_SECONDS = 120  # don't race a _fail_run that is still in flight
RECONCILE_LOOKBACK_SECONDS = 24 * 60 * 60  # wide enough to catch jobs orphaned by consumer outages

SHUTDOWN_DRAIN_TIMEOUT_SECONDS = 30.0

# Cap on the exponential backoff between failed polls — flat retries make the
# whole fleet hammer a degraded queue DB in lockstep.
POLL_BACKOFF_MAX_SECONDS = 30.0

# Per-poll fetch cap multiplier: fetch at most (free slots x this) batches so a poll
# never leases far more groups than it can dispatch. Runs average ~2 batches per
# group (batch 0 + final), so x3 gives headroom for multi-batch runs without
# re-creating the over-claim problem.
BATCHES_PER_GROUP_FETCH_FACTOR = 3


class OwnershipLostError(Exception):
    """Raised when the group lease for a (team_id, schema_id) is no longer held by this consumer."""


@dataclass
class BatchConsumerConfig:
    """Tuning knobs for the batch consumer."""

    database_url: str
    max_concurrency: int = 16
    max_attempts: int = MAX_ATTEMPTS
    poll_interval_seconds: float = POLL_INTERVAL_SECONDS
    poll_limit: int = 50
    health_port: int = 8080
    health_timeout_seconds: float = 60.0
    heartbeat_interval_seconds: float = HEARTBEAT_INTERVAL_SECONDS
    recovery_interval_seconds: float = RECOVERY_INTERVAL_SECONDS
    retry_backoff_base_seconds: int = RETRY_BACKOFF_BASE_SECONDS
    recovery_grace_seconds: int | None = None
    # Group-lease validity window. Defaults to recovery_grace_seconds so lease
    # reclamation and the executing-status recovery sweep fire together.
    lease_ttl_seconds: int | None = None
    reconcile_interval_seconds: float = RECONCILE_INTERVAL_SECONDS
    reconcile_grace_seconds: int = RECONCILE_GRACE_SECONDS
    reconcile_lookback_seconds: int = RECONCILE_LOOKBACK_SECONDS
    reconcile_limit: int = 100
    # Ceilings on queue-DB operations. Without them a claim query or sweep that
    # degrades past "slow" into "never returns" silently wedges the consumer:
    # the awaiting task holds its slot forever, with no error and no log.
    connect_timeout_seconds: int = 10
    poll_timeout_seconds: float | None = 180.0
    sweep_timeout_seconds: float | None = 300.0
    # Added to each connection's client ceiling to form its server-side
    # statement_timeout, so an abandoned poll or sweep can't keep burning DB CPU.
    statement_timeout_margin_seconds: float = 30.0
    # When set, the consumer stops reporting itself healthy once any single batch
    # has been executing longer than this, so a wedged sink connection turns into
    # a liveness-probe restart instead of an indefinite, invisible stall.
    stuck_batch_timeout_seconds: float | None = None
    # Withhold liveness after this many consecutive failed polls: a pod that
    # cannot poll does no work but would otherwise pass liveness forever.
    poll_failure_liveness_threshold: int | None = 10

    def __post_init__(self) -> None:
        if self.recovery_grace_seconds is None:
            self.recovery_grace_seconds = RECOVERY_GRACE_SECONDS
        if self.lease_ttl_seconds is None:
            self.lease_ttl_seconds = self.recovery_grace_seconds


class BatchConsumerAdapter(Protocol):
    """Sink-specific queue operations the shared engine drives.

    Contract notes:
    - ``fail_run`` MUST NOT raise: the engine calls it from error paths that must
      not crash the consumer. Isolate each internal step (queue write, app-DB
      write, lock release) and swallow-with-capture failures.
    - All other methods may raise; the engine isolates them per group/batch.
    """

    log_prefix: str
    executing_state: str
    succeeded_state: str
    waiting_retry_state: str
    # Whether each group task gets its own dedicated connection. Lease-based
    # adapters set True (lease ownership is token-based, any connection works).
    # Advisory-lock-based adapters set False (lock is session-scoped, must stay
    # on the poll connection that acquired it).
    per_group_connections: bool

    async def fetch_and_lock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int,
        retry_backoff_base_seconds: int,
        owner_token: str,
        lease_ttl_seconds: int,
    ) -> list[PendingBatch]: ...

    async def unlock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[PendingBatch],
        owner_token: str,
    ) -> None: ...

    async def release_all_owned(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
    ) -> None:
        """Release every group this consumer owns. Best-effort cleanup on graceful shutdown."""
        ...

    async def update_status(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int,
        error_response: dict[str, Any] | None = None,
    ) -> None: ...

    async def fail_run(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
        reason: str,
    ) -> None: ...

    async def verify_advisory_lock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
    ) -> bool: ...

    async def renew_lease(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
        lease_ttl_seconds: int,
    ) -> bool: ...

    async def get_stale_executing(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int,
        keep_locks: bool = False,
    ) -> list[PendingBatch]: ...

    async def reconcile_failed_runs(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int,
        lookback_seconds: int,
        limit: int,
    ) -> None: ...

    async def should_process_batch(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> bool: ...

    def is_retryable_error(self, err: Exception) -> bool:
        """Whether a processing error can plausibly succeed on retry — deterministic
        data/config errors fail identically every attempt, so retrying only delays
        the run's terminal state."""
        ...

    async def after_batch_processed(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> None: ...


class BatchConsumer:
    def __init__(
        self,
        config: BatchConsumerConfig,
        process_batch: ProcessBatchFn,
        adapter: BatchConsumerAdapter,
        health_reporter: Callable[[], None] | None = None,
        metrics: ConsumerMetrics | None = None,
    ) -> None:
        self._config = config
        self._process_batch = process_batch
        self._adapter = adapter
        # Per-pod identity for group-lease ownership. A new token each start means
        # a restarted pod cannot accidentally renew a lease it abandoned pre-restart.
        self._owner_token = str(uuid4())
        self._health_reporter = health_reporter
        self._metrics = metrics or DELTA_CONSUMER_METRICS
        self._shutdown = asyncio.Event()
        self._poll_conn: psycopg.AsyncConnection[Any] | None = None
        self._recovery_conn: psycopg.AsyncConnection[Any] | None = None
        self._poll_conn_lock = asyncio.Lock()
        self._recovery_conn_lock = asyncio.Lock()
        self._recovery_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._in_flight: dict[tuple[int, str], asyncio.Task[None]] = {}
        # Monotonic stamp of the last reconcile sweep; runs inside the recovery loop so both share one connection.
        self._last_reconcile_monotonic = 0.0
        # batch_id -> monotonic start, for the stuck-batch watchdog.
        self._inflight_started: dict[str, float] = {}
        self._last_stuck_log_monotonic = 0.0
        # Consecutive failed polls, for the poll-failure liveness trip.
        self._consecutive_poll_failures = 0
        self._last_poll_failure_log_monotonic = 0.0

    @property
    def _lease_ttl_seconds(self) -> int:
        return self._config.lease_ttl_seconds or self._config.recovery_grace_seconds or RECOVERY_GRACE_SECONDS

    def _statement_timeout_ms(self, client_timeout_seconds: float | None) -> int | None:
        """Server-side statement_timeout backstop in milliseconds; None when the
        client ceiling is disabled (same "0 disables" contract)."""
        if not client_timeout_seconds:
            return None
        return int((client_timeout_seconds + self._config.statement_timeout_margin_seconds) * 1000)

    async def _connect(self, *, statement_timeout_seconds: float | None = None) -> psycopg.AsyncConnection[Any]:
        conn = await psycopg.AsyncConnection.connect(
            self._config.database_url,
            autocommit=True,
            connect_timeout=self._config.connect_timeout_seconds,
        )
        # Session-scoped SET, not a libpq startup option: PgBouncer rejects
        # statement_timeout inside the `options` startup parameter.
        timeout_ms = self._statement_timeout_ms(statement_timeout_seconds)
        if timeout_ms is not None:
            try:
                await conn.execute(f"SET statement_timeout = {timeout_ms}")
            except psycopg.Error:
                await conn.close()
                raise
        return conn

    async def _drop_conn(self, attr: str) -> None:
        """Close and forget a connection after a timed-out operation.

        A cancelled psycopg operation can leave the connection mid-protocol;
        re-dialing on the next cycle is cheaper than reasoning about its state.
        """
        conn: psycopg.AsyncConnection[Any] | None = getattr(self, attr)
        setattr(self, attr, None)
        if conn is None:
            return
        try:
            await asyncio.wait_for(conn.close(), timeout=5.0)
        except Exception:
            pass

    async def _ensure_poll_conn(self) -> psycopg.AsyncConnection[Any]:
        """Return the poll connection, reconnecting if a failover/pgbouncer bounce dropped it."""
        if self._poll_conn is not None and not self._poll_conn.closed and not self._poll_conn.broken:
            return self._poll_conn
        async with self._poll_conn_lock:
            if self._poll_conn is None or self._poll_conn.closed or self._poll_conn.broken:
                logger.warning(self._event("queue_db_poll_connection_reconnecting"))
                self._poll_conn = await self._connect(statement_timeout_seconds=self._config.poll_timeout_seconds)
            return self._poll_conn

    async def _ensure_recovery_conn(self) -> psycopg.AsyncConnection[Any]:
        """Return the recovery/reconcile connection, reconnecting so a dropped one can't disable the sweeps forever."""
        if self._recovery_conn is not None and not self._recovery_conn.closed and not self._recovery_conn.broken:
            return self._recovery_conn
        async with self._recovery_conn_lock:
            if self._recovery_conn is None or self._recovery_conn.closed or self._recovery_conn.broken:
                logger.warning(self._event("queue_db_recovery_connection_reconnecting"))
                self._recovery_conn = await self._connect(statement_timeout_seconds=self._config.sweep_timeout_seconds)
            return self._recovery_conn

    async def _wait_or_shutdown(self, timeout: float) -> None:
        try:
            await asyncio.wait_for(self._shutdown.wait(), timeout=timeout)
        except TimeoutError:
            pass

    async def run(self) -> None:
        self._install_signal_handlers()

        self._poll_conn = await self._connect(statement_timeout_seconds=self._config.poll_timeout_seconds)
        self._recovery_conn = await self._connect(statement_timeout_seconds=self._config.sweep_timeout_seconds)

        logger.info(
            self._event("batch_consumer_started"),
            max_concurrency=self._config.max_concurrency,
            poll_interval=self._config.poll_interval_seconds,
            poll_limit=self._config.poll_limit,
            owner_token=self._owner_token,
            per_group_connections=self._adapter.per_group_connections,
        )

        try:
            # Liveness must be reporting before the startup sweep runs: the sweep
            # scans the whole queue and can outlast the health server's startup
            # grace window, and a pod liveness-killed mid-sweep can never boot.
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            await self._recovery_sweep_with_timeout()
            self._recovery_task = asyncio.create_task(self._recovery_loop())

            while not self._shutdown.is_set():
                self._report_health()

                self._reap_finished_tasks()

                # Skip polling while shared-connection groups are in-flight to avoid concurrent _poll_conn access.
                if not self._adapter.per_group_connections and self._in_flight:
                    await self._wait_or_shutdown(self._config.poll_interval_seconds)
                    continue

                available = self._config.max_concurrency - len(self._in_flight)
                if available <= 0:
                    await self._wait_or_shutdown(self._config.poll_interval_seconds)
                    continue

                poll_start = time.monotonic()
                try:
                    conn = await self._ensure_poll_conn()
                    async with asyncio.timeout(self._config.poll_timeout_seconds):
                        batches = await self._fetch_batches(conn, available=available)
                except TimeoutError:
                    # error, not exception: the timeout is the designed recovery
                    # path and its traceback carries no diagnostic value.
                    logger.error(  # noqa: TRY400
                        self._event("poll_timed_out"),
                        timeout_seconds=self._config.poll_timeout_seconds,
                        consecutive_failures=self._consecutive_poll_failures + 1,
                    )
                    self._note_poll_failure("timeout", duration=time.monotonic() - poll_start)
                    await self._drop_conn("_poll_conn")
                    await self._wait_or_shutdown(self._poll_retry_delay())
                    continue
                except psycopg.OperationalError as e:
                    logger.exception(self._event("poll_failed_queue_db_unreachable"))
                    capture_exception(e)
                    self._note_poll_failure("db_unreachable", duration=time.monotonic() - poll_start)
                    await self._wait_or_shutdown(self._poll_retry_delay())
                    continue
                self._consecutive_poll_failures = 0
                poll_duration = time.monotonic() - poll_start
                self._metrics.poll_duration_seconds.observe(poll_duration)
                self._metrics.poll_batches_fetched.observe(len(batches))
                if poll_duration > self._lease_ttl_seconds / 2:
                    # Leases are claimed at query start, so a poll this slow hands
                    # groups over with most of their TTL already burned — the
                    # leading indicator of fetch-expire-refetch churn fleet-wide.
                    logger.warning(
                        self._event("poll_duration_approaching_lease_ttl"),
                        poll_duration_seconds=round(poll_duration, 3),
                        lease_ttl_seconds=self._lease_ttl_seconds,
                    )

                if not batches:
                    await self._wait_or_shutdown(self._config.poll_interval_seconds)
                    continue

                await self._dispatch_groups(conn, batches)

                await self._wait_or_shutdown(self._config.poll_interval_seconds)
        finally:
            await self._close()

    async def _fetch_batches(self, conn: psycopg.AsyncConnection[Any], *, available: int) -> list[PendingBatch]:
        """Claim the next batches to process. ``available`` is the number of free
        group slots; subclasses may use it to bound how many groups they claim."""
        return await self._adapter.fetch_and_lock(
            conn,
            limit=self._fetch_limit(available),
            retry_backoff_base_seconds=self._config.retry_backoff_base_seconds,
            owner_token=self._owner_token,
            lease_ttl_seconds=self._lease_ttl_seconds,
        )

    def _fetch_limit(self, available: int) -> int:
        """Cap the poll fetch so we never lease far more groups than we have free slots to run.

        ``fetch_and_lock`` claims a lease for every group it returns, and a
        leased-but-undispatched group is dark to the whole fleet until its TTL
        expires.
        """
        return min(self._config.poll_limit, available * BATCHES_PER_GROUP_FETCH_FACTOR)

    async def _dispatch_groups(self, conn: psycopg.AsyncConnection[Any], batches: list[PendingBatch]) -> None:
        """Start a group task per fetched group, up to ``max_concurrency``; release the rest.

        Groups the poll leased but we cannot dispatch are unlocked immediately —
        holding their leases would leave them unclaimable fleet-wide until the
        lease TTL expires. Groups already in flight keep their (just renewed) leases.
        """
        groups = _group_by_key(batches)

        logger.debug(
            self._event("poll_returned"),
            batch_count=len(batches),
            group_count=len(groups),
        )

        undispatched: list[PendingBatch] = []
        for key, group_batches in groups.items():
            if key in self._in_flight:
                continue
            if len(self._in_flight) >= self._config.max_concurrency:
                undispatched.extend(group_batches)
                continue
            task = asyncio.create_task(self._process_group_tracked(key, group_batches))
            self._in_flight[key] = task
            self._metrics.active_groups.inc()

        if undispatched:
            logger.info(
                self._event("released_undispatched_groups"),
                batch_count=len(undispatched),
            )
            try:
                await self._adapter.unlock(conn, batches=undispatched, owner_token=self._owner_token)
            except Exception as e:
                logger.exception(self._event("release_undispatched_failed"))
                capture_exception(e)

    def _reap_finished_tasks(self) -> None:
        """Remove completed group tasks from the in-flight registry."""
        finished = [key for key, task in self._in_flight.items() if task.done()]
        for key in finished:
            self._in_flight.pop(key)
            self._metrics.active_groups.dec()

    async def _process_group_tracked(self, key: tuple[int, str], batches: list[PendingBatch]) -> None:
        """Wrapper that ensures the group task never propagates exceptions to the event loop."""
        try:
            await self._process_group(key, batches)
        except Exception as e:
            logger.exception(
                self._event("process_group_unhandled_error"),
                team_id=key[0],
                schema_id=key[1],
            )
            capture_exception(e)

    async def _process_group(self, key: tuple[int, str], batches: list[PendingBatch]) -> None:
        team_id, schema_id = key
        owns_conn = self._adapter.per_group_connections
        group_conn: psycopg.AsyncConnection[Any] | None = None
        try:
            if owns_conn:
                group_conn = await self._connect()
            else:
                group_conn = self._poll_conn
                assert group_conn is not None

            # The lease was claimed when the poll query started; a slow poll can
            # burn most of its TTL before the group task runs. Re-up it here so
            # processing starts with a full window instead of expiring mid-batch
            # and churning the group to another pod.
            renewed = await self._adapter.renew_lease(
                group_conn,
                team_id=team_id,
                schema_id=schema_id,
                owner_token=self._owner_token,
                lease_ttl_seconds=self._lease_ttl_seconds,
            )
            if not renewed:
                logger.warning(
                    self._event("lease_lost_before_dispatch"),
                    team_id=team_id,
                    schema_id=schema_id,
                )
                return

            for batch in batches:
                if self._shutdown.is_set():
                    logger.info(
                        self._event("shutdown_mid_group"),
                        team_id=team_id,
                        schema_id=schema_id,
                        remaining=len(batches) - batches.index(batch),
                    )
                    break
                try:
                    succeeded = await self._process_single(batch, lock_conn=group_conn)
                except OwnershipLostError:
                    logger.warning(
                        self._event("ownership_lost_abandoning_group"),
                        team_id=team_id,
                        schema_id=schema_id,
                    )
                    break
                except Exception as e:
                    logger.exception(
                        self._event("process_single_unhandled_error"),
                        team_id=team_id,
                        external_data_schema_id=schema_id,
                        batch_id=batch.id,
                        batch_index=batch.batch_index,
                    )
                    capture_exception(e)
                    succeeded = False
                if not succeeded:
                    logger.info(
                        self._event("group_halted_by_non_success"),
                        team_id=team_id,
                        schema_id=schema_id,
                        run_uuid=batch.run_uuid,
                        remaining=len(batches) - batches.index(batch) - 1,
                    )
                    break
        finally:
            await self._unlock_group(group_conn, batches, team_id=team_id, schema_id=schema_id)
            if owns_conn and group_conn is not None:
                try:
                    await group_conn.close()
                except Exception:
                    pass

    async def _unlock_group(
        self,
        group_conn: psycopg.AsyncConnection[Any] | None,
        batches: list[PendingBatch],
        *,
        team_id: int,
        schema_id: str,
    ) -> None:
        """Release the group's claim after processing. ``group_conn`` is None when
        opening the per-group connection failed before processing started."""
        if group_conn is None:
            return
        try:
            await self._adapter.unlock(group_conn, batches=batches, owner_token=self._owner_token)
        except Exception as e:
            logger.exception(
                self._event("unlock_for_batches_failed"),
                team_id=team_id,
                external_data_schema_id=schema_id,
            )
            capture_exception(e)

    async def _get_status_conn(self, lock_conn: psycopg.AsyncConnection[Any] | None) -> psycopg.AsyncConnection[Any]:
        """Return the connection to use for status writes, preferring the lock session."""
        if lock_conn is not None:
            if lock_conn.closed or lock_conn.broken:
                raise OwnershipLostError("lock session is dead")
            return lock_conn
        return await self._ensure_poll_conn()

    async def _verify_ownership(self, lock_conn: psycopg.AsyncConnection[Any] | None, batch: PendingBatch) -> None:
        """Raise OwnershipLostError if this consumer no longer holds the group lease."""
        if lock_conn is None:
            return
        try:
            owns = await self._adapter.verify_advisory_lock(
                lock_conn, team_id=batch.team_id, schema_id=batch.schema_id, owner_token=self._owner_token
            )
        except Exception as e:
            raise OwnershipLostError("lease verification query failed") from e
        if not owns:
            raise OwnershipLostError(f"group lease lost for ({batch.team_id}, {batch.schema_id})")

    async def _batch_heartbeat(
        self,
        lock_conn: psycopg.AsyncConnection[Any],
        batch: PendingBatch,
        attempt: int,
    ) -> None:
        """Renew the group lease and re-insert EXECUTING status periodically to prevent premature recovery.

        Renewing the lease and refreshing the executing-status grace window on
        the same cadence keeps the two reclaim signals consistent: a pod that
        stops heartbeating loses its lease and ages out of the grace window at
        the same time. ``renew_lease`` returning False means another pod
        reclaimed the group, so we stop heartbeating immediately.
        """
        interval = max((self._config.recovery_grace_seconds or RECOVERY_GRACE_SECONDS) / 3, 10.0)
        while True:
            await asyncio.sleep(interval)
            try:
                renewed = await self._adapter.renew_lease(
                    lock_conn,
                    team_id=batch.team_id,
                    schema_id=batch.schema_id,
                    owner_token=self._owner_token,
                    lease_ttl_seconds=self._lease_ttl_seconds,
                )
                if not renewed:
                    raise OwnershipLostError(f"group lease lost for ({batch.team_id}, {batch.schema_id})")
                await self._adapter.update_status(
                    lock_conn,
                    batch_id=batch.id,
                    job_state=self._adapter.executing_state,
                    attempt=attempt,
                )
            except Exception:
                return

    async def _process_single(self, batch: PendingBatch, lock_conn: psycopg.AsyncConnection[Any] | None = None) -> bool:
        """Bind per-batch log context, then process. Returns True only on success.

        Binds structlog contextvars so every downstream log line (including loader calls)
        routes to log_entries under the right schema/workflow before any logger fires.
        """
        team_id = str(batch.team_id)
        schema_id = batch.schema_id
        attempt = batch.latest_attempt + 1

        workflow_id = batch.metadata.get("workflow_id") or ""
        workflow_run_id = batch.metadata.get("workflow_run_id") or ""
        workflow_type = "cdc-extraction" if workflow_id.startswith("cdc-extraction-") else "external-data-job"

        bound_keys = (
            "team_id",
            "external_data_schema_id",
            "external_data_source_id",
            "external_data_job_id",
            "run_uuid",
            "batch_id",
            "resource_name",
            "workflow_type",
            "workflow_id",
            "workflow_run_id",
            "log_source_id",
            "attempt",
        )
        structlog.contextvars.bind_contextvars(
            team_id=batch.team_id,
            external_data_schema_id=batch.schema_id,
            external_data_source_id=batch.source_id,
            external_data_job_id=batch.job_id,
            run_uuid=batch.run_uuid,
            batch_id=batch.id,
            resource_name=batch.resource_name,
            workflow_type=workflow_type,
            workflow_id=workflow_id,
            workflow_run_id=workflow_run_id,
            log_source_id=batch.schema_id,
            attempt=attempt,
        )
        self._inflight_started[batch.id] = time.monotonic()
        try:
            await self._verify_ownership(lock_conn, batch)
            return await self._process_single_inner(batch, attempt, team_id, schema_id, lock_conn)
        finally:
            self._inflight_started.pop(batch.id, None)
            structlog.contextvars.unbind_contextvars(*bound_keys)

    async def _process_single_inner(
        self,
        batch: PendingBatch,
        attempt: int,
        team_id: str,
        schema_id: str,
        lock_conn: psycopg.AsyncConnection[Any] | None = None,
    ) -> bool:
        if attempt > self._config.max_attempts:
            logger.error(
                self._event("batch_max_retries_exceeded"),
                batch_id=batch.id,
                run_uuid=batch.run_uuid,
                attempt=attempt,
            )
            await self._fail_run(batch, reason=f"max retries exceeded (attempt {attempt})", conn=lock_conn)
            return False

        status_conn = await self._get_status_conn(lock_conn)

        logger.info(
            self._event("batch_picked_up"),
            batch_id=batch.id,
            run_uuid=batch.run_uuid,
            batch_index=batch.batch_index,
            is_final_batch=batch.is_final_batch,
            attempt=attempt,
            resource_name=batch.resource_name,
        )

        heartbeat_task: asyncio.Task[None] | None = None
        try:
            start = time.monotonic()
            # Before the executing write: adapters may read the batch's latest
            # status here, and our own 'executing' row would mask a terminal
            # status written while the batch waited in this claim.
            should_process = await self._adapter.should_process_batch(status_conn, batch=batch)

            # Pre-increment: if we OOM during processing, recovery sees attempt=N+1
            # and knows this attempt was consumed.
            await self._adapter.update_status(
                status_conn,
                batch_id=batch.id,
                job_state=self._adapter.executing_state,
                attempt=attempt,
            )

            if should_process:
                if lock_conn is not None:
                    heartbeat_task = asyncio.create_task(self._batch_heartbeat(lock_conn, batch, attempt))
                await self._process_batch(batch)

                # Cancel heartbeat before post-processing DB writes to avoid
                # concurrent use of the group connection (psycopg async
                # connections are not safe for concurrent coroutine access).
                if heartbeat_task is not None:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass
                    heartbeat_task = None

                await self._adapter.after_batch_processed(status_conn, batch=batch)

            duration = time.monotonic() - start
            self._metrics.batch_processing_duration_seconds.labels(team_id=team_id, schema_id=schema_id).observe(
                duration
            )

            await self._verify_ownership(lock_conn, batch)
            await self._adapter.update_status(
                status_conn,
                batch_id=batch.id,
                job_state=self._adapter.succeeded_state,
                attempt=attempt,
            )
            self._metrics.batches_processed_total.labels(team_id=team_id, schema_id=schema_id, status="success").inc()
            logger.info(
                self._event("batch_processed_ok"),
                batch_id=batch.id,
                run_uuid=batch.run_uuid,
                batch_index=batch.batch_index,
                is_final_batch=batch.is_final_batch,
                duration_seconds=round(duration, 3),
            )
            return True
        except OwnershipLostError:
            raise
        except Exception as err:
            self._metrics.batches_processed_total.labels(team_id=team_id, schema_id=schema_id, status="error").inc()
            self._metrics.batch_retry_total.labels(attempt=str(attempt), error_type=type(err).__name__).inc()

            await self._handle_batch_failure(batch, attempt, err, lock_conn=lock_conn, status_conn=status_conn)
            return False
        finally:
            if heartbeat_task is not None:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

    async def _handle_batch_failure(
        self,
        batch: PendingBatch,
        attempt: int,
        err: Exception,
        *,
        lock_conn: psycopg.AsyncConnection[Any] | None,
        status_conn: psycopg.AsyncConnection[Any],
    ) -> None:
        """Write the retry/terminal state after a processing error."""
        if not self._adapter.is_retryable_error(err):
            # Deterministic failure: retrying repeats the same outcome. The raw
            # message is the customer-visible latest_error, so keep it unwrapped.
            logger.exception(
                self._event("batch_failed_non_retryable"),
                batch_id=batch.id,
                run_uuid=batch.run_uuid,
                attempt=attempt,
            )
            capture_exception(err)
            await self._fail_run(batch, reason=str(err), conn=lock_conn)
        elif attempt >= self._config.max_attempts:
            logger.exception(
                self._event("batch_failed_no_retries_left"),
                batch_id=batch.id,
                run_uuid=batch.run_uuid,
                attempt=attempt,
            )
            capture_exception(err)
            await self._fail_run(batch, reason=f"max retries exceeded: {err}", conn=lock_conn)
        else:
            logger.warning(
                self._event("batch_failed_will_retry"),
                batch_id=batch.id,
                attempt=attempt,
                error=str(err),
            )
            await self._adapter.update_status(
                status_conn,
                batch_id=batch.id,
                job_state=self._adapter.waiting_retry_state,
                attempt=attempt,
                error_response={"error": str(err)[:1000]},
            )

    async def _fail_run(
        self,
        batch: PendingBatch,
        reason: str,
        conn: psycopg.AsyncConnection[Any] | None = None,
    ) -> None:
        """Fail the run via the adapter; the adapter isolates each step so a failure can't crash the consumer."""
        conn = conn or await self._ensure_poll_conn()

        try:
            await self._adapter.fail_run(conn, batch=batch, reason=reason)
        except Exception as e:
            # Adapters are documented no-raise; this is the engine's backstop so a
            # buggy adapter cannot crash _recovery_sweep or _process_single_inner.
            logger.exception(self._event("adapter_fail_run_raised"), batch_id=batch.id, run_uuid=batch.run_uuid)
            capture_exception(e)
        self._metrics.runs_failed_total.inc()

    async def _recovery_loop(self) -> None:
        while not self._shutdown.is_set():
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=self._config.recovery_interval_seconds)
            except TimeoutError:
                pass

            if self._shutdown.is_set():
                break

            try:
                await self._recovery_sweep_with_timeout()
            except Exception as e:
                logger.exception(self._event("recovery_sweep_error"))
                capture_exception(e)

            now = time.monotonic()
            if now - self._last_reconcile_monotonic >= self._config.reconcile_interval_seconds:
                self._last_reconcile_monotonic = now
                try:
                    async with asyncio.timeout(self._config.sweep_timeout_seconds):
                        await self._reconcile_failed_runs()
                except TimeoutError:
                    logger.error(  # noqa: TRY400 — designed recovery path, traceback is noise
                        self._event("reconcile_sweep_timed_out"),
                        timeout_seconds=self._config.sweep_timeout_seconds,
                    )
                    await self._drop_conn("_recovery_conn")
                except Exception as e:
                    logger.exception(self._event("reconcile_sweep_error"))
                    capture_exception(e)

    async def _recovery_sweep_with_timeout(self) -> None:
        """Run the recovery sweep under the sweep timeout; a sweep that never returns must not stall the consumer."""
        try:
            async with asyncio.timeout(self._config.sweep_timeout_seconds):
                await self._recovery_sweep()
        except TimeoutError:
            logger.error(  # noqa: TRY400 — designed recovery path, traceback is noise
                self._event("recovery_sweep_timed_out"),
                timeout_seconds=self._config.sweep_timeout_seconds,
            )
            await self._drop_conn("_recovery_conn")

    async def _reconcile_failed_runs(self) -> None:
        """Reconcile runs whose queue batch failed but whose terminal-state write never landed."""
        conn = await self._ensure_recovery_conn()

        await self._adapter.reconcile_failed_runs(
            conn,
            grace_seconds=self._config.reconcile_grace_seconds,
            lookback_seconds=self._config.reconcile_lookback_seconds,
            limit=self._config.reconcile_limit,
        )

    def _note_poll_failure(self, reason: str, *, duration: float) -> None:
        """Record a failed poll: the success path never reaches the poll histograms,
        so without this a fleet whose polls all fail looks healthier than a slow one."""
        self._consecutive_poll_failures += 1
        self._metrics.poll_failures_total.labels(reason=reason).inc()
        self._metrics.poll_duration_seconds.observe(duration)

    def _poll_retry_delay(self) -> float:
        """Capped, jittered backoff before retrying a failed poll: a degraded queue DB
        gets exponentially less pressure and the fleet's retries desynchronize."""
        base = self._config.poll_interval_seconds
        failures = max(self._consecutive_poll_failures, 1)
        backoff = min(base * 2 ** (failures - 1), POLL_BACKOFF_MAX_SECONDS)
        return backoff + random.uniform(0, base)

    def _report_health(self) -> None:
        """Report liveness, unless the stuck-batch watchdog or the poll-failure trip fired.

        Withholding the report makes the health server's timeout fail the liveness
        probe, so Kubernetes restarts the pod and the recovery sweep reassigns the
        wedged batch -- a sync thread blocked on a dead sink connection cannot be
        cancelled from the event loop, so a restart is the only real remedy.
        Likewise for polling: a pod whose polls all fail does no work but would
        otherwise report healthy forever.
        """
        if self._health_reporter is None:
            return
        threshold = self._config.poll_failure_liveness_threshold
        if threshold is not None and self._consecutive_poll_failures >= threshold:
            now = time.monotonic()
            if now - self._last_poll_failure_log_monotonic > 60:
                self._last_poll_failure_log_monotonic = now
                logger.error(
                    self._event("poll_failure_liveness_tripped"),
                    consecutive_failures=self._consecutive_poll_failures,
                    threshold=threshold,
                )
            return
        timeout = self._config.stuck_batch_timeout_seconds
        if timeout is not None and self._inflight_started:
            now = time.monotonic()
            oldest_id, oldest_started = min(self._inflight_started.items(), key=lambda kv: kv[1])
            if now - oldest_started > timeout:
                if now - self._last_stuck_log_monotonic > 60:
                    self._last_stuck_log_monotonic = now
                    logger.error(
                        self._event("stuck_batch_watchdog_tripped"),
                        batch_id=oldest_id,
                        running_seconds=round(now - oldest_started, 1),
                        timeout_seconds=timeout,
                    )
                return
        self._health_reporter()

    async def _heartbeat_loop(self) -> None:
        """Report liveness on a fixed cadence, independent of batch processing.

        A poll cycle can run far longer than the health timeout (e.g. large final-batch
        compaction), so the main loop's per-poll health report is not enough on its own.
        """
        while not self._shutdown.is_set():
            self._report_health()
            try:
                await asyncio.wait_for(self._shutdown.wait(), timeout=self._config.heartbeat_interval_seconds)
            except TimeoutError:
                pass

    async def _recovery_sweep(self) -> None:
        conn = await self._ensure_recovery_conn()

        grace_seconds = self._config.recovery_grace_seconds
        assert grace_seconds is not None
        # keep_locks lets advisory-lock sinks (duckgres) hold their probe locks
        # through the re-queue so a concurrent consumer can't pick a batch up
        # mid-recovery. The lease sink ignores it: get_stale_executing already
        # excludes any group with a live lease, and the finally-unlock below is a
        # no-op for leases this pod doesn't own.
        stale = await self._adapter.get_stale_executing(conn, grace_seconds=grace_seconds, keep_locks=True)
        if not stale:
            self._metrics.recovery_sweeps_total.labels(outcome="clean").inc()
            return

        self._metrics.recovery_sweeps_total.labels(outcome="orphans_found").inc()
        logger.info(self._event("recovery_sweep_found_stale_batches"), count=len(stale))

        recovery_bound_keys = (
            "team_id",
            "external_data_schema_id",
            "external_data_source_id",
            "external_data_job_id",
            "run_uuid",
            "batch_id",
            "resource_name",
            "log_source_id",
            "attempt",
        )
        try:
            for batch in stale:
                structlog.contextvars.bind_contextvars(
                    team_id=batch.team_id,
                    external_data_schema_id=batch.schema_id,
                    external_data_source_id=batch.source_id,
                    external_data_job_id=batch.job_id,
                    run_uuid=batch.run_uuid,
                    batch_id=batch.id,
                    resource_name=batch.resource_name,
                    log_source_id=batch.schema_id,
                    attempt=batch.latest_attempt,
                )
                try:
                    if batch.latest_attempt >= self._config.max_attempts:
                        logger.warning(
                            self._event("batch_recovered_max_retries_exceeded"), attempt=batch.latest_attempt
                        )
                        await self._fail_run(batch, reason="max retries exceeded (likely OOM)", conn=conn)
                    else:
                        logger.warning(self._event("batch_recovered_for_retry"), attempt=batch.latest_attempt)
                        await self._adapter.update_status(
                            conn,
                            batch_id=batch.id,
                            job_state=self._adapter.waiting_retry_state,
                            attempt=batch.latest_attempt,
                            error_response={"error": "executing timed out - pod restart or OOM"},
                        )
                finally:
                    structlog.contextvars.unbind_contextvars(*recovery_bound_keys)
        finally:
            # Release probe locks held by keep_locks=True (advisory sinks). For the
            # lease sink this only deletes leases this pod owns, so it's a no-op for
            # the abandoned groups recovered above.
            try:
                await self._adapter.unlock(conn, batches=stale, owner_token=self._owner_token)
            except Exception:
                logger.exception(self._event("recovery_sweep_unlock_failed"))

    def _install_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown.set)

    async def _close(self) -> None:
        self._shutdown.set()

        for task in (self._recovery_task, self._heartbeat_task):
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Drain in-flight group tasks; each task releases its own lease and closes its connection.
        if self._in_flight:
            logger.info(self._event("draining_in_flight_groups"), count=len(self._in_flight))
            tasks = list(self._in_flight.values())
            done, pending = await asyncio.wait(tasks, timeout=SHUTDOWN_DRAIN_TIMEOUT_SECONDS)
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.wait(pending, timeout=5.0)
            self._metrics.active_groups.dec(len(self._in_flight))
            self._in_flight.clear()

        if self._recovery_conn is not None and not self._recovery_conn.closed:
            await self._recovery_conn.close()

        # Release every group we own so a surviving pod can reclaim it immediately
        # instead of waiting out the lease TTL. Best-effort: if the connection is
        # broken (or this is a SIGKILL we never reach), the lease just expires.
        if self._poll_conn is not None and not self._poll_conn.closed and not self._poll_conn.broken:
            try:
                await self._adapter.release_all_owned(self._poll_conn, owner_token=self._owner_token)
            except Exception as e:
                logger.exception(self._event("release_all_owned_failed_on_shutdown"))
                capture_exception(e)
        if self._poll_conn is not None and not self._poll_conn.closed:
            await self._poll_conn.close()

        logger.info(self._event("batch_consumer_stopped"))

    def _event(self, name: str) -> str:
        if not self._adapter.log_prefix:
            return name
        return f"{self._adapter.log_prefix}_{name}"


ProcessBatchFn = Callable[[PendingBatch], Coroutine[Any, Any, None]]


def _group_by_key(batches: list[PendingBatch]) -> dict[tuple[int, str], list[PendingBatch]]:
    groups: dict[tuple[int, str], list[PendingBatch]] = defaultdict(list)
    for batch in batches:
        groups[(batch.team_id, batch.schema_id)].append(batch)
    return groups
