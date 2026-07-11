from typing import Any
from uuid import uuid4

import pytest

import psycopg

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    BATCH_TABLE,
    LEASE_TABLE,
    STATUS_TABLE,
    STATUS_VIEW,
    BatchQueue,
    PendingBatch,
)

# Distinct per-pod identities for the group-lease tests.
OWNER_A = str(uuid4())
OWNER_B = str(uuid4())


async def _claim(conn: psycopg.AsyncConnection[Any], owner: str = OWNER_A, **kwargs: Any) -> list[PendingBatch]:
    return await BatchQueue.get_unprocessed_and_lock(conn, owner_token=owner, **kwargs)


async def _release(conn: psycopg.AsyncConnection[Any], *, batches: list[PendingBatch], owner: str = OWNER_A) -> None:
    await BatchQueue.unlock_for_batches(conn, batches=batches, owner_token=owner)


def _get_test_database_url() -> str:
    from django.db import connection

    s = connection.settings_dict
    host = s.get("HOST", "localhost") or "localhost"
    port = s.get("PORT", "5432") or "5432"
    return f"postgres://{s['USER']}:{s['PASSWORD']}@{host}:{port}/{s['NAME']}"


def _ensure_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {BATCH_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            source_id VARCHAR(200) NOT NULL,
            job_id VARCHAR(200) NOT NULL,
            run_uuid VARCHAR(200) NOT NULL,
            batch_index INT NOT NULL,
            s3_path TEXT NOT NULL,
            row_count INT NOT NULL,
            byte_size BIGINT NOT NULL,
            is_final_batch BOOLEAN NOT NULL,
            total_batches INT,
            total_rows BIGINT,
            sync_type VARCHAR(32) NOT NULL,
            cumulative_row_count BIGINT NOT NULL DEFAULT 0,
            resource_name VARCHAR(400) NOT NULL,
            is_resume BOOLEAN NOT NULL DEFAULT FALSE,
            is_first_ever_sync BOOLEAN NOT NULL DEFAULT FALSE,
            metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            latest_state VARCHAR(32) NOT NULL DEFAULT 'pending',
            latest_attempt SMALLINT NOT NULL DEFAULT 0,
            state_changed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    # Self-heal pre-existing test DBs where CREATE TABLE IF NOT EXISTS is a no-op.
    conn.execute(f"""
        ALTER TABLE {BATCH_TABLE}
            ADD COLUMN IF NOT EXISTS latest_state VARCHAR(32) NOT NULL DEFAULT 'pending',
            ADD COLUMN IF NOT EXISTS latest_attempt SMALLINT NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS state_changed_at TIMESTAMPTZ
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_claimable_idx ON {BATCH_TABLE} (team_id, created_at, batch_index)
            WHERE latest_state IN ('pending', 'waiting_retry')
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_run_gate_idx ON {BATCH_TABLE} (run_uuid, latest_state, batch_index)
            WHERE latest_state IN ('executing', 'waiting_retry', 'failed')
    """)
    conn.execute(f"""
        CREATE INDEX IF NOT EXISTS sb_schema_busy_idx ON {BATCH_TABLE} (team_id, schema_id)
            WHERE latest_state = 'executing'
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {STATUS_TABLE} (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            batch_id UUID NOT NULL REFERENCES {BATCH_TABLE}(id) ON DELETE CASCADE,
            job_state VARCHAR(32) NOT NULL,
            attempt SMALLINT NOT NULL DEFAULT 0,
            exec_time TIMESTAMPTZ,
            error_response JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {LEASE_TABLE} (
            id BIGSERIAL PRIMARY KEY,
            team_id BIGINT NOT NULL,
            schema_id VARCHAR(200) NOT NULL,
            owner_token VARCHAR(64) NOT NULL,
            expires_at TIMESTAMPTZ NOT NULL,
            acquired_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT sgl_team_schema_uniq UNIQUE (team_id, schema_id)
        )
    """)
    conn.execute(f"DROP VIEW IF EXISTS {STATUS_VIEW}")
    conn.execute(f"""
        CREATE VIEW {STATUS_VIEW} AS
        SELECT DISTINCT ON (batch_id) *
        FROM {STATUS_TABLE}
        ORDER BY batch_id ASC, created_at DESC, id DESC
    """)


def _truncate_tables(conn: psycopg.Connection[Any]) -> None:
    conn.execute(f"TRUNCATE {STATUS_TABLE}, {BATCH_TABLE}, {LEASE_TABLE} RESTART IDENTITY CASCADE")


_BATCH_DEFAULTS: dict[str, Any] = {
    "team_id": 1,
    "schema_id": "schema-1",
    "source_id": "source-1",
    "job_id": "job-1",
    "run_uuid": "run-1",
    "batch_index": 0,
    "s3_path": "s3://bucket/path",
    "row_count": 100,
    "byte_size": 1024,
    "is_final_batch": False,
    "total_batches": None,
    "total_rows": None,
    "sync_type": "full_refresh",
    "cumulative_row_count": 0,
    "resource_name": "test_resource",
    "is_resume": False,
    "is_first_ever_sync": False,
    "metadata": {},
}


async def _insert_batch(conn: psycopg.AsyncConnection[Any], **overrides: Any) -> str:
    params = {**_BATCH_DEFAULTS, **overrides}
    return await BatchQueue.insert(conn, **params)


@pytest.fixture(scope="session")
def _db_url() -> str:
    return _get_test_database_url()


@pytest.fixture(scope="session", autouse=True)
def _create_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        _ensure_tables(conn)


@pytest.fixture(autouse=True)
def _clean_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        _truncate_tables(conn)
        conn.execute("SELECT pg_advisory_unlock_all()")


@pytest.fixture
async def conn(_db_url: str):
    async with await psycopg.AsyncConnection.connect(_db_url, autocommit=True) as c:
        yield c


@pytest.fixture
async def conn_b(_db_url: str):
    async with await psycopg.AsyncConnection.connect(_db_url, autocommit=True) as c:
        yield c


@pytest.fixture
def sync_conn(_db_url: str):
    with psycopg.Connection.connect(_db_url, autocommit=True) as c:
        yield c


@pytest.mark.django_db(transaction=True)
class TestBatchQueueInsert:
    @pytest.mark.asyncio
    async def test_insert_returns_uuid(self, conn):
        batch_id = await _insert_batch(conn)

        assert len(batch_id) == 36
        assert batch_id.count("-") == 4

    @pytest.mark.asyncio
    async def test_insert_unique_ids(self, conn):
        id1 = await _insert_batch(conn, batch_index=0)
        id2 = await _insert_batch(conn, batch_index=1)

        assert id1 != id2


@pytest.mark.django_db(transaction=True)
class TestBatchQueueGetUnprocessed:
    @pytest.mark.asyncio
    async def test_returns_new_batches(self, conn):
        await _insert_batch(conn, batch_index=0)
        await _insert_batch(conn, batch_index=1)
        await _insert_batch(conn, batch_index=2)

        batches = await _claim(conn)

        assert len(batches) == 3
        assert sorted(b.batch_index for b in batches) == [0, 1, 2]

    @pytest.mark.asyncio
    async def test_skips_succeeded_batches(self, conn):
        bid = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=bid, job_state="succeeded", attempt=1)

        batches = await _claim(conn)

        assert len(batches) == 0

    @pytest.mark.asyncio
    async def test_returns_waiting_retry_batches(self, conn):
        bid = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=bid, job_state="waiting_retry", attempt=1)

        batches = await _claim(conn)

        assert len(batches) == 1
        assert batches[0].latest_attempt == 1

    @pytest.mark.asyncio
    async def test_skips_entire_failed_run(self, conn):
        await _insert_batch(conn, batch_index=0, run_uuid="run-fail")
        bid2 = await _insert_batch(conn, batch_index=1, run_uuid="run-fail")
        await BatchQueue.update_status(conn, batch_id=bid2, job_state="failed", attempt=1)

        batches = await _claim(conn)

        assert len(batches) == 0

    @pytest.mark.asyncio
    async def test_respects_limit(self, conn):
        for i in range(10):
            await _insert_batch(conn, batch_index=i)

        batches = await _claim(conn, limit=3)

        assert len(batches) == 3

    @pytest.mark.asyncio
    async def test_excludes_schema_with_in_flight_batch(self, conn):
        # A schema with an executing batch contributes no candidates, even for
        # NULL-status batches from a different (later) run of the same schema.
        executing_bid = await _insert_batch(conn, schema_id="busy", run_uuid="run-a", batch_index=0)
        await _insert_batch(conn, schema_id="busy", run_uuid="run-b", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=executing_bid, job_state="executing", attempt=1)

        batches = await _claim(conn)

        assert batches == []

    @pytest.mark.asyncio
    async def test_in_flight_schema_does_not_starve_other_schemas(self, conn):
        # Regression: a busy schema's older backlog (from a later run) must not fill
        # the LIMIT window ahead of a different schema's claimable work.
        a_exec = await _insert_batch(conn, schema_id="A", run_uuid="a-run-1", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=a_exec, job_state="executing", attempt=1)
        for i in range(5):  # older than B, would fill limit=3 if not excluded
            await _insert_batch(conn, schema_id="A", run_uuid="a-run-2", batch_index=i)
        await _insert_batch(conn, schema_id="B", run_uuid="b-run-1", batch_index=0)  # newest

        batches = await _claim(conn, limit=3)

        assert [b.schema_id for b in batches] == ["B"]
        await _release(conn, batches=batches)

    @pytest.mark.asyncio
    async def test_heavy_team_does_not_monopolize_poll_window(self, conn):
        # One team's deep, older backlog must not fill the whole LIMIT window under
        # global FIFO — round-robin interleaving must still admit another team's newer batch.
        for i in range(5):
            await _insert_batch(conn, team_id=1, schema_id="heavy", run_uuid="heavy-run", batch_index=i)
        await _insert_batch(conn, team_id=2, schema_id="light", run_uuid="light-run", batch_index=0)
        await conn.execute(f"UPDATE {BATCH_TABLE} SET created_at = created_at - interval '1 hour' WHERE team_id = 1")

        batches = await _claim(conn, limit=3)

        assert {b.team_id for b in batches} == {1, 2}
        await _release(conn, batches=batches)

    @pytest.mark.asyncio
    async def test_in_flight_gating_clears_after_terminal_status(self, conn):
        # Once the executing batch is superseded by a terminal status, the schema's
        # queued batches become selectable again.
        exec_bid = await _insert_batch(conn, schema_id="S", run_uuid="run-1", batch_index=0)
        await _insert_batch(conn, schema_id="S", run_uuid="run-2", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=exec_bid, job_state="executing", attempt=1)
        # Backdate the executing row so the succeeded row below is unambiguously
        # the latest for the view's (created_at DESC, id DESC) tie-break.
        await conn.execute(
            f"UPDATE {STATUS_TABLE} SET created_at = created_at - interval '5 seconds' WHERE batch_id = %s",
            [exec_bid],
        )

        assert await _claim(conn) == []

        await BatchQueue.update_status(conn, batch_id=exec_bid, job_state="succeeded", attempt=1)

        batches = await _claim(conn)

        assert [b.run_uuid for b in batches] == ["run-2"]
        await _release(conn, batches=batches)


