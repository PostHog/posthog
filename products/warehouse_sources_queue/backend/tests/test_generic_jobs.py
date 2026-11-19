import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest

import psycopg

from products.warehouse_sources_queue.backend.core.batch_consumer import BatchConsumerConfig, _group_by_key
from products.warehouse_sources_queue.backend.core.generic_jobs import JOB_LEASE_TABLE, JOB_TABLE, Job, JobsTable
from products.warehouse_sources_queue.backend.core.jobs_db import PendingBatch
from products.warehouse_sources_queue.backend.core.overlap import GroupJobState, OverlapPolicy, overlap_allows
from products.warehouse_sources_queue.backend.sdk.jobs import (
    Fail,
    FollowerSpec,
    GenericJobAdapter,
    JobConsumer,
    JobContext,
    JobRetryRequested,
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


@pytest.fixture(scope="package")
def _db_url(django_db_setup: None) -> str:
    return get_test_database_url()


@pytest.fixture(scope="package", autouse=True)
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


@pytest.mark.parametrize(
    "policy,has_running,has_pending,expected",
    [
        pytest.param(OverlapPolicy.SKIP, False, False, True, id="skip_idle_group"),
        pytest.param(OverlapPolicy.SKIP, True, False, False, id="skip_running"),
        pytest.param(OverlapPolicy.SKIP, False, True, False, id="skip_pending"),
        pytest.param(OverlapPolicy.SKIP, True, True, False, id="skip_running_and_pending"),
        pytest.param(OverlapPolicy.BUFFER_ONE, False, False, True, id="buffer_one_idle_group"),
        pytest.param(OverlapPolicy.BUFFER_ONE, True, False, True, id="buffer_one_running_buffers"),
        pytest.param(OverlapPolicy.BUFFER_ONE, False, True, False, id="buffer_one_pending"),
        pytest.param(OverlapPolicy.BUFFER_ONE, True, True, False, id="buffer_one_running_and_pending"),
    ],
)
def test_overlap_allows(policy: OverlapPolicy, has_running: bool, has_pending: bool, expected: bool) -> None:
    assert overlap_allows(policy, GroupJobState(has_running=has_running, has_pending=has_pending)) is expected


async def _seed_job(
    conn: psycopg.AsyncConnection[Any],
    *,
    state: str,
    superseded: bool = False,
    age: str | None = None,
    **overrides: Any,
) -> None:
    job_id = await _insert(conn, **overrides)
    if state != "pending":
        await JobsTable.update_status(conn, job_id=job_id, job_state=state, attempt=1)
    async with conn.cursor() as cur:
        await cur.execute(
            f"""
            UPDATE {JOB_TABLE}
            SET superseded = %(superseded)s,
                created_at = CASE WHEN %(age)s::interval IS NULL THEN created_at ELSE now() - %(age)s::interval END
            WHERE id = %(id)s
            """,
            {"superseded": superseded, "age": age, "id": job_id},
        )


IDLE = GroupJobState()
RUNNING = GroupJobState(has_running=True)
PENDING = GroupJobState(has_pending=True)


@pytest.mark.django_db(transaction=True)
class TestOverlapPolicy:
    @pytest.mark.parametrize("policy", list(OverlapPolicy))
    @pytest.mark.parametrize(
        "seed,expected_state",
        [
            pytest.param(None, IDLE, id="no_job"),
            pytest.param({"state": "pending"}, PENDING, id="pending"),
            pytest.param({"state": "executing"}, RUNNING, id="executing"),
            pytest.param({"state": "waiting_retry"}, RUNNING, id="waiting_retry"),
            pytest.param({"state": "succeeded"}, IDLE, id="succeeded"),
            pytest.param({"state": "failed"}, IDLE, id="failed"),
            pytest.param({"state": "pending", "superseded": True}, IDLE, id="superseded_pending"),
            pytest.param({"state": "executing", "superseded": True}, IDLE, id="superseded_executing"),
            pytest.param({"state": "waiting"}, IDLE, id="waiting_is_never_claimed"),
            pytest.param({"state": "pending", "age": "7 days"}, IDLE, id="pending_past_claim_eligibility"),
            pytest.param({"state": "waiting_retry", "age": "7 days"}, IDLE, id="waiting_retry_past_claim_eligibility"),
            pytest.param({"state": "executing", "age": "7 days"}, RUNNING, id="executing_inside_partition_window"),
            pytest.param({"state": "executing", "age": "15 days"}, IDLE, id="executing_past_partition_window"),
            pytest.param({"state": "pending", "kind": "test.other"}, IDLE, id="other_kind"),
            pytest.param({"state": "pending", "lane": "other"}, IDLE, id="other_lane"),
            pytest.param({"state": "pending", "group_key": "1:group-2"}, IDLE, id="other_group"),
        ],
    )
    @pytest.mark.asyncio
    async def test_live_state_and_insert_guard_agree(
        self,
        conn: psycopg.AsyncConnection[Any],
        policy: OverlapPolicy,
        seed: dict[str, Any] | None,
        expected_state: GroupJobState,
    ) -> None:
        group_key = JOB_DEFAULTS["group_key"]
        if seed is not None:
            await _seed_job(conn, **seed)

        states = await JobsTable.get_group_job_states(conn, kind=KIND, lane=LANE, group_keys=[group_key, "1:absent"])
        assert states == {group_key: expected_state, "1:absent": IDLE}

        inserted = await _try_insert(conn, overlap_policy=policy)
        assert (inserted is not None) is overlap_allows(policy, expected_state)

    @pytest.mark.asyncio
    async def test_lookup_reads_many_groups_in_one_call(self, conn: psycopg.AsyncConnection[Any]) -> None:
        await _seed_job(conn, state="executing", group_key="1:a", dedup_key="a-running")
        await _seed_job(conn, state="pending", group_key="1:a", dedup_key="a-pending")
        await _seed_job(conn, state="pending", group_key="1:b", dedup_key="b-pending")
        await _seed_job(conn, state="succeeded", group_key="1:c", dedup_key="c-done")

        states = await JobsTable.get_group_job_states(conn, kind=KIND, lane=LANE, group_keys=["1:a", "1:b", "1:c"])

        assert states == {"1:a": GroupJobState(has_running=True, has_pending=True), "1:b": PENDING, "1:c": IDLE}

    @pytest.mark.parametrize(
        "policy,expected_jobs",
        [
            pytest.param(OverlapPolicy.SKIP, 1, id="skip_refuses_behind_running"),
            pytest.param(OverlapPolicy.BUFFER_ONE, 2, id="buffer_one_buffers_exactly_one"),
        ],
    )
    @pytest.mark.asyncio
    async def test_repeated_enqueue_behind_a_running_job(
        self, conn: psycopg.AsyncConnection[Any], policy: OverlapPolicy, expected_jobs: int
    ) -> None:
        await _seed_job(conn, state="executing")
        for _ in range(3):
            await _try_insert(conn, overlap_policy=policy)

        async with conn.cursor() as cur:
            await cur.execute(f"SELECT count(*) FROM {JOB_TABLE}")
            assert await cur.fetchone() == (expected_jobs,)

    @pytest.mark.parametrize("policy", list(OverlapPolicy))
    @pytest.mark.asyncio
    async def test_policy_insert_keeps_the_dedup_guard(
        self, conn: psycopg.AsyncConnection[Any], policy: OverlapPolicy
    ) -> None:
        await _seed_job(conn, state="succeeded", dedup_key="k1")

        assert await _try_insert(conn, dedup_key="k1", overlap_policy=policy) is None
        assert await _try_insert(conn, dedup_key="k2", overlap_policy=policy) is not None


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
    async def test_run_gate_holds_followers_behind_every_unsucceeded_step(self, conn):
        run_id = "run-1"
        first = await _insert(conn, run_id=run_id, sequence=0, dedup_key="s0", priority=0)
        second = await _insert(conn, run_id=run_id, sequence=1, dedup_key="s1", priority=10)

        # A higher-priority later step must not be returned alongside its pending prerequisite.
        assert [job.id for job in await _claim(conn)] == [first]

        await JobsTable.update_status(conn, job_id=first, job_state="executing")
        assert await _claim(conn) == []

        await JobsTable.update_status(conn, job_id=first, job_state="waiting_retry", attempt=1)
        async with conn.cursor() as cur:
            await cur.execute(f"DELETE FROM {JOB_LEASE_TABLE}")
        assert [job.id for job in await _claim(conn, retry_backoff_base_seconds=0)] == [first]

        await JobsTable.update_status(conn, job_id=first, job_state="failed", attempt=1)
        assert await _claim(conn) == []
        assert await JobsTable.get_latest_state(conn, job_id=second) == "pending"

    @pytest.mark.asyncio
    async def test_engine_groups_jobs_by_the_lease_key_not_team(self, conn):
        await _insert(conn, team_id=1, dedup_key="team-1")
        await _insert(conn, team_id=2, dedup_key="team-2")

        claimed = await _claim(conn)
        assert {job.team_id for job in claimed} == {1, 2}
        assert len(_group_by_key(cast("list[PendingBatch]", claimed))) == 1

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
    @pytest.mark.parametrize("terminal_state", ["failed", "succeeded"])
    @pytest.mark.asyncio
    async def test_terminal_states_are_absorbing_for_guarded_writes(self, terminal_state, conn):
        job_id = await _insert(conn)
        await JobsTable.update_status(conn, job_id=job_id, job_state=terminal_state)

        wrote = await JobsTable.update_status_unless_failed(conn, job_id=job_id, job_state="executing")
        assert wrote is False
        assert await JobsTable.get_latest_state(conn, job_id=job_id) == terminal_state

    @pytest.mark.asyncio
    async def test_failure_transition_requires_the_current_executing_attempt(self, conn):
        job_id = await _insert(conn)
        [job] = await _claim(conn)
        adapter = GenericJobAdapter(lane=LANE, kinds=[KIND])

        await adapter.update_status(conn, batch_id=job_id, job_state="executing", attempt=1)
        await adapter.fail_run(conn, batch=job, reason="failed")

        async with conn.cursor() as cur:
            await cur.execute(f"SELECT latest_state, latest_attempt FROM {JOB_TABLE} WHERE id = %s", (job_id,))
            assert await cur.fetchone() == ("failed", 1)

        # A stale attempt cannot overwrite a later owner's terminal result.
        other_id = await _insert(conn, dedup_key="other", group_key="other")
        [other] = await _claim(conn)
        await adapter.update_status(conn, batch_id=other_id, job_state="executing", attempt=1)
        await JobsTable.update_status(conn, job_id=other_id, job_state="succeeded", attempt=2)
        await adapter.fail_run(conn, batch=other, reason="stale")
        assert await JobsTable.get_latest_state(conn, job_id=other_id) == "succeeded"

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

    @pytest.mark.asyncio
    async def test_recovery_is_bounded_and_single_flight(self, conn, conn_b):
        for index in range(2):
            job_id = await _insert(conn, group_key=f"group-{index}", dedup_key=f"job-{index}")
            await JobsTable.update_status(conn, job_id=job_id, job_state="executing", attempt=1)
        async with conn.cursor() as cur:
            await cur.execute(f"UPDATE {JOB_TABLE} SET state_changed_at = now() - interval '1 hour'")

        stale = await JobsTable.get_stale_executing(conn, lane=LANE, kinds=[KIND], limit=1)
        assert len(stale) == 1
        assert await JobsTable.get_stale_executing(conn_b, lane=LANE, kinds=[KIND], limit=1) == []

        async with conn.cursor() as cur:
            await cur.execute(
                f"UPDATE {JOB_LEASE_TABLE} SET expires_at = now() - interval '1 minute' WHERE group_key = %s",
                (JobsTable.RECOVERY_SWEEP_GROUP_KEY,),
            )
        assert len(await JobsTable.get_stale_executing(conn_b, lane=LANE, kinds=[KIND], limit=1)) == 1


@pytest.mark.django_db(transaction=True)
class TestClaimableGauge:
    @pytest.mark.asyncio
    async def test_count_uses_run_backoff_and_lease_gates(self, conn):
        run_id = "run-depth"
        first = await _insert(conn, run_id=run_id, sequence=0, dedup_key="first")
        await _insert(conn, run_id=run_id, sequence=1, dedup_key="second")
        assert await JobsTable.get_claimable_count(conn, lane=LANE, kinds=[KIND]) == 1

        await JobsTable.update_status(conn, job_id=first, job_state="waiting_retry", attempt=1)
        assert await JobsTable.get_claimable_count(conn, lane=LANE, kinds=[KIND], retry_backoff_base_seconds=3600) == 0

        await JobsTable.update_status(conn, job_id=first, job_state="pending", attempt=1)
        await _claim(conn)
        assert await JobsTable.get_claimable_count(conn, lane=LANE, kinds=[KIND]) == 0


def test_explicit_retry_bypasses_custom_exception_classifier():
    adapter = GenericJobAdapter(lane=LANE, kinds=[KIND], is_retryable=lambda _: False)
    assert adapter.is_retryable_error(JobRetryRequested("again")) is True
    assert adapter.is_retryable_error(Exception("no")) is False


@pytest.mark.asyncio
async def test_follower_state_is_replaced_and_scoped_to_one_group_task():
    adapter = GenericJobAdapter(lane=LANE, kinds=[KIND])
    follower = FollowerSpec(kind=KIND, lane=LANE, group_key="follower", team_id=1, payload={})

    async def attempt() -> None:
        adapter.stash_followers("job", (follower,))
        adapter.stash_followers("job", ())
        assert adapter._pending_followers.get() == ("job", ())

    await asyncio.create_task(attempt())
    assert adapter._pending_followers.get() is None


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
