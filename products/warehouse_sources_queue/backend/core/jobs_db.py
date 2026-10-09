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
import random
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

BATCH_TABLE = "sourcebatch"
STATUS_TABLE = "sourcebatchstatus"
STATUS_VIEW = "v_latest_source_batch_status"
LEASE_TABLE = "sourcegrouplease"

# Lock order for `sourcegrouplease`: a statement that locks more than one lease row
# must take those locks in ascending (team_id, schema_id).
#
# Four paths write this table concurrently across the fleet: the claim upsert in
# `get_unprocessed_and_lock`, the heartbeat `renew_lease`, the `unlock_for_batches`
# delete, and the shutdown `release_all_owned_leases`. Postgres locks rows in whatever
# order the plan happens to emit them, so two pods whose group sets overlap can lock the
# same rows in opposite orders and deadlock. That also takes down single-row writers
# caught in the cycle, because a waiter holds an ExclusiveLock on the tuple it is queued
# for while it waits. `renew_lease` can therefore be a link in a cycle it did not cause.
#
# Single-row statements (`renew_lease`, `delete_expired_lease`,
# `try_acquire_reconcile_sweep_slot`, `try_acquire_queue_gauges_slot`) satisfy the order for free. Multi-row statements
# have to force it, either with `ORDER BY team_id, schema_id` on the rows an upsert
# reads, or with an ordered `FOR UPDATE` sub-select that takes every lock before the
# delete runs.

# Default group-lease validity window, in seconds. The consumer renews the
# lease on its heartbeat (~every grace/3); a group whose owner stops renewing
# becomes reclaimable once this window elapses. Coordinated with the consumer's
# recovery_grace_seconds so lease reclamation and the executing-status recovery
# sweep fire together.
LEASE_TTL_SECONDS = 300

# Sentinel lease row that single-flights the reconcile sweep across the fleet.
# Real groups have team_id >= 1 and UUID schema ids, so this key can never
# collide with (or be claimed/unlocked as) an actual group. The slot TTL sits
# just under the engine's 300s reconcile interval so single-flighting never
# makes reconcile latency worse than the old every-pod cadence: the first pod
# whose timer fires after expiry wins the next sweep.
RECONCILE_SWEEP_LEASE_TEAM_ID = 0
RECONCILE_SWEEP_LEASE_SCHEMA_ID = "__reconcile-sweep__"
RECONCILE_SWEEP_SLOT_TTL_SECONDS = 240

# Sentinel lease row that elects the one pod that samples the queue-wide gauges
# (freshness and depth). Every pod reads the same queue, so when each pod runs the
# probes the queue DB does N times the work for the same numbers, in competition
# with the claim path. Same TTL as the sweep slot: it sits under the 300s reconcile
# interval, so the slot is free again when a pod's next timer fires. The key has a
# per-fleet suffix (see ``queue_gauges_slot_key``), because each fleet exports the
# gauges from its own pods.
QUEUE_GAUGES_LEASE_SCHEMA_ID_PREFIX = "__queue-gauges__"
QUEUE_GAUGES_SLOT_TTL_SECONDS = 240

# Server-side ceiling for one gauge statement. On a struggling queue DB a gauge must
# give up quickly and skip its sample, not compete with the claim path for seconds.
GAUGE_STATEMENT_TIMEOUT_MS = 5_000

# Partition pruning hint: only scan partitions within this window.
# Set to 2x the retention period so the planner can skip dropped
# partitions. Not a correctness filter -- older partitions are already
# gone by the time this matters.
PARTITION_PRUNING_INTERVAL = "14 days"

# Oldest a batch may be and still be claimed or recovery-swept. MUST stay below
# the retention window (RETENTION_DAYS in
# posthog/temporal/warehouse_sources_queue_partition_management/activities.py),
# because that job fails and drops old batches on the assumption that no
# consumer can still claim them. The half-day margin absorbs clock skew and
# sweep timing. It MUST also stay below the warehouse bucket's lifecycle rule,
# which deletes extraction parquet 8 days after upload, so that a claimed
# batch's file still exists. Applies only to the outer claim
# candidates and the recovery sweep — never to the head-of-line/failed-run/
# schema-busy gates, which must keep seeing rows aged past this window for as
# long as they exist.
CLAIM_ELIGIBILITY_INTERVAL = "6 days 12 hours"

# One claim reads a window of the queue, not the whole claimable set, so its cost
# does not grow with a backlog. The window is the next CLAIM_WINDOW_TEAMS teams that
# hold claim candidates, in team_id order from the consumer's cursor, with wrap. A
# backlog over more teams than this is served in rotation: oldest first inside the
# window, not oldest first across the queue.
CLAIM_WINDOW_TEAMS = 100

# Candidates one claim reads per window team and scan round, oldest first.
# The effective depth is never below the claim's LIMIT, so one team can fill a claim.
CLAIM_WINDOW_TEAM_DEPTH = 50

# Scan rounds per window team. A round that finds candidates held by a run gate
# makes the next round read past those runs, so gated batches cannot fill the depth
# and hide the open ones behind them. The cap bounds the cost: a team with gated
# candidates deeper than rounds x depth waits until a gate clears.
CLAIM_WINDOW_GATE_ROUNDS = 5

# Full windows one claim call may read when they give no batch, before it returns
# empty. Without this, each window of teams with nothing open costs the consumer one
# poll interval. The call also stops after one turn over all teams.
CLAIM_MAX_EMPTY_WINDOWS = 20

_MAX_TEAM_ID = 2**63 - 1

# Quiet time (no batch inserts or status writes) before lock takeover treats a run as
# abandoned. Must exceed worst-case loader backlog latency — an unclaimed backlog is still live.
TAKEOVER_STALE_THRESHOLD_SECONDS = 6 * 60 * 60

# Lookback for the queue-freshness probe. Bounds both the probe's cost and the
# reported age: an unclaimed batch older than this saturates the gauge at the
# window, which is already far past any sane alert threshold.
FRESHNESS_WINDOW_SECONDS = 48 * 60 * 60
FRESHNESS_WINDOW = f"{FRESHNESS_WINDOW_SECONDS} seconds"

# How many of the deepest (team_id, schema_id) groups the depth probe's
# concentration share covers. Small enough that a near-1 share means a handful
# of tenants own the queue, large enough that one bursty tenant does not.
DEPTH_TOP_GROUPS = 5


class _Unset:
    """Sentinel for ``update_status_unless_failed(expected_state_changed_at=...)``.

    ``state_changed_at`` is nullable, so ``None`` is a legitimate value to arm the
    compare-and-swap against. ``_UNSET`` is the only signal for "no CAS wanted",
    keeping an ordinary write and a CAS against a genuinely-null observation apart.
    """


_UNSET = _Unset()


def pending_batch_select_columns(status_alias: str) -> str:
    return f"""
        b.id, b.team_id, b.schema_id, b.source_id, b.job_id,
        b.run_uuid, b.batch_index, b.s3_path, b.row_count, b.byte_size,
        b.is_final_batch, b.total_batches, b.total_rows, b.sync_type,
        b.cumulative_row_count, b.resource_name, b.is_resume,
        b.is_first_ever_sync, b.metadata, b.destination_ids,
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


def sync_type_scope_sql(
    *,
    sync_types: list[str] | None = None,
    exclude_sync_types: list[str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Optional AND-clause partitioning claim/sweep work by ``sourcebatch.sync_type``.

    Lets a consumer fleet own a subset of the queue (e.g. a CDC-only deployment) while a
    sibling fleet runs with the complement. The clause may only ever scope *which rows a
    fleet claims or sweeps* — never the run/failed/schema-busy gates, which must keep
    seeing every class so cross-class runs of one (team_id, schema_id) still serialize
    (a CDC schema's initial snapshot enqueues ``full_refresh`` batches).
    """
    if sync_types and exclude_sync_types:
        raise ValueError("sync_types and exclude_sync_types are mutually exclusive")
    if sync_types:
        return "AND b.sync_type = ANY(%(claim_sync_types)s)", {"claim_sync_types": list(sync_types)}
    if exclude_sync_types:
        return (
            "AND b.sync_type != ALL(%(claim_exclude_sync_types)s)",
            {"claim_exclude_sync_types": list(exclude_sync_types)},
        )
    return "", {}


