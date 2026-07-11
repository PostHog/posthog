"""
Postgres-based job queue for warehouse source batch processing.

Replaces the Kafka topic `warehouse_sources_jobs` with direct Postgres inserts
and lease-based coordination. All SQL is isolated here so that the producer
(Temporal activity) and consumer share a single interface to the queue.

Group ownership uses a row-based lease (`sourcegrouplease`) keyed by
(team_id, schema_id): claimed via a conditional upsert, renewed by the
consumer heartbeat, and reclaimable by any pod once it expires. This replaces
the old session-scoped Postgres advisory lock, whose ownership was tied to a
live server session and so could be orphaned indefinitely on SIGKILL, pgbouncer
session lingering, or node loss — wedging the whole loader fleet.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

BATCH_TABLE = "sourcebatch"
STATUS_TABLE = "sourcebatchstatus"
STATUS_VIEW = "v_latest_source_batch_status"
LEASE_TABLE = "sourcegrouplease"

# Default group-lease validity window, in seconds. The consumer renews the
# lease on its heartbeat (~every grace/3); a group whose owner stops renewing
# becomes reclaimable once this window elapses. Coordinated with the consumer's
# recovery_grace_seconds so lease reclamation and the executing-status recovery
# sweep fire together.
LEASE_TTL_SECONDS = 300

# Partition pruning hint: only scan partitions within this window.
# Set to 2x the retention period so the planner can skip dropped
# partitions. Not a correctness filter — older partitions are already
# gone by the time this matters.
PARTITION_PRUNING_INTERVAL = "14 days"

# Quiet time (no batch inserts or status writes) before lock takeover treats a run as
# abandoned. Must exceed worst-case loader backlog latency — an unclaimed backlog is still live.
TAKEOVER_STALE_THRESHOLD_SECONDS = 6 * 60 * 60

# Lookback for the queue-freshness probe. Bounds both the probe's cost and the
# reported age: an unclaimed batch older than this saturates the gauge at the
# window, which is already far past any sane alert threshold.
FRESHNESS_WINDOW_SECONDS = 48 * 60 * 60
FRESHNESS_WINDOW = f"{FRESHNESS_WINDOW_SECONDS} seconds"


def pending_batch_select_columns(status_alias: str) -> str:
    return f"""
        b.id, b.team_id, b.schema_id, b.source_id, b.job_id,
        b.run_uuid, b.batch_index, b.s3_path, b.row_count, b.byte_size,
        b.is_final_batch, b.total_batches, b.total_rows, b.sync_type,
        b.cumulative_row_count, b.resource_name, b.is_resume,
        b.is_first_ever_sync, b.metadata,
        COALESCE({status_alias}.attempt, 0) AS latest_attempt,
        b.created_at
    """


def latest_status_lateral(batch_alias: str, status_alias: str, *, join: str = "LEFT") -> str:
    """Per-batch latest-status lookup, driven by the (batch_id, created_at DESC, id DESC) index.

    Replaces joins against the ``DISTINCT ON`` latest-status view: the view has
    to reduce the *entire* status table before the planner can join it, so its
    cost grows with total queue history no matter how few batches the outer
    query touches — under backlog that made every poll and sweep degrade
    together. A lateral LIMIT 1 probe costs one index descent per outer batch
    instead.

    ``join="LEFT"`` keeps outer batches with no status row (``status_alias``
    columns come back NULL); ``join="INNER"`` drops them.
    """
    join_kw = "LEFT JOIN" if join == "LEFT" else "JOIN"
    return f"""
        {join_kw} LATERAL (
            SELECT id, batch_id, job_state, attempt, exec_time, error_response, created_at
            FROM {STATUS_TABLE}
            WHERE batch_id = {batch_alias}.id
              AND created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
            ORDER BY created_at DESC, id DESC
            LIMIT 1
        ) {status_alias} ON true
    """


def pending_batch_predicate(status_alias: str) -> str:
    """A batch is pending (still actionable) when it has no status row yet or its latest state is non-terminal."""
    return f"({status_alias}.batch_id IS NULL OR {status_alias}.job_state IN ('waiting', 'waiting_retry', 'executing'))"


def build_status_dual_write_sql(*, with_batch_created_at: bool) -> str:
    """Single-statement status INSERT + denormalized-state UPDATE (atomic under autocommit).

    The UPDATE guards: exact ``created_at`` match prunes to one partition when the
    caller knows it (PendingBatch always does; the window fallback keeps ad-hoc
    callers bounded); the ``IS DISTINCT FROM`` check makes heartbeat re-inserts a
    0-row no-op so they never churn the batch heap; the monotonic
    ``state_changed_at`` check makes cross-connection races converge to the status
    row with the greatest ``created_at`` — the same answer the latest-status
    lateral gives.
    """
    created_at_predicate = (
        "b.created_at = %(batch_created_at)s"
        if with_batch_created_at
        else f"b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'"
    )
    return f"""
        WITH ins AS (
            INSERT INTO {STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            VALUES (%(batch_id)s, %(job_state)s, %(attempt)s, now(), %(error_response)s, now())
            RETURNING batch_id, job_state, attempt, created_at
        )
        UPDATE {BATCH_TABLE} b
        SET latest_state = ins.job_state, latest_attempt = ins.attempt, state_changed_at = ins.created_at
        FROM ins
        WHERE b.id = ins.batch_id
          AND {created_at_predicate}
          AND ((b.latest_state, b.latest_attempt) IS DISTINCT FROM (ins.job_state, ins.attempt)
               OR b.state_changed_at IS NULL)
          AND (b.state_changed_at IS NULL OR b.state_changed_at <= ins.created_at)
    """


def _bulk_fail_dual_write_sql(where_sql: str) -> str:
    """Bulk 'failed' status inserts plus the denormalized-state UPDATE, one statement.

    ``targets`` carries ``(id, created_at)`` so the UPDATE join prunes partitions
    exactly; rowcount reports updated batches (== inserted statuses, minus any a
    concurrent newer write already superseded via the monotonic guard).
    """
    return f"""
        WITH targets AS (
            SELECT b.id, b.created_at
            FROM {BATCH_TABLE} b
            {latest_status_lateral("b", "s")}
            WHERE
                b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                AND {where_sql}
                AND {pending_batch_predicate("s")}
        ),
        ins AS (
            INSERT INTO {STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            SELECT t.id, 'failed', 0, now(), %(error_response)s, now()
            FROM targets t
            RETURNING batch_id, created_at
        )
        UPDATE {BATCH_TABLE} b
        SET latest_state = 'failed', latest_attempt = 0, state_changed_at = ins.created_at
        FROM ins
        JOIN targets t ON t.id = ins.batch_id
        WHERE b.id = t.id
          AND b.created_at = t.created_at
          AND (b.state_changed_at IS NULL OR b.state_changed_at <= ins.created_at)
    """


# Shared between the async consumer path and the sync ops command so both agree
# on what counts as a pending (fail-able) batch.
FAIL_RUN_SQL = _bulk_fail_dual_write_sql("b.run_uuid = %(run_uuid)s")


def _state_claim_candidates_sql() -> str:
    """Claimable-batch candidates read from the denormalized state columns.

    The claimable scan and every NOT EXISTS gate are answered by the partial
    indexes (sb_claimable_idx, sb_run_gate_idx, sb_schema_busy_idx), so the
    work tracks the claimable set instead of everything retained. 'pending'
    means no status row yet; 'waiting' is deliberately not claimable.
    """
    return f"""
        SELECT
            b.id, b.team_id, b.schema_id, b.source_id, b.job_id,
            b.run_uuid, b.batch_index, b.s3_path, b.row_count, b.byte_size,
            b.is_final_batch, b.total_batches, b.total_rows, b.sync_type,
            b.cumulative_row_count, b.resource_name, b.is_resume,
            b.is_first_ever_sync, b.metadata,
            b.latest_attempt,
            b.created_at
        FROM {BATCH_TABLE} b
        WHERE
            b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
            AND (
                b.latest_state = 'pending'
                OR (
                    b.latest_state = 'waiting_retry'
                    AND b.state_changed_at <= now() - make_interval(
                        secs => %(backoff)s * GREATEST(b.latest_attempt, 1)
                    )
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM {BATCH_TABLE} b_prev
                WHERE b_prev.run_uuid = b.run_uuid
                    AND b_prev.batch_index < b.batch_index
                    AND b_prev.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND (
                        b_prev.latest_state = 'executing'
                        OR (
                            b_prev.latest_state = 'waiting_retry'
                            AND b_prev.state_changed_at > now() - make_interval(
                                secs => %(backoff)s * GREATEST(b_prev.latest_attempt, 1)
                            )
                        )
                    )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM {BATCH_TABLE} b2
                WHERE b2.run_uuid = b.run_uuid
                    AND b2.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND b2.latest_state = 'failed'
            )
            AND NOT EXISTS (
                SELECT 1
                FROM {BATCH_TABLE} b_busy
                WHERE b_busy.team_id = b.team_id
                    AND b_busy.schema_id = b.schema_id
                    AND b_busy.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND b_busy.latest_state = 'executing'
            )
    """


def _stale_executing_sql(scope_sql: str = "") -> str:
    """Shared body of the stale-executing sweep (async consumer and its sync ops twin).

    The denormalized-column pre-filter keeps the lateral probing only
    currently-executing batches. The lateral itself must stay: heartbeats
    refresh the status log, deliberately not the column, so the grace clock
    comes from ``s.created_at``.
    """
    return f"""
        SELECT
            {pending_batch_select_columns("s")}
        FROM {BATCH_TABLE} b
        {latest_status_lateral("b", "s", join="INNER")}
        LEFT JOIN {LEASE_TABLE} l ON l.team_id = b.team_id AND l.schema_id = b.schema_id
        WHERE
            b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
            AND b.latest_state = 'executing'
            AND s.job_state = 'executing'
            AND s.created_at <= now() - make_interval(secs => %(grace)s)
            AND (l.team_id IS NULL OR l.expires_at <= now())
            {scope_sql}
        ORDER BY b.created_at ASC, b.batch_index ASC
    """


# Retained for the duckgres sink, which still coordinates via session advisory
# locks (see duckgres/jobs_db.py). The delta queue now uses leases instead.
async def unlock_advisory_locks(
    conn: psycopg.AsyncConnection[Any],
    *,
    batches: list[PendingBatch],
    namespace: int,
) -> None:
    for batch in batches:
        await conn.execute(
            "SELECT pg_advisory_unlock(%(ns)s, hashtext(%(key)s))",
            {"ns": namespace, "key": f"{batch.team_id}:{batch.schema_id}"},
        )


@dataclass(frozen=True, slots=True)
class PendingBatch:
    """A batch row fetched from the queue, ready to be processed by the consumer."""

    id: str
    team_id: int
    schema_id: str
    source_id: str
    job_id: str
    run_uuid: str
    batch_index: int
    s3_path: str
    row_count: int
    byte_size: int
    is_final_batch: bool
    total_batches: int | None
    total_rows: int | None
    sync_type: str
    cumulative_row_count: int
    resource_name: str
    is_resume: bool
    is_first_ever_sync: bool
    metadata: dict[str, Any]
    latest_attempt: int
    created_at: datetime | None = None

    def to_export_signal(self) -> dict[str, Any]:
        """Temporary bridge: convert a PendingBatch into an ExportSignalMessage dict
        so we can reuse the existing process_message() for local testing. The final
        solution will operate on PendingBatch directly without this conversion."""
        return {
            "team_id": self.team_id,
            "job_id": self.job_id,
            "schema_id": self.schema_id,
            "source_id": self.source_id,
            "resource_name": self.resource_name,
            "run_uuid": self.run_uuid,
            "batch_index": self.batch_index,
            "s3_path": self.s3_path,
            "row_count": self.row_count,
            "byte_size": self.byte_size,
            "is_final_batch": self.is_final_batch,
            "total_batches": self.total_batches,
            "total_rows": self.total_rows,
            "sync_type": self.sync_type,
            "cumulative_row_count": self.cumulative_row_count,
            "is_resume": self.is_resume,
            "is_first_ever_sync": self.is_first_ever_sync,
            "timestamp_ns": self.metadata.get("timestamp_ns", time.time_ns()),
            "data_folder": self.metadata.get("data_folder"),
            "schema_path": self.metadata.get("schema_path"),
            "primary_keys": self.metadata.get("primary_keys"),
            "partition_count": self.metadata.get("partition_count"),
            "partition_size": self.metadata.get("partition_size"),
            "partition_keys": self.metadata.get("partition_keys"),
            "partition_format": self.metadata.get("partition_format"),
            "partition_mode": self.metadata.get("partition_mode"),
            "cdc_write_mode": self.metadata.get("cdc_write_mode"),
            "cdc_table_mode": self.metadata.get("cdc_table_mode"),
        }


@dataclass(frozen=True, slots=True)
class FailedRunRef:
    """Identity of a run with a ``failed`` queue batch, used by the reconcile sweep to fail its ExternalDataJob."""

    run_uuid: str
    job_id: str
    team_id: int
    schema_id: str
    workflow_run_id: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class RunActivitySummary:
    """Queue DB activity for a holder's run, used by the lock takeover decision matrix."""

    has_batches: bool
    has_non_terminal: bool
    is_stale: bool
    # Ages behind the staleness verdict, surfaced so takeover logs are diagnosable.
    last_status_write_age_seconds: float | None = None
    oldest_unclaimed_age_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class ActiveRunRef:
    """Per-run aggregate of queue batches, used by the ops management command."""

    run_uuid: str
    job_id: str
    team_id: int
    schema_id: str
    source_id: str
    workflow_run_id: str | None
    pending_batches: int
    total_batches: int
    latest_activity_at: datetime | None


@dataclass(frozen=True, slots=True)
class GroupLease:
    """A ``sourcegrouplease`` row plus computed liveness, for ops inspection."""

    team_id: int
    schema_id: str
    owner_token: str
    acquired_at: datetime
    updated_at: datetime
    expires_at: datetime
    is_live: bool


class BatchQueue:
    """
    Async interface to the Postgres batch queue tables. Each method runs
    its own query against the provided connection — callers manage connections
    and transactions.
    """

    # -- writes (producer side) ------------------------------------------------

    @staticmethod
    async def insert(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        source_id: str,
        job_id: str,
        run_uuid: str,
        batch_index: int,
        s3_path: str,
        row_count: int,
        byte_size: int,
        is_final_batch: bool,
        total_batches: int | None,
        total_rows: int | None,
        sync_type: str,
        cumulative_row_count: int,
        resource_name: str,
        is_resume: bool,
        is_first_ever_sync: bool,
        metadata: dict[str, Any],
    ) -> str:
        """Insert a batch row into the queue. Returns the new batch id."""
        row = await conn.execute(
            f"""
            INSERT INTO {BATCH_TABLE} (
                id, team_id, schema_id, source_id, job_id, run_uuid,
                batch_index, s3_path, row_count, byte_size, is_final_batch,
                total_batches, total_rows, sync_type, cumulative_row_count,
                resource_name, is_resume, is_first_ever_sync, metadata, created_at
            ) VALUES (
                gen_random_uuid(),
                %(team_id)s, %(schema_id)s, %(source_id)s, %(job_id)s, %(run_uuid)s,
                %(batch_index)s, %(s3_path)s, %(row_count)s, %(byte_size)s, %(is_final_batch)s,
                %(total_batches)s, %(total_rows)s, %(sync_type)s, %(cumulative_row_count)s,
                %(resource_name)s, %(is_resume)s, %(is_first_ever_sync)s, %(metadata)s, now()
            )
            RETURNING id
            """,
            {
                "team_id": team_id,
                "schema_id": schema_id,
                "source_id": source_id,
                "job_id": job_id,
                "run_uuid": run_uuid,
                "batch_index": batch_index,
                "s3_path": s3_path,
                "row_count": row_count,
                "byte_size": byte_size,
                "is_final_batch": is_final_batch,
                "total_batches": total_batches,
                "total_rows": total_rows,
                "sync_type": sync_type,
                "cumulative_row_count": cumulative_row_count,
                "resource_name": resource_name,
                "is_resume": is_resume,
                "is_first_ever_sync": is_first_ever_sync,
                "metadata": json.dumps(metadata),
            },
        )
        batch_id: str = str((await row.fetchone())[0])  # type: ignore[index]
        return batch_id

    # -- reads (consumer side) -------------------------------------------------

    @staticmethod
    async def get_unprocessed_and_lock(
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
        limit: int = 50,
        retry_backoff_base_seconds: int = 0,
        lease_ttl_seconds: int = LEASE_TTL_SECONDS,
    ) -> list[PendingBatch]:
        """Fetch unprocessed batches whose (team_id, schema_id) group lease is claimable by ``owner_token``.

        Candidates come from the denormalized state columns, so poll cost
        tracks the claimable set rather than everything retained in the
        14-day window.

        Group ownership is a row in ``sourcegrouplease`` keyed by
        (team_id, schema_id). The outer query claims-or-renews the lease for
        each candidate group in a single writable CTE: a group is returned only
        when the lease is free (no row), already owned by ``owner_token``, or
        expired (a previous owner abandoned it). A live lease held by another
        pod fails the conditional ``DO UPDATE`` and that group's rows are
        dropped by the ``JOIN claimed``. This replaces the old session advisory
        lock so an abandoned group simply expires rather than wedging the fleet.

        Uses a MATERIALIZED CTE so that candidate selection (with LIMIT) is
        fully resolved before the lease claim runs. ``candidate_groups`` is
        ``SELECT DISTINCT`` because ``INSERT ... ON CONFLICT DO UPDATE`` cannot
        affect the same (team_id, schema_id) row twice in one statement.

        ``retry_backoff_base_seconds`` gates the ``waiting_retry`` branch on
        ``state_changed_at``: a batch is only eligible when
        ``now() - state_changed_at >= retry_backoff_base_seconds * GREATEST(latest_attempt, 1)``
        (attempt is floored at 1 so that a zero-attempt row still waits at least one
        base period).

        Head-of-line gating per run: a batch is excluded if any earlier
        ``batch_index`` in the same ``run_uuid`` is currently ``executing`` or
        in ``waiting_retry`` whose backoff window has not yet elapsed. Earlier
        batches that are unprocessed (``pending``) or ``waiting_retry`` with
        backoff met are treated as siblings that will be returned alongside
        in the same poll and processed sequentially by the consumer.

        In-flight schema gating: a batch is also excluded if its
        ``(team_id, schema_id)`` already has an ``executing`` batch (i.e. the
        group is being processed by its lease holder). This keeps a schema's
        other queued runs from consuming the ``LIMIT`` window ahead of the lease
        claim and starving other schemas' claimable work.

        Per-team fairness: candidates are interleaved round-robin across teams so one
        team's deep backlog cannot monopolize the ``LIMIT`` window; within a team,
        oldest-first order (and so per-run ``batch_index`` ordering) is preserved.

        Disjoint windows across pods: groups live-leased by *another* owner are
        excluded from candidates entirely, not merely dropped at the claim step.
        Otherwise every pod computes the same top-``LIMIT`` window and groups
        already owned elsewhere occupy window slots that losing pods can never
        claim — with enough of them at the head of the queue the whole window is
        dead weight and fleet concurrency collapses to roughly one window's worth.
        Own-leased groups stay in the window so a pod can keep draining a group it
        already holds.
        """
        candidates_sql = _state_claim_candidates_sql()
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                WITH candidates AS MATERIALIZED (
                    {candidates_sql}
                        AND NOT EXISTS (
                            SELECT 1
                            FROM {LEASE_TABLE} l_live
                            WHERE l_live.team_id = b.team_id
                                AND l_live.schema_id = b.schema_id
                                AND l_live.expires_at > now()
                                AND l_live.owner_token != %(owner)s
                        )
                    ORDER BY
                        row_number() OVER (
                            PARTITION BY b.team_id ORDER BY b.created_at ASC, b.batch_index ASC
                        ) ASC,
                        b.created_at ASC,
                        b.batch_index ASC
                    LIMIT %(limit)s
                ),
                candidate_groups AS (
                    SELECT DISTINCT team_id, schema_id FROM candidates
                ),
                claimed AS (
                    INSERT INTO {LEASE_TABLE} (team_id, schema_id, owner_token, expires_at, acquired_at, updated_at)
                    SELECT team_id, schema_id, %(owner)s, now() + make_interval(secs => %(ttl)s), now(), now()
                    FROM candidate_groups
                    ON CONFLICT (team_id, schema_id) DO UPDATE
                        SET owner_token = excluded.owner_token,
                            expires_at = excluded.expires_at,
                            acquired_at = CASE
                                WHEN {LEASE_TABLE}.owner_token = excluded.owner_token THEN {LEASE_TABLE}.acquired_at
                                ELSE now()
                            END,
                            updated_at = now()
                        WHERE {LEASE_TABLE}.expires_at < now()
                           OR {LEASE_TABLE}.owner_token = excluded.owner_token
                    RETURNING team_id, schema_id
                )
                SELECT c.*
                FROM candidates c
                JOIN claimed USING (team_id, schema_id)
                ORDER BY c.created_at ASC, c.batch_index ASC
                """,
                {"limit": limit, "backoff": retry_backoff_base_seconds, "owner": owner_token, "ttl": lease_ttl_seconds},
            )
            rows = await cur.fetchall()
        return [PendingBatch(**row) for row in rows]

    @staticmethod
    async def update_status(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int = 0,
        error_response: dict[str, Any] | None = None,
        batch_created_at: datetime | None = None,
    ) -> None:
        """Append a status row and mirror it into the batch's denormalized state columns.

        ``batch_created_at`` (from PendingBatch) prunes the state UPDATE to one
        partition; without it the update falls back to the retention-window scan.
        """
        params: dict[str, Any] = {
            "batch_id": batch_id,
            "job_state": job_state,
            "attempt": attempt,
            "error_response": json.dumps(error_response) if error_response else None,
        }
        if batch_created_at is not None:
            params["batch_created_at"] = batch_created_at
        await conn.execute(
            build_status_dual_write_sql(with_batch_created_at=batch_created_at is not None),
            params,
        )

    @staticmethod
    async def renew_lease(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
        lease_ttl_seconds: int = LEASE_TTL_SECONDS,
    ) -> bool:
        """Extend this owner's group lease. Returns False if the lease was lost (row gone or reclaimed)."""
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE {LEASE_TABLE}
                SET expires_at = now() + make_interval(secs => %(ttl)s), updated_at = now()
                WHERE team_id = %(team_id)s AND schema_id = %(schema_id)s AND owner_token = %(owner)s
                RETURNING 1
                """,
                {"team_id": team_id, "schema_id": schema_id, "owner": owner_token, "ttl": lease_ttl_seconds},
            )
            return (await cur.fetchone()) is not None

    @staticmethod
    async def verify_advisory_lock(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
    ) -> bool:
        """Check whether ``owner_token`` still holds a live group lease for (team_id, schema_id).

        Named ``verify_advisory_lock`` for interface continuity with the
        consumer engine and the duckgres sink; ownership is now a lease row, not
        a session advisory lock.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT EXISTS (
                    SELECT 1 FROM {LEASE_TABLE}
                    WHERE team_id = %(team_id)s
                      AND schema_id = %(schema_id)s
                      AND owner_token = %(owner)s
                      AND expires_at > now()
                )
                """,
                {"team_id": team_id, "schema_id": schema_id, "owner": owner_token},
            )
            row = await cur.fetchone()
            return bool(row and row[0])

    @staticmethod
    def verify_group_lease_sync(
        database_url: str,
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
        connect_timeout_seconds: int = 10,
    ) -> bool:
        """Sync counterpart of verify_advisory_lock: the Delta write runs in a worker thread
        that can't share the group's async connection, so use a short-lived sync one."""
        with psycopg.connect(database_url, autocommit=True, connect_timeout=connect_timeout_seconds) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT EXISTS (
                        SELECT 1 FROM {LEASE_TABLE}
                        WHERE team_id = %(team_id)s
                          AND schema_id = %(schema_id)s
                          AND owner_token = %(owner)s
                          AND expires_at > now()
                    )
                    """,
                    {"team_id": team_id, "schema_id": schema_id, "owner": owner_token},
                )
                row = cur.fetchone()
                return bool(row and row[0])

    @staticmethod
    async def get_stale_executing(
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int = 0,
    ) -> list[PendingBatch]:
        """Find batches stuck in 'executing' whose group lease is absent or expired (previous pod gone).

        A batch is orphaned when its latest status is 'executing', that status
        row is older than ``grace_seconds`` (the heartbeat stopped refreshing
        it), and no live lease covers its (team_id, schema_id) group. Unlike the
        old advisory-lock probe — which a lingering pgbouncer session could hold
        indefinitely and block recovery — an abandoned lease simply expires, so
        this sweep can always reclaim a genuinely orphaned group.

        ``grace_seconds`` requires the 'executing' status row to be older than
        this threshold before the batch is considered orphaned.
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_stale_executing_sql(), {"grace": grace_seconds})
            rows = await cur.fetchall()

        return [PendingBatch(**row) for row in rows]

    @staticmethod
    async def fail_run(
        conn: psycopg.AsyncConnection[Any],
        *,
        run_uuid: str,
        reason: str,
    ) -> int:
        """Mark every pending batch in a run as failed. Returns the count of batches failed."""
        cursor = await conn.execute(
            FAIL_RUN_SQL,
            {
                "run_uuid": run_uuid,
                "error_response": json.dumps({"error": reason}),
            },
        )
        return cursor.rowcount or 0

    @staticmethod
    def fail_run_sync(
        conn: psycopg.Connection[Any],
        *,
        run_uuid: str,
        reason: str,
    ) -> int:
        """Sync twin of ``fail_run`` for the ops management command."""
        cursor = conn.execute(
            FAIL_RUN_SQL,
            {
                "run_uuid": run_uuid,
                "error_response": json.dumps({"error": reason}),
            },
        )
        return cursor.rowcount or 0

    @staticmethod
    def fail_batches_for_job_sync(
        conn: psycopg.Connection[Any],
        *,
        job_id: str,
        reason: str,
    ) -> int:
        """Mark every non-terminal batch of a job as failed, across all its runs.

        Takeover uses this before force-failing the job: leftover claimable
        batches would otherwise load after the takeover and stale-overwrite
        newer data or flip the FAILED job back to COMPLETED via the final batch.
        """
        cursor = conn.execute(
            _bulk_fail_dual_write_sql("b.job_id = %(job_id)s"),
            {
                "job_id": job_id,
                "error_response": json.dumps({"error": reason}),
            },
        )
        return cursor.rowcount or 0

    @staticmethod
    def supersede_other_runs(
        conn: psycopg.Connection[Any],
        *,
        job_id: str,
        current_run_uuid: str,
    ) -> int:
        """Mark non-terminal batches from older runs of the same job as superseded."""
        cursor = conn.execute(
            _bulk_fail_dual_write_sql("b.job_id = %(job_id)s AND b.run_uuid != %(current_run_uuid)s"),
            {
                "job_id": job_id,
                "current_run_uuid": current_run_uuid,
                "error_response": json.dumps({"error": "superseded by newer attempt", "superseded": True}),
            },
        )
        return cursor.rowcount or 0

    @staticmethod
    async def get_failed_runs(
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int,
        lookback_seconds: int,
        limit: int,
    ) -> list[FailedRunRef]:
        """Return one ref per run with a ``failed`` batch older than ``grace_seconds``, within ``lookback_seconds``.

        Ordered by latest failure first so fresh failures still land in the window when
        already-reconciled runs outnumber ``limit`` within the lookback. The
        denormalized-column pre-filter keeps the lateral (still needed for the
        failure timestamp and error payload) probing only failed batches.
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT run_uuid, job_id, team_id, schema_id, metadata, error_response
                FROM (
                    SELECT DISTINCT ON (b.run_uuid)
                        b.run_uuid, b.job_id, b.team_id, b.schema_id, b.metadata, s.error_response,
                        s.created_at AS failed_at
                    FROM {BATCH_TABLE} b
                    {latest_status_lateral("b", "s", join="INNER")}
                    WHERE
                        b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND b.latest_state = 'failed'
                        AND s.job_state = 'failed'
                        AND s.created_at <= now() - make_interval(secs => %(grace)s)
                        AND s.created_at >= now() - make_interval(secs => %(lookback)s)
                        AND COALESCE((s.error_response->>'superseded')::boolean, false) = false
                    ORDER BY b.run_uuid, s.created_at DESC
                ) failed_runs
                ORDER BY failed_at DESC
                LIMIT %(limit)s
                """,
                {"grace": grace_seconds, "lookback": lookback_seconds, "limit": limit},
            )
            rows = await cur.fetchall()

        return [
            FailedRunRef(
                run_uuid=row["run_uuid"],
                job_id=row["job_id"],
                team_id=row["team_id"],
                schema_id=row["schema_id"],
                workflow_run_id=(row["metadata"] or {}).get("workflow_run_id"),
                reason=(row["error_response"] or {}).get("error"),
            )
            for row in rows
        ]

    @staticmethod
    async def get_oldest_unclaimed_batch_age_seconds(
        conn: psycopg.AsyncConnection[Any],
    ) -> float | None:
        """Age in seconds of the oldest batch no consumer has ever picked up, or None when none are waiting.

        'pending' means no status row yet — this is the queue's data-freshness
        signal, and it rises whenever loading stalls regardless of the cause.
        Answered from the claimable partial index; bounded to
        ``FRESHNESS_WINDOW`` so the reported age saturates instead of scanning
        unbounded history.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT EXTRACT(EPOCH FROM (now() - min(b.created_at)))
                FROM {BATCH_TABLE} b
                WHERE b.created_at > now() - interval '{FRESHNESS_WINDOW}'
                  AND b.latest_state = 'pending'
                """
            )
            row = await cur.fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    @staticmethod
    def get_oldest_non_terminal_batch_age_seconds(
        conn: psycopg.Connection[Any],
        *,
        team_id: int,
        schema_ids: list[str],
    ) -> float | None:
        """Age in seconds of the oldest batch still working through the queue for these schemas, or None.

        Non-terminal means unclaimed ('pending', 'waiting') or claimed but unfinished
        ('executing', 'waiting_retry'), read from the denormalized state columns.
        Sync because its caller is the CDC producer's backpressure guard, which runs
        in synchronous activity code. Bounded to the pruning window — older batches
        are gone anyway.
        """
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT EXTRACT(EPOCH FROM (now() - min(b.created_at)))
                FROM {BATCH_TABLE} b
                WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                  AND b.team_id = %(team_id)s
                  AND b.schema_id = ANY(%(schema_ids)s)
                  AND b.latest_state IN ('pending', 'waiting', 'waiting_retry', 'executing')
                """,
                {"team_id": team_id, "schema_ids": schema_ids},
            )
            row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        return float(row[0])

    @staticmethod
    async def unlock_for_batches(
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[PendingBatch],
        owner_token: str,
    ) -> None:
        """Release the group leases for ``batches``' (team_id, schema_id) groups held by ``owner_token``.

        The ``owner_token`` predicate is load-bearing: if this owner's lease
        already expired and another pod reclaimed the group, the delete must be
        a no-op rather than removing the new owner's lease.
        """
        pairs = list({(b.team_id, b.schema_id) for b in batches})
        if not pairs:
            return
        team_ids = [team_id for team_id, _ in pairs]
        schema_ids = [schema_id for _, schema_id in pairs]
        await conn.execute(
            f"""
            DELETE FROM {LEASE_TABLE}
            WHERE owner_token = %(owner)s
              AND (team_id, schema_id) IN (
                  SELECT * FROM unnest(%(team_ids)s::bigint[], %(schema_ids)s::varchar[])
              )
            """,
            {"owner": owner_token, "team_ids": team_ids, "schema_ids": schema_ids},
        )

    @staticmethod
    async def release_all_owned_leases(
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
    ) -> None:
        """Delete every group lease held by ``owner_token``. Used for best-effort cleanup on shutdown."""
        await conn.execute(
            f"DELETE FROM {LEASE_TABLE} WHERE owner_token = %(owner)s",
            {"owner": owner_token},
        )

    @staticmethod
    def get_run_activity_summary(
        conn: psycopg.Connection[Any],
        *,
        job_id: str,
        workflow_run_id: str,
    ) -> RunActivitySummary:
        """Check the queue DB for batch activity belonging to a holder's run.

        Used by the lock takeover decision matrix to distinguish genuinely stale
        RUNNING jobs from ones the loader still has work for. Unclaimed batches
        (no status row yet — hence the LEFT JOIN) count as non-terminal.
        Staleness reflects loader progress only: status writes, or — when the
        loader has never claimed anything — how long the oldest batch has sat
        unclaimed. Batch inserts are producer activity and must not reset the
        clock, or a streaming producer keeps a dead loader "active" forever.
        """
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT
                    COUNT(*) AS batch_count,
                    COUNT(*) FILTER (
                        WHERE s.batch_id IS NULL
                            OR s.job_state NOT IN ('succeeded', 'failed')
                    ) AS non_terminal_count,
                    MAX(s.created_at) AS last_status_write_at,
                    MIN(b.created_at) FILTER (WHERE s.batch_id IS NULL) AS oldest_unclaimed_at
                FROM {BATCH_TABLE} b
                {latest_status_lateral("b", "s")}
                WHERE
                    b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND b.job_id = %(job_id)s
                    AND b.metadata->>'workflow_run_id' = %(workflow_run_id)s
                """,
                {"job_id": job_id, "workflow_run_id": workflow_run_id},
            )
            row = cur.fetchone()

        if row is None or row["batch_count"] == 0:
            return RunActivitySummary(has_batches=False, has_non_terminal=False, is_stale=True)

        def _age(moment: datetime | None) -> float | None:
            if moment is None:
                return None
            return (datetime.now(moment.tzinfo) - moment).total_seconds()

        last_status_write_age = _age(row["last_status_write_at"])
        oldest_unclaimed_age = _age(row["oldest_unclaimed_at"])
        loader_progress_age = last_status_write_age if last_status_write_age is not None else oldest_unclaimed_age

        return RunActivitySummary(
            has_batches=True,
            has_non_terminal=row["non_terminal_count"] > 0,
            is_stale=loader_progress_age is None or loader_progress_age > TAKEOVER_STALE_THRESHOLD_SECONDS,
            last_status_write_age_seconds=last_status_write_age,
            oldest_unclaimed_age_seconds=oldest_unclaimed_age,
        )

    @staticmethod
    def count_batches_for_run(
        conn: psycopg.Connection[Any],
        *,
        job_id: str,
    ) -> int:
        """Count queue batches enqueued for a job, regardless of status.

        Unlike ``get_run_activity_summary`` (which inner-joins the status view and so
        reports ``has_batches=False`` for batches the loader hasn't claimed yet), this
        counts raw batch rows. It lets a caller tell a run that enqueued *nothing* (safe
        to finalize) apart from one whose batches are merely unclaimed — where the loader
        still owns completion and failing the job would strand a late load. The pruning
        window bounds the scan to batches the queue still retains, so a ``0`` here is only
        trustworthy for jobs newer than ``PARTITION_PRUNING_INTERVAL``.
        """
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT COUNT(*) AS batch_count
                FROM {BATCH_TABLE} b
                WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND b.job_id = %(job_id)s
                """,
                {"job_id": job_id},
            )
            row = cur.fetchone()
        return int(row["batch_count"]) if row else 0

    # -- ops / management command helpers (sync) --------------------------------

    @staticmethod
    def get_active_runs(
        conn: psycopg.Connection[Any],
        *,
        team_id: int | None = None,
        schema_ids: list[str] | None = None,
        run_uuid: str | None = None,
        only_pending: bool = True,
    ) -> list[ActiveRunRef]:
        """Aggregate queue batches per run within the targeting scope.

        ``only_pending=True`` keeps only runs with at least one non-terminal
        batch (no status row yet, or waiting/waiting_retry/executing) — the runs
        an operator can still act on. ``only_pending=False`` is for direct
        ``run_uuid`` lookups where a fully-terminal run should still be visible.
        """
        scope_sql, params = _scope_filters(team_id=team_id, schema_ids=schema_ids, run_uuid=run_uuid)
        having = f"HAVING COUNT(*) FILTER (WHERE {pending_batch_predicate('s')}) > 0"
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT
                    b.run_uuid,
                    b.team_id,
                    b.schema_id,
                    MAX(b.job_id) AS job_id,
                    MAX(b.source_id) AS source_id,
                    MAX(b.metadata->>'workflow_run_id') AS workflow_run_id,
                    COUNT(*) FILTER (
                        WHERE {pending_batch_predicate("s")}
                    ) AS pending_batches,
                    COUNT(*) AS total_batches,
                    GREATEST(MAX(s.created_at), MAX(b.created_at)) AS latest_activity_at
                FROM {BATCH_TABLE} b
                {latest_status_lateral("b", "s")}
                WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                {scope_sql}
                GROUP BY b.run_uuid, b.team_id, b.schema_id
                {having if only_pending else ""}
                ORDER BY latest_activity_at ASC
                """,
                params,
            )
            rows = cur.fetchall()
        return [ActiveRunRef(**row) for row in rows]

    @staticmethod
    def get_state_summary(
        conn: psycopg.Connection[Any],
        *,
        team_id: int | None = None,
        schema_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Batch counts by latest state within the scope; ``state='unclaimed'`` means no status row yet.

        Each row carries the oldest ``created_at`` in its state so the caller
        can derive freshness signals (e.g. age of the oldest unclaimed batch).
        """
        scope_sql, params = _scope_filters(team_id=team_id, schema_ids=schema_ids)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT
                    COALESCE(s.job_state, 'unclaimed') AS state,
                    COUNT(*) AS batch_count,
                    MIN(b.created_at) AS oldest_created_at
                FROM {BATCH_TABLE} b
                {latest_status_lateral("b", "s")}
                WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                {scope_sql}
                GROUP BY 1
                ORDER BY 1
                """,
                params,
            )
            return cur.fetchall()

    @staticmethod
    def get_leases(
        conn: psycopg.Connection[Any],
        *,
        team_id: int | None = None,
        schema_ids: list[str] | None = None,
    ) -> list[GroupLease]:
        """Group leases within the scope, with computed liveness."""
        scope_sql, params = _scope_filters(team_id=team_id, schema_ids=schema_ids, alias="l")
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(
                f"""
                SELECT team_id, schema_id, owner_token, acquired_at, updated_at, expires_at,
                       expires_at > now() AS is_live
                FROM {LEASE_TABLE} l
                WHERE true
                {scope_sql}
                ORDER BY team_id, schema_id
                """,
                params,
            )
            rows = cur.fetchall()
        return [GroupLease(**row) for row in rows]

    @staticmethod
    def force_release_leases(
        conn: psycopg.Connection[Any],
        *,
        pairs: list[tuple[int, str]],
    ) -> int:
        """Delete group leases for ``pairs`` regardless of owner. Ops override only.

        Unlike ``unlock_for_batches`` there is deliberately no ``owner_token``
        predicate: the operator has decided the holder is dead. Deleting a live
        lease makes its holder's next ``renew_lease`` return False and abort the
        group, so callers must gate live leases behind explicit confirmation.
        """
        if not pairs:
            return 0
        cursor = conn.execute(
            f"""
            DELETE FROM {LEASE_TABLE}
            WHERE (team_id, schema_id) IN (
                SELECT * FROM unnest(%(team_ids)s::bigint[], %(schema_ids)s::varchar[])
            )
            """,
            {
                "team_ids": [team_id for team_id, _ in pairs],
                "schema_ids": [schema_id for _, schema_id in pairs],
            },
        )
        return cursor.rowcount or 0

    @staticmethod
    def get_stale_executing_sync(
        conn: psycopg.Connection[Any],
        *,
        grace_seconds: int = 0,
        team_id: int | None = None,
        schema_ids: list[str] | None = None,
    ) -> list[PendingBatch]:
        """Sync, scope-filtered twin of ``get_stale_executing`` for ops inspection."""
        scope_sql, params = _scope_filters(team_id=team_id, schema_ids=schema_ids)
        params["grace"] = grace_seconds
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_stale_executing_sql(scope_sql), params)
            rows = cur.fetchall()
        return [PendingBatch(**row) for row in rows]


def _scope_filters(
    *,
    team_id: int | None = None,
    schema_ids: list[str] | None = None,
    run_uuid: str | None = None,
    alias: str = "b",
) -> tuple[str, dict[str, Any]]:
    """Build optional AND-clauses for the ops helpers' targeting scope."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    if team_id is not None:
        clauses.append(f"AND {alias}.team_id = %(scope_team_id)s")
        params["scope_team_id"] = team_id
    if schema_ids is not None:
        clauses.append(f"AND {alias}.schema_id = ANY(%(scope_schema_ids)s)")
        params["scope_schema_ids"] = schema_ids
    if run_uuid is not None:
        clauses.append(f"AND {alias}.run_uuid = %(scope_run_uuid)s")
        params["scope_run_uuid"] = run_uuid
    return "\n".join(clauses), params