@pytest.mark.django_db(transaction=True)
class TestBatchQueueUpdateStatus:
    @pytest.mark.asyncio
    async def test_appends_multiple_statuses(self, conn):
        bid = await _insert_batch(conn)

        await BatchQueue.update_status(conn, batch_id=bid, job_state="executing", attempt=1)
        await BatchQueue.update_status(conn, batch_id=bid, job_state="succeeded", attempt=1)

        row = await conn.execute(f"SELECT count(*) FROM {STATUS_TABLE} WHERE batch_id = %s", [bid])
        count = (await row.fetchone())[0]
        assert count == 2


@pytest.mark.django_db(transaction=True)
class TestBatchQueueFailRun:
    @pytest.mark.asyncio
    async def test_fails_only_pending_batches(self, conn):
        bid1 = await _insert_batch(conn, batch_index=0, run_uuid="run-x")
        await _insert_batch(conn, batch_index=1, run_uuid="run-x")
        await _insert_batch(conn, batch_index=2, run_uuid="run-x")
        await BatchQueue.update_status(conn, batch_id=bid1, job_state="succeeded", attempt=1)

        count = await BatchQueue.fail_run(conn, run_uuid="run-x", reason="test failure")

        assert count == 2

        batches = await _claim(conn)
        assert len(batches) == 0


