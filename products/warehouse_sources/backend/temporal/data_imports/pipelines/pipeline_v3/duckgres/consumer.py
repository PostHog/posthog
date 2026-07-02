from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import psycopg
import structlog
from asgiref.sync import sync_to_async
from prometheus_client import Gauge

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.batch_consumer import (
    MAX_ATTEMPTS,
    POLL_INTERVAL_SECONDS,
    RECOVERY_INTERVAL_SECONDS,
    BatchConsumer as SharedBatchConsumer,
    BatchConsumerConfig,
    OwnershipLostError,
    ProcessBatchFn,
    _group_by_key,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.backfill import (
    blocked_schema_ids as compute_blocked_schema_ids,
    run_backfill_planner,
    sink_eligible_schema_ids as compute_eligible_schema_ids,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.enablement import (
    duckgres_sink_team_ids,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.jobs_db import (
    DuckgresBatchQueue,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    LEASE_TTL_SECONDS,
    PendingBatch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.metrics import (
    make_consumer_metrics,
)
from products.warehouse_sources_queue.backend.models import SourceBatchDuckgresStatus

logger = structlog.get_logger(__name__)

DuckgresConsumerConfig = BatchConsumerConfig

# How often the fetch path refreshes the enabled-team set and runs the
# supersede sweep + backlog gauges (the poll loop itself runs every ~2s).
ENABLEMENT_REFRESH_SECONDS = 60.0
MAINTENANCE_INTERVAL_SECONDS = 30.0

SINK_ELIGIBLE_BACKLOG = Gauge(
    "duckgres_sink_eligible_backlog",
    "Delta-succeeded data batches not yet applied to Duckgres (non-failed runs)",
    multiprocess_mode="livemax",
)
SINK_OLDEST_ELIGIBLE_AGE_SECONDS = Gauge(
    "duckgres_sink_oldest_eligible_age_seconds",
    "Age of the oldest delta-succeeded batch the Duckgres sink has not applied. "
    "Queue retention permanently drops batches after RETENTION_DAYS — alert well before that.",
    multiprocess_mode="livemax",
)
SINK_BLOCKED_BACKLOG = Gauge(
    "duckgres_sink_blocked_backlog",
    "Delta-succeeded batches held back because their schema is not yet primed (backfill pending/in-flight)",
    multiprocess_mode="livemax",
)
SINK_BLOCKED_OLDEST_AGE_SECONDS = Gauge(
    "duckgres_sink_blocked_oldest_age_seconds",
    "Age of the oldest blocked batch — approaching queue retention means the post-backfill handoff will gap",
    multiprocess_mode="livemax",
)
SINK_SUPERSEDED_BATCHES_TOTAL = Gauge(
    "duckgres_sink_superseded_batches",
    "Batches retired because a newer replace-run made their work obsolete (last sweep)",
    multiprocess_mode="livemax",
)


class DuckgresBatchConsumerAdapter:
    log_prefix: str = "duckgres"
    executing_state: str = SourceBatchDuckgresStatus.State.EXECUTING.value
    succeeded_state: str = SourceBatchDuckgresStatus.State.SUCCEEDED.value
    waiting_retry_state: str = SourceBatchDuckgresStatus.State.WAITING_RETRY.value
    # Lease ownership is token-based (sourceduckgresgrouplease), so any connection
    # works per group — the poll loop keeps claiming new groups while others are
    # in flight instead of barriering on the slowest batch of each poll cycle.
    per_group_connections: bool = True

    def __init__(self, lease_ttl_seconds: int = LEASE_TTL_SECONDS) -> None:
        # TTL used when verify_advisory_lock extends the lease at batch
        # boundaries; the consumer passes its configured group-lease TTL.
        self._lease_ttl_seconds = lease_ttl_seconds
        self._team_ids: list[int] | None = None
        self._team_ids_fetched_at: float | None = None
        self._last_maintenance_at = 0.0
        # None = not yet computed; the fetch claims nothing until the first
        # successful planner pass so unprimed schemas can't sneak live batches in.
        self._blocked_schema_ids: list[str] | None = None
        # Allow-list of v3-enabled schema ids (prod only). None = not yet computed
        # (fetch claims nothing) in prod; stays None in dev where team_ids is None
        # and the sink is intentionally ungated.
        self._eligible_schema_ids: list[str] | None = None

    async def _enabled_team_ids(self) -> list[int] | None:
        """Cached duckgres-enabled team set; keeps the previous set on app-DB errors."""
        now = time.monotonic()
        if self._team_ids_fetched_at is not None and now - self._team_ids_fetched_at < ENABLEMENT_REFRESH_SECONDS:
            return self._team_ids
        try:
            first_resolution = self._team_ids_fetched_at is None
            previous = self._team_ids
            self._team_ids = await sync_to_async(duckgres_sink_team_ids, thread_sensitive=False)()
            self._team_ids_fetched_at = now
            if first_resolution or self._team_ids != previous:
                # Only on the first resolution or an actual change — the refresh
                # itself runs every ~60s and would otherwise spam.
                logger.info(
                    "duckgres_sink_enabled_teams_resolved",
                    first_resolution=first_resolution,
                    team_count=None if self._team_ids is None else len(self._team_ids),
                )
        except Exception as e:
            logger.exception("duckgres_sink_enablement_refresh_failed")
            capture_exception(e)
            if self._team_ids_fetched_at is None:
                # Never had a set: claim nothing rather than everything.
                self._team_ids = []
                self._team_ids_fetched_at = now
        return self._team_ids

    async def _run_maintenance(self, conn: psycopg.AsyncConnection[Any], team_ids: list[int] | None) -> None:
        """Supersede obsolete runs and refresh the sink lag gauges (every ~30s)."""
        now = time.monotonic()
        if now - self._last_maintenance_at < MAINTENANCE_INTERVAL_SECONDS:
            return
        self._last_maintenance_at = now

        superseded = await DuckgresBatchQueue.supersede_replaced_runs(conn, team_ids=team_ids)
        SINK_SUPERSEDED_BATCHES_TOTAL.set(superseded)
        if superseded:
            logger.info("duckgres_superseded_obsolete_batches", count=superseded)

        backlog, oldest_age, blocked, blocked_age = await DuckgresBatchQueue.get_backlog_stats(
            conn,
            team_ids=team_ids,
            blocked_schema_ids=self._blocked_schema_ids,
            eligible_schema_ids=self._eligible_schema_ids,
        )
        SINK_ELIGIBLE_BACKLOG.set(backlog)
        SINK_OLDEST_ELIGIBLE_AGE_SECONDS.set(oldest_age or 0.0)
        SINK_BLOCKED_BACKLOG.set(blocked)
        SINK_BLOCKED_OLDEST_AGE_SECONDS.set(blocked_age or 0.0)

        block_list_was_unset = self._blocked_schema_ids is None
        try:
            # Backfill planner: bootstrap/plan/reconcile schema priming, then
            # refresh the live-batch block list it derives from.
            await sync_to_async(run_backfill_planner, thread_sensitive=False)(team_ids)
            self._blocked_schema_ids = await sync_to_async(compute_blocked_schema_ids, thread_sensitive=False)(team_ids)
            # v3 allow-list: prod only. In dev (team_ids None) the sink stays
            # ungated, matching the team filter. Kept in the planner try so a
            # transient app-DB/flag blip leaves the previous allow-list intact.
            if team_ids is not None:
                self._eligible_schema_ids = await sync_to_async(compute_eligible_schema_ids, thread_sensitive=False)(
                    team_ids
                )
            if block_list_was_unset:
                # First successful planner pass: the sink can now claim live
                # batches (fetch returns [] until this happens).
                logger.info(
                    "duckgres_backfill_block_list_ready",
                    blocked_schema_count=len(self._blocked_schema_ids),
                )
        except Exception as e:
            # An app-DB blip must not crash the poll loop; keep the previous
            # block list (or keep claiming nothing if we never had one).
            logger.exception("duckgres_backfill_planner_failed")
            capture_exception(e)

        # Heartbeat: confirms the ~30s maintenance pass (enablement set, supersede
        # sweep, planner) actually ran. Bounded to one line per maintenance tick.
        logger.info(
            "duckgres_maintenance_ran",
            team_count=None if team_ids is None else len(team_ids),
            eligible_backlog=backlog,
            blocked_backlog=blocked,
            blocked_schema_count=None if self._blocked_schema_ids is None else len(self._blocked_schema_ids),
            eligible_schema_count=None if self._eligible_schema_ids is None else len(self._eligible_schema_ids),
        )

    async def fetch_and_lock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int,
        retry_backoff_base_seconds: int,
        owner_token: str,
        lease_ttl_seconds: int,
        max_groups: int | None = None,
        exclude_groups: list[tuple[int, str]] | None = None,
    ) -> list[PendingBatch]:
        team_ids = await self._enabled_team_ids()
        if team_ids is not None and not team_ids:
            return []

        await self._run_maintenance(conn, team_ids)

        if self._blocked_schema_ids is None:
            # Planner has not succeeded yet: claiming live batches now could
            # write partial history for unprimed schemas. Wait for it.
            return []

        if team_ids is not None and self._eligible_schema_ids is None:
            # Prod: the v3 allow-list has not been computed yet. Claim nothing
            # rather than risk applying batches for non-v3 source types. (Dev,
            # team_ids None, is intentionally ungated.)
            return []

        return await DuckgresBatchQueue.get_delta_succeeded_and_lock(
            conn,
            owner_token=owner_token,
            limit=limit,
            retry_backoff_base_seconds=retry_backoff_base_seconds,
            team_ids=team_ids,
            blocked_schema_ids=self._blocked_schema_ids,
            eligible_schema_ids=self._eligible_schema_ids,
            lease_ttl_seconds=lease_ttl_seconds,
            max_groups=max_groups,
            exclude_groups=exclude_groups,
        )

    async def unlock(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[PendingBatch],
        owner_token: str,
    ) -> None:
        await DuckgresBatchQueue.unlock_for_batches(conn, batches=batches, owner_token=owner_token)

    async def release_all_owned(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
    ) -> None:
        await DuckgresBatchQueue.release_all_owned_leases(conn, owner_token=owner_token)

    async def update_status(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int,
        error_response: dict[str, Any] | None = None,
    ) -> None:
        # Invariant: the sink never writes ANY status over a terminal 'failed'.
        # A supersede/replan/fail_run can retire the batch at any point in its
        # lifecycle — before the executing write, or mid-processing (replan and
        # fail_run target executing batches too) — and statuses are latest-row-
        # wins, so an unconditional executing/succeeded/waiting_retry write
        # would mask the terminal state and un-retire the run. A blocked insert
        # means the batch was retired out from under this claim: abort the
        # group without writing (see update_status_unless_failed for the
        # accepted residual race).
        inserted = await DuckgresBatchQueue.update_status_unless_failed(
            conn,
            batch_id=batch_id,
            job_state=job_state,
            attempt=attempt,
            error_response=error_response,
        )
        if not inserted:
            raise OwnershipLostError(f"batch {batch_id} was terminally retired while claimed")

    async def fail_run(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
        reason: str,
    ) -> None:
        # Contract: fail_run must not raise (see BatchConsumerAdapter docstring).
        try:
            await DuckgresBatchQueue.fail_run(conn, run_uuid=batch.run_uuid, reason=reason)
        except Exception as e:
            logger.exception(
                "duckgres_fail_run_queue_update_failed",
                batch_id=batch.id,
                run_uuid=batch.run_uuid,
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
        # Verify-and-extend: the engine checks ownership at every batch boundary,
        # and a group can hold a whole backfill run of quick chunks whose in-batch
        # heartbeats never fire (each chunk finishes before the heartbeat's first
        # sleep elapses). Without renewing here, a group running longer than the
        # lease TTL would lose ownership mid-run and be reclaimed while actively
        # processing. Renewal returns False exactly when the lease was lost, so
        # it is a strict superset of a read-only verify.
        return await DuckgresBatchQueue.renew_lease(
            conn,
            team_id=team_id,
            schema_id=schema_id,
            owner_token=owner_token,
            lease_ttl_seconds=self._lease_ttl_seconds,
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
        return await DuckgresBatchQueue.renew_lease(
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
        # keep_locks is meaningless for a lease sink: get_stale_executing holds
        # nothing, and the lease LEFT JOIN already excludes live groups. The
        # DuckgresBatchConsumer overrides _recovery_sweep, so the base engine's
        # keep-then-unlock recovery flow never runs for this adapter.
        return await DuckgresBatchQueue.get_stale_executing(conn, grace_seconds=grace_seconds)

    async def reconcile_failed_runs(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int,
        lookback_seconds: int,
        limit: int,
    ) -> None:
        # The Duckgres sink owns no ExternalDataJob lifecycle: a failed Duckgres run
        # must not mark the import job failed (Delta already succeeded), so there is
        # nothing to reconcile here.
        return None

    async def should_process_batch(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> bool:
        # A co-claimed batch can be terminally retired while it waits in this
        # group's claim (superseded by a newer replace run, or a backfill
        # replan): applying it anyway could swap stale backfill data over a
        # table the replace run has since rebuilt. Abort the WHOLE group with
        # no status write — the 'failed' status must stand, and any successor
        # in this claim is retired too (skipping just this batch would let the
        # swap proceed).
        if await DuckgresBatchQueue.is_failed(conn, batch_id=batch.id):
            raise OwnershipLostError(f"batch {batch.id} was terminally retired while claimed")
        already_applied = await DuckgresBatchQueue.has_applied(conn, batch=batch)
        if batch.is_final_batch:
            if not already_applied:
                raise RuntimeError(f"Final Duckgres marker received before batch {batch.batch_index} was applied")
            return False
        return not already_applied

    async def after_batch_processed(
        self,
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> None:
        if not batch.is_final_batch:
            await DuckgresBatchQueue.mark_applied(conn, batch=batch)


class DuckgresBatchConsumer(SharedBatchConsumer):
    """Duckgres batch consumer: the shared engine plus the sink's lease-safety
    behaviors, kept out of the base engine so the delta consumer is unaffected.

    Overrides:
    - _fetch_batches: caps leased groups to free slots and excludes in-flight
      groups, so a saturated pod never pins groups it cannot start.
    - _unlock_group: releases leases via the poll connection when the group
      connection failed to open (a claimed-but-unstarted group would otherwise
      be renewed by every poll and block other pods indefinitely).
    - _handle_batch_failure: fences error-path status writes on ownership — a
      worker that outlived its lease must not stamp retry/terminal states over
      the new owner's lifecycle.
    - _recovery_sweep: fenced requeue/terminal-failure (write-time re-check of
      state, staleness age, and lease absence) and no post-sweep lease release
      (an owner-scoped delete could strip a lease the poll loop just claimed).
    """

    def __init__(
        self,
        config: DuckgresConsumerConfig,
        process_batch: ProcessBatchFn,
        health_reporter: Callable[[], None] | None = None,
    ) -> None:
        # __post_init__ resolves lease_ttl_seconds (defaults to recovery grace),
        # so the adapter's boundary renewals use the same TTL as the claim.
        adapter = DuckgresBatchConsumerAdapter(lease_ttl_seconds=config.lease_ttl_seconds or LEASE_TTL_SECONDS)
        super().__init__(
            config=config,
            process_batch=process_batch,
            adapter=adapter,
            health_reporter=health_reporter,
            metrics=make_consumer_metrics("duckgres"),
        )
        self._duckgres_adapter = adapter

    async def _fetch_batches(self, conn: psycopg.AsyncConnection[Any], *, available: int) -> list[PendingBatch]:
        return await self._duckgres_adapter.fetch_and_lock(
            conn,
            # Full poll_limit, NOT the base engine's _fetch_limit batch-count
            # heuristic: a single backfill run legitimately co-claims many
            # chunks into one group, and max_groups below already bounds the
            # over-claim by GROUPS — the precise unit a lease covers.
            limit=self._config.poll_limit,
            retry_backoff_base_seconds=self._config.retry_backoff_base_seconds,
            owner_token=self._owner_token,
            lease_ttl_seconds=self._lease_ttl_seconds,
            # Never lease more groups than we have slots to start: an unstarted
            # group's lease would be renewed by every subsequent poll and block
            # other pods from it for as long as this pod stays saturated.
            max_groups=available,
            # In-flight groups can't be started again; without the exclusion
            # their momentarily-eligible batches re-consume the claim budget
            # and starve other schemas.
            exclude_groups=list(self._in_flight),
        )

    async def _unlock_group(
        self,
        group_conn: psycopg.AsyncConnection[Any] | None,
        batches: list[PendingBatch],
        *,
        team_id: int,
        schema_id: str,
    ) -> None:
        if group_conn is None:
            # The group connection never materialized (queue-DB blip, pool
            # exhaustion) but the leases were already claimed at fetch time.
            # Release them via the poll connection — lease release is
            # token-scoped, any connection works — or this pod pins the groups
            # (every poll renews its own leases) until it can connect again.
            try:
                fallback_conn = await self._ensure_poll_conn()
            except Exception:
                return  # queue DB fully unreachable; lease TTL is the backstop
            try:
                await self._duckgres_adapter.unlock(fallback_conn, batches=batches, owner_token=self._owner_token)
            except Exception as e:
                logger.exception(
                    self._event("unlock_for_batches_failed"),
                    team_id=team_id,
                    external_data_schema_id=schema_id,
                )
                capture_exception(e)
            return
        await super()._unlock_group(group_conn, batches, team_id=team_id, schema_id=schema_id)

    async def _handle_batch_failure(
        self,
        batch: PendingBatch,
        attempt: int,
        err: Exception,
        *,
        lock_conn: psycopg.AsyncConnection[Any] | None,
        status_conn: psycopg.AsyncConnection[Any],
    ) -> None:
        # Fence the error-path writes on ownership: a worker can outlive its
        # lease (expiry mid-batch, group reclaimed), and a stale writer must
        # not stamp waiting_retry over the new owner's lifecycle — or fail the
        # whole run out from under the pod now processing it. Raising abandons
        # the group with no status write; the new owner drives the batch.
        try:
            await self._verify_ownership(lock_conn, batch)
        except OwnershipLostError:
            logger.warning(
                self._event("ownership_lost_suppressing_error_status"),
                batch_id=batch.id,
                run_uuid=batch.run_uuid,
                error=str(err)[:500],
            )
            raise
        await super()._handle_batch_failure(batch, attempt, err, lock_conn=lock_conn, status_conn=status_conn)

    async def _recovery_sweep(self) -> None:
        conn = await self._ensure_recovery_conn()

        grace_seconds = self._config.recovery_grace_seconds
        assert grace_seconds is not None
        # get_stale_executing already excludes any group with a live lease and
        # holds nothing itself, so — unlike the base sweep — no claims are
        # released afterwards: this pod's poll loop can reclaim a just-requeued
        # group (same owner token) while the sweep is still running, and an
        # owner-scoped delete here would strip that fresh lease mid-flight.
        stale = await self._duckgres_adapter.get_stale_executing(conn, grace_seconds=grace_seconds)
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
                # Both writes are fenced inside the insert itself (still
                # 'executing', still older than grace, no live lease), so a
                # batch retired, reclaimed, or freshly heartbeated between the
                # unlocked stale scan and the write is skipped, never clobbered.
                if batch.latest_attempt >= self._config.max_attempts:
                    failed = await DuckgresBatchQueue.fail_run_if_stale(
                        conn, batch=batch, reason="max retries exceeded (likely OOM)", grace_seconds=grace_seconds
                    )
                    if failed:
                        logger.warning(
                            self._event("batch_recovered_max_retries_exceeded"), attempt=batch.latest_attempt
                        )
                        self._metrics.runs_failed_total.inc()
                    else:
                        logger.info(self._event("batch_recovery_skipped_not_stale"), batch_id=batch.id)
                else:
                    requeued = await DuckgresBatchQueue.requeue_stale_executing(
                        conn,
                        batch=batch,
                        error_response={"error": "executing timed out - pod restart or OOM"},
                        grace_seconds=grace_seconds,
                    )
                    if requeued:
                        logger.warning(self._event("batch_recovered_for_retry"), attempt=batch.latest_attempt)
                    else:
                        logger.info(self._event("batch_recovery_skipped_not_stale"), batch_id=batch.id)
            finally:
                structlog.contextvars.unbind_contextvars(*recovery_bound_keys)


__all__ = [
    "DuckgresBatchConsumer",
    "DuckgresBatchConsumerAdapter",
    "DuckgresConsumerConfig",
    "MAX_ATTEMPTS",
    "POLL_INTERVAL_SECONDS",
    "RECOVERY_INTERVAL_SECONDS",
    "_group_by_key",
]
