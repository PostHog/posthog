import asyncio
from typing import Any
from uuid import uuid4

import pytest

import psycopg

from products.warehouse_sources_queue.backend.core.batch_consumer import BatchConsumerConfig
from products.warehouse_sources_queue.backend.core.generic_jobs import JOB_LEASE_TABLE, JOB_TABLE, Job, JobsTable
from products.warehouse_sources_queue.backend.sdk.jobs import (
    Fail,
    FollowerSpec,
    JobConsumer,
    JobContext,
    Outcome,
    Success,
)
from products.warehouse_sources_queue.backend.testing import (
    JOB_DEFAULTS,
    ensure_generic_job_tables,
    get_test_database_url,
    truncate_generic_job_tables,
)

OWNER_A = str(uuid4())
OWNER_B = str(uuid4())

LANE = "test"
KIND = "test.kind"


async def _try_insert(conn: psycopg.AsyncConnection[Any], **overrides: Any) -> str | None:
    return await JobsTable.insert(conn, **{**JOB_DEFAULTS, **overrides})


async def _insert(conn: psycopg.AsyncConnection[Any], **overrides: Any) -> str:
    job_id = await _try_insert(conn, **overrides)
    assert job_id is not None
    return job_id


async def _claim(
    conn: psycopg.AsyncConnection[Any],
    owner: str = OWNER_A,
    *,
    lane: str = LANE,
    kinds: list[str] | None = None,
    **kwargs: Any,
) -> list[Job]:
    return await JobsTable.get_unprocessed_and_lock(conn, owner_token=owner, lane=lane, kinds=kinds or [KIND], **kwargs)


@pytest.fixture(scope="session")
def _db_url() -> str:
    return get_test_database_url()


@pytest.fixture(scope="session", autouse=True)
def _create_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        ensure_generic_job_tables(conn)


@pytest.fixture(autouse=True)
def _clean_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        truncate_generic_job_tables(conn)


@pytest.fixture
async def conn(_db_url: str):
    async with await psycopg.AsyncConnection.connect(_db_url, autocommit=True) as c:
        yield c


@pytest.fixture
async def conn_b(_db_url: str):
    async with await psycopg.AsyncConnection.connect(_db_url, autocommit=True) as c:
        yield c


@pytest.mark.django_db(transaction=True)
class TestEnqueueDedup:
    @pytest.mark.asyncio
    async def test_dedup_refuses_live_duplicate_and_frees_on_failure(self, conn):
        first = await _insert(conn, dedup_key="k1")
        assert await _try_insert(conn, dedup_key="k1") is None

        await JobsTable.update_status(conn, job_id=first, job_state="failed")
        assert await _try_insert(conn, dedup_key="k1") is not None

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"kind": "test.other", "dedup_key": "k1"}, id="other_kind"),
            pytest.param({"dedup_key": None}, id="no_dedup_key"),
        ],
    )
    @pytest.mark.asyncio
    async def test_dedup_scopes_to_kind_and_key(self, overrides, conn):
        assert await _try_insert(conn, dedup_key="k1") is not None
        assert await _try_insert(conn, **overrides) is not None

    @pytest.mark.asyncio
    async def test_insert_many_enqueues_all_in_one_call(self, conn):
        ids = await JobsTable.insert_many(
            conn,
            [
                {**JOB_DEFAULTS, "dedup_key": "a"},
                {**JOB_DEFAULTS, "group_key": "1:group-2", "dedup_key": "b"},
            ],
        )
        assert len(ids) == 2
        assert await JobsTable.get_claimable_count(conn, lane=LANE, kinds=[KIND]) == 2


@pytest.mark.django_db(transaction=True)
class TestClaim:
    @pytest.mark.asyncio
    async def test_claims_pending_job_and_leases_its_group(self, conn):
        job_id = await _insert(conn)
        claimed = await _claim(conn)
        assert [j.id for j in claimed] == [job_id]

        async with conn.cursor() as cur:
            await cur.execute(f"SELECT lane, group_key, owner_token FROM {JOB_LEASE_TABLE}")
            leases = await cur.fetchall()
        assert leases == [(LANE, JOB_DEFAULTS["group_key"], OWNER_A)]

    @pytest.mark.parametrize(
        "insert_overrides",
        [
            pytest.param({"lane": "other"}, id="wrong_lane"),
            pytest.param({"kind": "test.other"}, id="wrong_kind"),
        ],
    )
    @pytest.mark.asyncio
    async def test_claim_filters_by_lane_and_kind(self, insert_overrides, conn):
        await _insert(conn, **insert_overrides)
        assert await _claim(conn) == []

    @pytest.mark.asyncio
    async def test_live_lease_by_other_owner_blocks_claim(self, conn, conn_b):
        await _insert(conn)
        assert len(await _claim(conn, OWNER_A)) == 1
        await _insert(conn, dedup_key="second")
        assert await _claim(conn_b, OWNER_B) == []
        # The holder itself can keep draining the group.
        assert len(await _claim(conn, OWNER_A)) == 2

    @pytest.mark.asyncio
    async def test_lanes_lease_independently_for_one_group(self, conn, conn_b):
        await _insert(conn)
        await _insert(conn, lane="load", kind="load.kind")
        extract = await _claim(conn, OWNER_A)
        load = await _claim(conn_b, OWNER_B, lane="load", kinds=["load.kind"])
        assert len(extract) == 1
        assert len(load) == 1

    @pytest.mark.asyncio
    async def test_executing_group_is_not_reclaimable(self, conn, conn_b):
        job_id = await _insert(conn)
        await _claim(conn, OWNER_A)
        await JobsTable.update_status(conn, job_id=job_id, job_state="executing")
        await _insert(conn, dedup_key="second")
        # Even after the lease lapses, the executing row keeps the group busy
        # for everyone (the recovery sweep, not the claim path, handles it).
        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE {JOB_LEASE_TABLE} SET expires_at = now() - interval '1 minute'")
        assert await _claim(conn_b, OWNER_B) == []

    @pytest.mark.asyncio
    async def test_run_gate_holds_followers_behind_executing_and_failed_steps(self, conn):
        run_id = "run-1"
        first = await _insert(conn, run_id=run_id, sequence=0, dedup_key="s0")
        await _insert(conn, run_id=run_id, sequence=1, dedup_key="s1")

        await JobsTable.update_status(conn, job_id=first, job_state="executing")
        assert await _claim(conn) == []

        await JobsTable.update_status(conn, job_id=first, job_state="failed", attempt=1)
        assert await _claim(conn) == []

    @pytest.mark.asyncio
    async def test_waiting_retry_respects_backoff(self, conn):
        job_id = await _insert(conn)
        await JobsTable.update_status(conn, job_id=job_id, job_state="waiting_retry", attempt=1)
        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE {JOB_LEASE_TABLE} SET expires_at = now() - interval '1 minute'")

        assert await _claim(conn, retry_backoff_base_seconds=3600) == []
        claimed = await _claim(conn, retry_backoff_base_seconds=0)
        assert [j.id for j in claimed] == [job_id]
        assert claimed[0].latest_attempt == 1