async def _insert_lease(
    conn: psycopg.AsyncConnection[Any],
    *,
    team_id: int = 1,
    schema_id: str = "schema-1",
    owner: str = OWNER_A,
    expires_in_seconds: int = 300,
) -> None:
    """Insert a lease row directly. Negative ``expires_in_seconds`` makes it already expired."""
    await conn.execute(
        f"INSERT INTO {LEASE_TABLE} (team_id, schema_id, owner_token, expires_at) "
        f"VALUES (%s, %s, %s, now() + make_interval(secs => %s))",
        [team_id, schema_id, owner, expires_in_seconds],
    )


async def _lease_owner(
    conn: psycopg.AsyncConnection[Any], *, team_id: int = 1, schema_id: str = "schema-1"
) -> str | None:
    row = await (
        await conn.execute(
            f"SELECT owner_token FROM {LEASE_TABLE} WHERE team_id = %s AND schema_id = %s", [team_id, schema_id]
        )
    ).fetchone()
    return row[0] if row else None


async def _lease_expiry(conn: psycopg.AsyncConnection[Any], *, team_id: int = 1, schema_id: str = "schema-1") -> Any:
    row = await (
        await conn.execute(
            f"SELECT expires_at FROM {LEASE_TABLE} WHERE team_id = %s AND schema_id = %s", [team_id, schema_id]
        )
    ).fetchone()
    return row[0] if row else None


async def _lease_count(conn: psycopg.AsyncConnection[Any], *, team_id: int = 1, schema_id: str = "schema-1") -> int:
    row = await (
        await conn.execute(
            f"SELECT count(*) FROM {LEASE_TABLE} WHERE team_id = %s AND schema_id = %s", [team_id, schema_id]
        )
    ).fetchone()
    return int(row[0]) if row else 0


async def _insert_backdated_executing(
    conn: psycopg.AsyncConnection[Any], *, batch_id: str, age_seconds: int = 120, attempt: int = 1
) -> None:
    # Seed through the dual-write, then backdate both clocks, so the log and
    # the state columns stay consistent like they do under real writers.
    await BatchQueue.update_status(conn, batch_id=batch_id, job_state="executing", attempt=attempt)
    await conn.execute(
        f"UPDATE {STATUS_TABLE} SET created_at = created_at - make_interval(secs => %s) WHERE batch_id = %s",
        [age_seconds, batch_id],
    )
    await conn.execute(
        f"UPDATE {BATCH_TABLE} SET state_changed_at = state_changed_at - make_interval(secs => %s) WHERE id = %s",
        [age_seconds, batch_id],
    )


@pytest.mark.django_db(transaction=True)
class TestBatchQueueGroupLease:
    @pytest.mark.asyncio
    async def test_live_lease_excludes_other_owner(self, conn, conn_b):
        await _insert_batch(conn, team_id=1, schema_id="s1", batch_index=0)
        await _insert_batch(conn, team_id=1, schema_id="s1", batch_index=1)
        await _insert_batch(conn, team_id=1, schema_id="s1", batch_index=2)

        batches = await _claim(conn, owner=OWNER_A)
        assert len(batches) == 3
        assert await _lease_owner(conn, schema_id="s1") == OWNER_A

        batches_b = await _claim(conn_b, owner=OWNER_B)
        assert len(batches_b) == 0, "another owner must not claim a group with a live lease"

        await _release(conn, batches=batches, owner=OWNER_A)
        assert await _lease_owner(conn, schema_id="s1") is None

        batches_b = await _claim(conn_b, owner=OWNER_B)
        assert len(batches_b) == 3, "the group is claimable once its lease is released"
        assert await _lease_owner(conn, schema_id="s1") == OWNER_B

    @pytest.mark.asyncio
    async def test_same_owner_reclaim_is_idempotent(self, conn):
        await _insert_batch(conn, team_id=1, schema_id="s1", batch_index=0)
        await _insert_batch(conn, team_id=1, schema_id="s1", batch_index=1)

        first = await _claim(conn, owner=OWNER_A)
        assert len(first) == 2
        expiry_1 = await _lease_expiry(conn, schema_id="s1")

        # Re-claiming the same group renews (no ON CONFLICT error, single lease row, later expiry).
        second = await _claim(conn, owner=OWNER_A)
        assert len(second) == 2
        assert await _lease_count(conn, schema_id="s1") == 1
        assert await _lease_expiry(conn, schema_id="s1") >= expiry_1

    @pytest.mark.asyncio
    async def test_different_keys_lease_independently(self, conn, conn_b):
        await _insert_batch(conn, team_id=1, schema_id="s1")
        await _insert_batch(conn, team_id=2, schema_id="s2")

        batches_a = await _claim(conn, owner=OWNER_A)
        assert len(batches_a) == 2

        await _release(conn, batches=[b for b in batches_a if b.schema_id == "s1"], owner=OWNER_A)

        batches_b = await _claim(conn_b, owner=OWNER_B)
        assert len(batches_b) == 1, "only the released group is reclaimable"
        assert batches_b[0].schema_id == "s1"

    @pytest.mark.asyncio
    async def test_expired_lease_is_reclaimed(self, conn, conn_b):
        await _insert_batch(conn, team_id=1, schema_id="s1", batch_index=0)
        await _insert_batch(conn, team_id=1, schema_id="s1", batch_index=1)
        # A previous owner died without releasing; its lease has already expired.
        await _insert_lease(conn, team_id=1, schema_id="s1", owner=OWNER_A, expires_in_seconds=-1)

        batches = await _claim(conn_b, owner=OWNER_B)

        assert len(batches) == 2, "an expired lease must not block a new owner"
        assert await _lease_owner(conn, schema_id="s1") == OWNER_B
        assert await _lease_expiry(conn, schema_id="s1") is not None

    @pytest.mark.asyncio
    async def test_release_does_not_delete_another_owners_lease(self, conn):
        # A slow group whose lease already expired and was reclaimed by another pod
        # must not delete the new owner's lease when its own finally-block releases.
        await _insert_batch(conn, team_id=1, schema_id="s1")
        claimed = await _claim(conn, owner=OWNER_B)
        assert await _lease_owner(conn, schema_id="s1") == OWNER_B

        # The old owner (A) tries to release the same group; its token no longer matches.
        await _release(conn, batches=claimed, owner=OWNER_A)

        assert await _lease_owner(conn, schema_id="s1") == OWNER_B, "a non-owner release must be a no-op"


