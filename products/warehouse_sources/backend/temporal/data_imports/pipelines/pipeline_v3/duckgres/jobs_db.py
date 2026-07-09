from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import psycopg
from psycopg.rows import dict_row

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.batch_kind import (
    LIVE_BATCH_SQL_PREDICATE,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    LEASE_TTL_SECONDS,
    PARTITION_PRUNING_INTERVAL,
    STATUS_TABLE,
    PendingBatch,
    pending_batch_select_columns,
)

DUCKGRES_STATUS_TABLE = "sourcebatchduckgresstatus"
# Latest-status view, still consumed by the reset_duckgres_failed_runs management
# command. The eligibility queries here use per-batch LATERAL lookups instead.
DUCKGRES_STATUS_VIEW = "v_latest_source_batch_duckgres_status"
DUCKGRES_APPLY_TABLE = "sourcebatchduckgresapply"
# Twin of the delta queue's sourcegrouplease — separate table because both
# consumers process the same (team_id, schema_id) groups and must never contend.
DUCKGRES_LEASE_TABLE = "sourceduckgresgrouplease"


def _latest_status_lateral(status_table: str, batch_alias: str) -> str:
    """Latest status row for one batch via the (batch_id, created_at DESC, id DESC)
    index. Drop-in for a join to the DISTINCT ON v_latest_source_batch* view, but a
    per-batch lookup instead of materializing the whole view. SELECTs `_ls.*` so all
    downstream <alias>.<col> references (job_state, created_at, attempt, batch_id) work.

    The created_at bound exists for partition pruning, mirroring the delta queue's
    `latest_status_lateral`: both status tables are range-partitioned by created_at,
    and without the predicate every probe descends into every partition. A batch's
    status rows are always written within the queue's retention horizon, so the
    2x-retention bound cannot hide a live row."""
    return (
        f"LATERAL (SELECT _ls.* FROM {status_table} _ls "
        f"WHERE _ls.batch_id = {batch_alias}.id "
        f"AND _ls.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}' "
        f"ORDER BY _ls.created_at DESC, _ls.id DESC LIMIT 1)"
    )


# Server-side guard for the heavy eligibility-CTE maintenance queries (supersede
# + backlog): each scans PARTITION_PRUNING_INTERVAL of sourcebatch per enabled
# team, and on a high-volume org an unbounded run can saturate the shared queue
# DB. Worse, every ~30s poll starts another, so slow runs stack into many
# concurrent multi-hour scans that also starve the Delta consumer on the same
# DB. Cap each statement so a slow query fails fast and the poll loop retries on
# the next tick instead of wedging. Tune up if a legitimate run needs longer.
ELIGIBILITY_QUERY_STATEMENT_TIMEOUT_MS = 30_000


@asynccontextmanager
async def _statement_timeout(conn: psycopg.AsyncConnection[Any], timeout_ms: int) -> AsyncIterator[None]:
    """Bound the wrapped query with a server-side ``statement_timeout``.

    The consumer connection is autocommit, so ``SET LOCAL`` needs an explicit
    transaction; it scopes the timeout to this block and resets it on exit.
    """
    async with conn.transaction():
        await conn.execute(f"SET LOCAL statement_timeout = {int(timeout_ms)}")
        yield


# Structured classification key written into duckgres status error_response by
# every terminal-retire writer. Consumers (the backfill reconciler) dispatch on
# this, not on error-message prose.
RETIRE_KIND_SUPERSEDED_BY_REPLACE = "superseded_by_replace"

# A LIVE batch held back because its schema's history is not yet primed.
# Replace-head runs bypass the block: they rebuild the table from scratch, so
# applying them to an unprimed schema is always safe — and they are the
# healing path for schemas parked in NEEDS_RESYNC. Single definition, used by
# both the eligibility gate and the backlog split. Expects %(blocked_schema_ids)s.
BLOCKED_LIVE_BATCH_CONDITION = f"""(
                            %(blocked_schema_ids)s::varchar[] IS NOT NULL
                            AND b.schema_id = ANY(%(blocked_schema_ids)s)
                            AND {LIVE_BATCH_SQL_PREDICATE}
                            AND NOT EXISTS (
                                SELECT 1
                                FROM {BATCH_TABLE} bh
                                WHERE bh.run_uuid = b.run_uuid
                                    AND bh.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                                    AND bh.batch_index = 0
                                    AND bh.is_final_batch = false
                                    AND bh.is_resume = false
                                    AND (
                                        bh.sync_type = 'full_refresh'
                                        OR (bh.sync_type = 'incremental' AND bh.is_first_ever_sync)
                                    )
                            )
                        )"""

