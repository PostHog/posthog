import uuid
import asyncio
import logging
import dataclasses
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import pytest

import psycopg

from posthog.dataclasses import frozen

from products.warehouse_sources_queue.backend.core.batch_consumer import BatchConsumerConfig, OwnershipLostError
from products.warehouse_sources_queue.backend.core.generic_jobs import JOB_TABLE, Job, JobsTable
from products.warehouse_sources_queue.backend.core.job_steps import JobStepsTable
from products.warehouse_sources_queue.backend.sdk import (
    STEP_RESULT_MAX_BYTES,
    Fail,
    JobConsumer,
    JobContext,
    NonRetryableStepError,
    StepPolicy,
    StepRecord,
    StepState,
    Success,
    WorkflowContext,
    WorkflowHandler,
    WorkflowRetry,
    get_workflow,
    workflow,
)
from products.warehouse_sources_queue.backend.sdk.workflows import OnFailure
from products.warehouse_sources_queue.backend.testing import (
    JOB_DEFAULTS,
    SimulatedCrash,
    WorkflowTestRunner,
    ensure_generic_job_tables,
    get_test_database_url,
    truncate_generic_job_tables,
)

LANE = "test"


@frozen
class Order:
    order_id: uuid.UUID
    quantity: int


@frozen
class Quote:
    order_id: uuid.UUID
    total_cents: int


async def reserve(order: Order) -> int:
    return order.quantity


async def price(order: Order, reserved: int) -> Quote:
    return Quote(order_id=order.order_id, total_cents=reserved * 250)


async def charge(quote: Quote) -> dict[str, Any]:
    # A stored result that comes back as a dict instead of a Quote fails here.
    assert isinstance(quote, Quote)
    return {"charged_cents": quote.total_cents, "order_id": str(quote.order_id)}


async def notify(receipt: dict[str, Any]) -> str:
    return f"sent {receipt['charged_cents']}"


@workflow(kind="test.order", lane=LANE, payload=Order)
async def order_workflow(ctx: WorkflowContext[Order]) -> None:
    reserved = await ctx.step("reserve", reserve, ctx.payload)
    quote = await ctx.step("price", price, ctx.payload, reserved)
    receipt = await ctx.step("charge", charge, quote)
    await ctx.step("notify", notify, receipt)


@frozen
class PolicyCase:
    max_attempts: int
    on_failure: OnFailure
    timeout_seconds: float | None = None


async def flaky() -> str:
    return "real"


async def echo(value: str | None) -> str | None:
    return value


@workflow(kind="test.policy", lane=LANE, payload=PolicyCase)
async def policy_workflow(ctx: WorkflowContext[PolicyCase]) -> None:
    case = ctx.payload
    timeout = timedelta(seconds=case.timeout_seconds) if case.timeout_seconds is not None else None
    policy = StepPolicy(max_attempts=case.max_attempts, on_failure=case.on_failure, timeout=timeout)
    value = await ctx.step("flaky", flaky, policy=policy)
    await ctx.step("after", echo, value)


@frozen
class ResultCase:
    kind: str
    size: int = 0


async def produce(case: ResultCase) -> Any:
    if case.kind == "not_serializable":
        return object()
    return "x" * case.size


@workflow(kind="test.result", lane=LANE, payload=ResultCase)
async def result_workflow(ctx: WorkflowContext[ResultCase]) -> None:
    await ctx.step("produce", produce, ctx.payload)


async def noop() -> None:
    return None


@workflow(kind="test.keys", lane=LANE, payload=dict[str, str])
async def keys_workflow(ctx: WorkflowContext[dict[str, str]]) -> None:
    await ctx.step("first", noop)
    await ctx.step(ctx.payload["second_key"], noop)


async def observe_version(version: str) -> str:
    return version


@workflow(kind="test.versioned", lane=LANE, payload=dict[str, str], version="1")
async def versioned_v1(ctx: WorkflowContext[dict[str, str]]) -> None:
    await ctx.step("a", observe_version, ctx.started_version)
    await ctx.step("b", observe_version, ctx.started_version)


async def _versioned_v2_run(ctx: WorkflowContext[dict[str, str]]) -> None:
    await ctx.step("a", observe_version, ctx.started_version)
    await ctx.step("added", observe_version, ctx.started_version)
    await ctx.step("b", observe_version, ctx.started_version)


# The next deploy of the same kind: one step added between two existing steps.
versioned_v2 = dataclasses.replace(versioned_v1, version="2", run=_versioned_v2_run)


