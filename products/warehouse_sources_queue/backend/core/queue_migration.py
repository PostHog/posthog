"""
Cross-queue coordination for moving the batch queue to another queue with no downtime.

A queue is whatever a connection URL reaches: another database, or the same database
through a role whose ``search_path`` selects another set of tables. During a migration
two queues hold work: the draining queue (no new runs) and the active queue.

The draining queue's lease table is the one authority for group ownership. A consumer
of the draining queue holds a group's lease there because it claimed there. A consumer
of the active queue must take the same lease there too, and must find no live batch of
the group there, before it loads the group. So one group never loads from both queues
at once, and its draining batches load first. Only the active side takes two leases,
so two consumers cannot each hold one lease and wait for the other.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable
from typing import Any, TypeVar

import psycopg
import structlog

from posthog.dataclasses import frozen

from products.warehouse_sources_queue.backend.core.jobs_db import (
    BATCH_TABLE,
    LEASE_TABLE,
    LEASE_TTL_SECONDS,
    PARTITION_PRUNING_INTERVAL,
    BatchQueue,
)

logger = structlog.get_logger(__name__)

GroupKey = tuple[int, str]
T = TypeVar("T")

_LIVE_STATES = "('pending', 'waiting', 'waiting_retry', 'executing')"

# A run that inserted a batch this recently and has no final batch may still insert more.
OPEN_RUN_WINDOW = "24 hours"


def _group_arrays(groups: Iterable[GroupKey]) -> tuple[list[int], list[str]]:
    # Ascending (team_id, schema_id) is the fleet-wide lease lock order (see jobs_db).
    pairs = sorted(set(groups))
    return [team_id for team_id, _ in pairs], [schema_id for _, schema_id in pairs]


async def claim_group_leases(
    conn: psycopg.AsyncConnection[Any],
    *,
    groups: Iterable[GroupKey],
    owner_token: str,
    lease_ttl_seconds: int = LEASE_TTL_SECONDS,
) -> set[GroupKey]:
    """Claim or renew the leases of ``groups``. Returns the groups this owner now holds.

    A group whose lease another owner holds live is left out, like in the claim query.
    """
    team_ids, schema_ids = _group_arrays(groups)
    if not team_ids:
        return set()
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            INSERT INTO {LEASE_TABLE} (team_id, schema_id, owner_token, expires_at, acquired_at, updated_at)
            SELECT g.team_id, g.schema_id, %(owner)s, now() + make_interval(secs => %(ttl)s), now(), now()
            FROM unnest(%(team_ids)s::bigint[], %(schema_ids)s::varchar[]) AS g(team_id, schema_id)
            ORDER BY g.team_id, g.schema_id
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
            """,
            {"team_ids": team_ids, "schema_ids": schema_ids, "owner": owner_token, "ttl": lease_ttl_seconds},
        )
        return {(row[0], row[1]) for row in await cur.fetchall()}


async def release_group_leases(
    conn: psycopg.AsyncConnection[Any],
    *,
    groups: Iterable[GroupKey],
    owner_token: str,
) -> None:
    """Delete the leases of ``groups`` that ``owner_token`` holds. Best effort.

    A lease row that another statement has locked stays and expires after its TTL.
    """
    team_ids, schema_ids = _group_arrays(groups)
    if not team_ids:
        return
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
            FOR UPDATE SKIP LOCKED
        )
        """,
        {"owner": owner_token, "team_ids": team_ids, "schema_ids": schema_ids},
    )


async def groups_with_live_batches(
    conn: psycopg.AsyncConnection[Any],
    *,
    groups: Iterable[GroupKey],
) -> set[GroupKey]:
    """The groups among ``groups`` that still have a batch to load in this queue.

    A run that holds a failed batch does not count, because the claim query never offers
    its other batches again (same rule as ``get_oldest_non_terminal_batch_age_seconds``).
    """
    team_ids, schema_ids = _group_arrays(groups)
    if not team_ids:
        return set()
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            SELECT DISTINCT b.team_id, b.schema_id
            FROM {BATCH_TABLE} b
            WHERE b.created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
              AND (b.team_id, b.schema_id) IN (
                  SELECT * FROM unnest(%(team_ids)s::bigint[], %(schema_ids)s::varchar[])
              )
              AND b.latest_state IN {_LIVE_STATES}
              AND NOT b.superseded
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
            {"team_ids": team_ids, "schema_ids": schema_ids},
        )
        return {(row[0], row[1]) for row in await cur.fetchall()}


def queue_has_run(conn: psycopg.Connection[Any], *, run_uuids: list[str]) -> bool:
    """Whether this queue holds a batch of any of ``run_uuids``."""
    if not run_uuids:
        return False
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT EXISTS (
                SELECT 1 FROM {BATCH_TABLE}
                WHERE created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                  AND run_uuid = ANY(%(run_uuids)s)
            )
            """,
            {"run_uuids": run_uuids},
        )
        row = cur.fetchone()
    return bool(row and row[0])


@frozen
class DrainStatus:
    """How much work a queue still holds. See ``drained``."""

    live_batches: int
    open_runs: int
    seconds_since_last_insert: float | None

    @property
    def drained(self) -> bool:
        """No batch waits or loads, and no recent run is still expected to insert one."""
        return self.live_batches == 0 and self.open_runs == 0