@pytest.mark.django_db(transaction=True)
class TestBatchQueueLeaseRenewal:
    @pytest.mark.asyncio
    async def test_renew_extends_expiry_for_owner(self, conn):
        await _insert_lease(conn, team_id=1, schema_id="s1", owner=OWNER_A, expires_in_seconds=10)
        before = await _lease_expiry(conn, schema_id="s1")

        renewed = await BatchQueue.renew_lease(
            conn, team_id=1, schema_id="s1", owner_token=OWNER_A, lease_ttl_seconds=300
        )

        assert renewed is True
        assert await _lease_expiry(conn, schema_id="s1") > before

    @pytest.mark.asyncio
    async def test_renew_returns_false_for_non_owner(self, conn):
        await _insert_lease(conn, team_id=1, schema_id="s1", owner=OWNER_A, expires_in_seconds=300)

        renewed = await BatchQueue.renew_lease(
            conn, team_id=1, schema_id="s1", owner_token=OWNER_B, lease_ttl_seconds=300
        )

        assert renewed is False, "a non-owner cannot renew the lease"

    @pytest.mark.asyncio
    async def test_renew_returns_false_when_absent(self, conn):
        renewed = await BatchQueue.renew_lease(
            conn, team_id=1, schema_id="s1", owner_token=OWNER_A, lease_ttl_seconds=300
        )

        assert renewed is False


@pytest.mark.django_db(transaction=True)
class TestVerifyGroupLeaseSync:
    # Must agree with the async verify_advisory_lock predicate: a divergence
    # (e.g. dropping the expiry check) silently disarms the pre-commit guard.
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "lease_expires_in,checked_owner,expected",
        [
            (300, OWNER_A, True),  # live lease, right owner
            (-1, OWNER_A, False),  # expired lease
            (300, OWNER_B, False),  # live lease held by someone else
            (None, OWNER_A, False),  # no lease row at all
        ],
    )
    async def test_matches_lease_state(self, conn, _db_url, lease_expires_in, checked_owner, expected):
        if lease_expires_in is not None:
            await _insert_lease(conn, team_id=1, schema_id="s1", owner=OWNER_A, expires_in_seconds=lease_expires_in)

        owns = BatchQueue.verify_group_lease_sync(
            _db_url, team_id=1, schema_id="s1", owner_token=checked_owner, connect_timeout_seconds=5
        )

        assert owns is expected


@pytest.mark.django_db(transaction=True)
class TestQueueFreshnessProbe:
    @pytest.mark.asyncio
    async def test_reports_only_batches_never_picked_up(self, conn):
        assert await BatchQueue.get_oldest_unclaimed_batch_age_seconds(conn) is None

        bid = await _insert_batch(conn)
        age = await BatchQueue.get_oldest_unclaimed_batch_age_seconds(conn)
        assert age is not None and age >= 0

        # Any status row means the batch was picked up — it must stop counting.
        await BatchQueue.update_status(conn, batch_id=bid, job_state="executing", attempt=1)
        assert await BatchQueue.get_oldest_unclaimed_batch_age_seconds(conn) is None


@pytest.mark.django_db(transaction=True)
class TestOldestNonTerminalBatchAge:
    @pytest.mark.parametrize(
        "job_state,expect_pending",
        [
            (None, True),  # never claimed
            ("executing", True),
            ("waiting_retry", True),
            ("succeeded", False),
            ("failed", False),
        ],
    )
    @pytest.mark.asyncio
    async def test_counts_only_non_terminal_states(self, conn, sync_conn, job_state, expect_pending):
        bid = await _insert_batch(conn)
        if job_state is not None:
            await BatchQueue.update_status(conn, batch_id=bid, job_state=job_state, attempt=1)

        age = BatchQueue.get_oldest_non_terminal_batch_age_seconds(sync_conn, team_id=1, schema_ids=["schema-1"])

        if expect_pending:
            assert age is not None and age >= 0
        else:
            assert age is None

    @pytest.mark.asyncio
    async def test_scoped_to_team_and_schemas(self, conn, sync_conn):
        await _insert_batch(conn)

        assert (
            BatchQueue.get_oldest_non_terminal_batch_age_seconds(sync_conn, team_id=1, schema_ids=["other-schema"])
            is None
        )
        assert (
            BatchQueue.get_oldest_non_terminal_batch_age_seconds(sync_conn, team_id=2, schema_ids=["schema-1"]) is None
        )
        assert (
            BatchQueue.get_oldest_non_terminal_batch_age_seconds(
                sync_conn, team_id=1, schema_ids=["schema-1", "other-schema"]
            )
            is not None
        )