async def fail_on_first_attempt(attempt: int) -> int:
    if attempt == 1:
        raise RuntimeError("the source timed out")
    return attempt


@workflow(kind="test.engine", lane=LANE, payload=dict[str, str])
async def engine_workflow(ctx: WorkflowContext[dict[str, str]]) -> None:
    await ctx.step("first", noop)
    await ctx.step(
        "flaky", fail_on_first_attempt, ctx.attempt, policy=StepPolicy(max_attempts=2, on_failure="retry_job")
    )


def _fails(times: int, error: type[Exception] = RuntimeError) -> Callable[[], Awaitable[str]]:
    calls = 0

    async def step() -> str:
        nonlocal calls
        calls += 1
        if calls <= times:
            raise error(f"failure {calls}")
        return "ok"

    return step


async def _slow() -> str:
    await asyncio.sleep(5)
    return "late"


def _asks_for_retry_once() -> Callable[[], Awaitable[str]]:
    asked = False

    async def step() -> str:
        nonlocal asked
        if not asked:
            asked = True
            raise WorkflowRetry("worker shutdown", tag="shutdown")
        return "ok"

    return step


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


def _attempts(runner: WorkflowTestRunner[Any]) -> int:
    assert runner.job is not None
    return runner.job.latest_attempt + 1