def get_drain_status(conn: psycopg.Connection[Any]) -> DrainStatus:
    """Read how much work this queue still holds.

    ``open_runs`` counts the runs that inserted a batch in the last ``OPEN_RUN_WINDOW``
    and have neither a final batch nor a failed batch nor a superseded batch. A producer
    stays on the queue where its run started, so such a run can still insert here.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH runs AS (
                SELECT
                    run_uuid,
                    max(created_at) AS last_insert,
                    bool_or(is_final_batch) AS has_final,
                    bool_or(latest_state = 'failed') AS has_failed,
                    bool_or(superseded) AS has_superseded,
                    count(*) FILTER (WHERE latest_state IN {_LIVE_STATES} AND NOT superseded) AS live_batches
                FROM {BATCH_TABLE}
                WHERE created_at > now() - interval '{PARTITION_PRUNING_INTERVAL}'
                GROUP BY run_uuid
            )
            SELECT
                coalesce(sum(live_batches) FILTER (WHERE NOT has_failed), 0),
                count(*) FILTER (
                    WHERE NOT has_final AND NOT has_failed AND NOT has_superseded
                      AND last_insert > now() - interval '{OPEN_RUN_WINDOW}'
                ),
                EXTRACT(EPOCH FROM (now() - max(last_insert)))
            FROM runs
            """
        )
        row = cur.fetchone()
    assert row is not None
    return DrainStatus(
        live_batches=int(row[0]),
        open_runs=int(row[1]),
        seconds_since_last_insert=float(row[2]) if row[2] is not None else None,
    )


class DrainingQueueLeases:
    """The leases a consumer of the active queue holds in the draining queue.

    Every method fails closed: it retries a failed statement once on a new connection and
    then raises, and the caller treats that as a lease it does not hold. So the active
    queue stops loading while the draining queue is unreachable.
    """

    def __init__(self, database_url: str, *, connect_timeout_seconds: int = 10) -> None:
        self.database_url = database_url
        self._connect_timeout_seconds = connect_timeout_seconds
        self._conn: psycopg.AsyncConnection[Any] | None = None
        # Group tasks renew on one shared connection, and psycopg runs one statement at a time on it.
        self._lock = asyncio.Lock()

    async def _connect(self) -> psycopg.AsyncConnection[Any]:
        conn = await psycopg.AsyncConnection.connect(
            self.database_url, autocommit=True, connect_timeout=self._connect_timeout_seconds
        )
        # The queue sits behind a transaction pooler, which cannot replay a server-prepared statement.
        conn.prepare_threshold = None
        return conn

    async def _run(self, operation: Callable[[psycopg.AsyncConnection[Any]], Awaitable[T]]) -> T:
        async with self._lock:
            for attempt in (1, 2):
                try:
                    if self._conn is None or self._conn.closed:
                        self._conn = await self._connect()
                    return await operation(self._conn)
                except psycopg.Error:
                    await self._discard()
                    if attempt == 2:
                        raise
        raise AssertionError("unreachable")

    async def _discard(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            try:
                await conn.close()
            except Exception:
                pass

    async def claim(
        self, groups: Iterable[GroupKey], *, owner_token: str, lease_ttl_seconds: int = LEASE_TTL_SECONDS
    ) -> set[GroupKey]:
        """Take the draining leases of ``groups``. Returns the groups that may load from the active queue.

        A group is left out when another owner holds its draining lease, or when the draining
        queue still has a batch of it to load. A lease taken for a group of the second kind is
        released at once, so that a consumer of the draining queue can claim the group.
        """
        wanted = set(groups)
        if not wanted:
            return set()

        async def _claim(conn: psycopg.AsyncConnection[Any]) -> set[GroupKey]:
            held = await claim_group_leases(
                conn, groups=wanted, owner_token=owner_token, lease_ttl_seconds=lease_ttl_seconds
            )
            busy = await groups_with_live_batches(conn, groups=held)
            await release_group_leases(conn, groups=busy, owner_token=owner_token)
            return held - busy

        return await self._run(_claim)

    async def renew(
        self, *, team_id: int, schema_id: str, owner_token: str, lease_ttl_seconds: int = LEASE_TTL_SECONDS
    ) -> bool:
        return await self._run(
            lambda conn: BatchQueue.renew_lease(
                conn,
                team_id=team_id,
                schema_id=schema_id,
                owner_token=owner_token,
                lease_ttl_seconds=lease_ttl_seconds,
            )
        )

    async def verify(self, *, team_id: int, schema_id: str, owner_token: str) -> bool:
        return await self._run(
            lambda conn: BatchQueue.verify_advisory_lock(
                conn, team_id=team_id, schema_id=schema_id, owner_token=owner_token
            )
        )

    async def release(self, groups: Iterable[GroupKey], *, owner_token: str) -> None:
        released = set(groups)
        await self._run(lambda conn: release_group_leases(conn, groups=released, owner_token=owner_token))

    async def release_all(self, *, owner_token: str) -> None:
        await self._run(lambda conn: BatchQueue.release_all_owned_leases(conn, owner_token=owner_token))

    async def close(self) -> None:
        async with self._lock:
            await self._discard()