@pytest.mark.django_db(transaction=True)
class TestGroupLeaseRecovery:
    @pytest.mark.asyncio
    async def test_absent_lease_orphan_is_recovered(self, conn):
        bid = await _insert_batch(conn)
        await _insert_backdated_executing(conn, batch_id=bid, age_seconds=120, attempt=1)

        stale = await BatchQueue.get_stale_executing(conn, grace_seconds=60)

        assert len(stale) == 1
        assert str(stale[0].id) == bid
        assert stale[0].latest_attempt == 1

    @pytest.mark.asyncio
    async def test_expired_lease_orphan_is_recovered(self, conn):
        """The prod-US wedge, in lease terms.

        A pod is SIGKILLed mid-group and never releases ownership; its lease
        expires. Recovery must reclaim the orphaned 'executing' batch off the
        expired lease. The old advisory lock had no expiry, so an orphaned owner
        (SIGKILL / pgbouncer session lingering / node loss) blocked recovery
        indefinitely — the wedge. An expired lease cannot.
        """
        bid = await _insert_batch(conn)
        await _insert_backdated_executing(conn, batch_id=bid, age_seconds=120)
        await _insert_lease(conn, owner=OWNER_A, expires_in_seconds=-1)

        stale = await BatchQueue.get_stale_executing(conn, grace_seconds=60)

        assert len(stale) == 1
        assert str(stale[0].id) == bid

    @pytest.mark.asyncio
    async def test_live_lease_shields_executing_from_recovery(self, conn):
        """A live lease means the owner is alive (heartbeating); its group is never reclaimed.

        This is the discriminating guard for the lease behaviour: the batch's
        'executing' status is already past the grace window, so the only thing
        keeping recovery from reclaiming it is the live lease. The pre-lease sweep
        had no lease awareness and would reclaim it here.
        """
        bid = await _insert_batch(conn)
        await _insert_backdated_executing(conn, batch_id=bid, age_seconds=120)
        await _insert_lease(conn, owner=OWNER_A, expires_in_seconds=300)

        stale = await BatchQueue.get_stale_executing(conn, grace_seconds=60)

        assert stale == [], "a live lease shields its group from recovery"

    @pytest.mark.asyncio
    async def test_grace_shields_recent_executing(self, conn):
        bid = await _insert_batch(conn)
        # Fresh 'executing', no lease: still must wait out the grace window before recovery.
        await BatchQueue.update_status(conn, batch_id=bid, job_state="executing", attempt=1)

        assert await BatchQueue.get_stale_executing(conn, grace_seconds=3600) == []

    @pytest.mark.asyncio
    async def test_grace_lets_aged_executing_through(self, conn):
        bid = await _insert_batch(conn)
        await _insert_backdated_executing(conn, batch_id=bid, age_seconds=120)

        stale = await BatchQueue.get_stale_executing(conn, grace_seconds=60)
        assert len(stale) == 1
        assert str(stale[0].id) == bid


@pytest.mark.django_db(transaction=True)
class TestBatchQueueRetryBackoff:
    @pytest.mark.asyncio
    async def test_backoff_gates_fresh_waiting_retry(self, conn):
        bid = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=bid, job_state="waiting_retry", attempt=1)

        # With a large backoff base, the just-failed batch isn't picked up.
        assert await _claim(conn, retry_backoff_base_seconds=3600) == []

        # With backoff disabled, it's eligible immediately.
        batches = await _claim(conn, retry_backoff_base_seconds=0)
        assert len(batches) == 1
        await _release(conn, batches=batches)

    @pytest.mark.asyncio
    async def test_backoff_scales_with_attempt(self, conn):
        bid = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=bid, job_state="waiting_retry", attempt=3)
        # Backdate both the status log (audit trail) and the state column
        # (the backoff clock the claim reads) by 10 seconds.
        await conn.execute(
            f"UPDATE {STATUS_TABLE} SET created_at = created_at - interval '10 seconds' WHERE batch_id = %s",
            [bid],
        )
        await conn.execute(
            f"UPDATE {BATCH_TABLE} SET state_changed_at = state_changed_at - interval '10 seconds' WHERE id = %s",
            [bid],
        )

        # base=5, attempt=3 -> 15s required, only 10s elapsed: blocked.
        assert await _claim(conn, retry_backoff_base_seconds=5) == []

        # base=3, attempt=3 -> 9s required, 10s elapsed: eligible.
        batches = await _claim(conn, retry_backoff_base_seconds=3)
        assert len(batches) == 1
        await _release(conn, batches=batches)

    @pytest.mark.asyncio
    async def test_backoff_does_not_gate_first_pickup(self, conn):
        # batches with no status rows (s.batch_id IS NULL) must always be eligible,
        # regardless of the backoff knob.
        await _insert_batch(conn)
        batches = await _claim(conn, retry_backoff_base_seconds=3600)
        assert len(batches) == 1
        await _release(conn, batches=batches)


