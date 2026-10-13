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
KIND = "test.kind"


def _state(
    schedule_key: str, *, kind: str = KIND, due_in_seconds: float, interval: int = INTERVAL, offset: int = 0
) -> DueSchedule:
    return DueSchedule(
        kind=kind,
        schedule_key=schedule_key,
        team_id=1,
        interval_seconds=interval,
        offset_seconds=offset,
        next_due_at=datetime.now(UTC) + timedelta(seconds=due_in_seconds),
    )


def _decision(
    schedule_key: str,
    window_boundary: datetime,
    decision: str = "would_fire",
    *,
    kind: str = KIND,
    due_at: datetime | None = None,
) -> DecisionRecord:
    return DecisionRecord(
        team_id=1,
        kind=kind,
        schedule_key=schedule_key,
        window_boundary=window_boundary,
        due_at=due_at or window_boundary,
        decision=decision,
        interval_seconds=INTERVAL,
        late_seconds=1.0,
    )


async def _fetch_states(conn: psycopg.AsyncConnection[Any]) -> dict[tuple[str, str], dict[str, Any]]:
    async with conn.cursor(row_factory=dict_row) as cur:
        await cur.execute(f"SELECT * FROM {SCHEDULER_STATE_TABLE}")
        return {(row["kind"], row["schedule_key"]): row for row in await cur.fetchall()}


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
            [_state("due-schedule", due_in_seconds=-60), _state("future-schedule", due_in_seconds=3600)],
        )

        async with conn.transaction():
            due = await SchedulerStateTable.claim_due(conn, kind=KIND, limit=10)
            assert [row.schedule_key for row in due] == ["due-schedule"]
            await SchedulerStateTable.advance_states(
                conn, [(row, datetime.now(UTC) + timedelta(seconds=INTERVAL)) for row in due]
            )

        async with conn.transaction():
            assert await SchedulerStateTable.claim_due(conn, kind=KIND, limit=10) == []

    @pytest.mark.asyncio
    async def test_decision_insert_dedups_on_kind_key_and_due_time(self, conn):
        boundary = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
        first = _decision("s1", boundary)

        assert await SchedulerStateTable.insert_decisions(conn, [first]) == ([first], 0)
        # The same due time again (a duplicate tick) is refused; a skip decision
        # must not overwrite the recorded one either.
        assert await SchedulerStateTable.insert_decisions(
            conn, [_decision("s1", boundary, decision="skip_overlap")]
        ) == ([], 1)

        recadenced = _decision("s1", boundary, due_at=boundary + timedelta(minutes=30))
        other_schedule = _decision("s2", boundary)
        assert await SchedulerStateTable.insert_decisions(conn, [recadenced, other_schedule]) == (
            [recadenced, other_schedule],
            0,
        )
        other_kind = _decision("s1", boundary, kind="other.kind")
        assert await SchedulerStateTable.insert_decisions(conn, [other_kind]) == ([other_kind], 0)

    @pytest.mark.asyncio
    async def test_state_operations_are_scoped_to_kind(self, conn):
        first = _state("shared", due_in_seconds=-60)
        second = _state("shared", kind="other.kind", due_in_seconds=-60)
        await SchedulerStateTable.upsert_states(conn, [first, second])

        assert set(await _fetch_states(conn)) == {(KIND, "shared"), ("other.kind", "shared")}
        async with conn.transaction():
            assert await SchedulerStateTable.claim_due(conn, kind=KIND, limit=10) == [first]
        assert await SchedulerStateTable.delete_states(conn, KIND, ["shared"]) == 1
        assert set(await _fetch_states(conn)) == {("other.kind", "shared")}

    @pytest.mark.asyncio
    async def test_upsert_preserves_next_due_at_unless_cadence_changed(self, conn):
        first = _state("s1", due_in_seconds=600)
        await SchedulerStateTable.upsert_states(conn, [first])

        await SchedulerStateTable.upsert_states(conn, [_state("s1", due_in_seconds=9999)])
        states = await _fetch_states(conn)
        assert states[(KIND, "s1")]["next_due_at"] == first.next_due_at

        recadenced = _state("s1", due_in_seconds=120, interval=3600, offset=60)
        await SchedulerStateTable.upsert_states(conn, [recadenced])
        states = await _fetch_states(conn)
        assert states[(KIND, "s1")]["next_due_at"] == recadenced.next_due_at
        assert states[(KIND, "s1")]["interval_seconds"] == 3600
        assert states[(KIND, "s1")]["offset_seconds"] == 60

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "new_interval,new_offset",
        [
            pytest.param(3600, 0, id="interval_changed"),
            pytest.param(INTERVAL, 60, id="offset_changed"),
            pytest.param(3600, 60, id="both_changed"),
        ],
    )
    async def test_single_upsert_applies_due_time_rule_per_row(self, conn, new_interval, new_offset):
        unchanged = _state("unchanged", due_in_seconds=600)
        await SchedulerStateTable.upsert_states(conn, [unchanged, _state("recadenced", due_in_seconds=600)])

        recadenced = _state("recadenced", due_in_seconds=120, interval=new_interval, offset=new_offset)
        new = _state("new", due_in_seconds=300, interval=3600, offset=30)
        await SchedulerStateTable.upsert_states(conn, [_state("unchanged", due_in_seconds=9999), recadenced, new])

        states = await _fetch_states(conn)
        assert {
            key: (row["next_due_at"], row["interval_seconds"], row["offset_seconds"])
            for (_, key), row in states.items()
        } == {
            "unchanged": (unchanged.next_due_at, INTERVAL, 0),
            "recadenced": (recadenced.next_due_at, new_interval, new_offset),
            "new": (new.next_due_at, 3600, 30),
        }

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

        assert await SchedulerStateTable.delete_states_not_refreshed_since(conn, KIND, cutoff) == 1
        assert set(await _fetch_states(conn)) == {(KIND, "kept")}

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
