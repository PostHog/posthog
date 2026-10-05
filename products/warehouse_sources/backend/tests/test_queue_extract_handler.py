import asyncio
import datetime as dt
import contextlib
import dataclasses
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import OperationalError

import psycopg
from asgiref.sync import sync_to_async
from temporalio.common import WorkflowIDReusePolicy

from posthog.api.test.test_organization import create_organization
from posthog.api.test.test_team import create_team
from posthog.models.team import Team

from products.warehouse_sources.backend.models import ExternalDataJob, ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.queue_runs.budgets import LONG_RUN_TIMEOUT, RETRY_WINDOW_MARGIN
from products.warehouse_sources.backend.queue_runs.claim_gate import MemoryClaimGate
from products.warehouse_sources.backend.queue_runs.extract_handler import (
    POST_IMPORT_DONE_SNAPSHOT_KEY,
    RUN_PLAN_SNAPSHOT_KEY,
    SHUTDOWN_RETRY_TAG,
    ExtractHandlerConfig,
    SyncExtractHandler,
)
from products.warehouse_sources.backend.queue_runs.payloads import (
    EXTRACT_LANE,
    SYNC_EXTRACT_KIND,
    SyncExtractPayload,
    SyncTrigger,
    scheduled_workflow_id,
)
from products.warehouse_sources.backend.temporal.data_imports.external_data_job import (
    SYNC_RUN_STALLED_MESSAGE,
    SYNC_RUN_TOO_LONG_MESSAGE,
    WORKER_RESTART_ERROR_MESSAGE,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    BillingLimitsWillBeReachedException,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.typings import PipelineResult
from products.warehouse_sources.backend.temporal.data_imports.post_import_job import build_post_import_workflow_id
from products.warehouse_sources.backend.temporal.data_imports.run_control import RunControl
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.import_data_sync import (
    ImportDataActivityInputs,
)
from products.warehouse_sources_queue.backend.sdk import (
    JOB_CLAIM_ELIGIBILITY,
    BatchConsumerConfig,
    Fail,
    Job,
    JobConsumer,
    JobContext,
    JobsTable,
    Outcome,
    Retry,
    Success,
)
from products.warehouse_sources_queue.backend.testing import (
    ensure_generic_job_tables,
    get_test_database_url,
    truncate_generic_job_tables,
)

HANDLER = "products.warehouse_sources.backend.queue_runs.extract_handler"
POST_EXTRACTION = "products.warehouse_sources.backend.queue_runs.post_extraction"
FINALIZER = "products.warehouse_sources.backend.temporal.data_imports.external_data_job"
CREATE_JOB = "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.create_job_model"

# The debug caps (see external_data_job.MAX_*_SOURCE_RETRIES) are 3 for every run shape.
RUN_CAP = 3
ENGINE_MAX_ATTEMPTS = 30
FIRE_AT = dt.datetime(2026, 9, 1, 12, 0, tzinfo=dt.UTC)

Extraction = Callable[[ImportDataActivityInputs, Any, RunControl], Awaitable[PipelineResult]]

WITH_BATCHES: PipelineResult = {"should_trigger_cdp_producer": False, "consumer_manages_job_status": True}
# What `run_extraction` returns when it stops before the pipeline, which sends every other run to the loader.
BEFORE_PIPELINE: PipelineResult = {"should_trigger_cdp_producer": False, "consumer_manages_job_status": False}


class _FakeExtraction:
    def __init__(self, body: Extraction) -> None:
        self._body = body
        self.controls: list[RunControl] = []
        self.inputs: list[ImportDataActivityInputs] = []

    async def __call__(self, inputs: ImportDataActivityInputs, logger: Any, control: RunControl) -> PipelineResult:
        self.controls.append(control)
        self.inputs.append(inputs)
        return await self._body(inputs, logger, control)


def _returns(result: PipelineResult) -> Extraction:
    async def body(inputs: ImportDataActivityInputs, logger: Any, control: RunControl) -> PipelineResult:
        return result

    return body


def _raises(error: BaseException) -> Extraction:
    async def body(inputs: ImportDataActivityInputs, logger: Any, control: RunControl) -> PipelineResult:
        raise error

    return body


def _stops_at_shutdown_check(inputs: ImportDataActivityInputs, logger: Any, control: RunControl) -> Any:
    # What the pipeline does for a resumable or incremental run: it checks between batches.
    async def body() -> PipelineResult:
        async with control.shutdown_monitor:
            await control.shutdown_monitor.wait_for_worker_shutdown()
            control.shutdown_monitor.raise_if_is_worker_shutdown()
        raise AssertionError("unreachable")

    return body()


def _never_stops(inputs: ImportDataActivityInputs, logger: Any, control: RunControl) -> Any:
    # What the pipeline does for a full refresh: it never checks for shutdown.
    async def body() -> PipelineResult:
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    return body()


def _cancel_then(then: Extraction) -> Extraction:
    # The cancel endpoint writes the terminal status first; the run finds out on its next probe.
    async def body(inputs: ImportDataActivityInputs, logger: Any, control: RunControl) -> PipelineResult:
        await sync_to_async(
            lambda: ExternalDataJob.objects.filter(id=inputs.run_id).update(
                status=ExternalDataJob.Status.FAILED, latest_error="Sync cancelled by user"
            )
        )()
        return await then(inputs, logger, control)

    return body


def _cancel_then_finishes_during_grace(
    inputs: ImportDataActivityInputs, logger: Any, control: RunControl
) -> Awaitable[PipelineResult]:
    async def body() -> PipelineResult:
        await sync_to_async(
            lambda: ExternalDataJob.objects.filter(id=inputs.run_id).update(
                status=ExternalDataJob.Status.FAILED, latest_error="Sync cancelled by user"
            )
        )()
        # Let the watcher observe cancellation, then finish before its grace period expires.
        await asyncio.sleep(0.02)
        return WITH_BATCHES

    return body()


@contextlib.asynccontextmanager
async def _no_workload_reporting(**_: Any) -> AsyncIterator[None]:
    yield


@pytest.fixture(scope="module")
def _db_url(django_db_setup: None) -> str:
    return get_test_database_url()


@pytest.fixture(autouse=True)
def _queue_tables(_db_url: str) -> None:
    with psycopg.Connection.connect(_db_url, autocommit=True) as conn:
        ensure_generic_job_tables(conn)
        truncate_generic_job_tables(conn)


@pytest.fixture
async def conn(_db_url: str) -> AsyncIterator[psycopg.AsyncConnection[Any]]:
    async with await psycopg.AsyncConnection.connect(_db_url, autocommit=True) as c:
        yield c


@pytest.fixture(autouse=True)
def boundaries() -> Any:
    with (
        patch(f"{FINALIZER}.get_rows", AsyncMock(return_value=0)),
        patch(f"{FINALIZER}.finish_row_tracking", AsyncMock()),
        patch(f"{FINALIZER}.areport_usage", AsyncMock()),
        patch(f"{FINALIZER}.update_should_sync") as update_should_sync,
        patch("posthoganalytics.capture"),
        patch(f"{HANDLER}.aworkload_reporting", _no_workload_reporting),
        patch(f"{POST_EXTRACTION}.create_warehouse_templates_for_source") as create_templates,
    ):
        yield MagicMock(update_should_sync=update_should_sync, create_templates=create_templates)


@pytest.fixture
def temporal() -> MagicMock:
    client = MagicMock()
    client.start_workflow = AsyncMock()
    return client


@pytest.fixture
def team() -> Team:
    return create_team(organization=create_organization("queue org"))


@pytest.fixture
def schema(team: Team) -> ExternalDataSchema:
    source = ExternalDataSource.objects.create(source_id="src", connection_id="conn", team=team, source_type="Stripe")
    return ExternalDataSchema.objects.create(name="Charge", team=team, source=source)


def _payload(schema: ExternalDataSchema, trigger: SyncTrigger = SyncTrigger.SCHEDULE) -> SyncExtractPayload:
    return SyncExtractPayload(
        team_id=schema.team_id,
        schema_id=schema.id,
        source_id=schema.source_id,
        trigger=trigger,
        billable=True,
        reset_pipeline=None,
        workflow_id=scheduled_workflow_id(schema.id, FIRE_AT),
        due_at=FIRE_AT,
    )


async def _enqueue(conn: psycopg.AsyncConnection[Any], payload: SyncExtractPayload) -> str:
    job_id = await JobsTable.insert(
        conn,
        kind=SYNC_EXTRACT_KIND,
        lane=EXTRACT_LANE,
        group_key=payload.group_key,
        team_id=payload.team_id,
        payload=payload.to_json(),
    )
    assert job_id is not None
    return job_id


async def _claim(conn: psycopg.AsyncConnection[Any], payload: SyncExtractPayload) -> Job:
    await _enqueue(conn, payload)
    [job] = await JobsTable.get_unprocessed_and_lock(
        conn, owner_token="test-owner", lane=EXTRACT_LANE, kinds=[SYNC_EXTRACT_KIND]
    )
    return job


async def _record_retries(conn: psycopg.AsyncConnection[Any], job: Job, tags: list[str | None]) -> Job:
    """Write the status rows the engine writes for earlier attempts, and return the next claim of the job."""
    for attempt, tag in enumerate(tags, start=1):
        response: dict[str, Any] = {"error": f"attempt {attempt} failed"}
        if tag is not None:
            response["reason"] = tag
        await JobsTable.update_status(
            conn,
            job_id=job.id,
            job_state="waiting_retry",
            attempt=attempt,
            error_response=response,
            job_created_at=job.created_at,
        )
    return dataclasses.replace(job, latest_attempt=len(tags))


def _ctx(
    db_url: str, *, shutdown_event: asyncio.Event | None = None, max_attempts: int = ENGINE_MAX_ATTEMPTS
) -> JobContext:
    return JobContext(
        logger=MagicMock(),
        shutdown_event=shutdown_event or asyncio.Event(),
        database_url=db_url,
        max_attempts=max_attempts,
    )


def _handler(temporal: MagicMock, **config: Any) -> SyncExtractHandler:
    return SyncExtractHandler(
        config=ExtractHandlerConfig(
            **{
                "cancel_probe_interval_seconds": 0.01,
                "cancel_grace_seconds": 0.05,
                "shutdown_grace_seconds": 0.05,
                **config,
            }
        ),
        temporal_client_factory=AsyncMock(return_value=temporal),
    )


async def _handle(handler: SyncExtractHandler, job: Job, ctx: JobContext, extraction: _FakeExtraction) -> Outcome:
    with patch(f"{HANDLER}.run_extraction", extraction):
        return await handler.handle(job, ctx)


def _jobs(schema: ExternalDataSchema) -> list[ExternalDataJob]:
    return list(ExternalDataJob.objects.filter(schema_id=schema.id).order_by("created_at"))


def _started_workflow_ids(temporal: MagicMock) -> list[str]:
    return [call.kwargs["id"] for call in temporal.start_workflow.call_args_list]


def _loader_finishes_first(inputs: ImportDataActivityInputs, logger: Any, control: RunControl) -> Any:
    # The final batch can load before the handler writes the phase.
    async def body() -> PipelineResult:
        await sync_to_async(
            lambda: ExternalDataJob.objects.filter(id=inputs.run_id).update(status=ExternalDataJob.Status.COMPLETED)
        )()
        return WITH_BATCHES

    return body()


@pytest.mark.parametrize(
    "body,expected_status,expected_phase,expect_post_import",
    [
        pytest.param(
            _returns(WITH_BATCHES), ExternalDataJob.Status.RUNNING, "loading", False, id="batches_go_to_the_loader"
        ),
        pytest.param(
            _loader_finishes_first, ExternalDataJob.Status.COMPLETED, "loading", False, id="loader_finishes_first"
        ),
        pytest.param(
            _returns(BEFORE_PIPELINE),
            ExternalDataJob.Status.COMPLETED,
            "extracting",
            True,
            id="repartition_hold_completes_here",
        ),
        pytest.param(
            _returns({**BEFORE_PIPELINE, "skip_post_import_activities": True, "fast_returned": True}),
            ExternalDataJob.Status.COMPLETED,
            "extracting",
            False,
            id="fast_return_completes_here_without_post_import",
        ),
    ],
)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_first_attempt_creates_the_job_and_hands_it_on(
    body: Extraction,
    expected_status: str,
    expected_phase: str,
    expect_post_import: bool,
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    payload = _payload(schema)
    job = await _claim(conn, payload)
    extraction = _FakeExtraction(body)

    outcome = await _handle(_handler(temporal), job, _ctx(_db_url), extraction)

    assert outcome == Success()
    [row] = await sync_to_async(_jobs)(schema)
    assert (row.workflow_id, row.workflow_run_id) == (payload.workflow_id, job.id)
    assert (row.status, row.phase, row.pipeline_version) == (
        expected_status,
        expected_phase,
        ExternalDataJob.PipelineVersion.V3,
    )
    [control] = extraction.controls
    assert (
        control.workflow_id,
        control.workflow_run_id,
        control.attempt,
        control.verify_v3_lock,
        control.always_final_marker,
    ) == (payload.workflow_id, job.id, 1, False, True)
    assert extraction.inputs[0].run_id == str(row.id)
    assert (build_post_import_workflow_id(str(row.id)) in _started_workflow_ids(temporal)) is expect_post_import


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_later_attempt_reuses_the_job_row_and_its_plan(
    schema: ExternalDataSchema, temporal: MagicMock, conn: psycopg.AsyncConnection[Any], _db_url: str
) -> None:
    job = await _claim(conn, _payload(schema))
    handler = _handler(temporal)
    first = _FakeExtraction(_raises(ValueError("source hiccup")))
    assert isinstance(await _handle(handler, job, _ctx(_db_url), first), Retry)

    retried = await _record_retries(conn, job, [None])
    second = _FakeExtraction(_returns(WITH_BATCHES))
    outcome = await _handle(handler, retried, _ctx(_db_url), second)

    assert outcome == Success()
    [row] = await sync_to_async(_jobs)(schema)
    assert RUN_PLAN_SNAPSHOT_KEY in (row.schema_snapshot or {})
    assert [inputs.run_id for inputs in first.inputs + second.inputs] == [str(row.id), str(row.id)]
    assert second.controls[0].attempt == 2
    assert row.phase == "loading"


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_plan_write_failure_rolls_back_job_creation_and_retries(
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    job = await _claim(conn, _payload(schema))

    with patch(f"{HANDLER}._update_run_snapshot", side_effect=OperationalError("app db down")):
        outcome = await _handle(_handler(temporal), job, _ctx(_db_url), _FakeExtraction(_returns(WITH_BATCHES)))

    assert isinstance(outcome, Retry)
    assert await sync_to_async(ExternalDataJob.objects.filter(schema_id=schema.id).exists)() is False


@pytest.mark.parametrize(
    "earlier_retries,engine_max_attempts,expected_outcome,expect_extraction",
    [
        pytest.param([None], ENGINE_MAX_ATTEMPTS, Retry, True, id="second_counted_attempt_retries"),
        pytest.param([None, None], ENGINE_MAX_ATTEMPTS, Fail, True, id="third_counted_attempt_fails"),
        pytest.param(
            [SHUTDOWN_RETRY_TAG, SHUTDOWN_RETRY_TAG, None],
            ENGINE_MAX_ATTEMPTS,
            Retry,
            True,
            id="shutdowns_do_not_count",
        ),
        pytest.param([SHUTDOWN_RETRY_TAG], 2, Fail, True, id="engine_cap_ends_the_run"),
        pytest.param([None, None, None], ENGINE_MAX_ATTEMPTS, Fail, False, id="attempts_lost_to_crashes_end_the_run"),
    ],
)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_retryable_errors_retry_until_the_cap(
    earlier_retries: list[str | None],
    engine_max_attempts: int,
    expected_outcome: type,
    expect_extraction: bool,
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    job = await _claim(conn, _payload(schema))
    handler = _handler(temporal)
    failing = _FakeExtraction(_raises(ValueError("source hiccup")))
    await _handle(handler, job, _ctx(_db_url), failing)

    retried = await _record_retries(conn, job, earlier_retries)
    last = _FakeExtraction(_raises(ValueError("source hiccup")))
    outcome = await _handle(handler, retried, _ctx(_db_url, max_attempts=engine_max_attempts), last)

    assert isinstance(outcome, expected_outcome)
    assert bool(last.controls) is expect_extraction
    [row] = await sync_to_async(_jobs)(schema)
    if expected_outcome is Retry:
        assert row.status == ExternalDataJob.Status.RUNNING
    else:
        assert row.status == ExternalDataJob.Status.FAILED
        expected_error = "source hiccup" if expect_extraction else SYNC_RUN_STALLED_MESSAGE
        assert row.latest_error == expected_error


def _non_retryable_error() -> NonRetryableException:
    # The shape `handle_non_retryable_error` raises: the classified source error is the cause.
    error = NonRetryableException()
    error.__cause__ = Exception("Could not establish session to SSH gateway")
    return error


@pytest.mark.parametrize(
    "error,expected_status,expect_disable",
    [
        pytest.param(
            _non_retryable_error(), ExternalDataJob.Status.FAILED, True, id="non_retryable_disables_the_schema"
        ),
        pytest.param(
            BillingLimitsWillBeReachedException("over the limit"),
            ExternalDataJob.Status.BILLING_LIMIT_TOO_LOW,
            False,
            id="billing_limit_too_low",
        ),
    ],
)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_errors_the_workflow_never_retries_fail_on_the_first_attempt(
    error: BaseException,
    expected_status: str,
    expect_disable: bool,
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    boundaries: MagicMock,
    _db_url: str,
) -> None:
    payload = _payload(schema)
    job = await _claim(conn, payload)

    outcome = await _handle(_handler(temporal), job, _ctx(_db_url), _FakeExtraction(_raises(error)))

    assert isinstance(outcome, Fail)
    [row] = await sync_to_async(_jobs)(schema)
    assert row.status == expected_status
    assert boundaries.update_should_sync.called is expect_disable
    if expect_disable:
        # The disable's teardown skips this run, so it makes no Temporal cancel call for it.
        assert boundaries.update_should_sync.call_args.kwargs["disable_exclude_workflow_id"] == payload.workflow_id


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_billing_limit_at_job_creation_stops_the_run(
    schema: ExternalDataSchema, temporal: MagicMock, conn: psycopg.AsyncConnection[Any], _db_url: str
) -> None:
    job = await _claim(conn, _payload(schema))
    extraction = _FakeExtraction(_returns(WITH_BATCHES))

    with patch(f"{CREATE_JOB}.billing_limit_reached", return_value=True):
        outcome = await _handle(_handler(temporal), job, _ctx(_db_url), extraction)

    assert outcome == Success()
    assert extraction.controls == []
    [row] = await sync_to_async(_jobs)(schema)
    assert row.status == ExternalDataJob.Status.BILLING_LIMIT_REACHED


@pytest.mark.parametrize(
    "time_left,expect_extraction",
    [
        pytest.param(dt.timedelta(milliseconds=200), True, id="budget_runs_out_mid_run"),
        pytest.param(-dt.timedelta(seconds=1), False, id="claim_window_already_closed"),
    ],
)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_run_past_its_time_budget_fails_as_too_long(
    time_left: dt.timedelta,
    expect_extraction: bool,
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    job = await _claim(conn, _payload(schema))
    handler = SyncExtractHandler(
        temporal_client_factory=AsyncMock(return_value=temporal),
        clock=lambda: job.created_at + JOB_CLAIM_ELIGIBILITY - time_left,
    )
    extraction = _FakeExtraction(_never_stops)

    outcome = await _handle(handler, job, _ctx(_db_url), extraction)

    assert isinstance(outcome, Fail)
    assert bool(extraction.controls) is expect_extraction
    [row] = await sync_to_async(_jobs)(schema)
    assert (row.status, row.latest_error) == (ExternalDataJob.Status.FAILED, SYNC_RUN_TOO_LONG_MESSAGE)


@pytest.mark.parametrize("body", [_stops_at_shutdown_check, _never_stops], ids=["cooperative", "never_checks"])
@pytest.mark.parametrize(
    "engine_max_attempts,expected_outcome", [(ENGINE_MAX_ATTEMPTS, Retry), (1, Fail)], ids=["requeued", "at_engine_cap"]
)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_shutdown_requeues_the_run_without_counting_it(
    body: Extraction,
    engine_max_attempts: int,
    expected_outcome: type,
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    job = await _claim(conn, _payload(schema))
    shutdown = asyncio.Event()
    started = asyncio.Event()

    async def run(inputs: ImportDataActivityInputs, logger: Any, control: RunControl) -> PipelineResult:
        started.set()
        return await body(inputs, logger, control)

    task = asyncio.create_task(
        _handle(
            _handler(temporal),
            job,
            _ctx(_db_url, shutdown_event=shutdown, max_attempts=engine_max_attempts),
            _FakeExtraction(run),
        )
    )
    await started.wait()
    shutdown.set()
    outcome = await task

    [row] = await sync_to_async(_jobs)(schema)
    if expected_outcome is Retry:
        assert outcome == Retry(reason="worker shutdown", tag=SHUTDOWN_RETRY_TAG)
        assert (row.status, row.phase) == (ExternalDataJob.Status.RUNNING, "extracting")
    else:
        assert isinstance(outcome, Fail)
        assert (row.status, row.latest_error) == (ExternalDataJob.Status.FAILED, WORKER_RESTART_ERROR_MESSAGE)


@pytest.mark.parametrize("body", [_stops_at_shutdown_check, _never_stops], ids=["cooperative", "never_checks"])
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_cancelled_run_stops_without_writing_a_status(
    body: Extraction,
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    job = await _claim(conn, _payload(schema))

    outcome = await _handle(_handler(temporal), job, _ctx(_db_url), _FakeExtraction(_cancel_then(body)))

    assert outcome == Fail(reason="run cancelled")
    [row] = await sync_to_async(_jobs)(schema)
    assert (row.status, row.latest_error, row.phase) == (
        ExternalDataJob.Status.FAILED,
        "Sync cancelled by user",
        "extracting",
    )
    assert temporal.start_workflow.call_count == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_run_finishing_during_cancellation_grace_still_stops(
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    job = await _claim(conn, _payload(schema))

    outcome = await _handle(_handler(temporal), job, _ctx(_db_url), _FakeExtraction(_cancel_then_finishes_during_grace))

    assert outcome == Fail(reason="run cancelled")
    [row] = await sync_to_async(_jobs)(schema)
    assert row.status == ExternalDataJob.Status.FAILED
    assert row.phase == "extracting"
    assert temporal.start_workflow.call_count == 0


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_disabled_schema_is_not_started(
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    await sync_to_async(ExternalDataSchema.objects.filter(id=schema.id).update)(should_sync=False)
    job = await _claim(conn, _payload(schema))
    extraction = _FakeExtraction(_returns(WITH_BATCHES))

    outcome = await _handle(_handler(temporal), job, _ctx(_db_url), extraction)

    assert outcome == Success()
    assert extraction.controls == []
    assert await sync_to_async(ExternalDataJob.objects.filter(schema_id=schema.id).exists)() is False


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_payload_source_must_belong_to_the_schema(
    schema: ExternalDataSchema,
    team: Team,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    other_source = await sync_to_async(ExternalDataSource.objects.create)(
        source_id="other", connection_id="other", team=team, source_type="Stripe"
    )
    payload = dataclasses.replace(_payload(schema), source_id=other_source.id)
    job = await _claim(conn, payload)
    extraction = _FakeExtraction(_returns(WITH_BATCHES))

    outcome = await _handle(_handler(temporal), job, _ctx(_db_url), extraction)

    assert isinstance(outcome, Fail)
    assert extraction.controls == []
    assert await sync_to_async(ExternalDataJob.objects.filter(schema_id=schema.id).exists)() is False


def _running_temporal_job(schema: ExternalDataSchema) -> None:
    ExternalDataJob.objects.create(
        team_id=schema.team_id,
        pipeline_id=schema.source_id,
        schema=schema,
        status=ExternalDataJob.Status.RUNNING,
        workflow_id=str(schema.id),
        workflow_run_id="temporal-run",
    )


def _staged_repartition_swap(schema: ExternalDataSchema) -> None:
    schema.sync_type_config = {
        **(schema.sync_type_config or {}),
        "repartition_swap": {"state": "ready", "temp_uri": "s3://temp", "live_uri": "s3://live"},
    }
    schema.save()


@pytest.mark.parametrize(
    "setup,expected_jobs",
    [
        pytest.param(_running_temporal_job, 1, id="overlaps_a_running_temporal_run"),
        pytest.param(_staged_repartition_swap, 0, id="held_for_repartition"),
    ],
)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_run_that_cannot_start_ends_without_a_job_row(
    setup: Callable[[ExternalDataSchema], None],
    expected_jobs: int,
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    await sync_to_async(setup)(schema)
    job = await _claim(conn, _payload(schema))
    extraction = _FakeExtraction(_returns(WITH_BATCHES))

    outcome = await _handle(_handler(temporal), job, _ctx(_db_url), extraction)

    assert outcome == Success()
    assert extraction.controls == []
    rows = await sync_to_async(_jobs)(schema)
    assert len(rows) == expected_jobs
    assert all(row.workflow_run_id != job.id for row in rows)


@pytest.mark.parametrize(
    "result,person_properties,templates,expected_ids",
    [
        pytest.param(
            {**WITH_BATCHES, "should_trigger_cdp_producer": True},
            False,
            False,
            ["dwh-cdp-producer-job-{job}"],
            id="cdp_producer",
        ),
        pytest.param(WITH_BATCHES, True, True, ["sync-warehouse-person-properties-{job}"], id="person_properties"),
        pytest.param(
            {**WITH_BATCHES, "should_trigger_cdp_producer": True, "skip_post_import_activities": True},
            True,
            True,
            ["dwh-cdp-producer-job-{job}"],
            id="externally_managed_schema",
        ),
    ],
)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_post_extraction_work_follows_the_workflow_conditions(
    result: PipelineResult,
    person_properties: bool,
    templates: bool,
    expected_ids: list[str],
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    boundaries: MagicMock,
    _db_url: str,
) -> None:
    job = await _claim(conn, _payload(schema))
    if not templates:
        # Stripe needs templates only until its first completed sync.
        await sync_to_async(ExternalDataJob.objects.create)(
            team_id=schema.team_id, pipeline_id=schema.source_id, schema=schema, status=ExternalDataJob.Status.COMPLETED
        )

    with patch(f"{CREATE_JOB}.person_property_sync_enabled_for", return_value=person_properties):
        outcome = await _handle(_handler(temporal), job, _ctx(_db_url), _FakeExtraction(_returns(result)))

    assert outcome == Success()
    row = await sync_to_async(ExternalDataJob.objects.get)(workflow_run_id=job.id)
    assert _started_workflow_ids(temporal) == [expected.format(job=row.id) for expected in expected_ids]
    for call in temporal.start_workflow.call_args_list:
        assert call.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
    expect_templates = templates and not result.get("skip_post_import_activities", False)
    assert boundaries.create_templates.called is expect_templates


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_terminal_retry_resumes_unfinished_post_import(
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    job = await _claim(conn, _payload(schema))
    handler = _handler(temporal)

    with patch(f"{HANDLER}.start_post_import", AsyncMock(side_effect=BaseException("process died"))):
        with pytest.raises(BaseException, match="process died"):
            await _handle(handler, job, _ctx(_db_url), _FakeExtraction(_returns(NO_BATCHES)))

    [row] = await sync_to_async(_jobs)(schema)
    assert row.status == ExternalDataJob.Status.COMPLETED
    assert not (row.schema_snapshot or {}).get(POST_IMPORT_DONE_SNAPSHOT_KEY, False)

    start_post_import = AsyncMock()
    with patch(f"{HANDLER}.start_post_import", start_post_import):
        outcome = await _handle(handler, job, _ctx(_db_url), _FakeExtraction(_returns(NO_BATCHES)))

    assert outcome == Success()
    start_post_import.assert_awaited_once()
    row = await sync_to_async(ExternalDataJob.objects.get)(id=row.id)
    assert (row.schema_snapshot or {})[POST_IMPORT_DONE_SNAPSHOT_KEY] is True


@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_the_consumer_runs_a_queued_extraction_end_to_end(
    schema: ExternalDataSchema, temporal: MagicMock, conn: psycopg.AsyncConnection[Any], _db_url: str
) -> None:
    queue_job_id = await _enqueue(conn, _payload(schema))
    consumer = JobConsumer(
        config=BatchConsumerConfig(
            database_url=_db_url,
            max_concurrency=1,
            poll_interval_seconds=0.05,
            recovery_interval_seconds=3600,
            reconcile_interval_seconds=3600,
        ),
        lane=EXTRACT_LANE,
        handlers={SYNC_EXTRACT_KIND: _handler(temporal)},
    )

    with patch(f"{HANDLER}.run_extraction", _FakeExtraction(_returns(WITH_BATCHES))):
        run_task = asyncio.create_task(consumer.run())
        try:
            async with asyncio.timeout(30):
                while await JobsTable.get_latest_state(conn, job_id=queue_job_id) != "succeeded":
                    await asyncio.sleep(0.05)
        finally:
            consumer.request_shutdown()
            await run_task

    row = await sync_to_async(ExternalDataJob.objects.get)(workflow_run_id=queue_job_id)
    assert (row.status, row.phase) == (ExternalDataJob.Status.RUNNING, "loading")


async def _left_executing_by_a_dead_pod(conn: psycopg.AsyncConnection[Any], job: Job, attempt: int) -> None:
    await JobsTable.update_status(
        conn, job_id=job.id, job_state="executing", attempt=attempt, job_created_at=job.created_at
    )
    async with conn.cursor() as cur:
        await cur.execute("UPDATE queuejob SET state_changed_at = now() - interval '1 hour' WHERE id = %s", (job.id,))


async def _left_waiting_at_the_cap(conn: psycopg.AsyncConnection[Any], job: Job, attempt: int) -> None:
    await JobsTable.update_status(
        conn, job_id=job.id, job_state="waiting_retry", attempt=attempt, job_created_at=job.created_at
    )


def _complete_row(row: ExternalDataJob) -> None:
    ExternalDataJob.objects.filter(id=row.id).update(status=ExternalDataJob.Status.COMPLETED)


def _delete_row(row: ExternalDataJob) -> None:
    ExternalDataJob.objects.filter(id=row.id).delete()


def _keep_row(row: ExternalDataJob) -> None:
    return


@pytest.mark.parametrize(
    "engine_path,change_row,finalizer_error,expected_status",
    [
        pytest.param(_left_executing_by_a_dead_pod, _keep_row, None, ExternalDataJob.Status.FAILED, id="sweep_at_cap"),
        pytest.param(_left_waiting_at_the_cap, _keep_row, None, ExternalDataJob.Status.FAILED, id="claim_after_cap"),
        pytest.param(
            _left_executing_by_a_dead_pod, _complete_row, None, ExternalDataJob.Status.COMPLETED, id="already_completed"
        ),
        pytest.param(_left_executing_by_a_dead_pod, _delete_row, None, None, id="no_job_row"),
        pytest.param(
            _left_executing_by_a_dead_pod,
            _keep_row,
            RuntimeError("app db down"),
            ExternalDataJob.Status.FAILED,
            id="transient_hook_failure_is_retried",
        ),
    ],
)
@pytest.mark.django_db(transaction=True)
@pytest.mark.asyncio
async def test_a_job_the_engine_fails_by_itself_fails_its_run(
    engine_path: Callable[[psycopg.AsyncConnection[Any], Job, int], Awaitable[None]],
    change_row: Callable[[ExternalDataJob], None],
    finalizer_error: Exception | None,
    expected_status: str | None,
    schema: ExternalDataSchema,
    temporal: MagicMock,
    conn: psycopg.AsyncConnection[Any],
    _db_url: str,
) -> None:
    engine_max_attempts = 2
    job = await _claim(conn, _payload(schema))
    handler = _handler(temporal)
    assert isinstance(await _handle(handler, job, _ctx(_db_url), _FakeExtraction(_raises(ValueError("oom")))), Retry)
    [row] = await sync_to_async(_jobs)(schema)
    await sync_to_async(change_row)(row)
    await engine_path(conn, job, engine_max_attempts)
    await JobsTable.release_all_owned(conn, owner_token="test-owner")
    consumer = JobConsumer(
        config=BatchConsumerConfig(
            database_url=_db_url,
            max_concurrency=1,
            max_attempts=engine_max_attempts,
            poll_interval_seconds=0.05,
            recovery_interval_seconds=0.05,
            recovery_grace_seconds=60,
            reconcile_interval_seconds=3600,
            retry_backoff_base_seconds=0,
        ),
        lane=EXTRACT_LANE,
        handlers={SYNC_EXTRACT_KIND: handler},
    )
    extraction = _FakeExtraction(_returns(WITH_BATCHES))

    with (
        patch(f"{HANDLER}.run_extraction", extraction),
        patch(f"{HANDLER}._update_job_status", AsyncMock(side_effect=[finalizer_error, None]))
        if finalizer_error
        else contextlib.nullcontext(),
    ):
        run_task = asyncio.create_task(consumer.run())
        try:
            async with asyncio.timeout(30):
                while await JobsTable.get_latest_state(conn, job_id=job.id) != "failed":
                    await asyncio.sleep(0.05)
        finally:
            consumer.request_shutdown()
            await run_task

    assert extraction.controls == []
    rows = await sync_to_async(_jobs)(schema)
    assert [r.status for r in rows] == ([expected_status] if expected_status is not None else [])
    if expected_status == ExternalDataJob.Status.FAILED:
        assert rows[0].latest_error == SYNC_RUN_STALLED_MESSAGE


class _FakePodMemory:
    def __init__(self, limit_mb: float | None, current_mb: float | None) -> None:
        self._limit_mb = limit_mb
        self._current_mb = current_mb

    def limit_mb(self) -> float | None:
        return self._limit_mb

    def current_mb(self) -> float | None:
        return self._current_mb


@pytest.mark.parametrize(
    "limit_mb,current_mb,expected_open",
    [
        pytest.param(8192, 4096, True, id="enough_headroom"),
        pytest.param(8192, 7680, False, id="below_the_reserve"),
        pytest.param(None, 7680, True, id="no_limit"),
        pytest.param(8192, None, True, id="usage_unreadable"),
    ],
)
def test_memory_claim_gate(limit_mb: float | None, current_mb: float | None, expected_open: bool) -> None:
    gate = MemoryClaimGate(min_free_mb=1024, pod_memory=_FakePodMemory(limit_mb, current_mb))  # type: ignore[arg-type]
    assert gate() is expected_open


def test_long_runs_end_inside_the_claim_window() -> None:
    assert LONG_RUN_TIMEOUT + RETRY_WINDOW_MARGIN < JOB_CLAIM_ELIGIBILITY
