import asyncio
from typing import Any, cast
from uuid import uuid4

import pytest

import psycopg

from products.warehouse_sources_queue.backend.core.batch_consumer import BatchConsumerConfig, _group_by_key
from products.warehouse_sources_queue.backend.core.generic_jobs import JOB_LEASE_TABLE, JOB_TABLE, Job, JobsTable
from products.warehouse_sources_queue.backend.core.jobs_db import PendingBatch
from products.warehouse_sources_queue.backend.core.metrics import (
    GENERIC_JOBS_CLAIMABLE,
    GENERIC_JOBS_CLAIMS_GATED_TOTAL,
    GENERIC_JOBS_OLDEST_UNCLAIMED_SECONDS,
)
from products.warehouse_sources_queue.backend.sdk.jobs import (
    Fail,
    FollowerSpec,
    GenericJobAdapter,
    JobConsumer,
    JobContext,
    JobRetryRequested,
    Outcome,
    Retry,
    RetryHistory,
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

    @pytest.mark.asyncio
    async def test_reconcile_cadence_publishes_depth_per_kind(self, conn):
        other_kind = "test.other"
        for index in range(2):
            await _insert(conn, group_key=f"1:group-{index}")
        await _insert(conn, kind=other_kind, group_key="1:group-other")
        adapter = GenericJobAdapter(lane=LANE, kinds=[KIND, other_kind])

        await adapter.reconcile_failed_runs(conn, grace_seconds=0, lookback_seconds=0, limit=0)

        assert GENERIC_JOBS_CLAIMABLE.labels(lane=LANE, kind=KIND)._value.get() == 2
        assert GENERIC_JOBS_CLAIMABLE.labels(lane=LANE, kind=other_kind)._value.get() == 1
        assert GENERIC_JOBS_OLDEST_UNCLAIMED_SECONDS.labels(lane=LANE, kind=KIND)._value.get() >= 0


@pytest.mark.django_db(transaction=True)
class TestClaimGate:
    @pytest.mark.parametrize("gate_open", [True, False])
    @pytest.mark.asyncio
    async def test_a_closed_gate_claims_nothing(self, gate_open, conn):
        await _insert(conn)
        adapter = GenericJobAdapter(lane=LANE, kinds=[KIND], claim_gate=lambda: gate_open)
        gated_before = GENERIC_JOBS_CLAIMS_GATED_TOTAL.labels(lane=LANE)._value.get()

        claimed = await adapter.fetch_and_lock(
            conn, limit=10, retry_backoff_base_seconds=0, owner_token=OWNER_A, lease_ttl_seconds=60
        )

        assert len(claimed) == (1 if gate_open else 0)
        assert GENERIC_JOBS_CLAIMS_GATED_TOTAL.labels(lane=LANE)._value.get() - gated_before == (0 if gate_open else 1)


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

    @pytest.mark.asyncio
    async def test_tagged_retries_are_recorded_and_left_out_of_the_retry_history(self, conn, _db_url):
        outcomes: list[Outcome] = [
            Retry(reason="worker shutdown", tag="shutdown"),
            Retry(reason="source said no"),
            Success(),
        ]
        histories: list[RetryHistory] = []

        class _ScriptedHandler:
            async def handle(self, job: Job, ctx: JobContext) -> Outcome:
                histories.append(await ctx.retry_history(job, uncounted_tag="shutdown"))
                return outcomes[len(histories) - 1]

        job_id = await _insert(conn)
        consumer = JobConsumer(
            config=BatchConsumerConfig(
                database_url=_db_url,
                max_concurrency=1,
                poll_interval_seconds=0.05,
                recovery_interval_seconds=3600,
                reconcile_interval_seconds=3600,
                retry_backoff_base_seconds=0,
            ),
            lane=LANE,
            handlers={KIND: _ScriptedHandler()},
        )
        run_task = asyncio.create_task(consumer.run())
        try:
            async with asyncio.timeout(30):
                while await JobsTable.get_latest_state(conn, job_id=job_id) != "succeeded":
                    await asyncio.sleep(0.05)
        finally:
            consumer.request_shutdown()
            await run_task

        assert histories == [
            RetryHistory(counted_retries=0, last_error=None),
            RetryHistory(counted_retries=0, last_error=None),
            RetryHistory(counted_retries=1, last_error="source said no"),
        ]
        async with conn.cursor() as cur:
            await cur.execute(
                "SELECT error_response->>'reason' FROM queuejobstatus WHERE job_id = %s AND job_state = 'waiting_retry' "
                "ORDER BY created_at",
                (job_id,),
            )
            assert [row[0] for row in await cur.fetchall()] == ["shutdown", None]


class _EngineFailureRecordingHandler(_RecordingHandler):
    def __init__(self, outcome: Outcome, *, hook_error: Exception | None = None) -> None:
        super().__init__(outcome)
        self.hook_error = hook_error
        self.engine_failures: list[tuple[str, str]] = []

    async def on_engine_failed(self, job: Job, reason: str) -> None:
        self.engine_failures.append((job.id, reason))
        if self.hook_error is not None:
            error, self.hook_error = self.hook_error, None
            raise error


async def _left_waiting_at_cap(conn: psycopg.AsyncConnection[Any], job_id: str, max_attempts: int) -> None:
    await JobsTable.update_status(conn, job_id=job_id, job_state="waiting_retry", attempt=max_attempts)


async def _left_executing_by_a_dead_pod(conn: psycopg.AsyncConnection[Any], job_id: str, max_attempts: int) -> None:
    await JobsTable.update_status(conn, job_id=job_id, job_state="executing", attempt=max_attempts)
    async with conn.cursor() as cur:
        await cur.execute(
            f"UPDATE {JOB_TABLE} SET state_changed_at = now() - interval '1 hour' WHERE id = %s", (job_id,)
        )


async def _fresh(conn: psycopg.AsyncConnection[Any], job_id: str, max_attempts: int) -> None:
    return


async def _run_consumer_until_failed(
    conn: psycopg.AsyncConnection[Any], db_url: str, handler: Any, job_ids: list[str], *, max_attempts: int
) -> None:
    consumer = JobConsumer(
        config=BatchConsumerConfig(
            database_url=db_url,
            max_concurrency=2,
            max_attempts=max_attempts,
            poll_interval_seconds=0.05,
            recovery_interval_seconds=0.05,
            recovery_grace_seconds=60,
            reconcile_interval_seconds=3600,
            retry_backoff_base_seconds=0,
        ),
        lane=LANE,
        handlers={KIND: handler},
    )
    run_task = asyncio.create_task(consumer.run())
    try:
        async with asyncio.timeout(30):
            while [await JobsTable.get_latest_state(conn, job_id=job_id) for job_id in job_ids] != ["failed"] * len(
                job_ids
            ):
                await asyncio.sleep(0.05)
    finally:
        consumer.request_shutdown()
        await run_task


@pytest.mark.django_db(transaction=True)
class TestEngineFailedHook:
    @pytest.mark.parametrize(
        "setup,outcome,max_attempts,expect_handler,expect_hook",
        [
            pytest.param(_fresh, Fail(reason="handler gave up"), 3, True, False, id="handler_fail_skips_the_hook"),
            pytest.param(_fresh, Retry(reason="again"), 1, True, True, id="retry_at_the_engine_cap"),
            pytest.param(_left_waiting_at_cap, Success(), 2, False, True, id="claim_after_the_cap"),
            pytest.param(_left_executing_by_a_dead_pod, Success(), 2, False, True, id="recovery_sweep_at_the_cap"),
        ],
    )
    @pytest.mark.asyncio
    async def test_the_hook_hears_about_each_job_the_engine_fails_by_itself(
        self, setup, outcome, max_attempts, expect_handler, expect_hook, conn, _db_url
    ):
        job_id = await _insert(conn)
        await setup(conn, job_id, max_attempts)
        handler = _EngineFailureRecordingHandler(outcome)

        await _run_consumer_until_failed(conn, _db_url, handler, [job_id], max_attempts=max_attempts)

        assert (handler.seen == [job_id]) is expect_handler
        assert [failed_id for failed_id, _ in handler.engine_failures] == ([job_id] if expect_hook else [])

    @pytest.mark.asyncio
    async def test_a_transient_hook_failure_is_retried_before_the_job_becomes_terminal(self, conn, _db_url):
        job_id = await _insert(conn)
        await _left_executing_by_a_dead_pod(conn, job_id, 2)
        handler = _EngineFailureRecordingHandler(Success(), hook_error=RuntimeError("app db down"))

        await _run_consumer_until_failed(conn, _db_url, handler, [job_id], max_attempts=2)

        assert handler.seen == []
        assert [failed_id for failed_id, _ in handler.engine_failures] == [job_id, job_id]
