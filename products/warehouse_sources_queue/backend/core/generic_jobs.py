"""Generic job queue: SQL and row types for the ``queuejob`` tables.

The generic layer carries heterogeneous work items (``kind``), grouped by an
opaque ``group_key`` and serialized per group within a ``lane``. It reuses the
``sourcebatch`` physics: denormalized state columns on the job row, an
append-only status log written in the same statement, lease-based group
ownership, and partial indexes that keep every query's cost tracking the
claimable set. All SQL lives here; the consumer engine (``batch_consumer.py``)
drives it through ``GenericJobAdapter`` in the SDK.

Nothing produces or consumes these tables yet — this layer lands ahead of the
run orchestrator so it can ship with tests and no production traffic.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from posthog.dataclasses import frozen

JOB_TABLE = "queuejob"
JOB_STATUS_TABLE = "queuejobstatus"
JOB_LEASE_TABLE = "queuejoblease"

# Claim eligibility must stay under the 7-day retention window (see
# jobs_db.CLAIM_ELIGIBILITY_INTERVAL for the reasoning); generic jobs carry
# their payload inline rather than in S3, but the partitions still drop at
# retention, so a job must not be claimable after its partition can vanish.
JOB_CLAIM_ELIGIBILITY_INTERVAL = "6 days 12 hours"
JOB_PARTITION_PRUNING_INTERVAL = "14 days"

JOB_LEASE_TTL_SECONDS = 300

TERMINAL_JOB_STATES = ("succeeded", "failed")


@frozen
class Job:
    """One claimed generic job row.

    The consumer engine predates this layer and reads batch-shaped attribute
    names (it groups on ``(team_id, schema_id)`` and logs ``run_uuid`` /
    ``resource_name`` / ``batch_index``), so the engine-facing names below are
    aliases onto the generic fields. They exist only to satisfy the engine;
    handlers should read the generic fields.
    """

    id: str
    kind: str
    lane: str
    group_key: str
    team_id: int
    run_id: str | None
    sequence: int
    payload: dict[str, Any]
    priority: int
    dedup_key: str | None
    latest_attempt: int
    state_changed_at: datetime | None
    created_at: datetime

    # -- engine-facing aliases (see class docstring) -------------------------
    @property
    def schema_id(self) -> str:
        return self.group_key

    @property
    def run_uuid(self) -> str:
        return self.run_id or str(self.id)

    @property
    def job_id(self) -> str:
        return self.run_id or str(self.id)

    @property
    def batch_index(self) -> int:
        return self.sequence

    @property
    def resource_name(self) -> str:
        return self.kind

    @property
    def source_id(self) -> str:
        return self.lane

    @property
    def metadata(self) -> dict[str, Any]:
        return self.payload

    @property
    def is_final_batch(self) -> bool:
        return False


def _job_status_dual_write_sql(*, with_job_created_at: bool) -> str:
    """Single-statement status INSERT + denormalized-state UPDATE.

    Same guards as ``jobs_db.build_status_dual_write_sql``: exact ``created_at``
    prunes to one partition when known, the ``IS DISTINCT FROM`` check makes
    heartbeat re-inserts a 0-row no-op, and the monotonic ``state_changed_at``
    check makes cross-connection races converge on the newest status row.
    """
    created_at_predicate = (
        "j.created_at = %(job_created_at)s"
        if with_job_created_at
        else f"j.created_at > now() - interval '{JOB_PARTITION_PRUNING_INTERVAL}'"
    )
    return f"""
        WITH ins AS (
            INSERT INTO {JOB_STATUS_TABLE} (job_id, job_state, attempt, exec_time, error_response, created_at)
            VALUES (%(job_id)s, %(job_state)s, %(attempt)s, now(), %(error_response)s, now())
            RETURNING job_id, job_state, attempt, created_at
        )
        UPDATE {JOB_TABLE} j
        SET latest_state = ins.job_state, latest_attempt = ins.attempt, state_changed_at = ins.created_at
        FROM ins
        WHERE j.id = ins.job_id
          AND {created_at_predicate}
          AND ((j.latest_state, j.latest_attempt) IS DISTINCT FROM (ins.job_state, ins.attempt)
               OR j.state_changed_at IS NULL)
          AND (j.state_changed_at IS NULL OR j.state_changed_at <= ins.created_at)
    """


def _job_status_dual_write_unless_failed_sql(*, with_job_created_at: bool, with_expected_state_changed_at: bool) -> str:
    """Guarded twin: writes nothing over a terminal 'failed', so a late success
    cannot un-retire a job. Optionally arms a compare-and-swap on the caller's
    observed ``state_changed_at`` (the recovery sweep's fence against a live
    owner that finished between the stale scan and the re-queue)."""
    created_at_predicate = (
        "j.created_at = %(job_created_at)s"
        if with_job_created_at
        else f"j.created_at > now() - interval '{JOB_PARTITION_PRUNING_INTERVAL}'"
    )
    cas_predicate = (
        "\n              AND j.state_changed_at IS NOT DISTINCT FROM %(expected_state_changed_at)s"
        if with_expected_state_changed_at
        else ""
    )
    return f"""
        WITH target AS (
            SELECT j.id
            FROM {JOB_TABLE} j
            WHERE j.id = %(job_id)s
              AND {created_at_predicate}
              AND j.latest_state IS DISTINCT FROM 'failed'{cas_predicate}
            FOR UPDATE OF j
        ),
        ins AS (
            INSERT INTO {JOB_STATUS_TABLE} (job_id, job_state, attempt, exec_time, error_response, created_at)
            SELECT t.id, %(job_state)s, %(attempt)s, now(), %(error_response)s, now()
            FROM target t
            RETURNING job_id, job_state, attempt, created_at
        ),
        upd AS (
            UPDATE {JOB_TABLE} j
            SET latest_state = ins.job_state, latest_attempt = ins.attempt, state_changed_at = ins.created_at
            FROM ins
            WHERE j.id = ins.job_id
              AND {created_at_predicate}
              AND ((j.latest_state, j.latest_attempt) IS DISTINCT FROM (ins.job_state, ins.attempt)
                   OR j.state_changed_at IS NULL)
              AND (j.state_changed_at IS NULL OR j.state_changed_at <= ins.created_at)
            RETURNING j.id
        )
        SELECT count(*) FROM ins
    """


_JOB_COLUMNS = (
    "j.id, j.kind, j.lane, j.group_key, j.team_id, j.run_id, j.sequence, "
    "j.payload, j.priority, j.dedup_key, j.latest_attempt, j.state_changed_at, j.created_at"
)

# The insert's dedup guard. A partitioned table cannot enforce a unique index
# that omits the partition key, so live-pair uniqueness is a NOT EXISTS in the
# same statement: correct under one enqueuer per key (the scheduler is
# single-flighted; followers are enqueued by the single run finalizer), and a
# rare concurrent duplicate is bounded — both rows share the dedup_key, so the
# loser is observable and the handler contract stays idempotent.
_INSERT_SQL = f"""
    INSERT INTO {JOB_TABLE} (
        id, kind, lane, group_key, team_id, run_id, sequence, payload,
        priority, dedup_key, created_at
    )
    SELECT
        gen_random_uuid(), %(kind)s::varchar, %(lane)s, %(group_key)s, %(team_id)s, %(run_id)s,
        %(sequence)s, %(payload)s::jsonb, %(priority)s, %(dedup_key)s::varchar, now()
    WHERE %(dedup_key)s::varchar IS NULL OR NOT EXISTS (
        SELECT 1 FROM {JOB_TABLE} d
        WHERE d.kind = %(kind)s::varchar
          AND d.dedup_key = %(dedup_key)s::varchar
          AND d.created_at > now() - interval '{JOB_PARTITION_PRUNING_INTERVAL}'
          AND d.latest_state != 'failed'
          AND NOT d.superseded
    )
    RETURNING id