@pytest.mark.django_db(transaction=True)
class TestStatusWrites:
    @pytest.mark.asyncio
    async def test_failed_is_absorbing_for_guarded_writes(self, conn):
        job_id = await _insert(conn)
        await JobsTable.update_status(conn, job_id=job_id, job_state="failed")

        wrote = await JobsTable.update_status_unless_failed(conn, job_id=job_id, job_state="succeeded")
        assert wrote is False
        assert await JobsTable.get_latest_state(conn, job_id=job_id) == "failed"

    @pytest.mark.asyncio
    async def test_guarded_cas_refuses_stale_writer(self, conn):
        job_id = await _insert(conn)
        await JobsTable.update_status(conn, job_id=job_id, job_state="executing")

        # A writer that observed the pre-executing state (None) loses the CAS.
        wrote = await JobsTable.update_status_unless_failed(
            conn, job_id=job_id, job_state="waiting_retry", expected_state_changed_at=None, arm_cas=True
        )
        assert wrote is False
        assert await JobsTable.get_latest_state(conn, job_id=job_id) == "executing"


@pytest.mark.django_db(transaction=True)
class TestRecoverySweep:
    @pytest.mark.asyncio
    async def test_stale_executing_needs_expired_lease(self, conn):
        job_id = await _insert(conn)
        await _claim(conn, OWNER_A)
        await JobsTable.update_status(conn, job_id=job_id, job_state="executing")
        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE {JOB_TABLE} SET state_changed_at = now() - interval '1 hour'")

        assert await JobsTable.get_stale_executing(conn, lane=LANE, kinds=[KIND], grace_seconds=60) == []

        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE {JOB_LEASE_TABLE} SET expires_at = now() - interval '1 minute'")
        stale = await JobsTable.get_stale_executing(conn, lane=LANE, kinds=[KIND], grace_seconds=60)
        assert [j.id for j in stale] == [job_id]


class _RecordingHandler:
    def __init__(self, outcome: Outcome) -> None:
        self.outcome = outcome
        self.seen: list[str] = []

    async def handle(self, job: Job, ctx: JobContext) -> Outcome:
        self.seen.append(job.id)
        return self.outcome


@pytest.mark.django_db(transaction=True)
class TestJobConsumerEndToEnd:
    @pytest.mark.asyncio
    async def test_consumer_runs_handlers_enqueues_followers_and_fails_failures(self, conn, _db_url):
        follower = FollowerSpec(
            kind="test.follower",
            lane=LANE,
            group_key=JOB_DEFAULTS["group_key"],
            team_id=1,
            payload={"from": "parent"},
            dedup_key="follower-1",
        )
        ok_handler = _RecordingHandler(Success(followers=(follower,)))
        fail_handler = _RecordingHandler(Fail(reason="configured to fail"))
        follower_handler = _RecordingHandler(Success())

        ok_id = await _insert(conn, dedup_key="ok")
        fail_id = await _insert(conn, kind="test.failing", group_key="1:group-2", dedup_key="fails")

        consumer = JobConsumer(
            config=BatchConsumerConfig(
                database_url=_db_url,
                max_concurrency=2,
                poll_interval_seconds=0.05,
                recovery_interval_seconds=3600,
                reconcile_interval_seconds=3600,
                retry_backoff_base_seconds=0,
            ),
            lane=LANE,
            handlers={
                KIND: ok_handler,
                "test.failing": fail_handler,
                "test.follower": follower_handler,
            },
        )
        run_task = asyncio.create_task(consumer.run())

        async def _settled() -> bool:
            return (
                await JobsTable.get_latest_state(conn, job_id=ok_id) == "succeeded"
                and await JobsTable.get_latest_state(conn, job_id=fail_id) == "failed"
                and follower_handler.seen != []
            )

        try:
            async with asyncio.timeout(30):
                while not await _settled():
                    await asyncio.sleep(0.05)
        finally:
            consumer.request_shutdown()
            await run_task

        assert ok_handler.seen == [ok_id]
        assert fail_handler.seen == [fail_id]
        # The follower the successful handler returned was enqueued and processed.
        async with conn.cursor() as cur:
            await cur.execute(f"SELECT latest_state, payload->>'from' FROM {JOB_TABLE} WHERE kind = 'test.follower'")
            rows = await cur.fetchall()
        assert rows == [("succeeded", "parent")]