@pytest.mark.django_db(transaction=True)
class TestWorkflowSteps:
    @pytest.mark.parametrize(
        "crash_after,expected_step_attempts",
        [
            pytest.param(None, {"reserve": 1, "price": 1, "charge": 1, "notify": 1}, id="no_crash"),
            pytest.param("reserve", {"reserve": 1, "price": 2, "charge": 2, "notify": 2}, id="crash_after_first"),
            pytest.param("price", {"reserve": 1, "price": 1, "charge": 2, "notify": 2}, id="crash_after_typed_result"),
            pytest.param("charge", {"reserve": 1, "price": 1, "charge": 1, "notify": 2}, id="crash_after_third"),
            pytest.param("notify", {"reserve": 1, "price": 1, "charge": 1, "notify": 1}, id="crash_after_last"),
        ],
    )
    @pytest.mark.asyncio
    async def test_chain_runs_each_step_once_across_a_crash(self, crash_after, expected_step_attempts):
        order = Order(order_id=uuid.uuid4(), quantity=3)
        runner = WorkflowTestRunner(order_workflow, order, crash_after=crash_after)

        outcome = await runner.run_until_done()

        assert outcome == Success()
        assert runner.calls == Counter({"reserve": 1, "price": 1, "charge": 1, "notify": 1})
        assert {key: record.job_attempt for key, record in runner.steps.items()} == expected_step_attempts
        assert {record.state for record in runner.steps.values()} == {StepState.SUCCEEDED}
        assert runner.steps["price"].result == {"order_id": str(order.order_id), "total_cents": 750}
        assert runner.steps["notify"].result == "sent 750"

    @pytest.mark.parametrize(
        "case,make_override,expected_outcome,expected_calls,expected_attempts,expected_flaky_states,expected_after,expected_sleeps",
        [
            pytest.param(
                PolicyCase(max_attempts=3, on_failure="fail_job"),
                partial(_fails, 2),
                Success,
                3,
                1,
                ["failed", "failed", "succeeded"],
                "ok",
                [1.0, 2.0],
                id="fail_job_recovers_in_process",
            ),
            pytest.param(
                PolicyCase(max_attempts=3, on_failure="fail_job"),
                partial(_fails, 99),
                Fail,
                3,
                1,
                ["failed", "failed", "failed"],
                "not run",
                [1.0, 2.0],
                id="fail_job_gives_up",
            ),
            pytest.param(
                PolicyCase(max_attempts=2, on_failure="continue"),
                partial(_fails, 99),
                Success,
                2,
                1,
                ["failed", "failed", "skipped"],
                None,
                [1.0],
                id="continue_skips_the_step",
            ),
            pytest.param(
                PolicyCase(max_attempts=3, on_failure="retry_job"),
                partial(_fails, 2),
                Success,
                3,
                3,
                ["failed", "failed", "succeeded"],
                "ok",
                [],
                id="retry_job_recovers_on_a_later_attempt",
            ),
            pytest.param(
                PolicyCase(max_attempts=2, on_failure="retry_job"),
                partial(_fails, 99),
                Fail,
                2,
                2,
                ["failed", "failed"],
                "not run",
                [],
                id="retry_job_gives_up",
            ),
            pytest.param(
                PolicyCase(max_attempts=5, on_failure="fail_job"),
                partial(_fails, 99, NonRetryableStepError),
                Fail,
                1,
                1,
                ["failed"],
                "not run",
                [],
                id="non_retryable_gives_up_at_once",
            ),
            pytest.param(
                PolicyCase(max_attempts=1, on_failure="fail_job"),
                _asks_for_retry_once,
                Success,
                2,
                2,
                ["succeeded"],
                "ok",
                [],
                id="workflow_retry_from_a_step_records_nothing",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_step_policy(
        self,
        case,
        make_override,
        expected_outcome,
        expected_calls,
        expected_attempts,
        expected_flaky_states,
        expected_after,
        expected_sleeps,
    ):
        runner = WorkflowTestRunner(policy_workflow, case, overrides={"flaky": make_override()})

        outcome = await runner.run_until_done()

        assert isinstance(outcome, expected_outcome), outcome
        assert runner.calls["flaky"] == expected_calls
        assert _attempts(runner) == expected_attempts
        assert [r.state.value for r in runner.records if r.key == "flaky"] == expected_flaky_states
        if expected_after == "not run":
            assert "after" not in runner.steps
        else:
            assert runner.steps["after"].result == expected_after
        assert runner.clock.sleeps == expected_sleeps

    @pytest.mark.asyncio
    async def test_timeout_records_why_the_step_failed(self):
        case = PolicyCase(max_attempts=1, on_failure="fail_job", timeout_seconds=0.05)
        runner = WorkflowTestRunner(policy_workflow, case, overrides={"flaky": _slow})

        outcome = await runner.run()

        assert isinstance(outcome, Fail)
        assert "timed out after 0:00:00.050000" in (runner.steps["flaky"].error or "")
        assert "flaky" in outcome.reason

    @pytest.mark.parametrize(
        "case,expected_failure",
        [
            pytest.param(ResultCase(kind="string", size=STEP_RESULT_MAX_BYTES - 2), None, id="exactly_at_the_cap"),
            pytest.param(
                ResultCase(kind="string", size=STEP_RESULT_MAX_BYTES - 1),
                f"more than the {STEP_RESULT_MAX_BYTES} byte limit",
                id="one_byte_over_the_cap",
            ),
            pytest.param(ResultCase(kind="not_serializable"), "not JSON-serializable", id="not_serializable"),
        ],
    )
    @pytest.mark.asyncio
    async def test_result_must_fit_the_step_table(self, case, expected_failure):
        runner = WorkflowTestRunner(result_workflow, case)

        outcome = await runner.run()

        assert runner.calls["produce"] == 1
        if expected_failure is None:
            assert outcome == Success()
            assert runner.steps["produce"].result == "x" * case.size
        else:
            assert isinstance(outcome, Fail)
            assert expected_failure in outcome.reason
            assert "produce" not in runner.steps

    @pytest.mark.parametrize(
        "second_key,expected_failure",
        [
            pytest.param("second", None, id="distinct_key"),
            pytest.param("first", "already used in this run", id="duplicate_key"),
            pytest.param("__started__", "reserved", id="reserved_key"),
            pytest.param("", "1 to 200 characters", id="empty_key"),
            pytest.param("k" * 201, "1 to 200 characters", id="key_too_long"),
        ],
    )
    @pytest.mark.asyncio
    async def test_step_keys_are_unique_within_a_run(self, second_key, expected_failure):
        runner = WorkflowTestRunner(keys_workflow, {"second_key": second_key})

        outcome = await runner.run()

        assert runner.calls["first"] == 1
        if expected_failure is None:
            assert outcome == Success()
        else:
            assert isinstance(outcome, Fail)
            assert expected_failure in outcome.reason

    @pytest.mark.asyncio
    async def test_added_step_runs_on_a_resumed_job_and_started_version_stays_at_the_first(self):
        runner = WorkflowTestRunner(versioned_v1, {}, crash_after="a")
        with pytest.raises(SimulatedCrash):
            await runner.run()

        runner.definition = versioned_v2
        outcome = await runner.run()

        assert outcome == Success()
        assert runner.calls == Counter({"a": 1, "added": 1, "b": 1})
        assert {key: record.result for key, record in runner.steps.items()} == {"a": "1", "added": "1", "b": "1"}

        fresh = WorkflowTestRunner(versioned_v2, {})
        await fresh.run()
        assert fresh.steps["a"].result == "2"

    @pytest.mark.asyncio
    async def test_consumer_runs_a_workflow_and_retries_a_failed_step_on_the_next_attempt(self, conn, _db_url):
        job_id = await JobsTable.insert(
            conn, **{**JOB_DEFAULTS, "kind": engine_workflow.kind, "payload": engine_workflow.encode_payload({})}
        )
        assert job_id is not None
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
            handlers={engine_workflow.kind: WorkflowHandler(engine_workflow)},
        )
        run_task = asyncio.create_task(consumer.run())
        try:
            async with asyncio.timeout(30):
                while await JobsTable.get_latest_state(conn, job_id=job_id) not in ("succeeded", "failed"):
                    await asyncio.sleep(0.05)
        finally:
            consumer.request_shutdown()
            await run_task

        assert await JobsTable.get_latest_state(conn, job_id=job_id) == "succeeded"
        created_at = await _job_created_at(conn, job_id)
        records = await JobStepsTable.load(conn, job_id=job_id, job_created_at=created_at)
        assert [(r.key, r.job_attempt, r.state.value) for r in records] == [
            ("__started__", 1, "succeeded"),
            ("first", 1, "succeeded"),
            ("flaky", 1, "failed"),
            ("flaky", 2, "succeeded"),
        ]


async def _job_created_at(conn: psycopg.AsyncConnection[Any], job_id: str) -> datetime:
    async with conn.cursor() as cur:
        await cur.execute(f"SELECT created_at FROM {JOB_TABLE} WHERE id = %s", (job_id,))
        row = await cur.fetchone()
    assert row is not None
    return row[0]


@pytest.mark.django_db(transaction=True)
class TestStepFence:
    @pytest.mark.parametrize(
        "job_state,job_attempt,writer_attempt,accepted",
        [
            pytest.param("executing", 1, 1, True, id="current_attempt"),
            pytest.param("executing", 2, 1, False, id="zombie_of_an_earlier_attempt"),
            pytest.param("waiting_retry", 1, 1, False, id="attempt_requeued_by_the_sweep"),
            pytest.param("succeeded", 1, 1, False, id="job_already_ended"),
        ],
    )
    @pytest.mark.asyncio
    async def test_only_the_executing_attempt_records_a_step(
        self, conn, job_state, job_attempt, writer_attempt, accepted
    ):
        job_id = await JobsTable.insert(conn, **JOB_DEFAULTS)
        assert job_id is not None
        await JobsTable.update_status(conn, job_id=job_id, job_state=job_state, attempt=job_attempt)
        created_at = await _job_created_at(conn, job_id)
        now = datetime.now(UTC)
        record = StepRecord(
            key="extract",
            state=StepState.SUCCEEDED,
            job_attempt=writer_attempt,
            started_at=now,
            ended_at=now,
            result={"rows": 1},
            error=None,
        )

        if accepted:
            await JobStepsTable.record(
                conn, job_id=job_id, job_created_at=created_at, record=record, encoded_result='{"rows": 1}'
            )
        else:
            with pytest.raises(OwnershipLostError):
                await JobStepsTable.record(
                    conn, job_id=job_id, job_created_at=created_at, record=record, encoded_result='{"rows": 1}'
                )

        stored = await JobStepsTable.load(conn, job_id=job_id, job_created_at=created_at)
        assert [r.result for r in stored] == ([{"rows": 1}] if accepted else [])


class TestWorkflowRegistry:
    def test_kind_resolves_to_its_workflow_and_a_second_function_cannot_take_it(self):
        assert get_workflow("test.order") is order_workflow

        async def other(ctx: WorkflowContext[Order]) -> None:
            return None

        with pytest.raises(ValueError, match="already registered"):
            workflow(kind="test.order", lane=LANE, payload=Order)(other)
        with pytest.raises(KeyError, match="no workflow is registered"):
            get_workflow("test.unknown")

    @pytest.mark.asyncio
    async def test_payload_that_does_not_match_its_type_fails_the_job(self):
        job = Job(
            id=str(uuid.uuid4()),
            kind=order_workflow.kind,
            lane=LANE,
            group_key="1:group",
            team_id=1,
            run_id=None,
            sequence=0,
            payload={"order_id": "not-a-uuid", "quantity": 1},
            priority=0,
            dedup_key=None,
            latest_state="pending",
            latest_attempt=0,
            state_changed_at=None,
            created_at=datetime.now(UTC),
        )
        context = JobContext(
            logger=logging.getLogger(__name__),
            shutdown_event=asyncio.Event(),
            database_url="postgres://unused",
            max_attempts=1,
            lease_owner="test",
        )

        outcome = await WorkflowHandler(order_workflow).handle(job, context)

        assert isinstance(outcome, Fail)
        assert "order_id" in outcome.reason