"""


def _claim_candidates_sql() -> str:
    """Claimable-job candidates from the denormalized state columns.

    Mirrors ``jobs_db._state_claim_candidates_sql``: answered by the partial
    indexes, narrow ``(id, created_at)`` output so the fairness sort never
    touches wide rows, and the gates deliberately ignore the kind filter — a
    group must stay serialized within its lane whatever kinds its jobs carry.

    Run gate: a job waits while an earlier ``sequence`` in the same ``run_id``
    is executing, backing off, or failed (a failed step parks its followers
    rather than letting them run out of order).
    """
    return f"""
        SELECT j.id, j.created_at
        FROM {JOB_TABLE} j
        WHERE
            j.created_at > now() - interval '{JOB_CLAIM_ELIGIBILITY_INTERVAL}'
            AND j.lane = %(lane)s
            AND j.kind = ANY(%(kinds)s)
            AND NOT j.superseded
            AND (
                j.latest_state = 'pending'
                OR (
                    j.latest_state = 'waiting_retry'
                    AND j.state_changed_at <= now() - make_interval(
                        secs => %(backoff)s * GREATEST(j.latest_attempt, 1)
                    )
                )
            )
            AND (
                j.run_id IS NULL
                OR NOT EXISTS (
                    SELECT 1
                    FROM {JOB_TABLE} j_prev
                    WHERE j_prev.run_id = j.run_id
                        AND j_prev.sequence < j.sequence
                        AND j_prev.created_at > now() - interval '{JOB_PARTITION_PRUNING_INTERVAL}'
                        AND (
                            j_prev.latest_state IN ('executing', 'failed')
                            OR (
                                j_prev.latest_state = 'waiting_retry'
                                AND j_prev.state_changed_at > now() - make_interval(
                                    secs => %(backoff)s * GREATEST(j_prev.latest_attempt, 1)
                                )
                            )
                        )
                )
            )
            AND NOT EXISTS (
                SELECT 1
                FROM {JOB_TABLE} j_busy
                WHERE j_busy.lane = j.lane
                    AND j_busy.group_key = j.group_key
                    AND j_busy.created_at > now() - interval '{JOB_PARTITION_PRUNING_INTERVAL}'
                    AND j_busy.latest_state = 'executing'
            )
    """


class JobsTable:
    """Raw SQL over the generic job tables (the ``BatchQueue`` idiom)."""

    # -- writes (producer side) ----------------------------------------------

    @staticmethod
    async def insert(
        conn: psycopg.AsyncConnection[Any],
        *,
        kind: str,
        lane: str,
        group_key: str,
        team_id: int,
        payload: dict[str, Any],
        run_id: str | None = None,
        sequence: int = 0,
        priority: int = 0,
        dedup_key: str | None = None,
    ) -> str | None:
        """Enqueue one job. Returns the new id, or None when the dedup guard refused it."""
        cursor = await conn.execute(
            _INSERT_SQL,
            {
                "kind": kind,
                "lane": lane,
                "group_key": group_key,
                "team_id": team_id,
                "run_id": run_id,
                "sequence": sequence,
                "payload": json.dumps(payload),
                "priority": priority,
                "dedup_key": dedup_key,
            },
        )
        row = await cursor.fetchone()
        return str(row[0]) if row else None

    @staticmethod
    async def insert_many(
        conn: psycopg.AsyncConnection[Any],
        jobs: list[dict[str, Any]],
    ) -> list[str]:
        """Enqueue several jobs in one transaction — the atomic follower primitive.

        Each entry takes the ``insert`` keyword arguments. Runs inside a single
        transaction even on an autocommit connection, so a crash mid-way
        enqueues nothing (the caller's dedup keys make the retry idempotent).
        """
        ids: list[str] = []
        async with conn.transaction():
            for job in jobs:
                cursor = await conn.execute(
                    _INSERT_SQL,
                    {
                        "run_id": None,
                        "sequence": 0,
                        "priority": 0,
                        "dedup_key": None,
                        **{**job, "payload": json.dumps(job.get("payload", {}))},
                    },
                )
                row = await cursor.fetchone()
                if row:
                    ids.append(str(row[0]))
        return ids

    # -- reads (consumer side) -----------------------------------------------

    @staticmethod
    async def get_unprocessed_and_lock(
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
        lane: str,
        kinds: list[str],
        limit: int = 50,
        retry_backoff_base_seconds: int = 0,
        lease_ttl_seconds: int = JOB_LEASE_TTL_SECONDS,
    ) -> list[Job]:
        """Fetch claimable jobs whose (lane, group_key) lease is claimable by ``owner_token``.

        Same shape as ``BatchQueue.get_unprocessed_and_lock``: MATERIALIZED
        narrow candidates with per-team round-robin fairness (priority first
        within a team), join-back for the wide rows, and a claim-or-renew lease
        upsert in the same writable CTE. Groups live-leased by another owner
        are excluded from candidates so pods compute disjoint windows.
        """
        candidates_sql = _claim_candidates_sql()
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                WITH narrow AS MATERIALIZED (
                    {candidates_sql}
                        AND NOT EXISTS (
                            SELECT 1
                            FROM {JOB_LEASE_TABLE} l_live
                            WHERE l_live.lane = j.lane
                                AND l_live.group_key = j.group_key
                                AND l_live.expires_at > now()
                                AND l_live.owner_token != %(owner)s
                        )
                    ORDER BY
                        row_number() OVER (
                            PARTITION BY j.team_id
                            ORDER BY j.priority DESC, j.created_at ASC, j.sequence ASC
                        ) ASC,
                        j.priority DESC,
                        j.created_at ASC,
                        j.sequence ASC
                    LIMIT %(limit)s
                ),
                candidates AS MATERIALIZED (
                    SELECT {_JOB_COLUMNS}
                    FROM {JOB_TABLE} j
                    JOIN narrow n ON n.id = j.id AND n.created_at = j.created_at
                ),
                candidate_groups AS (
                    SELECT DISTINCT lane, group_key FROM candidates
                ),
                claimed AS (
                    INSERT INTO {JOB_LEASE_TABLE} (lane, group_key, owner_token, expires_at, acquired_at, updated_at)
                    SELECT lane, group_key, %(owner)s, now() + make_interval(secs => %(ttl)s), now(), now()
                    FROM candidate_groups
                    ON CONFLICT (lane, group_key) DO UPDATE
                        SET owner_token = excluded.owner_token,
                            expires_at = excluded.expires_at,
                            acquired_at = CASE
                                WHEN {JOB_LEASE_TABLE}.owner_token = excluded.owner_token
                                    THEN {JOB_LEASE_TABLE}.acquired_at
                                ELSE now()
                            END,
                            updated_at = now()
                        WHERE {JOB_LEASE_TABLE}.expires_at < now()
                           OR {JOB_LEASE_TABLE}.owner_token = excluded.owner_token
                    RETURNING lane, group_key
                )
                SELECT c.*
                FROM candidates c
                JOIN claimed USING (lane, group_key)
                ORDER BY c.priority DESC, c.created_at ASC, c.sequence ASC
                """,
                {
                    "limit": limit,
                    "backoff": retry_backoff_base_seconds,
                    "owner": owner_token,
                    "ttl": lease_ttl_seconds,
                    "lane": lane,
                    "kinds": kinds,
                },
            )
            rows = await cur.fetchall()
        return [Job(**{**row, "id": str(row["id"])}) for row in rows]

    # -- state transitions -----------------------------------------------------

    @staticmethod
    async def update_status(
        conn: psycopg.AsyncConnection[Any],
        *,
        job_id: str,
        job_state: str,
        attempt: int = 0,
        error_response: dict[str, Any] | None = None,
        job_created_at: datetime | None = None,
    ) -> None:
        params: dict[str, Any] = {
            "job_id": job_id,
            "job_state": job_state,
            "attempt": attempt,
            "error_response": json.dumps(error_response) if error_response else None,
        }
        if job_created_at is not None:
            params["job_created_at"] = job_created_at
        await conn.execute(
            _job_status_dual_write_sql(with_job_created_at=job_created_at is not None),
            params,
        )

    @staticmethod
    async def update_status_unless_failed(
        conn: psycopg.AsyncConnection[Any],
        *,
        job_id: str,
        job_state: str,
        attempt: int = 0,
        error_response: dict[str, Any] | None = None,
        job_created_at: datetime | None = None,
        expected_state_changed_at: datetime | None = None,
        arm_cas: bool = False,
    ) -> bool:
        """Guarded status write: returns False (writing nothing) over a terminal
        'failed'. Pass ``arm_cas=True`` to also require ``state_changed_at`` to
        equal ``expected_state_changed_at`` (including a genuine None)."""
        params: dict[str, Any] = {
            "job_id": job_id,
            "job_state": job_state,
            "attempt": attempt,
            "error_response": json.dumps(error_response) if error_response else None,
        }
        if job_created_at is not None:
            params["job_created_at"] = job_created_at
        if arm_cas:
            params["expected_state_changed_at"] = expected_state_changed_at
        cursor = await conn.execute(
            _job_status_dual_write_unless_failed_sql(
                with_job_created_at=job_created_at is not None,
                with_expected_state_changed_at=arm_cas,
            ),
            params,
        )
        row = await cursor.fetchone()
        return bool(row and row[0])

    @staticmethod
    async def get_latest_state(
        conn: psycopg.AsyncConnection[Any],
        *,
        job_id: str,
    ) -> str | None:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT latest_state FROM {JOB_TABLE}
                WHERE id = %(job_id)s
                  AND created_at > now() - interval '{JOB_PARTITION_PRUNING_INTERVAL}'
                """,
                {"job_id": job_id},
            )
            row = await cur.fetchone()
            return str(row[0]) if row else None

    # -- leases ----------------------------------------------------------------

    @staticmethod
    async def renew_lease(
        conn: psycopg.AsyncConnection[Any],
        *,
        lane: str,
        group_key: str,
        owner_token: str,
        lease_ttl_seconds: int = JOB_LEASE_TTL_SECONDS,
    ) -> bool:
        """Extend a live lease; expiry is terminal (False = ownership gone for good)."""
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                UPDATE {JOB_LEASE_TABLE}
                SET expires_at = now() + make_interval(secs => %(ttl)s), updated_at = now()
                WHERE lane = %(lane)s AND group_key = %(group_key)s AND owner_token = %(owner)s
                  AND expires_at > now()
                RETURNING 1
                """,
                {"lane": lane, "group_key": group_key, "owner": owner_token, "ttl": lease_ttl_seconds},
            )
            return (await cur.fetchone()) is not None

    @staticmethod
    async def verify_lease(
        conn: psycopg.AsyncConnection[Any],
        *,
        lane: str,
        group_key: str,
        owner_token: str,
    ) -> bool:
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT EXISTS (
                    SELECT 1 FROM {JOB_LEASE_TABLE}
                    WHERE lane = %(lane)s AND group_key = %(group_key)s
                      AND owner_token = %(owner)s AND expires_at > now()
                )
                """,
                {"lane": lane, "group_key": group_key, "owner": owner_token},
            )
            row = await cur.fetchone()
            return bool(row and row[0])

    @staticmethod
    async def delete_expired_lease(
        conn: psycopg.AsyncConnection[Any],
        *,
        lane: str,
        group_key: str,
    ) -> None:
        """Delete the group's lease only if already expired; a live lease never matches."""
        await conn.execute(
            f"""
            DELETE FROM {JOB_LEASE_TABLE}
            WHERE lane = %(lane)s AND group_key = %(group_key)s AND expires_at <= now()
            """,
            {"lane": lane, "group_key": group_key},
        )

    @staticmethod
    async def unlock_groups(
        conn: psycopg.AsyncConnection[Any],
        *,
        lane: str,
        group_keys: list[str],
        owner_token: str,
    ) -> None:
        """Hand groups back when their work finishes (drop this owner's leases)."""
        if not group_keys:
            return
        await conn.execute(
            f"""
            DELETE FROM {JOB_LEASE_TABLE}
            WHERE lane = %(lane)s AND group_key = ANY(%(group_keys)s) AND owner_token = %(owner)s
            """,
            {"lane": lane, "group_keys": group_keys, "owner": owner_token},
        )

    @staticmethod
    async def release_all_owned(
        conn: psycopg.AsyncConnection[Any],
        *,
        owner_token: str,
    ) -> None:
        """Best-effort cleanup of everything this pod holds, on graceful shutdown."""
        await conn.execute(
            f"DELETE FROM {JOB_LEASE_TABLE} WHERE owner_token = %(owner)s",
            {"owner": owner_token},
        )

    # -- sweeps and gauges -------------------------------------------------------

    @staticmethod
    async def get_stale_executing(
        conn: psycopg.AsyncConnection[Any],
        *,
        lane: str,
        kinds: list[str],
        grace_seconds: int = 0,
    ) -> list[Job]:
        """Jobs stuck in 'executing' whose group lease is absent or expired (owner gone)."""
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                f"""
                SELECT {_JOB_COLUMNS}
                FROM {JOB_TABLE} j
                WHERE j.created_at > now() - interval '{JOB_PARTITION_PRUNING_INTERVAL}'
                  AND j.lane = %(lane)s
                  AND j.kind = ANY(%(kinds)s)
                  AND j.latest_state = 'executing'
                  AND j.state_changed_at <= now() - make_interval(secs => %(grace)s)
                  AND NOT EXISTS (
                      SELECT 1 FROM {JOB_LEASE_TABLE} l
                      WHERE l.lane = j.lane AND l.group_key = j.group_key
                        AND l.expires_at > now()
                  )
                """,
                {"lane": lane, "kinds": kinds, "grace": grace_seconds},
            )
            rows = await cur.fetchall()
        return [Job(**{**row, "id": str(row["id"])}) for row in rows]

    @staticmethod
    async def get_claimable_count(
        conn: psycopg.AsyncConnection[Any],
        *,
        lane: str,
        kinds: list[str],
    ) -> int:
        """Depth gauge: jobs state-eligible for claiming right now (KEDA input)."""
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT count(*) FROM {JOB_TABLE} j
                WHERE j.created_at > now() - interval '{JOB_PARTITION_PRUNING_INTERVAL}'
                  AND j.lane = %(lane)s
                  AND j.kind = ANY(%(kinds)s)
                  AND NOT j.superseded
                  AND j.latest_state IN ('pending', 'waiting_retry')
                """,
                {"lane": lane, "kinds": kinds},
            )
            row = await cur.fetchone()
            return int(row[0]) if row else 0

    @staticmethod
    async def get_oldest_unclaimed_age_seconds(
        conn: psycopg.AsyncConnection[Any],
        *,
        lane: str,
        kinds: list[str],
    ) -> float:
        """Freshness gauge: age of the oldest job no consumer has ever picked up."""
        async with conn.cursor() as cur:
            await cur.execute(
                f"""
                SELECT COALESCE(EXTRACT(EPOCH FROM (now() - min(j.created_at))), 0)
                FROM {JOB_TABLE} j
                WHERE j.created_at > now() - interval '{JOB_PARTITION_PRUNING_INTERVAL}'
                  AND j.lane = %(lane)s
                  AND j.kind = ANY(%(kinds)s)
                  AND NOT j.superseded
                  AND j.latest_state = 'pending'
                """,
                {"lane": lane, "kinds": kinds},
            )
            row = await cur.fetchone()
            return float(row[0]) if row else 0.0