class TestPendingBatchToExportSignal:
    def test_maps_all_fields(self):
        batch = PendingBatch(
            id="00000000-0000-0000-0000-000000000001",
            team_id=42,
            schema_id="schema-1",
            source_id="source-1",
            job_id="job-1",
            run_uuid="run-1",
            batch_index=3,
            s3_path="s3://bucket/data.parquet",
            row_count=500,
            byte_size=2048,
            is_final_batch=True,
            total_batches=4,
            total_rows=2000,
            sync_type="incremental",
            cumulative_row_count=1500,
            resource_name="users",
            is_resume=True,
            is_first_ever_sync=False,
            metadata={
                "timestamp_ns": 123456789,
                "data_folder": "/tmp/data",
                "primary_keys": ["id"],
                "cdc_write_mode": "upsert",
            },
            latest_attempt=2,
        )

        signal = batch.to_export_signal()

        assert signal["team_id"] == 42
        assert signal["job_id"] == "job-1"
        assert signal["schema_id"] == "schema-1"
        assert signal["batch_index"] == 3
        assert signal["is_final_batch"] is True
        assert signal["total_batches"] == 4
        assert signal["sync_type"] == "incremental"
        assert signal["cumulative_row_count"] == 1500
        assert signal["is_resume"] is True
        assert signal["timestamp_ns"] == 123456789
        assert signal["data_folder"] == "/tmp/data"
        assert signal["primary_keys"] == ["id"]
        assert signal["cdc_write_mode"] == "upsert"


@pytest.mark.django_db(transaction=True)
class TestGetRunActivitySummary:
    WF_RUN_ID = "wf-run-1"

    def _summary(self, sync_conn: psycopg.Connection[Any]):
        return BatchQueue.get_run_activity_summary(sync_conn, job_id="job-1", workflow_run_id=self.WF_RUN_ID)

    @pytest.mark.parametrize("age_hours,expect_stale", [(0, False), (7, True)])
    @pytest.mark.asyncio
    async def test_unclaimed_batches_are_non_terminal_and_stale_only_after_grace(
        self, conn, sync_conn, age_hours, expect_stale
    ):
        # Unclaimed batches (no status rows yet) must read as live backlog, not batch-less;
        # only after the grace window with zero activity does the run become stealable.
        bid = await _insert_batch(conn, metadata={"workflow_run_id": self.WF_RUN_ID})
        await conn.execute(
            f"UPDATE {BATCH_TABLE} SET created_at = now() - make_interval(hours => %s) WHERE id = %s",
            (age_hours, bid),
        )

        summary = self._summary(sync_conn)

        assert summary.has_batches is True
        assert summary.has_non_terminal is True
        assert summary.is_stale is expect_stale

    @pytest.mark.asyncio
    async def test_partially_loaded_run_counts_unclaimed_backlog(self, conn, sync_conn):
        # Some batches succeeded, the rest unclaimed: mid-load, not all-terminal.
        done = await _insert_batch(conn, batch_index=0, metadata={"workflow_run_id": self.WF_RUN_ID})
        await BatchQueue.update_status(conn, batch_id=done, job_state="succeeded", attempt=1)
        await _insert_batch(conn, batch_index=1, metadata={"workflow_run_id": self.WF_RUN_ID})

        summary = self._summary(sync_conn)

        assert summary.has_non_terminal is True
        assert summary.is_stale is False

    @pytest.mark.asyncio
    async def test_all_terminal_batches_report_no_non_terminal(self, conn, sync_conn):
        # Every batch terminal but the job still RUNNING (final batch never
        # enqueued) is genuinely abandoned and must remain stealable.
        for i in range(2):
            bid = await _insert_batch(conn, batch_index=i, metadata={"workflow_run_id": self.WF_RUN_ID})
            await BatchQueue.update_status(conn, batch_id=bid, job_state="succeeded", attempt=1)

        summary = self._summary(sync_conn)

        assert summary.has_batches is True
        assert summary.has_non_terminal is False

    @pytest.mark.asyncio
    async def test_other_runs_batches_do_not_count(self, conn, sync_conn):
        await _insert_batch(conn, metadata={"workflow_run_id": "other-wf-run"})

        summary = self._summary(sync_conn)

        assert summary.has_batches is False
        assert summary.has_non_terminal is False
        assert summary.is_stale is True

    @pytest.mark.asyncio
    async def test_recent_producer_inserts_do_not_reset_staleness(self, conn, sync_conn):
        # A streaming producer kept dead-loader runs "active" for a whole outage:
        # only loader progress may reset the staleness clock.
        old = await _insert_batch(conn, batch_index=0, metadata={"workflow_run_id": self.WF_RUN_ID})
        await conn.execute(
            f"UPDATE {BATCH_TABLE} SET created_at = now() - interval '7 hours' WHERE id = %s",
            (old,),
        )
        await _insert_batch(conn, batch_index=1, metadata={"workflow_run_id": self.WF_RUN_ID})

        summary = self._summary(sync_conn)

        assert summary.has_non_terminal is True
        assert summary.is_stale is True

    @pytest.mark.asyncio
    async def test_old_status_write_is_stale_despite_new_batches(self, conn, sync_conn):
        # The loader last made progress hours ago; fresh producer inserts must not hide that.
        claimed = await _insert_batch(conn, batch_index=0, metadata={"workflow_run_id": self.WF_RUN_ID})
        await BatchQueue.update_status(conn, batch_id=claimed, job_state="executing", attempt=1)
        await conn.execute(
            f"UPDATE {STATUS_TABLE} SET created_at = now() - interval '7 hours' WHERE batch_id = %s",
            (claimed,),
        )
        await _insert_batch(conn, batch_index=1, metadata={"workflow_run_id": self.WF_RUN_ID})

        summary = self._summary(sync_conn)

        assert summary.has_non_terminal is True
        assert summary.is_stale is True

    @pytest.mark.asyncio
    async def test_recent_status_write_keeps_old_backlog_active(self, conn, sync_conn):
        # A slow-but-alive loader (old unclaimed backlog, fresh status writes) must not be stolen from.
        old = await _insert_batch(conn, batch_index=0, metadata={"workflow_run_id": self.WF_RUN_ID})
        await conn.execute(
            f"UPDATE {BATCH_TABLE} SET created_at = now() - interval '7 hours' WHERE id = %s",
            (old,),
        )
        claimed = await _insert_batch(conn, batch_index=1, metadata={"workflow_run_id": self.WF_RUN_ID})
        await BatchQueue.update_status(conn, batch_id=claimed, job_state="executing", attempt=1)

        summary = self._summary(sync_conn)

        assert summary.has_non_terminal is True
        assert summary.is_stale is False