# Shared CTE prelude for eligibility queries (note the trailing comma — callers
# append their own CTEs/SELECT). Expects a %(team_ids)s bigint[] parameter
# (NULL = no team filter).
#
# - cand_runs: runs with pending duckgres work — a delta-succeeded batch that is
#   not yet duckgres-succeeded. This is the driving set: every run the gate or
#   supersede logic compares (candidates incl. final-batch markers, incomplete
#   runs, replace_heads, victims) is delta-succeeded-and-not-duckgres-succeeded,
#   hence a member of cand_runs. run_starts/failed_runs scope to it so the work
#   the queries do is bounded by the live backlog, not the whole 14-day window.
# - run_starts: per-run start time, the total order used for cross-run gating
#   (run_uuid tiebreak makes it total even for identical timestamps).
# - failed_runs: runs terminally excluded from the sink — Delta-failed or
#   Duckgres-failed (including superseded).
# - incomplete_runs: non-failed runs that still owe unapplied data batches;
#   these block newer runs of the same schema (cross-run head-of-line).
ELIGIBILITY_CTES = f"""cand_runs AS MATERIALIZED (
                    -- Runs with pending duckgres work: a delta-succeeded batch that is not yet
                    -- duckgres-succeeded. Superset of every run the gate/supersede compares;
                    -- run_starts/failed_runs scope to it so the work is bounded by the backlog.
                    SELECT DISTINCT cb.run_uuid
                    FROM {BATCH_TABLE} cb
                    JOIN {_latest_status_lateral(STATUS_TABLE, "cb")} cds ON cds.job_state = 'succeeded'
                    LEFT JOIN {_latest_status_lateral(DUCKGRES_STATUS_TABLE, "cb")} cdgs ON true
                    WHERE cb.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR cb.team_id = ANY(%(team_ids)s))
                        AND (cdgs.job_state IS NULL OR cdgs.job_state <> 'succeeded')
                ),
                run_starts AS MATERIALIZED (
                    SELECT b_rs.run_uuid, min(b_rs.created_at) AS started_at
                    FROM {BATCH_TABLE} b_rs
                    WHERE b_rs.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR b_rs.team_id = ANY(%(team_ids)s))
                        AND b_rs.run_uuid IN (SELECT run_uuid FROM cand_runs)
                    GROUP BY b_rs.run_uuid
                ),
                failed_runs AS MATERIALIZED (
                    SELECT cr.run_uuid FROM cand_runs cr
                    WHERE EXISTS (
                        SELECT 1 FROM {BATCH_TABLE} fb
                        JOIN {_latest_status_lateral(STATUS_TABLE, "fb")} fds ON true
                        WHERE fb.run_uuid = cr.run_uuid
                            AND fb.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                            AND (%(team_ids)s::bigint[] IS NULL OR fb.team_id = ANY(%(team_ids)s))
                            AND fds.job_state = 'failed'
                    )
                    OR EXISTS (
                        SELECT 1 FROM {BATCH_TABLE} fb
                        JOIN {_latest_status_lateral(DUCKGRES_STATUS_TABLE, "fb")} fdgs ON true
                        WHERE fb.run_uuid = cr.run_uuid
                            AND fb.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                            AND (%(team_ids)s::bigint[] IS NULL OR fb.team_id = ANY(%(team_ids)s))
                            AND fdgs.job_state = 'failed'
                    )
                ),
                incomplete_runs AS MATERIALIZED (
                    SELECT old.team_id, old.schema_id, old.run_uuid, rs_ir.started_at,
                           bool_or((old.metadata->>'duckgres_backfill') IS NOT NULL) AS is_backfill_run
                    FROM {BATCH_TABLE} old
                    JOIN {_latest_status_lateral(STATUS_TABLE, "old")} ods ON ods.job_state = 'succeeded'
                    JOIN run_starts rs_ir ON rs_ir.run_uuid = old.run_uuid
                    LEFT JOIN {DUCKGRES_APPLY_TABLE} oa
                        ON oa.team_id = old.team_id
                        AND oa.schema_id = old.schema_id
                        AND oa.run_uuid = old.run_uuid
                        AND oa.batch_index = old.batch_index
                    WHERE old.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR old.team_id = ANY(%(team_ids)s))
                        AND old.is_final_batch = false
                        AND oa.id IS NULL
                        AND old.run_uuid NOT IN (SELECT run_uuid FROM failed_runs)
                    GROUP BY old.team_id, old.schema_id, old.run_uuid, rs_ir.started_at
                ),"""