def queue_gauges_slot_key(
    *,
    sync_types: list[str] | None = None,
    exclude_sync_types: list[str] | None = None,
) -> str:
    """Lease key of the gauge-sampling slot for one fleet partition.

    The gauges are queue-wide, but each fleet exports them from its own pods. One
    slot shared by all fleets would let a pod of one fleet win every round, and
    the other fleet's dashboards would go empty.
    """
    if sync_types:
        return f"{QUEUE_GAUGES_LEASE_SCHEMA_ID_PREFIX}:only:{','.join(sorted(sync_types))}"
    if exclude_sync_types:
        return f"{QUEUE_GAUGES_LEASE_SCHEMA_ID_PREFIX}:except:{','.join(sorted(exclude_sync_types))}"
    return QUEUE_GAUGES_LEASE_SCHEMA_ID_PREFIX


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
            RETURNING batch_id, job_state, attempt, created_at, error_response
        )
        UPDATE {BATCH_TABLE} b
        SET latest_state = ins.job_state, latest_attempt = ins.attempt, state_changed_at = ins.created_at,
            superseded = (ins.job_state = 'failed'
                          AND COALESCE((ins.error_response->>'superseded')::boolean, false))
        FROM ins
        WHERE b.id = ins.batch_id
          AND {created_at_predicate}
          AND ((b.latest_state, b.latest_attempt) IS DISTINCT FROM (ins.job_state, ins.attempt)
               OR b.state_changed_at IS NULL)
          AND (b.state_changed_at IS NULL OR b.state_changed_at <= ins.created_at)
    """


def build_status_dual_write_unless_failed_sql(
    *, with_batch_created_at: bool, with_expected_state_changed_at: bool = False
) -> str:
    """Guarded twin of :func:`build_status_dual_write_sql`: inserts nothing over a
    terminal 'failed', so a consumer's newer executing/succeeded rows can't
    un-retire a batch fail_run already failed. A 'failed' carrying
    ``%(supersedable_failed_error)s`` (the lock-takeover sentinel) stays writable —
    takeover deliberately lets an in-flight batch finish. Returns the INSERT count
    (0 = refused); the column UPDATE is a designed no-op for heartbeat re-inserts,
    so its rowcount can't be the signal.

    ``with_expected_state_changed_at`` arms a compare-and-swap on the caller's
    observed ``state_changed_at`` — the recovery sweep's fence against a live owner
    that completed the batch between the stale scan and the re-queue. The predicate
    rides the ``target`` CTE, so it is evaluated under the same ``FOR UPDATE OF b``
    row lock that already serializes this write: a stale requeue matches no target,
    inserts nothing, and reports 0 without racing the owner's denormalized write.
    """
    created_at_predicate = (
        "b.created_at = %(batch_created_at)s"
        if with_batch_created_at
        else f"b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'"
    )
    cas_predicate = (
        "\n              AND b.state_changed_at IS NOT DISTINCT FROM %(expected_state_changed_at)s"
        if with_expected_state_changed_at
        else ""
    )
    return f"""
        WITH target AS (
            SELECT b.id
            FROM {BATCH_TABLE} b
            {latest_status_lateral("b", "s")}
            WHERE b.id = %(batch_id)s
              AND {created_at_predicate}
              AND (
                  b.latest_state IS DISTINCT FROM 'failed'
                  OR s.error_response->>'error' = %(supersedable_failed_error)s
              ){cas_predicate}
            FOR UPDATE OF b
        ),
        ins AS (
            INSERT INTO {STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            SELECT t.id, %(job_state)s, %(attempt)s, now(), %(error_response)s, now()
            FROM target t
            RETURNING batch_id, job_state, attempt, created_at, error_response
        ),
        upd AS (
            UPDATE {BATCH_TABLE} b
            SET latest_state = ins.job_state, latest_attempt = ins.attempt, state_changed_at = ins.created_at,
                superseded = (ins.job_state = 'failed'
                              AND COALESCE((ins.error_response->>'superseded')::boolean, false))
            FROM ins
            WHERE b.id = ins.batch_id
              AND {created_at_predicate}
              AND ((b.latest_state, b.latest_attempt) IS DISTINCT FROM (ins.job_state, ins.attempt)
                   OR b.state_changed_at IS NULL)
              AND (b.state_changed_at IS NULL OR b.state_changed_at <= ins.created_at)
            RETURNING b.id
        )
        SELECT count(*) FROM ins
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
        SET latest_state = 'failed', latest_attempt = 0, state_changed_at = ins.created_at,
            superseded = COALESCE((%(error_response)s::jsonb->>'superseded')::boolean, false)
        FROM ins
        JOIN targets t ON t.id = ins.batch_id
        WHERE b.id = t.id
          AND b.created_at = t.created_at
          AND (b.state_changed_at IS NULL OR b.state_changed_at <= ins.created_at)
    """


# Both fail-run variants share _bulk_fail_dual_write_sql so the async consumer
# path and the sync ops command agree on what counts as a pending (fail-able)
# batch. The ops command targets by run_uuid alone (human-driven); consumer
# paths always know the run's group, so they scope by it too — guards against
# cross-group writes on a run_uuid collision and keeps the scan on the
# team/schema indexes.
FAIL_RUN_SQL = _bulk_fail_dual_write_sql("b.run_uuid = %(run_uuid)s")
FAIL_RUN_SCOPED_SQL = _bulk_fail_dual_write_sql(
    "b.run_uuid = %(run_uuid)s AND b.team_id = %(team_id)s AND b.schema_id = %(schema_id)s"
)


def _claim_candidate_predicate_sql(sync_type_scope: str = "") -> str:
    """WHERE body that makes batch ``b`` a claim candidate. See :func:`_state_claim_candidates_sql`."""
    return f"""
            b.created_at > now() - interval '{CLAIM_ELIGIBILITY_INTERVAL}'
            {sync_type_scope}
            AND (
                b.latest_state = 'pending'
                OR (
                    b.latest_state = 'waiting_retry'
                    AND b.state_changed_at <= now() - make_interval(
                        secs => %(backoff)s * GREATEST(b.latest_attempt, 1)
                    )
                )
            )
    """


def _state_claim_candidates_sql(sync_type_scope: str = "") -> str:
    """Claimable batches read from the denormalized state columns, before any gate.

    Answered by ``sb_claimable_idx``, so the scan tracks the claimable set
    instead of everything retained. 'pending' means no status row yet;
    'waiting' is deliberately not claimable.

    ``sync_type_scope`` (from :func:`sync_type_scope_sql`) narrows only this
    candidate set to this fleet's classes. It must never be applied to the
    gates in :func:`_claim_window_sql`: they have to see other fleets' batches
    so one schema's runs stay mutually exclusive across fleets.

    The candidate set is likewise bounded by ``CLAIM_ELIGIBILITY_INTERVAL``: a
    batch older than that may already have lost its parquet to retention, so it
    must never be claimed. The gates keep ``PARTITION_PRUNING_INTERVAL`` for the
    same reason the sync-type scope stays out of them — they must see every row
    that still exists.

    Selects only the narrow keys that the gates and the fairness ranking need.
    Selecting the wide row here (``metadata`` alone is ~1 KB per batch) made
    every poll sort megabytes-to-gigabytes of payload to keep ~50 rows.
    """
    return f"""
        SELECT b.id, b.created_at, b.batch_index, b.team_id, b.schema_id, b.run_uuid
        FROM {BATCH_TABLE} b
        WHERE {_claim_candidate_predicate_sql(sync_type_scope)}
    """


def _claim_window_sql(sync_type_scope: str = "") -> str:
    """CTEs that end in ``narrow``: the gated, fairness-ranked ``(id, created_at)`` claim window.

    The gates are evaluated once per group and once per scanned run, never once
    per candidate batch. A per-batch correlated probe is only cheap while the
    planner answers it from the partial indexes. On a hot daily partition
    those indexes churn and bloat, and after an analyze the planner can pick
    ``sb_run_uuid_idx``, ``sb_run_uuid_bi_idx`` or ``sb_team_schema_idx``
    instead. Each probe then reads every batch of its run or group, so a
    backlog of long runs costs (batches x run length) per poll. Here a bad
    index choice costs at most one run-length read per candidate run.

    Each gate keeps the semantics of the per-batch form:

    - ``closed_groups``: a group with an 'executing' batch is not claimable,
      and neither is a group with a live lease of another owner. Only the
      groups of the window's teams are read, so the set stays small however
      many groups the fleet holds. Each team carries its closed schemas as
      the keys of a jsonb object (``closed_schemas``), built once per
      statement. The key test is a binary search, so the filter does not
      depend on a hashed sub-plan fitting in ``work_mem`` and does not slow
      down with the number of closed groups of a team.
    - ``gates``: one ``sb_run_gate_idx`` probe per scanned run. A run with a
      'failed' batch is not claimable. ``first_blocked_index`` is the lowest
      batch_index that is 'executing' or 'waiting_retry' inside its backoff.
      "No such batch earlier than mine" is the same as "my batch_index <=
      that minimum". The probe is an aggregate in a LATERAL, so the planner
      cannot flatten it into an anti-join whose hash side is every failed
      batch in the pruning window.

    The fairness ranking then runs over the gated rows only, which is the set
    the per-batch form ranked. Per team, oldest first; round-robin across
    teams; the LIMIT applies last.

    The candidates are a bounded window, so the cost of a claim does not grow
    with the backlog:

    - ``window_teams``: a loose index scan over ``sb_claimable_idx``. Each step
      seeks the next team_id that holds a candidate, so a step costs one index
      descent per partition, whatever the depth of the team. The walk starts
      after ``%(team_cursor)s``, wraps at the highest team, and stops after
      ``CLAIM_WINDOW_TEAMS`` teams or one full turn. The row with
      ``is_team = false`` only marks the wrap.
    - ``team_scan``: per window team, rounds of ``scanned`` then ``gates``.
      ``scanned`` reads the oldest candidates up to ``CLAIM_WINDOW_TEAM_DEPTH``
      (or the LIMIT, if larger). The closed-group filter is inside the scan,
      so a deep backlog behind an executing batch cannot fill the depth and
      hide the other groups of the team. The closed-group and held-run filters
      sit in a ``CASE`` on purpose. The planner prices a bare ``<> ALL`` filter
      as if almost no row passes, expects about one row per partition, drops
      the ordered ``sb_claimable_idx`` scan that stops at the depth, and scans
      and sorts a whole partition for each team and round. It cannot see into
      the ``CASE``, takes half the rows, and keeps the ordered scan. The run
      gates cannot be a filter of
      the scan without a probe per batch, so they work in rounds: a round
      that finds held batches records their runs in ``gated_runs`` and
      ``gated_after`` (-1 for a failed run, else the blocked index), and the
      next round reads past exactly those batches. A team is done when a
      round finds nothing new to skip or has enough open batches for the
      LIMIT, or after ``CLAIM_WINDOW_GATE_ROUNDS`` rounds. Only the open
      batches of the last round leave the scan, so the skip list never
      decides what is claimable; the gates of that round do.

    When the queue holds no more than ``CLAIM_WINDOW_TEAMS`` teams and no team
    exceeds the depth, the window is the whole claimable set and the result is
    the same as an unbounded scan. Past those bounds:

    - A claim ranks the teams of its window only. A team outside the window
      waits for the rotation, even if its batch is older.
    - A team's open candidates past the depth stay unseen until earlier ones
      leave the queue.
    - A team whose held candidates run deeper than rounds x depth gives
      nothing until a gate clears (the backoff ends, or the reconcile sweep
      drains the failed run).

    Two costs stay outside the bound. The sync-type scope is a heap filter on
    the walk, so a fleet whose scope matches few of the claimable rows reads
    past the others to find its teams. And the per-team scan stops at the depth
    only when the plan reads the index in order; a plan that sorts reads every
    candidate of the window's teams.
    """
    candidate = _claim_candidate_predicate_sql(sync_type_scope)
    # ``round IN (0, 1, ...)`` means ``round < CLAIM_WINDOW_GATE_ROUNDS``. The planner takes
    # a third of the rows for a range test and far fewer for an equality list. With the
    # range test it prices the scan rounds above jit_above_cost.
    rounds_left = ", ".join(str(n) for n in range(CLAIM_WINDOW_GATE_ROUNDS))
    return f"""
        window_teams AS MATERIALIZED (
            WITH RECURSIVE walk (team_id, n, wrapped, is_team) AS (
                SELECT %(team_cursor)s::bigint, 0, false, false
                UNION ALL
                SELECT
                    COALESCE(seek.team_id, -1),
                    w.n + (seek.team_id IS NOT NULL)::int,
                    w.wrapped OR seek.team_id IS NULL,
                    seek.team_id IS NOT NULL
                FROM walk w
                CROSS JOIN LATERAL (
                    SELECT (
                        SELECT b.team_id
                        FROM {BATCH_TABLE} b
                        WHERE {candidate}
                            AND b.team_id > w.team_id
                            AND b.team_id <= CASE WHEN w.wrapped THEN %(team_cursor)s ELSE {_MAX_TEAM_ID} END
                        ORDER BY b.team_id ASC
                        LIMIT 1
                    ) AS team_id
                    OFFSET 0
                ) seek
                WHERE w.n < {CLAIM_WINDOW_TEAMS}
                    AND (seek.team_id IS NOT NULL OR NOT w.wrapped)
            )
            SELECT walk.team_id, walk.n, walk.wrapped FROM walk WHERE walk.is_team
        ),
        closed_groups AS MATERIALIZED (
            SELECT b_busy.team_id, b_busy.schema_id
            FROM {BATCH_TABLE} b_busy
            WHERE b_busy.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                AND b_busy.latest_state = 'executing'
                AND b_busy.team_id = ANY (ARRAY(SELECT t.team_id FROM window_teams t))
            UNION
            SELECT l_live.team_id, l_live.schema_id
            FROM {LEASE_TABLE} l_live
            WHERE l_live.expires_at > now()
                AND l_live.owner_token != %(owner)s
                AND l_live.team_id = ANY (ARRAY(SELECT t.team_id FROM window_teams t))
        ),
        team_scan AS MATERIALIZED (
            WITH RECURSIVE scan (
                team_id, closed_schemas, round, gated_runs, gated_after, done, ids, created_ats, batch_indexes
            ) AS (
                SELECT
                    t.team_id,
                    COALESCE(closed.schemas, '{{}}'::jsonb),
                    0, '{{}}'::varchar[], '{{}}'::int[], false,
                    '{{}}'::uuid[], '{{}}'::timestamptz[], '{{}}'::int[]
                FROM window_teams t
                LEFT JOIN (
                    SELECT g.team_id, jsonb_object_agg(g.schema_id, true) AS schemas
                    FROM closed_groups g
                    GROUP BY g.team_id
                ) closed ON closed.team_id = t.team_id
                UNION ALL
                SELECT
                    s.team_id,
                    s.closed_schemas,
                    s.round + 1,
                    s.gated_runs || r.new_runs,
                    s.gated_after || r.new_after,
                    cardinality(r.new_runs) = 0 OR cardinality(r.ids) >= %(limit)s,
                    r.ids,
                    r.created_ats,
                    r.batch_indexes
                FROM scan s
                CROSS JOIN LATERAL (
                    WITH scanned AS MATERIALIZED (
                        SELECT b.id, b.created_at, b.batch_index, b.run_uuid
                        FROM {BATCH_TABLE} b
                        WHERE {candidate}
                            AND b.team_id = s.team_id
                            AND CASE
                                WHEN NOT s.closed_schemas ? b.schema_id
                                    AND (
                                        b.run_uuid <> ALL (s.gated_runs)
                                        OR b.batch_index <= (s.gated_after)[array_position(s.gated_runs, b.run_uuid)]
                                    )
                                THEN true
                                ELSE false
                            END
                        ORDER BY b.created_at ASC, b.batch_index ASC
                        LIMIT GREATEST(%(limit)s, {CLAIM_WINDOW_TEAM_DEPTH})
                    ),
                    gates AS MATERIALIZED (
                        SELECT sr.run_uuid, gate.has_failed, gate.first_blocked_index
                        FROM (SELECT DISTINCT sc.run_uuid FROM scanned sc) sr
                        CROSS JOIN LATERAL (
                            SELECT
                                bool_or(b_gate.latest_state = 'failed') AS has_failed,
                                min(b_gate.batch_index) FILTER (
                                    WHERE b_gate.latest_state = 'executing'
                                        OR (
                                            b_gate.latest_state = 'waiting_retry'
                                            AND b_gate.state_changed_at > now() - make_interval(
                                                secs => %(backoff)s * GREATEST(b_gate.latest_attempt, 1)
                                            )
                                        )
                                ) AS first_blocked_index
                            FROM {BATCH_TABLE} b_gate
                            WHERE b_gate.run_uuid = sr.run_uuid
                                AND b_gate.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                                AND b_gate.latest_state IN ('executing', 'waiting_retry', 'failed')
                        ) gate
                    )
                    SELECT open.ids, open.created_ats, open.batch_indexes, held.new_runs, held.new_after
                    FROM (
                        SELECT
                            COALESCE(array_agg(sc.id), '{{}}'::uuid[]) AS ids,
                            COALESCE(array_agg(sc.created_at), '{{}}'::timestamptz[]) AS created_ats,
                            COALESCE(array_agg(sc.batch_index), '{{}}'::int[]) AS batch_indexes
                        FROM scanned sc
                        JOIN gates g ON g.run_uuid = sc.run_uuid
                        WHERE g.has_failed IS NOT TRUE
                            AND (g.first_blocked_index IS NULL OR sc.batch_index <= g.first_blocked_index)
                    ) open
                    CROSS JOIN (
                        SELECT
                            COALESCE(array_agg(g.run_uuid), '{{}}'::varchar[]) AS new_runs,
                            COALESCE(
                                array_agg(CASE WHEN g.has_failed THEN -1 ELSE g.first_blocked_index END),
                                '{{}}'::int[]
                            ) AS new_after
                        FROM gates g
                        WHERE g.run_uuid <> ALL (s.gated_runs)
                            AND EXISTS (
                                SELECT 1
                                FROM scanned sc
                                WHERE sc.run_uuid = g.run_uuid
                                    AND (g.has_failed OR sc.batch_index > g.first_blocked_index)
                            )
                    ) held
                ) r
                WHERE NOT s.done AND s.round IN ({rounds_left})
            )
            SELECT scan.team_id, scan.ids, scan.created_ats, scan.batch_indexes
            FROM scan
            WHERE scan.done OR scan.round = {CLAIM_WINDOW_GATE_ROUNDS}
        ),
        narrow AS MATERIALIZED (
            SELECT c.id, c.created_at
            FROM team_scan ts
            CROSS JOIN LATERAL unnest(ts.ids, ts.created_ats, ts.batch_indexes) AS c (id, created_at, batch_index)
            ORDER BY
                row_number() OVER (
                    PARTITION BY ts.team_id ORDER BY c.created_at ASC, c.batch_index ASC
                ) ASC,
                c.created_at ASC,
                c.batch_index ASC
            LIMIT %(limit)s
        )
    """


def _orphaned_candidate_runs_sql() -> str:
    """Runs holding a ``failed`` batch that still have claimable batches behind it.

    Split out from its caller so the plan-shape test can EXPLAIN exactly what runs,
    the same way :func:`_state_claim_candidates_sql` is pinned.
    """
    return f"""
        WITH stuck_runs AS (
            SELECT
                b.run_uuid,
                b.team_id,
                b.schema_id,
                MIN(b.created_at) AS oldest_created_at,
                count(*) AS non_terminal_batches
            FROM {BATCH_TABLE} b
            WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
              AND b.latest_state IN ('pending', 'waiting_retry')
            GROUP BY b.run_uuid, b.team_id, b.schema_id
        )
        SELECT r.run_uuid, r.team_id, r.schema_id, r.non_terminal_batches
        FROM stuck_runs r
        WHERE EXISTS (
            SELECT 1
            FROM {BATCH_TABLE} bf
            WHERE bf.run_uuid = r.run_uuid
              AND bf.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
              AND bf.latest_state = 'failed'
            OFFSET 0
        )
        ORDER BY r.oldest_created_at ASC
        LIMIT %(limit)s
    """


def _queue_freshness_sql() -> str:
    """Age, blocked count, and backlogged groups of the pending set, in one scan.

    The scan is ``latest_state = 'pending'`` inside ``FRESHNESS_WINDOW``, which
    ``sb_claimable_idx`` serves (its predicate covers 'pending'). The scan is
    aggregated into runs before the failed-run probe, so the probe costs one
    ``sb_run_gate_idx`` descent per run, not one per batch. The result is the
    same, because a run is blocked or not as a whole.

    ``gated_runs`` is MATERIALIZED on purpose. The final SELECT reads ``blocked``
    in three FILTER clauses. An inlined CTE copies the EXISTS sub-plan into each
    of them, which runs the probe up to three times per row.

    Split out from its caller so the plan-shape test can EXPLAIN exactly what runs.
    """
    return f"""
        WITH pending_runs AS (
            SELECT
                b.team_id,
                b.schema_id,
                b.run_uuid,
                min(b.created_at) AS oldest_created_at,
                count(*) AS batches
            FROM {BATCH_TABLE} b
            WHERE b.created_at > now() - interval '{FRESHNESS_WINDOW}'
              AND b.latest_state = 'pending'
            GROUP BY b.team_id, b.schema_id, b.run_uuid
        ),
        gated_runs AS MATERIALIZED (
            SELECT
                r.team_id,
                r.schema_id,
                r.oldest_created_at,
                r.batches,
                EXISTS (
                    SELECT 1
                    FROM {BATCH_TABLE} b_failed
                    WHERE b_failed.run_uuid = r.run_uuid
                      AND b_failed.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                      AND b_failed.latest_state = 'failed'
                ) AS blocked
            FROM pending_runs r
        )
        SELECT
            EXTRACT(EPOCH FROM (now() - min(oldest_created_at) FILTER (WHERE NOT blocked))),
            coalesce(sum(batches) FILTER (WHERE blocked), 0),
            count(DISTINCT (team_id, schema_id)) FILTER (
                WHERE NOT blocked
                  AND oldest_created_at <= now() - make_interval(secs => %(backlog_threshold)s)
            )
        FROM gated_runs
    """


def _claimable_count_sql() -> str:
    """Count the claimable set alone: an index-only walk of ``sb_claimable_idx``.

    ``created_at`` is a key column of that partial index, so the count needs no
    heap fetch, no per-run probe and no per-group probe. That is why it still
    finishes on a backlog where :func:`_queue_depth_sql` times out.
    """
    return f"""
        SELECT count(*)
        FROM {BATCH_TABLE} b
        WHERE b.created_at > now() - interval '{CLAIM_ELIGIBILITY_INTERVAL}'
          AND b.latest_state IN ('pending', 'waiting_retry')
    """


def _queue_depth_sql() -> str:
    """How the claimable set is spread over (team_id, schema_id) groups, in one scan.

    The claimable set is the same as ``sb_claimable_idx`` covers: 'pending' or
    'waiting_retry' inside ``CLAIM_ELIGIBILITY_INTERVAL``. The per-run and
    per-group gates below are not filters on that scan. The scan is aggregated
    into runs first, so the failed-run probe costs one ``sb_run_gate_idx``
    descent per run, and then into groups, so the executing probe costs one
    ``sb_schema_busy_idx`` descent per group. Both probes keep
    ``PARTITION_PRUNING_INTERVAL`` because they must see every row that still
    exists, the same as the claim query's gates.

    ``live_batches`` drops the runs that hold a failed batch: the claim query
    refuses those, so they are neither waiting for a slot nor waiting behind
    their group. Without that split a leaked run reads as capacity demand
    forever, which is the same distortion that made the age gauge exclude them.
    The headline count comes from :func:`_claimable_count_sql`, not from here.

    Split out from its caller so the plan-shape test can EXPLAIN exactly what
    runs, the way :func:`_state_claim_candidates_sql` is pinned.
    """
    return f"""
        WITH claimable_runs AS (
            SELECT b.team_id, b.schema_id, b.run_uuid, count(*) AS batches
            FROM {BATCH_TABLE} b
            WHERE b.created_at > now() - interval '{CLAIM_ELIGIBILITY_INTERVAL}'
              AND b.latest_state IN ('pending', 'waiting_retry')
            GROUP BY b.team_id, b.schema_id, b.run_uuid
        ),
        gated_runs AS (
            SELECT
                r.team_id,
                r.schema_id,
                r.batches,
                EXISTS (
                    SELECT 1
                    FROM {BATCH_TABLE} b_failed
                    WHERE b_failed.run_uuid = r.run_uuid
                      AND b_failed.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                      AND b_failed.latest_state = 'failed'
                ) AS blocked
            FROM claimable_runs r
        ),
        groups AS (
            SELECT
                g.team_id,
                g.schema_id,
                coalesce(sum(g.batches) FILTER (WHERE NOT g.blocked), 0) AS live_batches
            FROM gated_runs g
            GROUP BY g.team_id, g.schema_id
        ),
        ranked AS (
            SELECT
                g.live_batches,
                EXISTS (
                    SELECT 1
                    FROM {BATCH_TABLE} b_busy
                    WHERE b_busy.team_id = g.team_id
                      AND b_busy.schema_id = g.schema_id
                      AND b_busy.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                      AND b_busy.latest_state = 'executing'
                ) AS executing,
                row_number() OVER (ORDER BY g.live_batches DESC) AS depth_rank
            FROM groups g
        )
        SELECT
            count(*) FILTER (WHERE live_batches > 0) AS claimable_groups,
            coalesce(sum(live_batches), 0) AS live_batches,
            coalesce(sum(live_batches) FILTER (WHERE depth_rank <= %(top_groups)s), 0) AS top_groups_batches,
            coalesce(sum(live_batches) FILTER (WHERE NOT executing), 0) AS slot_waiting_batches,
            coalesce(sum(live_batches) FILTER (WHERE executing), 0) AS serialized_batches
        FROM ranked
    """


def _stranded_candidate_runs_sql() -> str:
    """Candidate selection for the stranded-run sweep: aggregate first, then gate per run.

    The bounded non-terminal scan collapses into (run, team, schema) groups
    BEFORE the lease and failed-run gates, so each gate runs as one index probe
    per candidate run. Gating the raw batch rows instead made the planner turn
    the failed-run NOT EXISTS into a hash anti-join whose hash side is every
    failed batch in the pruning window — that side scales with failure storms
    (millions of rows, rebuilt every sweep) while the probes scale with the
    candidate-run count.

    The ``OFFSET 0`` in the failed-run gate is an optimization fence: without
    it the planner flattens the subquery back into that same hash anti-join.
    It changes no semantics; the plan-shape test pins the probe.

    Loader progress anywhere in a (team_id, schema_id) group spares every run
    in it. The loader serializes a group and claims its batches oldest-first,
    so a run queued behind a long sibling makes no progress of its own until
    the sibling drains, however many hours that takes. An active-state
    transition in the group inside the stale window means the group is being
    drained and its other runs are waiting their turn, not abandoned. Only
    'executing', 'succeeded' and 'waiting_retry' count, as in
    ``supersede_other_runs``: a 'failed' write is the reconcile sweep's own
    output, and heartbeats refresh the status log but not ``state_changed_at``,
    so a wedged-but-heartbeating loader cannot shield a group forever (its live
    lease already protects it while it heartbeats). The group lease cannot
    stand in for this check: the loader releases it between claim windows, so
    a busy group is lease-less for an instant many times an hour. The probe
    runs once per group rather than once per run, because a genuinely stale
    group answers only after reading every batch it holds.
    """
    return f"""
        WITH stranded_runs AS (
            SELECT b.run_uuid, b.team_id, b.schema_id, MIN(b.created_at) AS oldest_created_at
            FROM {BATCH_TABLE} b
            WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
              AND b.created_at <= now() - make_interval(secs => %(stale)s)
              AND b.latest_state IN ('pending', 'waiting', 'waiting_retry', 'executing')
            GROUP BY b.run_uuid, b.team_id, b.schema_id
        ),
        progressing_groups AS (
            SELECT g.team_id, g.schema_id
            FROM (SELECT DISTINCT team_id, schema_id FROM stranded_runs) g
            WHERE EXISTS (
                SELECT 1 FROM {BATCH_TABLE} bp
                WHERE bp.team_id = g.team_id AND bp.schema_id = g.schema_id
                  AND bp.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                  AND bp.latest_state IN ('executing', 'succeeded', 'waiting_retry')
                  AND bp.state_changed_at > now() - make_interval(secs => %(stale)s)
            )
        )
        SELECT r.run_uuid, r.team_id, r.schema_id
        FROM stranded_runs r
        WHERE NOT EXISTS (
              SELECT 1 FROM {LEASE_TABLE} l
              WHERE l.team_id = r.team_id AND l.schema_id = r.schema_id
                AND l.expires_at > now()
          )
          AND NOT EXISTS (
              SELECT 1 FROM {BATCH_TABLE} bf
              WHERE bf.run_uuid = r.run_uuid
                AND bf.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                AND bf.latest_state = 'failed'
              OFFSET 0
          )
          AND NOT EXISTS (
              SELECT 1 FROM progressing_groups p
              WHERE p.team_id = r.team_id AND p.schema_id = r.schema_id
          )
        -- Oldest-batch-first, so the window can't be starved by an arbitrary set of
        -- not-yet-stale runs the outer HAVING later rejects: the longest-stranded runs
        -- always land in it, and successive sweeps make deterministic forward progress.
        ORDER BY r.oldest_created_at ASC
        LIMIT %(limit)s
    """


def _stale_executing_sql(scope_sql: str = "") -> str:
    """Shared body of the stale-executing sweep (async consumer and its sync ops twin).

    The denormalized-column pre-filter keeps the lateral probing only
    currently-executing batches. The lateral itself must stay: heartbeats
    refresh the status log, deliberately not the column, so the grace clock
    comes from ``s.created_at``. The observed ``state_changed_at`` rides along
    so the recovery sweep can compare-and-swap its re-queue against it.

    Bounded by ``CLAIM_ELIGIBILITY_INTERVAL``, matching the claim path: a
    recovered batch gets re-processed, which needs its parquet to still exist.
    """
    return f"""
        SELECT
            {pending_batch_select_columns("s")},
            b.state_changed_at
        FROM {BATCH_TABLE} b
        {latest_status_lateral("b", "s", join="INNER")}
        LEFT JOIN {LEASE_TABLE} l ON l.team_id = b.team_id AND l.schema_id = b.schema_id
        WHERE
            b.created_at > now() - interval '{CLAIM_ELIGIBILITY_INTERVAL}'
            AND b.latest_state = 'executing'
            AND s.job_state = 'executing'
            AND s.created_at <= now() - make_interval(secs => %(grace)s)
            AND (l.team_id IS NULL OR l.expires_at <= now())
            {scope_sql}
        ORDER BY b.created_at ASC, b.batch_index ASC
    """


@dataclass(frozen=False, slots=True)
class ClaimCursor:
    """Where one consumer's next claim starts its team window.

    Mutable on purpose: each claim moves it to the last team of the window it
    read, so consecutive claims rotate through every team that holds work.

    Pods that read the same windows compete for the same groups, so the
    position is spread at random where that costs no fairness: ``None`` makes
    the next claim start at a random team, and a claim whose window held the
    whole queue leaves the cursor on a random team of it. A claim that finds
    no team with work, or that fails, leaves ``None``.
    """

    team_id: int | None = None


@dataclass(frozen=True, slots=True)
class _ClaimedWindow:
    batches: list[PendingBatch]
    # None when no team holds a claim candidate.
    next_team_cursor: int | None
    # The window held CLAIM_WINDOW_TEAMS teams, so more teams can wait past it.
    full: bool
    # The walk passed the highest team and continued from the lowest.
    wrapped: bool


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
    # Snapshotted on the batch when the run started. Empty means the PostHog warehouse only.
    destination_ids: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    # Observed denormalized state clock at read time; None for sinks that don't surface it.
    state_changed_at: datetime | None = None

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
            "destination_ids": self.destination_ids or [],
            "external_destination_ids": self.metadata.get("external_destination_ids"),
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
class StrandedRunRef:
    """Identity of a run the loader abandoned: non-terminal batches, no live lease, no recent progress.

    Unlike ``FailedRunRef`` there is no ``failed`` queue batch — the extraction ended (workflow died
    or errored out) before a final batch, so nothing finalizes the run and ``get_failed_runs`` never
    sees it. The reconcile sweep fails these so they don't strand until the retention prune.
    """

    run_uuid: str
    job_id: str
    team_id: int
    schema_id: str
    workflow_run_id: str | None
    non_terminal_batches: int


@dataclass(frozen=True, slots=True)
class OrphanedRunRef:
    """A run holding a ``failed`` batch that still has non-terminal batches behind it.

    Carries no ``job_id``: the job is already terminal by the time a run reaches
    this state, so the only work left is terminalizing the queue rows.
    """

    run_uuid: str
    team_id: int
    schema_id: str
    non_terminal_batches: int


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
    latest_activity_at: datetime


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


@dataclass(frozen=True, slots=True)
class QueueFreshness:
    """What one freshness probe reads off the pending set.

    Three numbers rather than one because they fail differently: the age says
    how far the queue head has fallen behind, the blocked count says how much
    of the table can never move, and the group count says how widely the lag
    is spread. An alert on the age alone cannot tell one wedged tenant from a
    fleet-wide stall.
    """

    # None when nothing claimable is waiting.
    oldest_age_seconds: float | None
    blocked_batches: int
    backlogged_groups: int


@dataclass(frozen=True, slots=True)
class QueueDepth:
    """What one depth probe reads off the claimable set.

    The total alone cannot tell a few (team_id, schema_id) groups draining one
    batch at a time from a fleet that has run out of loader slots: the loader
    serializes each group by design, so a deep queue with idle slots is normal
    when the depth sits in a handful of groups. The other four numbers separate
    those two readings.
    """

    claimable_batches: int
    # The fields below are None when the breakdown statement timed out: the count
    # statement is much cheaper, so it can still land while a deep queue defeats
    # the per-run and per-group probes.
    claimable_groups: int | None
    # 0..1 share of those batches held by the DEPTH_TOP_GROUPS deepest groups; 0 when empty.
    top_groups_claimable_share: float | None
    # Batches whose group has nothing executing: they start as soon as a slot frees.
    slot_waiting_batches: int | None
    # Batches whose group already has a batch executing: they wait for their own group.
    serialized_batches: int | None


# Idle sync connections kept per queue DB for the worker-thread lease checks. Sized to the loader's
# group concurrency: every in-flight batch checks its lease a few times, and each check used to dial
# a fresh connection.
SYNC_POOL_MAX_IDLE = 16


class _SyncConnectionPool:
    """A small pool of autocommit connections for callers that run outside the event loop.

    Connections are handed out LIFO so the warm ones stay in use and are checked for liveness on
    the way out; one the server dropped while idle is closed instead of reused. Callers that hit an
    error mid-query discard the connection through `discard`, since the pool cannot tell a broken
    session from a healthy one until it fails.
    """

    def __init__(self, database_url: str, *, connect_timeout_seconds: int, max_idle: int = SYNC_POOL_MAX_IDLE) -> None:
        self._database_url = database_url
        self._connect_timeout_seconds = connect_timeout_seconds
        self._max_idle = max_idle
        self._lock = threading.Lock()
        self._idle: list[psycopg.Connection[Any]] = []

    def _checkout(self) -> psycopg.Connection[Any]:
        while True:
            with self._lock:
                conn = self._idle.pop() if self._idle else None
            if conn is None:
                return psycopg.connect(
                    self._database_url, autocommit=True, connect_timeout=self._connect_timeout_seconds
                )
            if not conn.closed and not conn.broken:
                return conn
            self._close_quietly(conn)

    def _checkin(self, conn: psycopg.Connection[Any]) -> None:
        if conn.closed or conn.broken:
            self._close_quietly(conn)
            return
        with self._lock:
            if len(self._idle) < self._max_idle:
                self._idle.append(conn)
                return
        self._close_quietly(conn)

    def discard(self, conn: psycopg.Connection[Any]) -> None:
        """Take `conn` out of circulation: the caller saw it fail and nothing should reuse it."""
        with self._lock:
            if conn in self._idle:
                self._idle.remove(conn)
        self._close_quietly(conn)

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[Any]]:
        conn = self._checkout()
        try:
            yield conn
        finally:
            if not conn.closed:
                self._checkin(conn)

    @property
    def idle_count(self) -> int:
        with self._lock:
            return len(self._idle)

    @staticmethod
    def _close_quietly(conn: psycopg.Connection[Any]) -> None:
        with suppress(Exception):
            conn.close()


_SYNC_POOLS: dict[tuple[str, int], _SyncConnectionPool] = {}
_SYNC_POOLS_LOCK = threading.Lock()


def _sync_connection_pool(database_url: str, connect_timeout_seconds: int) -> _SyncConnectionPool:
    key = (database_url, connect_timeout_seconds)
    with _SYNC_POOLS_LOCK:
        pool = _SYNC_POOLS.get(key)
        if pool is None:
            pool = _SyncConnectionPool(database_url, connect_timeout_seconds=connect_timeout_seconds)
            _SYNC_POOLS[key] = pool
        return pool


def _lease_is_held(conn: psycopg.Connection[Any], *, team_id: int, schema_id: str, owner_token: str) -> bool:
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


@asynccontextmanager
async def _gauge_cursor(
    conn: psycopg.AsyncConnection[Any], *, statement_timeout_ms: int
) -> AsyncIterator[psycopg.AsyncCursor[Any]]:
    """Cursor whose statements stop at ``statement_timeout_ms``; raises ``QueryCanceled`` past it.

    The timeout is transaction-local, so it never leaks into the session the
    caller shares with the sweeps (or into a pooled server connection).
    """
    async with conn.transaction():
        async with conn.cursor() as cur:
            await cur.execute("SELECT set_config('statement_timeout', %s, true)", (str(statement_timeout_ms),))
            yield cur


async def _try_acquire_fleet_slot(
    conn: psycopg.AsyncConnection[Any],
    *,
    schema_id: str,
    owner_token: str,
    ttl_seconds: int,
    reentrant: bool,
) -> bool:
    """CAS-acquire a sentinel lease row; True means this caller holds it until ``ttl_seconds`` pass."""
    reentry_clause = f" OR {LEASE_TABLE}.owner_token = excluded.owner_token" if reentrant else ""
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            INSERT INTO {LEASE_TABLE} (team_id, schema_id, owner_token, expires_at, acquired_at, updated_at)
            VALUES (%(team_id)s, %(schema_id)s, %(owner)s, now() + make_interval(secs => %(ttl)s), now(), now())
            ON CONFLICT (team_id, schema_id) DO UPDATE
                SET owner_token = excluded.owner_token,
                    expires_at = excluded.expires_at,
                    acquired_at = now(),
                    updated_at = now()
                WHERE {LEASE_TABLE}.expires_at <= now(){reentry_clause}
            RETURNING id
            """,
            {
                "team_id": RECONCILE_SWEEP_LEASE_TEAM_ID,
                "schema_id": schema_id,
                "owner": owner_token,
                "ttl": ttl_seconds,
            },
        )
        return await cur.fetchone() is not None


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
        sync_types: list[str] | None = None,
        exclude_sync_types: list[str] | None = None,
        cursor: ClaimCursor | None = None,
    ) -> list[PendingBatch]:
        """Fetch unprocessed batches whose (team_id, schema_id) group lease is claimable by ``owner_token``.

        Candidates come from the denormalized state columns, so poll cost
        tracks the claimable set rather than everything retained; candidates
        are also capped at ``CLAIM_ELIGIBILITY_INTERVAL`` old so a claimed
        batch's parquet is guaranteed to predate the retention sweep.

        Group ownership is a row in ``sourcegrouplease`` keyed by
        (team_id, schema_id). The outer query claims-or-renews the lease for
        each candidate group in a single writable CTE: a group is returned only
        when the lease is free (no row), already owned by ``owner_token``, or
        expired (a previous owner abandoned it). A live lease held by another
        pod fails the conditional ``DO UPDATE`` and that group's rows are
        dropped by the ``JOIN claimed``. This replaces the old session advisory
        lock so an abandoned group simply expires rather than wedging the fleet.

        Ranking runs over narrow ``(id, created_at)`` candidates and the wide
        rows are fetched only for the LIMIT winners (the ``candidates``
        join-back, ~LIMIT primary-key probes), so the fairness sort never
        handles full rows (see :func:`_state_claim_candidates_sql`). The
        candidates are a bounded window of teams, not the whole claimable set,
        and the run gate runs once per run, not once per candidate batch (see
        :func:`_claim_window_sql`).

        ``cursor`` carries the window position between the claims of one
        consumer. Without it every claim starts at the lowest team, which reads
        the whole queue only while it fits in one window. With it, a full
        window that gives no batch is not the answer: the call reads the next
        windows, up to ``CLAIM_MAX_EMPTY_WINDOWS`` or one turn over all teams.

        Uses a MATERIALIZED CTE so that candidate selection (with LIMIT) is
        fully resolved before the lease claim runs. ``candidate_groups`` is
        ``SELECT DISTINCT`` because ``INSERT ... ON CONFLICT DO UPDATE`` cannot
        affect the same (team_id, schema_id) row twice in one statement, and it
        is ordered and materialized so the upsert takes its lease-row locks in
        the fleet-wide order (see the lock-order note above).

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
        Across teams the order is oldest first among the teams of the claim's window.

        Disjoint windows across pods: groups live-leased by *another* owner are
        excluded from candidates entirely, not merely dropped at the claim step.
        Otherwise every pod computes the same top-``LIMIT`` window and groups
        already owned elsewhere occupy window slots that losing pods can never
        claim — with enough of them at the head of the queue the whole window is
        dead weight and fleet concurrency collapses to roughly one window's worth.
        Own-leased groups stay in the window so a pod can keep draining a group it
        already holds.

        ``sync_types`` / ``exclude_sync_types`` partition the queue between consumer
        fleets (see :func:`sync_type_scope_sql`); leases are shared state, so fleets
        with overlapping scopes still never process one group concurrently.
        """
        sync_type_scope, scope_params = sync_type_scope_sql(
            sync_types=sync_types, exclude_sync_types=exclude_sync_types
        )
        params = {
            "limit": limit,
            "backoff": retry_backoff_base_seconds,
            "owner": owner_token,
            "ttl": lease_ttl_seconds,
            **scope_params,
        }
        if cursor is None:
            return (await BatchQueue._claim_window(conn, sync_type_scope, {**params, "team_cursor": 0})).batches

        start = cursor.team_id if cursor.team_id is not None else await BatchQueue._random_team_cursor(conn)
        # A claim that fails or times out must not come back to the same window forever.
        cursor.team_id = None
        position = start
        wraps = 0
        for _ in range(CLAIM_MAX_EMPTY_WINDOWS):
            window = await BatchQueue._claim_window(conn, sync_type_scope, {**params, "team_cursor": position})
            if window.next_team_cursor is None:
                # No team holds work. The cursor stays unset, so the next claim picks a new random start.
                return []
            position = window.next_team_cursor
            wraps += window.wrapped
            full_turn = wraps > 1 or (wraps == 1 and position >= start)
            if window.batches or not window.full or full_turn:
                break
        cursor.team_id = position
        return window.batches

    @staticmethod
    async def _claim_window(
        conn: psycopg.AsyncConnection[Any], sync_type_scope: str, params: dict[str, Any]
    ) -> _ClaimedWindow:
        # The planner can price this statement above jit_above_cost although it runs in
        # milliseconds, and JIT compilation then costs far more than the statement. The
        # setting must be in place before the statement is planned, so it cannot be part of
        # it. The transaction holds only this one statement, so the lease upsert commits
        # as it does in autocommit. Consumer connections run with autocommit=True, so this
        # is the common case; a caller holding its own transaction gets a SAVEPOINT here
        # instead (psycopg nests `transaction()` blocks that way), so that caller's own
        # commit or rollback still governs the claim.
        async with conn.transaction():
            await conn.execute("SET LOCAL jit = off")
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    f"""
                    WITH {_claim_window_sql(sync_type_scope)},
                    candidates AS MATERIALIZED (
                        SELECT
                            b.id, b.team_id, b.schema_id, b.source_id, b.job_id,
                            b.run_uuid, b.batch_index, b.s3_path, b.row_count, b.byte_size,
                            b.is_final_batch, b.total_batches, b.total_rows, b.sync_type,
                            b.cumulative_row_count, b.resource_name, b.is_resume,
                            b.is_first_ever_sync, b.metadata, b.destination_ids,
                            b.latest_attempt,
                            b.created_at
                        FROM {BATCH_TABLE} b
                        JOIN narrow n ON n.id = b.id AND n.created_at = b.created_at
                    ),
                    candidate_groups AS MATERIALIZED (
                        SELECT DISTINCT team_id, schema_id FROM candidates
                        ORDER BY team_id, schema_id
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
                    ),
                    window_info AS (
                        SELECT
                            count(*) >= {CLAIM_WINDOW_TEAMS} AS window_full,
                            COALESCE(bool_or(t.wrapped), false) AS window_wrapped,
                            (array_agg(t.team_id ORDER BY t.n DESC))[1] AS last_team_id,
                            (array_agg(t.team_id ORDER BY random()))[1] AS random_team_id
                        FROM window_teams t
                    )
                    SELECT
                        CASE WHEN w.window_full THEN w.last_team_id ELSE w.random_team_id END AS next_team_cursor,
                        w.window_full,
                        w.window_wrapped,
                        c.*
                    FROM window_info w
                    LEFT JOIN (
                        candidates c
                        JOIN claimed ON claimed.team_id = c.team_id AND claimed.schema_id = c.schema_id
                    ) ON true
                    ORDER BY c.created_at ASC, c.batch_index ASC
                    """,
                    params,
                )
                rows = await cur.fetchall()
        # The window row is always present; the batch columns are NULL when nothing was claimed.
        next_team_cursor, full, wrapped = None, False, False
        for row in rows:
            next_team_cursor = row.pop("next_team_cursor")
            full = row.pop("window_full")
            wrapped = row.pop("window_wrapped")
        return _ClaimedWindow(
            batches=[PendingBatch(**row) for row in rows if row["id"] is not None],
            next_team_cursor=next_team_cursor,
            full=full,
            wrapped=wrapped,
        )

    @staticmethod
    async def _random_team_cursor(conn: psycopg.AsyncConnection[Any]) -> int:
        """A uniform point between the lowest and highest team_id that hold claimable-state batches."""
        cur = await conn.execute(
            f"""
            SELECT min(b.team_id), max(b.team_id)
            FROM {BATCH_TABLE} b
            WHERE b.created_at > now() - interval '{CLAIM_ELIGIBILITY_INTERVAL}'
                AND b.latest_state IN ('pending', 'waiting_retry')
            """
        )
        row = await cur.fetchone()
        if row is None or row[0] is None:
            return 0
        return random.randint(row[0] - 1, row[1])

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
    async def update_status_unless_failed(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int = 0,
        error_response: dict[str, Any] | None = None,
        batch_created_at: datetime | None = None,
        supersedable_failed_error: str | None = None,
        expected_state_changed_at: datetime | None | _Unset = _UNSET,
    ) -> bool:
        """Guarded twin of :meth:`update_status`: returns False (writing nothing) over
        a terminal 'failed' — see :func:`build_status_dual_write_unless_failed_sql`.

        ``expected_state_changed_at`` additionally arms a compare-and-swap on the
        observed ``state_changed_at`` (pass it, including a genuine ``None``, to
        require the state to be unchanged; leave it unset for an ordinary write): a
        stale requeue then writes nothing and returns False, same as a refused one."""
        arm_cas = not isinstance(expected_state_changed_at, _Unset)
        params: dict[str, Any] = {
            "batch_id": batch_id,
            "job_state": job_state,
            "attempt": attempt,
            "error_response": json.dumps(error_response) if error_response else None,
            "supersedable_failed_error": supersedable_failed_error,
        }
        if batch_created_at is not None:
            params["batch_created_at"] = batch_created_at
        if arm_cas:
            params["expected_state_changed_at"] = expected_state_changed_at
        cursor = await conn.execute(
            build_status_dual_write_unless_failed_sql(
                with_batch_created_at=batch_created_at is not None,
                with_expected_state_changed_at=arm_cas,
            ),
            params,
        )
        row = await cursor.fetchone()
        return bool(row and row[0])

    @staticmethod
    async def try_acquire_reconcile_sweep_slot(
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
        ttl_seconds: int = RECONCILE_SWEEP_SLOT_TTL_SECONDS,
    ) -> bool:
        """Claim the fleet-wide reconcile-sweep slot; True means this pod runs the sweep.

        A sentinel row in the group-lease table, CAS-acquired only when expired.
        There is deliberately no release and no same-owner re-entrancy clause:
        the TTL *is* the fleet-wide sweep cadence, so at most one sweep starts
        per TTL no matter how many pods (or how many startup sweeps after a
        restart wave) race for it. A lease row rather than a session advisory
        lock for the same reason as group claiming: a lingering pgbouncer
        session must not be able to hold the slot forever — a crashed winner's
        slot frees itself at expiry.
        """
        return await _try_acquire_fleet_slot(
            conn,
            schema_id=RECONCILE_SWEEP_LEASE_SCHEMA_ID,
            owner_token=owner_token,
            ttl_seconds=ttl_seconds,
            reentrant=False,
        )

    @staticmethod
    async def try_acquire_queue_gauges_slot(
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
        slot_key: str = QUEUE_GAUGES_LEASE_SCHEMA_ID_PREFIX,
        ttl_seconds: int = QUEUE_GAUGES_SLOT_TTL_SECONDS,
    ) -> bool:
        """Claim the gauge-sampling slot of one fleet; True means this pod samples the queue gauges.

        Unlike the sweep slot, the holder can renew its own live slot. The owner
        token is stable for the life of a consumer, and it asks once per reconcile
        interval. So when the interval is shorter than the TTL, the holder keeps
        the slot and samples on its own cadence. Without renewal it would lose its
        own slot to itself, and for the rest of the TTL no pod would sample.
        """
        return await _try_acquire_fleet_slot(
            conn,
            schema_id=slot_key,
            owner_token=owner_token,
            ttl_seconds=ttl_seconds,
            reentrant=True,
        )

    @staticmethod
    async def release_queue_gauges_slot(
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
        slot_key: str = QUEUE_GAUGES_LEASE_SCHEMA_ID_PREFIX,
    ) -> bool:
        """Delete the gauge slot row if ``owner_token`` still holds it; True means a row was deleted.

        One statement, so a pod that lost the slot to another pod cannot delete the
        new holder's row. After the delete, the next acquire inserts a fresh row at once.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                DELETE FROM {LEASE_TABLE}
                WHERE team_id = %(team_id)s AND schema_id = %(schema_id)s AND owner_token = %(owner)s
                RETURNING 1
                """,
                {"team_id": RECONCILE_SWEEP_LEASE_TEAM_ID, "schema_id": slot_key, "owner": owner_token},
            )
            return (await cur.fetchone()) is not None

    @staticmethod
    async def renew_lease(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
        lease_ttl_seconds: int = LEASE_TTL_SECONDS,
    ) -> bool:
        """Extend this owner's live group lease. Expiry is terminal: False means ownership
        is gone for good (row deleted, reclaimed, or expired) and the owner must abandon.

        The ``expires_at > now()`` predicate makes a lapsed lease unrenewable, so an owner
        whose lease expired (e.g. a >TTL queue-DB blip during a long write) can't resurrect
        it and finish over a batch the recovery sweep has already re-queued.

        One row per call, so this satisfies the lease lock order (see the note above)
        without doing anything: it can only ever wait, never hold one lease row while
        queueing for another."""
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE {LEASE_TABLE}
                SET expires_at = now() + make_interval(secs => %(ttl)s), updated_at = now()
                WHERE team_id = %(team_id)s AND schema_id = %(schema_id)s AND owner_token = %(owner)s
                  AND expires_at > now()
                RETURNING 1
                """,
                {"team_id": team_id, "schema_id": schema_id, "owner": owner_token, "ttl": lease_ttl_seconds},
            )
            return (await cur.fetchone()) is not None

    @staticmethod
    async def delete_expired_lease(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
    ) -> None:
        """Delete the group's lease only if it has already expired; a live lease never matches.

        The recovery sweep claims a corpse with this before re-queueing its batches, so a
        resurrecting owner's renew matches nothing even on pods still running the permissive
        (pre-expiry-fence) renew during a rollout.
        """
        await conn.execute(
            f"""
            DELETE FROM {LEASE_TABLE}
            WHERE team_id = %(team_id)s AND schema_id = %(schema_id)s AND expires_at <= now()
            """,
            {"team_id": team_id, "schema_id": schema_id},
        )

    @staticmethod
    async def verify_advisory_lock(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
    ) -> bool:
        """Check whether ``owner_token`` still holds a live group lease for (team_id, schema_id).

        Named ``verify_advisory_lock`` for interface continuity with the consumer engine;
        ownership is a lease row, not a session advisory lock.
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
        """Sync counterpart of verify_advisory_lock: the Delta write runs in a worker thread that
        can't share the group's async connection, so it borrows one from a small sync pool.

        A connection the queue DB dropped while idle (a pooler cull, a failover) surfaces as an
        OperationalError on first use; that connection is discarded and the query runs once more
        on a fresh one, so a stale pool entry cannot read as a lost lease.
        """
        pool = _sync_connection_pool(database_url, connect_timeout_seconds)
        for attempt in (1, 2):
            with pool.connection() as conn:
                try:
                    return _lease_is_held(conn, team_id=team_id, schema_id=schema_id, owner_token=owner_token)
                except psycopg.OperationalError:
                    pool.discard(conn)
                    if attempt == 2:
                        raise
        raise AssertionError("unreachable")

    @staticmethod
    async def get_stale_executing(
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int = 0,
        sync_types: list[str] | None = None,
        exclude_sync_types: list[str] | None = None,
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

        ``sync_types`` / ``exclude_sync_types`` keep a fleet's sweep on its own
        classes: each fleet judges staleness against its own grace, so a
        short-grace fleet must never re-queue a batch a long-grace fleet still
        considers mid-write.
        """
        sync_type_scope, scope_params = sync_type_scope_sql(
            sync_types=sync_types, exclude_sync_types=exclude_sync_types
        )
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_stale_executing_sql(sync_type_scope), {"grace": grace_seconds, **scope_params})
            rows = await cur.fetchall()

        return [PendingBatch(**row) for row in rows]

    @staticmethod
    async def fail_run(
        conn: psycopg.AsyncConnection[Any],
        *,
        run_uuid: str,
        team_id: int,
        schema_id: str,
        reason: str,
    ) -> int:
        """Mark every pending batch in a run as failed. Returns the count of batches failed."""
        cursor = await conn.execute(
            FAIL_RUN_SCOPED_SQL,
            {
                "run_uuid": run_uuid,
                "team_id": team_id,
                "schema_id": schema_id,
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
        progress_stale_seconds: int = TAKEOVER_STALE_THRESHOLD_SECONDS,
        spare_runs_with_progress: bool = True,
    ) -> int:
        """Mark non-terminal batches from *stalled* older runs of the same job as superseded.

        A run the loader is still working through is spared: any batch whose latest
        state is 'executing', 'succeeded', or 'waiting_retry' with ``state_changed_at``
        within ``progress_stale_seconds`` counts as loader progress. Superseding such a
        run destroys partially loaded work and, repeated on a timer, can re-enqueue a
        large table from zero forever while flooding the queue with failed rows. A run
        with no such write is genuinely stalled and still gets superseded, so dead runs
        recover here on the same clock as the stranded-run reconcile sweep.

        Progress is judged on active-state transitions only: 'pending'/'waiting' rows
        are producer output the loader never touched (superseding an unstarted backlog
        loses nothing, since this run re-enqueues equivalent data), and 'failed' is
        terminal. Heartbeats refresh only the status log, not ``state_changed_at``, so
        a wedged-but-heartbeating loader cannot keep a run unsupersedable forever.

        A spared run that stalls later is not re-checked here (this fires once, at the
        new run's first batch); the reconcile sweep's stranded-run pass owns that case.

        ``spare_runs_with_progress=False`` drops the sparing rule. Pass it when the
        incoming run overwrites the table regardless, which is a fresh non-resume
        ``full_refresh``: its batch 0 writes with ``mode="overwrite"`` (``should_overwrite_table``
        in ``load/processor.py``, applied in the full_refresh branch of ``core/delta/writer.py``),
        so every row an older attempt loaded is discarded the moment this run starts. Sparing
        those runs protects nothing, and leaves their batches to drain through the serial
        per-(team, schema) gate — holding the queue head for hours to write data that has
        already been thrown away. Incremental and CDC keep the sparing rule, because their
        partially merged work survives into the new run.
        """
        progress_guard = (
            f"""AND NOT EXISTS (
                    SELECT 1
                    FROM {BATCH_TABLE} b_live
                    WHERE b_live.run_uuid = b.run_uuid
                        AND b_live.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND b_live.latest_state IN ('executing', 'succeeded', 'waiting_retry')
                        AND b_live.state_changed_at > now() - make_interval(secs => %(progress_stale)s)
                )"""
            if spare_runs_with_progress
            else ""
        )
        cursor = conn.execute(
            _bulk_fail_dual_write_sql(
                f"""b.job_id = %(job_id)s AND b.run_uuid != %(current_run_uuid)s
                {progress_guard}"""
            ),
            {
                "job_id": job_id,
                "current_run_uuid": current_run_uuid,
                "progress_stale": progress_stale_seconds,
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
        already-reconciled runs outnumber ``limit`` within the lookback.

        Candidacy, the per-run pick, and the LIMIT run entirely off the
        denormalized batch columns: ``state_changed_at`` equals the failed
        status row's ``created_at`` (the dual-write CTEs guarantee it), and
        ``superseded`` mirrors the status payload's flag. The per-batch
        latest-status lateral this replaces was the sweep's melt-down under
        failure storms: each probe is a Merge Append across every status
        partition, and it ran once per failed batch in the window — 1.36M
        during the 2026-08 storm, minutes per sweep. The lateral now runs only
        for the ``LIMIT`` winners' error payloads.

        The post-LIMIT superseded re-check is the deploy-transition fence:
        failed rows written before the flag existed read ``superseded = false``
        until ``backfill_warehouse_queue_state reconcile`` has run, and
        reconciling such a run would fail an ExternalDataJob whose newer run is
        live. Until the backfill lands, those rows can occupy winner slots (the
        sweep returns fewer than ``limit`` refs), which only delays other
        reconciles to a later sweep.

        ``state_changed_at`` is nullable, and the NULL arm is exempt from the
        lookback only: batch ``created_at`` predates the failure, so a lookback
        measured on it would age such a row out while the run is still stranded
        (the stranded sweep skips runs that have a failed batch). Grace does
        apply to them, through that same ``created_at`` fallback, which also
        orders them. Every writer of ``latest_state = 'failed'`` also sets
        ``state_changed_at``, so the NULL arm matches only legacy rows.
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                WITH winners AS MATERIALIZED (
                    SELECT run_uuid, batch_id, batch_created_at, failed_at
                    FROM (
                        SELECT DISTINCT ON (b.run_uuid)
                            b.run_uuid, b.id AS batch_id, b.created_at AS batch_created_at,
                            COALESCE(b.state_changed_at, b.created_at) AS failed_at
                        FROM {BATCH_TABLE} b
                        WHERE
                            b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                            AND b.latest_state = 'failed'
                            AND NOT b.superseded
                            AND (b.state_changed_at IS NULL
                                 OR b.state_changed_at >= now() - make_interval(secs => %(lookback)s))
                            AND COALESCE(b.state_changed_at, b.created_at)
                                <= now() - make_interval(secs => %(grace)s)
                        ORDER BY b.run_uuid, COALESCE(b.state_changed_at, b.created_at) DESC
                    ) ranked
                    ORDER BY failed_at DESC
                    LIMIT %(limit)s
                )
                SELECT b.run_uuid, b.job_id, b.team_id, b.schema_id, b.metadata, s.error_response
                FROM winners w
                JOIN {BATCH_TABLE} b ON b.id = w.batch_id AND b.created_at = w.batch_created_at
                {latest_status_lateral("b", "s", join="INNER")}
                WHERE s.job_state = 'failed'
                  AND COALESCE((s.error_response->>'superseded')::boolean, false) = false
                ORDER BY w.failed_at DESC
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
    async def get_runs_with_orphaned_batches(
        conn: psycopg.AsyncConnection[Any],
        *,
        limit: int,
    ) -> list[OrphanedRunRef]:
        """Runs that hold a ``failed`` batch and still have non-terminal batches behind it.

        Those batches are stuck in both directions: the claim query refuses any
        run with a failed batch, and the stranded sweep excludes the same runs
        because ``get_failed_runs`` is supposed to own them. It cannot reach all
        of them. It is ``ORDER BY failed_at DESC LIMIT n`` inside a lookback,
        with no gate for runs it has already swept, so every sweep re-picks the
        same newest runs; once a failure ages past the lookback its leftovers
        are unreachable until the retention prune, days later.

        This pass closes that gap and cannot starve: oldest-first, and a run
        leaves the set as soon as its batches go terminal. Normally it returns
        nothing — the set is non-empty only when the newest-first pass has
        fallen behind.

        Shaped like :func:`_stranded_candidate_runs_sql`: aggregate the bounded
        claimable scan into runs first, then one ``sb_run_gate_idx`` probe per
        candidate run. Gating the raw batch rows instead turns the failed probe
        into a hash anti-join whose hash side is every failed batch in the
        window, which is exactly the shape that melted down under a failure
        storm. The ``OFFSET 0`` fence is what holds the probe shape.

        The candidate states are exactly ``sb_claimable_idx``'s, and must stay
        that way. Widening them to every non-terminal state (adding 'waiting'
        and 'executing') puts the scan outside that partial index, and the
        planner answers it with a parallel sequential scan of every partition
        instead — 12x the cost on the production queue, once every reconcile
        interval. It also loses nothing: a blocked batch is one no consumer
        could claim, and 'executing' rows belong to the stale-executing sweep.
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(_orphaned_candidate_runs_sql(), {"limit": limit})
            rows = await cur.fetchall()

        return [
            OrphanedRunRef(
                run_uuid=row["run_uuid"],
                team_id=row["team_id"],
                schema_id=row["schema_id"],
                non_terminal_batches=row["non_terminal_batches"],
            )
            for row in rows
        ]

    @staticmethod
    async def get_stale_stranded_runs(
        conn: psycopg.AsyncConnection[Any],
        *,
        stale_seconds: int,
        limit: int,
    ) -> list[StrandedRunRef]:
        """Runs the loader abandoned: non-terminal batches, no live lease, no loader progress for ``stale_seconds``.

        Complements ``get_failed_runs``, which only sees runs with a ``failed`` batch. When an
        extraction workflow dies mid-run its batches are left non-terminal with no failed batch and
        the ExternalDataJob stuck RUNNING; lock takeover only fires on the next scheduled run, so
        without this the batches strand until the retention prune (days later).

        Staleness is *loader progress only*: the newest status write across the run, or — when the
        loader never claimed anything — the oldest batch's age. Progress on any sibling run of the same
        (team_id, schema_id) group also spares the run: the loader drains a group one run at a time, so
        a run queued behind a long sibling is waiting, not abandoned. Batch inserts (producer activity)
        deliberately do not reset the clock, mirroring ``get_run_activity_summary``, so a live producer
        streaming into a dead loader still reads as stale. A live group lease means a pod is actively
        working the group (making progress, or the recovery sweep reclaims it on lease expiry), so those
        are excluded. Runs with a ``failed`` batch are excluded — ``get_failed_runs`` owns those.

        Seeded from the bounded non-terminal scan aggregated into runs, gated per run
        (oldest-batch-first, so the bounded candidate window always holds the
        longest-stranded runs rather than an arbitrary set — see
        :func:`_stranded_candidate_runs_sql`), then the full-run lateral confirms
        staleness, so a slow-but-live run (recent success, momentarily between lease
        renewals) is not swept.
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                WITH candidates AS (
                    {_stranded_candidate_runs_sql()}
                )
                SELECT
                    b.run_uuid,
                    b.team_id,
                    b.schema_id,
                    MAX(b.job_id) AS job_id,
                    MAX(b.metadata->>'workflow_run_id') AS workflow_run_id,
                    COUNT(*) FILTER (WHERE {pending_batch_predicate("s")}) AS non_terminal_batches
                FROM {BATCH_TABLE} b
                JOIN candidates c
                    ON c.run_uuid = b.run_uuid AND c.team_id = b.team_id AND c.schema_id = b.schema_id
                {latest_status_lateral("b", "s")}
                WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                GROUP BY b.run_uuid, b.team_id, b.schema_id
                HAVING COALESCE(MAX(s.created_at), MIN(b.created_at)) <= now() - make_interval(secs => %(stale)s)
                ORDER BY MIN(b.created_at) ASC
                """,
                {"stale": stale_seconds, "limit": limit},
            )
            rows = await cur.fetchall()

        return [
            StrandedRunRef(
                run_uuid=row["run_uuid"],
                job_id=row["job_id"],
                team_id=row["team_id"],
                schema_id=row["schema_id"],
                workflow_run_id=row["workflow_run_id"],
                non_terminal_batches=row["non_terminal_batches"],
            )
            for row in rows
        ]

    @staticmethod
    async def get_queue_freshness(
        conn: psycopg.AsyncConnection[Any],
        *,
        backlog_threshold_seconds: int,
        statement_timeout_ms: int = GAUGE_STATEMENT_TIMEOUT_MS,
    ) -> QueueFreshness:
        """Three readings off one scan of the pending set, bounded to ``FRESHNESS_WINDOW``.

        ``oldest_age_seconds`` excludes batches whose run already holds a
        ``failed`` batch. The claim query refuses those (see
        ``_state_claim_candidates_sql``) and the stranded sweep skips them too,
        so nothing can ever pick them up: counting them made the gauge report
        the age of an abandoned row rather than the queue's lag, and it grew at
        exactly one second per second until retention pruned it.
        ``get_oldest_non_terminal_batch_age_seconds`` already excludes them for
        the same reason.

        ``blocked_batches`` keeps that excluded population visible in its own
        lane, so a leak still shows up somewhere instead of disappearing.

        ``backlogged_groups`` is the breadth companion to the age: the age is a
        fleet-wide max, so one wedged (team, schema) pins it and a fleet-wide
        alert cannot tell one stuck tenant from a real stall. Counting the
        groups past the threshold separates those.

        Raises ``psycopg.errors.QueryCanceled`` past ``statement_timeout_ms``.
        """
        async with _gauge_cursor(conn, statement_timeout_ms=statement_timeout_ms) as cur:
            await cur.execute(_queue_freshness_sql(), {"backlog_threshold": backlog_threshold_seconds})
            row = await cur.fetchone()
        if row is None:
            return QueueFreshness(oldest_age_seconds=None, blocked_batches=0, backlogged_groups=0)
        return QueueFreshness(
            oldest_age_seconds=float(row[0]) if row[0] is not None else None,
            blocked_batches=int(row[1] or 0),
            backlogged_groups=int(row[2] or 0),
        )

    @staticmethod
    async def get_queue_depth(
        conn: psycopg.AsyncConnection[Any],
        *,
        statement_timeout_ms: int = GAUGE_STATEMENT_TIMEOUT_MS,
    ) -> QueueDepth:
        """How many batches are state-eligible for claiming right now, and where they sit.

        The depth companion to :meth:`get_queue_freshness`. ``claimable_batches``
        applies none of the claim's per-run, schema-busy, or lease gates (those
        need per-row probes, and this must stay one index-only count), nor the
        retry-backoff gate (it needs the fleet's backoff config, and this probe
        stays parameter-free), so the count reads slightly high. Bounded by
        ``CLAIM_ELIGIBILITY_INTERVAL`` to match what the claim query can see.

        The other four fields exclude batches whose run holds a failed batch, the
        same population :meth:`get_queue_freshness` reports as ``blocked_batches``,
        so ``slot_waiting_batches + serialized_batches`` is the depth minus those.
        See :func:`_queue_depth_sql` for why.

        Two statements, each with its own ``statement_timeout_ms``. A timeout in
        the count raises ``psycopg.errors.QueryCanceled``. A timeout in the
        breakdown returns the count with the four other fields set to None.
        """
        async with _gauge_cursor(conn, statement_timeout_ms=statement_timeout_ms) as cur:
            await cur.execute(_claimable_count_sql())
            count_row = await cur.fetchone()
        claimable_batches = int(count_row[0]) if count_row else 0
        try:
            async with _gauge_cursor(conn, statement_timeout_ms=statement_timeout_ms) as cur:
                await cur.execute(_queue_depth_sql(), {"top_groups": DEPTH_TOP_GROUPS})
                row = await cur.fetchone()
        except psycopg.errors.QueryCanceled:
            return QueueDepth(
                claimable_batches=claimable_batches,
                claimable_groups=None,
                top_groups_claimable_share=None,
                slot_waiting_batches=None,
                serialized_batches=None,
            )
        if row is None:
            return QueueDepth(
                claimable_batches=claimable_batches,
                claimable_groups=0,
                top_groups_claimable_share=0.0,
                slot_waiting_batches=0,
                serialized_batches=0,
            )
        live_batches = int(row[1])
        return QueueDepth(
            claimable_batches=claimable_batches,
            claimable_groups=int(row[0]),
            top_groups_claimable_share=int(row[2]) / live_batches if live_batches else 0.0,
            slot_waiting_batches=int(row[3]),
            serialized_batches=int(row[4]),
        )

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
        Runs containing a 'failed' batch are excluded, mirroring the loader's claim
        gate: their remaining batches can never be claimed (a batch enqueued into a
        run after ``fail_run`` swept it stays 'pending' forever — seen in production),
        so counting them would hold the backpressure guard down for the whole pruning
        window. Sync because its caller is the CDC producer's backpressure guard,
        which runs in synchronous activity code. Bounded to the pruning window —
        older batches are gone anyway.
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
                  AND NOT EXISTS (
                      SELECT 1
                      FROM {BATCH_TABLE} b_failed
                      WHERE b_failed.run_uuid = b.run_uuid
                          AND b_failed.team_id = b.team_id
                          AND b_failed.schema_id = b.schema_id
                          AND b_failed.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                          AND b_failed.latest_state = 'failed'
                  )
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

        The ordered ``FOR UPDATE`` sub-select takes every row lock before the
        delete runs, so this honors the fleet-wide lease lock order (see the
        note above). A bare multi-row ``DELETE`` locks in plan order instead,
        which is what let this statement deadlock against a concurrent claim.
        """
        pairs = sorted({(b.team_id, b.schema_id) for b in batches})
        if not pairs:
            return
        team_ids = [team_id for team_id, _ in pairs]
        schema_ids = [schema_id for _, schema_id in pairs]
        await conn.execute(
            f"""
            DELETE FROM {LEASE_TABLE}
            WHERE id IN (
                SELECT l.id
                FROM {LEASE_TABLE} l
                WHERE l.owner_token = %(owner)s
                  AND (l.team_id, l.schema_id) IN (
                      SELECT * FROM unnest(%(team_ids)s::bigint[], %(schema_ids)s::varchar[])
                  )
                ORDER BY l.team_id, l.schema_id
                FOR UPDATE
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
        """Delete every group lease held by ``owner_token``. Used for best-effort cleanup on shutdown.

        Ordered ``FOR UPDATE`` for the same reason as :meth:`unlock_for_batches`: a pod
        shutting down releases many groups at once, against a fleet still claiming them.
        """
        await conn.execute(
            f"""
            DELETE FROM {LEASE_TABLE}
            WHERE id IN (
                SELECT id
                FROM {LEASE_TABLE}
                WHERE owner_token = %(owner)s
                ORDER BY team_id, schema_id
                FOR UPDATE
            )
            """,
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
        scope_sql, params = scope_filters(team_id=team_id, schema_ids=schema_ids, run_uuid=run_uuid)
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
        scope_sql, params = scope_filters(team_id=team_id, schema_ids=schema_ids)
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
        scope_sql, params = scope_filters(team_id=team_id, schema_ids=schema_ids, alias="l")
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
        ordered = sorted(pairs)
        cursor = conn.execute(
            f"""
            DELETE FROM {LEASE_TABLE}
            WHERE id IN (
                SELECT l.id
                FROM {LEASE_TABLE} l
                WHERE (l.team_id, l.schema_id) IN (
                    SELECT * FROM unnest(%(team_ids)s::bigint[], %(schema_ids)s::varchar[])
                )
                ORDER BY l.team_id, l.schema_id
                FOR UPDATE
            )
            """,
            {
                "team_ids": [team_id for team_id, _ in ordered],
                "schema_ids": [schema_id for _, schema_id in ordered],
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
        scope_sql, params = scope_filters(team_id=team_id, schema_ids=schema_ids)
        params["grace"] = grace_seconds
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_stale_executing_sql(scope_sql), params)
            rows = cur.fetchall()
        return [PendingBatch(**row) for row in rows]


def scope_filters(
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