@pytest.mark.django_db(transaction=True)
class TestClaimWindowSkipsForeignLeasedGroups:
    @pytest.mark.asyncio
    async def test_foreign_leased_group_does_not_occupy_the_window(self, conn, conn_b):
        # Two claimable groups; A is older so it sits at the head of the window.
        await _insert_batch(conn, team_id=1, schema_id="schema-A", job_id="job-A", run_uuid="run-A")
        await _insert_batch(conn, team_id=2, schema_id="schema-B", job_id="job-B", run_uuid="run-B")

        got_b = await _claim(conn_b, owner=OWNER_B, limit=1)
        assert [b.schema_id for b in got_b] == ["schema-A"]

        # OWNER_A polls with a window of 1. If foreign-leased groups occupied window
        # slots (the pre-fix behavior), group A would fill the window, its lease claim
        # would fail, and OWNER_A would get nothing while group B sat claimable —
        # window starvation. The fix hands the slot to group B instead.
        got_a = await _claim(conn, owner=OWNER_A, limit=1)
        assert [b.schema_id for b in got_a] == ["schema-B"]

        # A holder's own live lease keeps its group claimable (group continuation).
        got_b_again = await _claim(conn_b, owner=OWNER_B, limit=2)
        assert "schema-A" in {b.schema_id for b in got_b_again}

        # Expired foreign leases stop shielding the group.
        await conn.execute(f"UPDATE {LEASE_TABLE} SET expires_at = now() - interval '1 second'")
        got_a_after_expiry = await _claim(conn, owner=OWNER_A, limit=2)
        assert "schema-A" in {b.schema_id for b in got_a_after_expiry}


@pytest.mark.django_db(transaction=True)
class TestCountBatchesForRun:
    @pytest.mark.asyncio
    async def test_counts_unclaimed_batches_and_zero_when_none(self, conn, _db_url):
        # Freshly inserted batches have no status row until the loader claims them. The count
        # must still see them: it exists so the CDC orphan reconciler can tell a run that
        # enqueued nothing (safe to fail) from one whose batches are merely unclaimed (a
        # status-view JOIN would report the latter as zero and strand a late load).
        await _insert_batch(conn, job_id="job-A", batch_index=0)
        await _insert_batch(conn, job_id="job-A", batch_index=1)
        await _insert_batch(conn, job_id="job-B", batch_index=0)

        with psycopg.Connection.connect(_db_url, autocommit=True) as sync_conn:
            assert BatchQueue.count_batches_for_run(sync_conn, job_id="job-A") == 2
            assert BatchQueue.count_batches_for_run(sync_conn, job_id="job-B") == 1
            assert BatchQueue.count_batches_for_run(sync_conn, job_id="job-missing") == 0


async def _batch_state(conn: psycopg.AsyncConnection[Any], batch_id: str) -> tuple[str, int, Any]:
    cur = await conn.execute(
        f"SELECT latest_state, latest_attempt, state_changed_at FROM {BATCH_TABLE} WHERE id = %s",
        (batch_id,),
    )
    row = await cur.fetchone()
    assert row is not None
    return row[0], row[1], row[2]