class DuckgresBatchQueue:
    @staticmethod
    async def get_delta_succeeded_and_lock(
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
        limit: int = 50,
        retry_backoff_base_seconds: int = 0,
        team_ids: list[int] | None = None,
        blocked_schema_ids: list[str] | None = None,
        eligible_schema_ids: list[str] | None = None,
        lease_ttl_seconds: int = LEASE_TTL_SECONDS,
        max_groups: int | None = None,
        exclude_groups: list[tuple[int, str]] | None = None,
    ) -> list[PendingBatch]:
        """Fetch Duckgres-eligible batches whose Delta load has succeeded.

        Duckgres has its own sink state. A source batch is eligible only after the
        Delta consumer marks that exact batch row as succeeded.

        Group ownership is a ``sourceduckgresgrouplease`` row per
        (team_id, schema_id), claimed-or-renewed in the writable CTE like the
        delta queue's lease claim: free, own, or expired leases are claimable;
        another pod's live lease drops the group via ``JOIN claimed``. Unlike
        the old session advisory lock, an abandoned group simply expires.

        Mixed-version rollout is a single cutover (as with the delta queue's
        migration): the claim is pacing, not correctness — concurrent
        processors are arbitrated per batch by the duckgres-side apply marker
        (``DuckgresBatchAlreadyAppliedError``, a handled no-op). We deliberately
        do NOT probe the old advisory lock: a zombie session holding it would
        wedge the group indefinitely, the failure mode leases remove.

        ``retry_backoff_base_seconds`` gates the ``waiting_retry`` branch on the age
        of the latest Duckgres status row, mirroring the Delta queue's backoff.

        ``team_ids`` restricts eligibility to duckgres-enabled teams (None = no
        filter, for tests/dev). The sink must never claim batches for orgs without
        a Duckgres deployment — they would burn retries and fail runs for nothing.

        ``blocked_schema_ids`` excludes LIVE batches for schemas whose history is
        not yet primed into duckgres (backfill pending/in-flight) — the schema's
        own backfill-run batches (metadata.duckgres_backfill) pass through.

        ``eligible_schema_ids`` restricts the claim to schemas whose source is on
        warehouse-pipelines-v3 (None = no filter, for tests/dev). This keeps the
        sink in lockstep with the v3 routing flag: the shared queue can hold
        batches for non-v3 source types (an earlier flag window, or the
        flag-independent CDC writer), and without this gate the team-scoped claim
        would apply them — including replace-head batches that bypass the unprimed
        block. Computed by ``sink_eligible_schema_ids``.

        Intra-run head-of-line: LIVE batches stay strictly ordered (any
        unapplied lower batch_index blocks). Backfill CHUNKS relax this so a
        whole run drains in one claim: a pending predecessor blocks a chunk
        only when it cannot be returned AHEAD of it in this same fetch (see the
        gate's inline comments). Co-claimable predecessors sort earlier, land
        in the same group, and the group is processed strictly in order with a
        halt on first non-success — so chunk 0's CREATE still applies first.

        Cross-run head-of-line: a batch is ineligible while an older run (by run
        start time) of the same (team_id, schema_id) still has unapplied,
        non-failed data batches. Without this, a newer run's batch-0
        CREATE OR REPLACE could interleave with an older run's remaining
        inserts/merges and permanently mix two runs' rows in the Duckgres table.
        Liveness: older runs either complete, fail (max attempts), or are
        superseded by ``supersede_replaced_runs`` — all three unblock the gate.
        """
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                WITH {ELIGIBILITY_CTES}
                candidates AS MATERIALIZED (
                    SELECT
                        {pending_batch_select_columns("dgs")}
                    FROM {BATCH_TABLE} b
                    JOIN {_latest_status_lateral(STATUS_TABLE, "b")} ds ON true
                    JOIN run_starts rs_b ON rs_b.run_uuid = b.run_uuid
                    LEFT JOIN {_latest_status_lateral(DUCKGRES_STATUS_TABLE, "b")} dgs ON true
                    WHERE
                        b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR b.team_id = ANY(%(team_ids)s))
                        AND (%(eligible_schema_ids)s::varchar[] IS NULL OR b.schema_id = ANY(%(eligible_schema_ids)s))
                        -- In-flight groups: re-claiming them burns the LIMIT and
                        -- max_groups budget on work this pod can't start.
                        AND NOT (
                            %(exclude_team_ids)s::bigint[] IS NOT NULL
                            AND (b.team_id, b.schema_id) IN (
                                SELECT * FROM unnest(%(exclude_team_ids)s::bigint[], %(exclude_schema_ids)s::varchar[])
                            )
                        )
                        -- Other pods' live-leased groups are unclaimable; filter
                        -- BEFORE the LIMIT or one leased backfill can fill the
                        -- window and starve other schemas.
                        AND NOT EXISTS (
                            SELECT 1 FROM {DUCKGRES_LEASE_TABLE} bl
                            WHERE bl.team_id = b.team_id
                                AND bl.schema_id = b.schema_id
                                AND bl.expires_at > now()
                                AND bl.owner_token <> %(owner)s
                        )
                        AND NOT {BLOCKED_LIVE_BATCH_CONDITION}
                        AND ds.job_state = 'succeeded'
                        AND (
                            dgs.batch_id IS NULL
                            OR (
                                dgs.job_state = 'waiting_retry'
                                AND dgs.created_at <= now() - make_interval(
                                    secs => %(backoff)s * GREATEST(COALESCE(dgs.attempt, 1), 1)
                                )
                            )
                        )
                        AND (
                            -- Self-apply exclusion, scoped to statusless batches: an
                            -- applied batch with no duckgres status row must not be
                            -- re-claimed. A batch stranded in waiting_retry AFTER its
                            -- apply marker landed (crash between mark_applied and the
                            -- 'succeeded' write) stays claimable on purpose: its no-op
                            -- pass converges the status to 'succeeded'.
                            b.is_final_batch = true
                            OR dgs.batch_id IS NOT NULL
                            OR NOT EXISTS (
                                SELECT 1
                                FROM {DUCKGRES_APPLY_TABLE} current_apply
                                WHERE current_apply.team_id = b.team_id
                                    AND current_apply.schema_id = b.schema_id
                                    AND current_apply.run_uuid = b.run_uuid
                                    AND current_apply.batch_index = b.batch_index
                            )
                        )
                        AND b.run_uuid NOT IN (SELECT run_uuid FROM failed_runs)
                        AND NOT EXISTS (
                            SELECT 1
                            FROM {BATCH_TABLE} prev
                            LEFT JOIN {DUCKGRES_APPLY_TABLE} a
                                ON a.team_id = prev.team_id
                                AND a.schema_id = prev.schema_id
                                AND a.run_uuid = prev.run_uuid
                                AND a.batch_index = prev.batch_index
                            LEFT JOIN {_latest_status_lateral(STATUS_TABLE, "prev")} ds_prev ON true
                            LEFT JOIN {_latest_status_lateral(DUCKGRES_STATUS_TABLE, "prev")} dgs_prev ON true
                            WHERE prev.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                                AND prev.team_id = b.team_id
                                AND prev.schema_id = b.schema_id
                                AND prev.run_uuid = b.run_uuid
                                AND prev.is_final_batch = false
                                AND (
                                    prev.batch_index < b.batch_index
                                    OR (b.is_final_batch = true AND prev.batch_index <= b.batch_index)
                                )
                                AND a.id IS NULL
                                AND (
                                    -- LIVE batches: any unapplied predecessor blocks.
                                    {LIVE_BATCH_SQL_PREDICATE}
                                    -- Backfill chunks: block only on predecessors that
                                    -- cannot be co-claimed AHEAD of this chunk —
                                    -- not delta-succeeded (fail closed; enqueue_chunks
                                    -- writes chunks pre-succeeded atomically):
                                    OR ds_prev.job_state IS DISTINCT FROM 'succeeded'
                                    -- sorting later in the fetch order (a reconcile
                                    -- replay re-inserts dropped chunks with a fresh
                                    -- created_at):
                                    OR (prev.created_at, prev.batch_index) > (b.created_at, b.batch_index)
                                    OR dgs_prev.job_state = 'executing'
                                    OR dgs_prev.job_state = 'succeeded'
                                    OR (
                                        dgs_prev.job_state = 'waiting_retry'
                                        AND dgs_prev.created_at > now() - make_interval(
                                            secs => %(backoff)s * GREATEST(COALESCE(dgs_prev.attempt, 1), 1)
                                        )
                                    )
                                )
                        )
                        AND (
                            -- Cross-run head-of-line: an older non-failed run of this
                            -- schema still has unapplied data batches. Applies to LIVE
                            -- batches only: a backfill run is ordered manually —
                            -- batches provably contained in its Delta snapshot are
                            -- pre-applied at plan time, and anything not contained must
                            -- apply AFTER the swap, so it must not gate the chunks. Live
                            -- batches still queue behind the backfill run itself via
                            -- this same check.
                            NOT EXISTS (
                                SELECT 1
                                FROM incomplete_runs ir
                                WHERE ir.team_id = b.team_id
                                    AND ir.schema_id = b.schema_id
                                    AND ir.run_uuid <> b.run_uuid
                                    AND (ir.started_at, ir.run_uuid) < (rs_b.started_at, b.run_uuid)
                                    -- A backfill chunk ignores older LIVE runs (see above)
                                    -- but still orders behind an older backfill run, so
                                    -- two generations can never interleave on the
                                    -- staging table.
                                    AND ({LIVE_BATCH_SQL_PREDICATE} OR ir.is_backfill_run)
                            )
                        )
                    ORDER BY b.created_at ASC, b.batch_index ASC, b.is_final_batch ASC
                    LIMIT %(limit)s
                ),
                candidate_groups AS (
                    -- Cap leased groups to the consumer's free slots, oldest work
                    -- first (NULL = no cap): a leased-but-unstarted group would be
                    -- renewed by every poll and stay dark to other pods.
                    SELECT c.team_id, c.schema_id
                    FROM candidates c
                    GROUP BY c.team_id, c.schema_id
                    ORDER BY min(c.created_at) ASC, c.team_id ASC, c.schema_id ASC
                    LIMIT COALESCE(%(max_groups)s, 2147483647)
                ),
                claimed AS (
                    INSERT INTO {DUCKGRES_LEASE_TABLE} (team_id, schema_id, owner_token, expires_at, acquired_at, updated_at)
                    SELECT team_id, schema_id, %(owner)s, now() + make_interval(secs => %(ttl)s), now(), now()
                    FROM candidate_groups
                    ON CONFLICT (team_id, schema_id) DO UPDATE
                        SET owner_token = excluded.owner_token,
                            expires_at = excluded.expires_at,
                            acquired_at = CASE
                                WHEN {DUCKGRES_LEASE_TABLE}.owner_token = excluded.owner_token THEN {DUCKGRES_LEASE_TABLE}.acquired_at
                                ELSE now()
                            END,
                            updated_at = now()
                        WHERE {DUCKGRES_LEASE_TABLE}.expires_at < now()
                           OR {DUCKGRES_LEASE_TABLE}.owner_token = excluded.owner_token
                    RETURNING team_id, schema_id
                )
                SELECT c.*
                FROM candidates c
                JOIN claimed USING (team_id, schema_id)
                ORDER BY c.created_at ASC, c.batch_index ASC, c.is_final_batch ASC
                """,
                {
                    "limit": limit,
                    "backoff": retry_backoff_base_seconds,
                    "team_ids": team_ids,
                    "blocked_schema_ids": blocked_schema_ids,
                    "eligible_schema_ids": eligible_schema_ids,
                    "owner": owner_token,
                    "ttl": lease_ttl_seconds,
                    "max_groups": max_groups,
                    "exclude_team_ids": [team_id for team_id, _ in exclude_groups] if exclude_groups else None,
                    "exclude_schema_ids": [schema_id for _, schema_id in exclude_groups] if exclude_groups else None,
                },
            )
            rows = await cur.fetchall()
        return [PendingBatch(**row) for row in rows]

    @staticmethod
    async def supersede_replaced_runs(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_ids: list[int] | None = None,
    ) -> int:
        """Fail older runs' pending duckgres work once a newer replace-run is ready.

        When a newer run whose batch 0 will CREATE OR REPLACE the table (full
        refresh, or first-ever incremental) is delta-succeeded and not yet
        applied, any older run's remaining unapplied duckgres work is worthless —
        applying it after the replace would mix stale rows into the new table.
        Mark those batches 'failed' (reason: superseded) so the failed-run
        exclusion retires them and the cross-run gate opens for the new run.

        Skips batches currently 'executing' (their attempt resolves on its own)
        and anything already terminal. Returns the number of batches superseded.
        """
        async with _statement_timeout(conn, ELIGIBILITY_QUERY_STATEMENT_TIMEOUT_MS), conn.cursor() as cur:
            await cur.execute(
                f"""
                WITH {ELIGIBILITY_CTES}
                replace_heads AS MATERIALIZED (
                    SELECT nb.team_id, nb.schema_id, nb.run_uuid, rs.started_at
                    FROM {BATCH_TABLE} nb
                    JOIN {_latest_status_lateral(STATUS_TABLE, "nb")} nds ON true
                    JOIN run_starts rs ON rs.run_uuid = nb.run_uuid
                    LEFT JOIN {DUCKGRES_APPLY_TABLE} na
                        ON na.team_id = nb.team_id
                        AND na.schema_id = nb.schema_id
                        AND na.run_uuid = nb.run_uuid
                        AND na.batch_index = nb.batch_index
                    WHERE nb.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR nb.team_id = ANY(%(team_ids)s))
                        AND nds.job_state = 'succeeded'
                        AND nb.batch_index = 0
                        AND nb.is_final_batch = false
                        AND nb.is_resume = false
                        AND (
                            nb.sync_type = 'full_refresh'
                            OR (nb.sync_type = 'incremental' AND nb.is_first_ever_sync)
                        )
                        AND na.id IS NULL
                        AND nb.run_uuid NOT IN (SELECT run_uuid FROM failed_runs)
                ),
                victims AS (
                    SELECT DISTINCT ON (old.id) old.id AS batch_id, rh.run_uuid AS superseded_by
                    FROM {BATCH_TABLE} old
                    JOIN replace_heads rh
                        ON rh.team_id = old.team_id AND rh.schema_id = old.schema_id
                    JOIN run_starts ors ON ors.run_uuid = old.run_uuid
                    JOIN {_latest_status_lateral(STATUS_TABLE, "old")} ods ON true
                    LEFT JOIN {_latest_status_lateral(DUCKGRES_STATUS_TABLE, "old")} odgs ON true
                    LEFT JOIN {DUCKGRES_APPLY_TABLE} oa
                        ON oa.team_id = old.team_id
                        AND oa.schema_id = old.schema_id
                        AND oa.run_uuid = old.run_uuid
                        AND oa.batch_index = old.batch_index
                    WHERE old.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND old.run_uuid <> rh.run_uuid
                        AND (ors.started_at, old.run_uuid) < (rh.started_at, rh.run_uuid)
                        AND ods.job_state = 'succeeded'
                        AND old.run_uuid NOT IN (SELECT run_uuid FROM failed_runs)
                        AND (old.is_final_batch = true OR oa.id IS NULL)
                        AND (odgs.batch_id IS NULL OR odgs.job_state = 'waiting_retry')
                    ORDER BY old.id, rh.started_at DESC, rh.run_uuid DESC
                )
                INSERT INTO {DUCKGRES_STATUS_TABLE} (batch_id, job_state, attempt, error_response)
                SELECT
                    v.batch_id,
                    'failed',
                    0,
                    jsonb_build_object('error', 'superseded by newer replace run ' || v.superseded_by, 'kind', '{RETIRE_KIND_SUPERSEDED_BY_REPLACE}')
                FROM victims v
                """,
                {"team_ids": team_ids},
            )
            return cur.rowcount or 0

    @staticmethod
    async def get_backlog_stats(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_ids: list[int] | None = None,
        blocked_schema_ids: list[str] | None = None,
        eligible_schema_ids: list[str] | None = None,
        failing_schema_ids: list[str] | None = None,
    ) -> tuple[int, float | None, int, float | None, int]:
        """(eligible_count, eligible_oldest_age, blocked_count, blocked_oldest_age, failing_blocked_count).

        Eligible = delta-succeeded, unapplied, non-failed data batches the sink
        can claim now — the lag/alert signal (7-day retention and permanent run
        failure are time-bounded loss modes). Blocked = the same but held back
        by an unprimed schema whose backfill is progressing normally; this is
        the pageable bucket — it drains on its own, so sustained growth means a
        real throughput problem. Failing-blocked = blocked batches behind a
        hard-blocked schema (failure streak at threshold / needs_resync);
        counted separately so one wedged schema can neither trigger nor mask
        the page. Durable per-schema failure tracking lives on
        DuckgresSinkSchemaState (this count ages out with queue retention).
        """
        async with _statement_timeout(conn, ELIGIBILITY_QUERY_STATEMENT_TIMEOUT_MS), conn.cursor() as cur:
            await cur.execute(
                f"""
                WITH {ELIGIBILITY_CTES}
                backlog AS (
                    SELECT
                        b.created_at,
                        {BLOCKED_LIVE_BATCH_CONDITION} AS is_blocked,
                        (
                            %(failing_schema_ids)s::varchar[] IS NOT NULL
                            AND b.schema_id = ANY(%(failing_schema_ids)s)
                        ) AS is_failing
                    FROM {BATCH_TABLE} b
                    JOIN {_latest_status_lateral(STATUS_TABLE, "b")} ds ON true
                    LEFT JOIN {DUCKGRES_APPLY_TABLE} a
                        ON a.team_id = b.team_id
                        AND a.schema_id = b.schema_id
                        AND a.run_uuid = b.run_uuid
                        AND a.batch_index = b.batch_index
                    WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                        AND (%(team_ids)s::bigint[] IS NULL OR b.team_id = ANY(%(team_ids)s))
                        AND (%(eligible_schema_ids)s::varchar[] IS NULL OR b.schema_id = ANY(%(eligible_schema_ids)s))
                        AND ds.job_state = 'succeeded'
                        AND b.is_final_batch = false
                        AND a.id IS NULL
                        AND b.run_uuid NOT IN (SELECT run_uuid FROM failed_runs)
                )
                SELECT
                    count(*) FILTER (WHERE NOT is_blocked),
                    EXTRACT(EPOCH FROM now() - min(created_at) FILTER (WHERE NOT is_blocked)),
                    count(*) FILTER (WHERE is_blocked AND NOT is_failing),
                    EXTRACT(EPOCH FROM now() - min(created_at) FILTER (WHERE is_blocked AND NOT is_failing)),
                    count(*) FILTER (WHERE is_blocked AND is_failing)
                FROM backlog
                """,
                {
                    "team_ids": team_ids,
                    "blocked_schema_ids": blocked_schema_ids,
                    "eligible_schema_ids": eligible_schema_ids,
                    "failing_schema_ids": failing_schema_ids,
                },
            )
            row = await cur.fetchone()

        def _age(v: Any) -> float | None:
            return float(v) if v is not None else None

        if row is None:
            return 0, None, 0, None, 0
        return int(row[0]), _age(row[1]), int(row[2]), _age(row[3]), int(row[4])

    @staticmethod
    async def update_status(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int = 0,
        error_response: dict[str, Any] | None = None,
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {DUCKGRES_STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            VALUES (%(batch_id)s, %(job_state)s, %(attempt)s, now(), %(error_response)s, now())
            """,
            {
                "batch_id": batch_id,
                "job_state": job_state,
                "attempt": attempt,
                "error_response": json.dumps(error_response) if error_response else None,
            },
        )

    @staticmethod
    async def mark_applied(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> None:
        await conn.execute(
            f"""
            INSERT INTO {DUCKGRES_APPLY_TABLE} (
                team_id, schema_id, run_uuid, batch_index, batch_id, row_count, created_at
            ) VALUES (
                %(team_id)s, %(schema_id)s, %(run_uuid)s, %(batch_index)s, %(batch_id)s, %(row_count)s, now()
            )
            ON CONFLICT (team_id, schema_id, run_uuid, batch_index) DO NOTHING
            """,
            {
                "team_id": batch.team_id,
                "schema_id": batch.schema_id,
                "run_uuid": batch.run_uuid,
                "batch_index": batch.batch_index,
                "batch_id": batch.id,
                "row_count": batch.row_count,
            },
        )

    @staticmethod
    async def update_status_unless_failed(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
        job_state: str,
        attempt: int = 0,
        error_response: dict[str, Any] | None = None,
    ) -> bool:
        """Append a status row only if the batch's latest status is not terminal 'failed'.

        The consumer routes every status write through this so a terminal
        'failed' (supersede/replan/fail_run can land at any point in a claimed
        batch's lifecycle) is never masked by a later row in the latest-status
        views. Guard and insert share one statement snapshot; returns False
        (writing nothing) when the batch is retired.

        Accepted residual: a failure writer whose statement overlaps this one
        can be mutually invisible. One statement wide, same class the supersede
        design accepts by skipping 'executing' victims, converges via the
        periodic sweeps — closing it needs a shared per-batch lock, not worth it.
        """
        cursor = await conn.execute(
            f"""
            INSERT INTO {DUCKGRES_STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            SELECT %(batch_id)s, %(job_state)s, %(attempt)s, now(), %(error_response)s, now()
            WHERE (
                SELECT cur.job_state
                FROM {DUCKGRES_STATUS_TABLE} cur
                WHERE cur.batch_id = %(batch_id)s
                ORDER BY cur.created_at DESC, cur.id DESC
                LIMIT 1
            ) IS DISTINCT FROM 'failed'
            """,
            {
                "batch_id": batch_id,
                "job_state": job_state,
                "attempt": attempt,
                "error_response": json.dumps(error_response) if error_response else None,
            },
        )
        return bool(cursor.rowcount)

    @staticmethod
    async def requeue_stale_executing(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
        error_response: dict[str, Any],
        grace_seconds: int,
    ) -> bool:
        """Flip a stale 'executing' batch to waiting_retry — fenced at write time.

        Between the unlocked stale scan and this write, the group can be
        reclaimed, a rival sweep can requeue first, or a leaseless live worker
        (old advisory-lock pod in the mixed-version window) can heartbeat a
        fresh 'executing'. The insert re-checks all of it in its own snapshot:
        latest status still 'executing', older than ``grace_seconds``, and no
        live lease. Returns False when skipped; a later sweep retries.
        """
        cursor = await conn.execute(
            f"""
            INSERT INTO {DUCKGRES_STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            SELECT %(batch_id)s, 'waiting_retry', %(attempt)s, now(), %(error_response)s, now()
            WHERE EXISTS (
                SELECT 1
                FROM (
                    SELECT cur.job_state, cur.created_at
                    FROM {DUCKGRES_STATUS_TABLE} cur
                    WHERE cur.batch_id = %(batch_id)s
                    ORDER BY cur.created_at DESC, cur.id DESC
                    LIMIT 1
                ) latest
                WHERE latest.job_state = 'executing'
                    AND latest.created_at <= now() - make_interval(secs => %(grace)s)
            )
            AND NOT EXISTS (
                SELECT 1 FROM {DUCKGRES_LEASE_TABLE} l
                WHERE l.team_id = %(team_id)s
                    AND l.schema_id = %(schema_id)s
                    AND l.expires_at > now()
            )
            """,
            {
                "batch_id": batch.id,
                "attempt": batch.latest_attempt,
                "error_response": json.dumps(error_response),
                "team_id": batch.team_id,
                "schema_id": batch.schema_id,
                "grace": grace_seconds,
            },
        )
        return bool(cursor.rowcount)

    @staticmethod
    async def fail_run_if_stale(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
        reason: str,
        grace_seconds: int,
    ) -> bool:
        """Terminally fail a run from recovery — fenced inside the insert itself.

        Same fence as ``requeue_stale_executing``, keyed on the anchor batch:
        the failure rows land only while its latest status is still 'executing',
        older than ``grace_seconds``, and the group has no live lease — all in
        this statement's snapshot. Returns False when the fence refuses. The
        group error path uses ``fail_run`` instead, since it legitimately fails
        runs while holding its own live lease.
        """
        cursor = await conn.execute(
            f"""
            INSERT INTO {DUCKGRES_STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            SELECT b.id, 'failed', 0, now(), %(error_response)s, now()
            FROM {BATCH_TABLE} b
            JOIN {_latest_status_lateral(STATUS_TABLE, "b")} ds ON true
            LEFT JOIN {_latest_status_lateral(DUCKGRES_STATUS_TABLE, "b")} dgs ON true
            WHERE
                b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                AND b.run_uuid = %(run_uuid)s
                AND ds.job_state = 'succeeded'
                AND (dgs.batch_id IS NULL OR dgs.job_state IN ('waiting_retry', 'executing'))
                AND EXISTS (
                    SELECT 1
                    FROM (
                        SELECT anchor.job_state, anchor.created_at
                        FROM {DUCKGRES_STATUS_TABLE} anchor
                        WHERE anchor.batch_id = %(anchor_batch_id)s
                        ORDER BY anchor.created_at DESC, anchor.id DESC
                        LIMIT 1
                    ) latest
                    WHERE latest.job_state = 'executing'
                        AND latest.created_at <= now() - make_interval(secs => %(grace)s)
                )
                AND NOT EXISTS (
                    SELECT 1 FROM {DUCKGRES_LEASE_TABLE} l
                    WHERE l.team_id = %(team_id)s
                        AND l.schema_id = %(schema_id)s
                        AND l.expires_at > now()
                )
            """,
            {
                "run_uuid": batch.run_uuid,
                "anchor_batch_id": batch.id,
                "team_id": batch.team_id,
                "schema_id": batch.schema_id,
                "error_response": json.dumps({"error": reason}),
                "grace": grace_seconds,
            },
        )
        return bool(cursor.rowcount)

    @staticmethod
    async def is_failed(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch_id: str,
    ) -> bool:
        """Whether the batch's LATEST duckgres status is terminal 'failed' — the
        consumer's per-batch re-check for co-claimed batches retired mid-claim."""
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT job_state
                FROM {DUCKGRES_STATUS_TABLE}
                WHERE batch_id = %(batch_id)s
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                {"batch_id": batch_id},
            )
            row = await cur.fetchone()
            return bool(row and row[0] == "failed")

    @staticmethod
    async def has_applied(
        conn: psycopg.AsyncConnection[Any],
        *,
        batch: PendingBatch,
    ) -> bool:
        row = await conn.execute(
            f"""
            SELECT 1
            FROM {DUCKGRES_APPLY_TABLE}
            WHERE team_id = %(team_id)s
                AND schema_id = %(schema_id)s
                AND run_uuid = %(run_uuid)s
                AND batch_index = %(batch_index)s
            LIMIT 1
            """,
            {
                "team_id": batch.team_id,
                "schema_id": batch.schema_id,
                "run_uuid": batch.run_uuid,
                "batch_index": batch.batch_index,
            },
        )
        return await row.fetchone() is not None

    @staticmethod
    async def fail_run(
        conn: psycopg.AsyncConnection[Any],
        *,
        run_uuid: str,
        reason: str,
    ) -> int:
        cursor = await conn.execute(
            f"""
            INSERT INTO {DUCKGRES_STATUS_TABLE} (batch_id, job_state, attempt, exec_time, error_response, created_at)
            SELECT b.id, 'failed', 0, now(), %(error_response)s, now()
            FROM {BATCH_TABLE} b
            JOIN {_latest_status_lateral(STATUS_TABLE, "b")} ds ON true
            LEFT JOIN {_latest_status_lateral(DUCKGRES_STATUS_TABLE, "b")} dgs ON true
            WHERE
                b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                AND b.run_uuid = %(run_uuid)s
                AND ds.job_state = 'succeeded'
                AND (dgs.batch_id IS NULL OR dgs.job_state IN ('waiting_retry', 'executing'))
            """,
            {
                "run_uuid": run_uuid,
                "error_response": json.dumps({"error": reason}),
            },
        )
        return cursor.rowcount or 0

    @staticmethod
    async def verify_lease(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
    ) -> bool:
        """Check whether ``owner_token`` still holds a live group lease for (team_id, schema_id)."""
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT EXISTS (
                    SELECT 1 FROM {DUCKGRES_LEASE_TABLE}
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
    async def renew_lease(
        conn: psycopg.AsyncConnection[Any],
        *,
        team_id: int,
        schema_id: str,
        owner_token: str,
        lease_ttl_seconds: int = LEASE_TTL_SECONDS,
    ) -> bool:
        """Extend this owner's group lease. Returns False when lost (gone,
        reclaimed, or expired) — an expired lease must never be resurrected here
        (recovery may have re-queued the group); re-claiming goes through the
        fetch's claim CTE only.
        """
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE {DUCKGRES_LEASE_TABLE}
                SET expires_at = now() + make_interval(secs => %(ttl)s), updated_at = now()
                WHERE team_id = %(team_id)s
                    AND schema_id = %(schema_id)s
                    AND owner_token = %(owner)s
                    AND expires_at > now()
                RETURNING 1
                """,
                {"team_id": team_id, "schema_id": schema_id, "owner": owner_token, "ttl": lease_ttl_seconds},
            )
            return (await cur.fetchone()) is not None

    @staticmethod
    async def get_stale_executing(
        conn: psycopg.AsyncConnection[Any],
        *,
        grace_seconds: int = 0,
    ) -> list[PendingBatch]:
        """Find batches stuck in 'executing' whose group lease is absent or
        expired — unlike the old advisory-lock probe, an abandoned lease always
        expires, so orphaned groups are always reclaimable."""
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT
                    {pending_batch_select_columns("dgs")}
                FROM {BATCH_TABLE} b
                JOIN {_latest_status_lateral(DUCKGRES_STATUS_TABLE, "b")} dgs ON true
                LEFT JOIN {DUCKGRES_LEASE_TABLE} l ON l.team_id = b.team_id AND l.schema_id = b.schema_id
                WHERE
                    b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                    AND dgs.job_state = 'executing'
                    AND dgs.created_at <= now() - make_interval(secs => %(grace)s)
                    AND (l.team_id IS NULL OR l.expires_at <= now())
                ORDER BY b.created_at ASC, b.batch_index ASC
                """,
                {"grace": grace_seconds},
            )
            rows = await cur.fetchall()

        return [PendingBatch(**row) for row in rows]

    @staticmethod
    async def unlock_for_batches(
        conn: psycopg.AsyncConnection[Any],
        *,
        batches: list[PendingBatch],
        owner_token: str,
    ) -> None:
        """Release the group leases for ``batches``' groups held by ``owner_token``
        — the owner predicate keeps this a no-op if another pod reclaimed the group."""
        pairs = list({(b.team_id, b.schema_id) for b in batches})
        if not pairs:
            return
        team_ids = [team_id for team_id, _ in pairs]
        schema_ids = [schema_id for _, schema_id in pairs]
        await conn.execute(
            f"""
            DELETE FROM {DUCKGRES_LEASE_TABLE}
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
        """Delete every group lease held by ``owner_token``. Best-effort cleanup on shutdown."""
        await conn.execute(
            f"DELETE FROM {DUCKGRES_LEASE_TABLE} WHERE owner_token = %(owner)s",
            {"owner": owner_token},
        )
