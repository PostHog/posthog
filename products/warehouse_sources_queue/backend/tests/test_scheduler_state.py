from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

import psycopg
from psycopg.rows import dict_row

from products.warehouse_sources_queue.backend.core.generic_jobs import JOB_LEASE_TABLE, JobsTable
from products.warehouse_sources_queue.backend.core.scheduler_state import (
    SCHEDULER_STATE_TABLE,
    DecisionRecord,
    DueSchedule,
    SchedulerStateTable,
)
from products.warehouse_sources_queue.backend.testing import (
    ensure_generic_job_tables,
    ensure_scheduler_tables,
    get_test_database_url,
    truncate_generic_job_tables,
    truncate_scheduler_tables,
)

OWNER_A = str(uuid4())
OWNER_B = str(uuid4())

INTERVAL = 21600


def _state(schema_id: str, *, due_in_seconds: float, interval: int = INTERVAL, offset: int = 0) -> DueSchedule:
    return DueSchedule(
        schema_id=schema_id,
        team_id=1,
        interval_seconds=interval,
        offset_seconds=offset,
        next_due_at=datetime.now(UTC) + timedelta(seconds=due_in_seconds),
    )


def _decision(schema_id: str, window_boundary: datetime, decision: str = "would_fire") -> DecisionRecord:
    return DecisionRecord(
        team_id=1,
        schema_id=schema_id,
        window_boundary=window_boundary,
        due_at=window_boundary,
        decision=decision,
        interval_seconds=INTERVAL,
        late_seconds=1.0,
    )


async def _fetch_states(conn: psycopg.AsyncConnection[Any]) -> dict[str, dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT * FROM {SCHEDULER_STATE_TABLE}")
        return {row["schema_id"]: row for row in await cur.fetchall()}


@pytest.fixture(scope="session")
def _db_url() -> str:
    return get_test_database_url()


@pytest.fixture(scope="session", autouse=True)
def _create_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        ensure_scheduler_tables(conn)
        ensure_generic_job_tables(conn)


@pytest.fixture(autouse=True)
def _clean_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        truncate_scheduler_tables(conn)
        truncate_generic_job_tables(conn)


@pytest.fixture
async def conn(_db_url: str):
    async with await psycopg.AsyncConnection.connect(_db_url, autocommit=True) as c:
        yield c


@pytest.mark.django_db(transaction=True)
class TestSchedulerState:
    @pytest.mark.asyncio
    async def test_claim_due_returns_only_due_rows_and_advances_them(self, conn):
        await SchedulerStateTable.upsert_states(
            conn,
            [_state("due-schema", due_in_seconds=-60), _state("future-schema", due_in_seconds=3600)],
        )

        async with conn.transaction():
            due = await SchedulerStateTable.claim_due(conn, limit=10)
            assert [row.schema_id for row in due] == ["due-schema"]
            await SchedulerStateTable.advance_states(
                conn, [(row.schema_id, datetime.now(UTC) + timedelta(seconds=INTERVAL)) for row in due]
            )

        async with conn.transaction():
            assert await SchedulerStateTable.claim_due(conn, limit=10) == []

    @pytest.mark.asyncio
    async def test_decision_insert_dedups_on_schema_and_window(self, conn):
        boundary = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

        assert await SchedulerStateTable.insert_decisions(conn, [_decision("s1", boundary)]) == (1, 0)
        # Same window again (a duplicate tick) is refused; a skip decision for
        # the same window must not overwrite the recorded one either.
        assert await SchedulerStateTable.insert_decisions(
            conn, [_decision("s1", boundary, decision="skip_overlap")]
        ) == (0, 1)
        assert await SchedulerStateTable.insert_decisions(
            conn, [_decision("s1", boundary + timedelta(seconds=INTERVAL)), _decision("s2", boundary)]
        ) == (2, 0)

    @pytest.mark.asyncio
    async def test_upsert_preserves_next_due_at_unless_cadence_changed(self, conn):
        first = _state("s1", due_in_seconds=600)
        await SchedulerStateTable.upsert_states(conn, [first])

        await SchedulerStateTable.upsert_states(conn, [_state("s1", due_in_seconds=9999)])
        states = await _fetch_states(conn)
        assert states["s1"]["next_due_at"] == first.next_due_at

        recadenced = _state("s1", due_in_seconds=120, interval=3600, offset=60)
        await SchedulerStateTable.upsert_states(conn, [recadenced])
        states = await _fetch_states(conn)
        assert states["s1"]["next_due_at"] == recadenced.next_due_at
        assert states["s1"]["interval_seconds"] == 3600
        assert states["s1"]["offset_seconds"] == 60

    @pytest.mark.asyncio
    async def test_stale_state_rows_deleted_after_refresh_cutoff(self, conn):
        await SchedulerStateTable.upsert_states(
            conn, [_state("kept", due_in_seconds=600), _state("stale", due_in_seconds=600)]
        )
        async with conn.cursor() as cur:
            await cur.execute("SELECT now()")
            row = await cur.fetchone()
            assert row is not None
            cutoff = row[0]
        await SchedulerStateTable.upsert_states(conn, [_state("kept", due_in_seconds=600)])

        assert await SchedulerStateTable.delete_states_not_refreshed_since(conn, cutoff) == 1
        assert set(await _fetch_states(conn)) == {"kept"}

    @pytest.mark.asyncio
    async def test_sentinel_slot_single_flights_within_ttl(self, conn):
        async def acquire(owner: str) -> bool:
            return await JobsTable.try_acquire_sentinel_slot(
                conn, lane="scheduler", group_key="tick-slot", owner_token=owner, ttl_seconds=60.0
            )

        assert await acquire(OWNER_A) is True
        # No same-owner re-entrancy: the TTL is the fleet cadence.
        assert await acquire(OWNER_A) is False
        assert await acquire(OWNER_B) is False

        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE {JOB_LEASE_TABLE} SET expires_at = now() - interval '1 second'")
        assert await acquire(OWNER_B) is True