@pytest.mark.django_db(transaction=True)
class TestStateDualWrite:
    """The denormalized columns must always mirror the latest status row — the
    A2 claim path reads only the columns, so silent drift breaks claiming."""

    @pytest.mark.parametrize(
        "sequence,expected_state,expected_attempt",
        [
            ([("executing", 1)], "executing", 1),
            ([("executing", 1), ("succeeded", 1)], "succeeded", 1),
            ([("executing", 1), ("waiting_retry", 1), ("executing", 2), ("failed", 2)], "failed", 2),
        ],
    )
    @pytest.mark.asyncio
    async def test_update_status_mirrors_latest_into_columns(self, conn, sequence, expected_state, expected_attempt):
        bid = await _insert_batch(conn)
        state, attempt, changed = await _batch_state(conn, bid)
        assert (state, attempt, changed) == ("pending", 0, None)

        for job_state, attempt_n in sequence:
            await BatchQueue.update_status(conn, batch_id=bid, job_state=job_state, attempt=attempt_n)

        state, attempt, changed = await _batch_state(conn, bid)
        assert (state, attempt) == (expected_state, expected_attempt)
        assert changed is not None

    @pytest.mark.asyncio
    async def test_update_status_with_batch_created_at_matches_row(self, conn):
        bid = await _insert_batch(conn)
        cur = await conn.execute(f"SELECT created_at FROM {BATCH_TABLE} WHERE id = %s", (bid,))
        row = await cur.fetchone()
        assert row is not None

        await BatchQueue.update_status(conn, batch_id=bid, job_state="executing", attempt=1, batch_created_at=row[0])

        state, attempt, _ = await _batch_state(conn, bid)
        assert (state, attempt) == ("executing", 1)

    @pytest.mark.asyncio
    async def test_heartbeat_reinsert_does_not_touch_the_columns(self, conn):
        # Heartbeats re-insert 'executing' every ~100s; if they updated the batch
        # heap the columns would churn/bloat exactly when the fleet is busiest.
        bid = await _insert_batch(conn)
        await BatchQueue.update_status(conn, batch_id=bid, job_state="executing", attempt=1)
        _, _, first_changed = await _batch_state(conn, bid)

        await BatchQueue.update_status(conn, batch_id=bid, job_state="executing", attempt=1)

        _, _, second_changed = await _batch_state(conn, bid)
        assert second_changed == first_changed
        cur = await conn.execute(f"SELECT count(*) FROM {STATUS_TABLE} WHERE batch_id = %s", (bid,))
        row = await cur.fetchone()
        assert row is not None and row[0] == 2  # the log still grows

    @pytest.mark.asyncio
    async def test_fail_run_fails_columns_of_pending_batches_only(self, conn):
        pending = await _insert_batch(conn, batch_index=0, run_uuid="run-dw")
        done = await _insert_batch(conn, batch_index=1, run_uuid="run-dw")
        await BatchQueue.update_status(conn, batch_id=done, job_state="succeeded", attempt=1)

        failed = await BatchQueue.fail_run(conn, run_uuid="run-dw", reason="boom")

        assert failed == 1
        assert (await _batch_state(conn, pending))[0] == "failed"
        assert (await _batch_state(conn, done))[0] == "succeeded"

    @pytest.mark.asyncio
    async def test_supersede_fails_columns_of_older_runs(self, conn, sync_conn):
        old = await _insert_batch(conn, run_uuid="run-old", job_id="job-dw")
        current = await _insert_batch(conn, run_uuid="run-new", job_id="job-dw")

        superseded = BatchQueue.supersede_other_runs(sync_conn, job_id="job-dw", current_run_uuid="run-new")

        assert superseded == 1
        assert (await _batch_state(conn, old))[0] == "failed"
        assert (await _batch_state(conn, current))[0] == "pending"

    @pytest.mark.asyncio
    async def test_fail_batches_for_job_fails_columns_across_runs(self, conn, sync_conn):
        # The takeover path writes through this site; drift here leaves stale
        # claimable columns exactly when a job was force-failed.
        first = await _insert_batch(conn, batch_index=0, run_uuid="run-tk1", job_id="job-tk")
        second = await _insert_batch(conn, batch_index=1, run_uuid="run-tk2", job_id="job-tk")

        failed = BatchQueue.fail_batches_for_job_sync(sync_conn, job_id="job-tk", reason="takeover")

        assert failed == 2
        assert (await _batch_state(conn, first))[0] == "failed"
        assert (await _batch_state(conn, second))[0] == "failed"


@pytest.mark.django_db(transaction=True)
class TestClaimGates:
    """Every claim gate exercised in one scenario; a predicate edit that breaks
    a gate shows up as a wrong claim set here."""

    async def _seed_rich_scenario(self, conn) -> None:
        # Claimable: fresh pending batches on two teams.
        await _insert_batch(conn, team_id=1, schema_id="s-a", run_uuid="run-a", batch_index=0)
        await _insert_batch(conn, team_id=1, schema_id="s-a", run_uuid="run-a", batch_index=1)
        await _insert_batch(conn, team_id=2, schema_id="s-b", run_uuid="run-b", batch_index=0)
        # Terminal: succeeded batch must not appear.
        done = await _insert_batch(conn, team_id=3, schema_id="s-c", run_uuid="run-c", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=done, job_state="succeeded", attempt=1)
        # Failed run: sibling pending batch must be excluded.
        failed = await _insert_batch(conn, team_id=4, schema_id="s-d", run_uuid="run-d", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=failed, job_state="failed", attempt=1)
        await _insert_batch(conn, team_id=4, schema_id="s-d", run_uuid="run-d", batch_index=1)
        # Busy schema: executing batch gates its sibling run.
        busy = await _insert_batch(conn, team_id=5, schema_id="s-e", run_uuid="run-e1", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=busy, job_state="executing", attempt=1)
        await _insert_batch(conn, team_id=5, schema_id="s-e", run_uuid="run-e2", batch_index=0)
        # waiting_retry with backoff already elapsed (backoff=0 in the claim call).
        retry = await _insert_batch(conn, team_id=6, schema_id="s-f", run_uuid="run-f", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=retry, job_state="waiting_retry", attempt=1)
        # 'waiting' latest state is not claimable.
        waiting = await _insert_batch(conn, team_id=7, schema_id="s-g", run_uuid="run-g", batch_index=0)
        await BatchQueue.update_status(conn, batch_id=waiting, job_state="waiting", attempt=0)

    @pytest.mark.asyncio
    async def test_claim_applies_every_gate_at_once(self, conn):
        await self._seed_rich_scenario(conn)

        claimed = await BatchQueue.get_unprocessed_and_lock(conn, owner_token=OWNER_A, limit=50)

        # run-a (2) + run-b (1) + run-f retry (1); failed-run siblings, busy-schema
        # runs, 'waiting', and terminal batches are all excluded.
        assert sorted((b.run_uuid, b.batch_index) for b in claimed) == [
            ("run-a", 0),
            ("run-a", 1),
            ("run-b", 0),
            ("run-f", 0),
        ]

    @pytest.mark.asyncio
    async def test_state_claim_candidates_can_use_the_claimable_index(self, conn):
        # The whole point of the state path is index-bound claiming; a predicate
        # edit that breaks the partial-index match silently reverts to O(retained).
        await _insert_batch(conn)
        await conn.execute("SET enable_seqscan = off")
        try:
            from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
                _state_claim_candidates_sql,
            )

            cur = await conn.execute(
                "EXPLAIN (FORMAT TEXT) " + _state_claim_candidates_sql() + " LIMIT 50",
                {"backoff": 0},
            )
            plan = "\n".join(row[0] for row in await cur.fetchall())
        finally:
            await conn.execute("SET enable_seqscan = on")
        assert "sb_claimable_idx" in plan
