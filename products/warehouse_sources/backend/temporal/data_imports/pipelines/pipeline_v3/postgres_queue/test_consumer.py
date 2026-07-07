import asyncio
from typing import Any, cast

import pytest
from unittest.mock import AsyncMock, patch

import psycopg
import structlog

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.batch_consumer import (
    OwnershipLostError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.load.health import HealthState
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer import (
    BatchConsumer,
    ConsumerConfig,
    _group_by_key,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    FRESHNESS_WINDOW_SECONDS,
    FailedRunRef,
    PendingBatch,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.metrics import (
    OLDEST_UNCLAIMED_BATCH_SECONDS,
)
from products.warehouse_sources_queue.backend.models import SourceBatchStatus


def _make_batch(**overrides: Any) -> PendingBatch:
    defaults: dict[str, Any] = {
        "id": "00000000-0000-0000-0000-000000000001",
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
        "latest_attempt": 0,
    }
    defaults.update(overrides)
    return PendingBatch(**defaults)


def _make_failed_run_ref(**overrides: Any) -> FailedRunRef:
    defaults: dict[str, Any] = {
        "run_uuid": "run-1",
        "job_id": "job-1",
        "team_id": 1,
        "schema_id": "schema-1",
        "workflow_run_id": "wf-1",
        "reason": "max retries exceeded: the connection is closed",
    }
    defaults.update(overrides)
    return FailedRunRef(**defaults)


def _make_consumer(max_attempts: int = 3, **kwargs) -> BatchConsumer:
    config = ConsumerConfig(
        database_url="postgres://unused:unused@localhost/unused",
        max_attempts=max_attempts,
        **kwargs,
    )
    mock_process = AsyncMock()
    consumer = BatchConsumer(config=config, process_batch=mock_process)
    consumer._poll_conn = _make_healthy_conn()
    consumer._recovery_conn = _make_healthy_conn()
    return consumer


def _make_healthy_conn(closed: bool = False, broken: bool = False) -> AsyncMock:
    # closed/broken must be real booleans, otherwise _ensure_*_conn sees a dead conn and dials the fake database_url.
    conn = AsyncMock()
    conn.closed = closed
    conn.broken = broken
    return conn


@pytest.fixture(autouse=True)
def _lease_renewal_succeeds():
    # Group dispatch renews the lease before processing; the real SQL can't run
    # against mock connections. Tests exercising renewal failure re-patch this.
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.renew_lease",
        new_callable=AsyncMock,
        return_value=True,
    ):
        yield


class TestProcessSingle:
    @pytest.mark.asyncio
    async def test_success_updates_status_to_executing_then_succeeded(self):
        consumer = _make_consumer()
        batch = _make_batch(latest_attempt=0)
        states: list[str] = []

        async def track_status(conn, *, batch_id, job_state, attempt, error_response=None):
            states.append(job_state)

        consumer._process_batch = AsyncMock()
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            side_effect=track_status,
        ):
            await consumer._process_single(batch)

        assert states == [SourceBatchStatus.State.EXECUTING, SourceBatchStatus.State.SUCCEEDED]

    @pytest.mark.asyncio
    async def test_error_sets_waiting_retry(self):
        consumer = _make_consumer(max_attempts=3)
        batch = _make_batch(latest_attempt=0)
        states: list[str] = []

        async def track_status(conn, *, batch_id, job_state, attempt, error_response=None):
            states.append(job_state)

        consumer._process_batch = AsyncMock(side_effect=ValueError("boom"))
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            side_effect=track_status,
        ):
            await consumer._process_single(batch)

        assert states == [SourceBatchStatus.State.EXECUTING, SourceBatchStatus.State.WAITING_RETRY]

    @pytest.mark.parametrize(
        "message",
        [
            "20009.59457503306999908717 is too large to store in a Decimal128 of precision 24.",
            "Primary key required for incremental syncs",
        ],
    )
    @pytest.mark.asyncio
    async def test_non_retryable_error_fails_run_on_first_attempt(self, message: str):
        # Deterministic data/config errors fail identically every attempt;
        # retrying them wastes all attempts on every scheduled run.
        consumer = _make_consumer(max_attempts=3)
        batch = _make_batch(latest_attempt=0)
        consumer._process_batch = AsyncMock(side_effect=ValueError(message))

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ) as mock_status,
            patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_fail,
        ):
            await consumer._process_single(batch)

        mock_fail.assert_called_once()
        assert mock_fail.call_args[1]["reason"] == message  # customer-visible error stays actionable
        states = [call[1]["job_state"] for call in mock_status.call_args_list]
        assert SourceBatchStatus.State.WAITING_RETRY not in states

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded_fails_run(self):
        consumer = _make_consumer(max_attempts=3)
        batch = _make_batch(latest_attempt=3)

        with patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_fail:
            await consumer._process_single(batch)

        mock_fail.assert_called_once()
        assert "max retries exceeded" in mock_fail.call_args[1]["reason"]

    @pytest.mark.asyncio
    async def test_error_at_max_attempts_fails_run(self):
        consumer = _make_consumer(max_attempts=2)
        batch = _make_batch(latest_attempt=1)
        consumer._process_batch = AsyncMock(side_effect=RuntimeError("crash"))

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_fail,
        ):
            await consumer._process_single(batch)

        mock_fail.assert_called_once()


class TestProcessGroup:
    @pytest.mark.asyncio
    async def test_processes_batches_in_order(self):
        consumer = _make_consumer()
        order: list[int] = []

        async def track_batch(batch):
            order.append(batch.batch_index)

        consumer._process_batch = track_batch

        batches = [_make_batch(batch_index=i, id=f"00000000-0000-0000-0000-{i + 1:012d}") for i in range(3)]

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.verify_advisory_lock",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=_make_healthy_conn()),
        ):
            await consumer._process_group((1, "schema-1"), batches)

        assert order == [0, 1, 2]
        mock_unlock.assert_called_once()

    @pytest.mark.asyncio
    async def test_unlocks_even_on_error(self):
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock(side_effect=RuntimeError("crash"))

        batches = [_make_batch()]

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.verify_advisory_lock",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(consumer, "_fail_run", new_callable=AsyncMock),
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=_make_healthy_conn()),
        ):
            await consumer._process_group((1, "schema-1"), batches)

        mock_unlock.assert_called_once()

    @pytest.mark.asyncio
    async def test_halts_group_when_batch_does_not_succeed(self):
        consumer = _make_consumer(max_attempts=3)
        processed: list[int] = []

        async def fail_on_one(batch):
            processed.append(batch.batch_index)
            if batch.batch_index == 1:
                raise RuntimeError("boom")

        consumer._process_batch = fail_on_one

        batches = [_make_batch(batch_index=i, id=f"00000000-0000-0000-0000-{i + 1:012d}") for i in range(3)]

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.verify_advisory_lock",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=_make_healthy_conn()),
        ):
            await consumer._process_group((1, "schema-1"), batches)

        # batch 2 must not be processed once batch 1 enters waiting_retry
        assert processed == [0, 1]

    @pytest.mark.asyncio
    async def test_stops_on_shutdown(self):
        consumer = _make_consumer()
        processed: list[int] = []

        async def track_and_shutdown(batch):
            processed.append(batch.batch_index)
            if batch.batch_index == 0:
                consumer._shutdown.set()

        consumer._process_batch = track_and_shutdown

        batches = [_make_batch(batch_index=i, id=f"00000000-0000-0000-0000-{i + 1:012d}") for i in range(3)]

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.verify_advisory_lock",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=_make_healthy_conn()),
        ):
            await consumer._process_group((1, "schema-1"), batches)

        assert processed == [0]

    @pytest.mark.asyncio
    async def test_abandons_group_when_lease_lost_before_dispatch(self):
        consumer = _make_consumer()
        batch = _make_batch()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.renew_lease",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=_make_healthy_conn()),
        ):
            await consumer._process_group((1, "schema-1"), [batch])

        # Another pod owns the group now — processing it here would double-write.
        cast(AsyncMock, consumer._process_batch).assert_not_called()
        mock_unlock.assert_called_once()


class TestRecoverySweep:
    @pytest.mark.asyncio
    async def test_retries_stale_below_max(self):
        consumer = _make_consumer(max_attempts=3)
        stale_batch = _make_batch(latest_attempt=1)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[stale_batch],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ) as mock_status,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
        ):
            await consumer._recovery_sweep()

        mock_status.assert_called_once_with(
            consumer._recovery_conn,
            batch_id=stale_batch.id,
            job_state=SourceBatchStatus.State.WAITING_RETRY,
            attempt=1,
            error_response={"error": "executing timed out - pod restart or OOM"},
        )
        mock_unlock.assert_called_once_with(
            consumer._recovery_conn, batches=[stale_batch], owner_token=consumer._owner_token
        )

    @pytest.mark.asyncio
    async def test_fails_exhausted_stale_batch(self):
        consumer = _make_consumer(max_attempts=3)
        stale_batch = _make_batch(latest_attempt=3)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[stale_batch],
            ),
            patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_fail,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
        ):
            await consumer._recovery_sweep()

        mock_fail.assert_called_once()
        assert "max retries exceeded" in mock_fail.call_args[1]["reason"]
        mock_unlock.assert_called_once()

    @pytest.mark.asyncio
    async def test_recovery_sweep_unlocks_on_error(self):
        consumer = _make_consumer(max_attempts=3)
        stale_batch = _make_batch(latest_attempt=1)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[stale_batch],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
                side_effect=Exception("db gone"),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
            pytest.raises(Exception, match="db gone"),
        ):
            await consumer._recovery_sweep()

        mock_unlock.assert_called_once_with(
            consumer._recovery_conn, batches=[stale_batch], owner_token=consumer._owner_token
        )


class TestStartupLiveness:
    @pytest.mark.asyncio
    async def test_heartbeat_reports_liveness_while_startup_sweep_runs(self):
        health_reported = asyncio.Event()
        config = ConsumerConfig(
            database_url="postgres://unused:unused@localhost/unused",
            heartbeat_interval_seconds=0.01,
        )
        consumer = BatchConsumer(config=config, process_batch=AsyncMock(), health_reporter=health_reported.set)

        release_sweep = asyncio.Event()

        async def blocking_sweep(*args: Any, **kwargs: Any) -> list[PendingBatch]:
            await release_sweep.wait()
            return []

        with (
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=_make_healthy_conn()),
            patch.object(consumer, "_install_signal_handlers"),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                side_effect=blocking_sweep,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.release_all_owned_leases",
                new_callable=AsyncMock,
            ),
        ):
            run_task = asyncio.create_task(consumer.run())
            # With the sweep blocked indefinitely, liveness must still be reported.
            await asyncio.wait_for(health_reported.wait(), timeout=1.0)
            consumer._shutdown.set()
            release_sweep.set()
            await asyncio.wait_for(run_task, timeout=5.0)


class TestQueueOperationTimeouts:
    @pytest.mark.asyncio
    async def test_hung_poll_times_out_and_consumer_keeps_polling(self):
        config = ConsumerConfig(
            database_url="postgres://unused:unused@localhost/unused",
            poll_interval_seconds=0.01,
            poll_timeout_seconds=0.05,
        )
        consumer = BatchConsumer(config=config, process_batch=AsyncMock())

        second_poll_started = asyncio.Event()
        fetch_calls = 0

        async def hung_fetch(*args: Any, **kwargs: Any) -> list[PendingBatch]:
            nonlocal fetch_calls
            fetch_calls += 1
            if fetch_calls >= 2:
                second_poll_started.set()
            await asyncio.sleep(3600)
            return []

        with (
            patch.object(
                consumer, "_connect", new_callable=AsyncMock, side_effect=lambda **kwargs: _make_healthy_conn()
            ),
            patch.object(consumer, "_install_signal_handlers"),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_unprocessed_and_lock",
                side_effect=hung_fetch,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.release_all_owned_leases",
                new_callable=AsyncMock,
            ),
        ):
            run_task = asyncio.create_task(consumer.run())
            # A second poll can only start if the first hung one timed out instead of wedging.
            await asyncio.wait_for(second_poll_started.wait(), timeout=2.0)
            consumer._shutdown.set()
            await asyncio.wait_for(run_task, timeout=5.0)

    @pytest.mark.asyncio
    async def test_hung_startup_sweep_times_out_and_polling_starts(self):
        config = ConsumerConfig(
            database_url="postgres://unused:unused@localhost/unused",
            poll_interval_seconds=0.01,
            sweep_timeout_seconds=0.05,
        )
        consumer = BatchConsumer(config=config, process_batch=AsyncMock())

        polling_started = asyncio.Event()

        async def hung_sweep(*args: Any, **kwargs: Any) -> list[PendingBatch]:
            await asyncio.sleep(3600)
            return []

        async def fetch(*args: Any, **kwargs: Any) -> list[PendingBatch]:
            polling_started.set()
            return []

        with (
            patch.object(
                consumer, "_connect", new_callable=AsyncMock, side_effect=lambda **kwargs: _make_healthy_conn()
            ),
            patch.object(consumer, "_install_signal_handlers"),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                side_effect=hung_sweep,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_unprocessed_and_lock",
                side_effect=fetch,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.release_all_owned_leases",
                new_callable=AsyncMock,
            ),
        ):
            run_task = asyncio.create_task(consumer.run())
            # Polling can only begin if the hung startup sweep was abandoned by the timeout.
            await asyncio.wait_for(polling_started.wait(), timeout=2.0)
            consumer._shutdown.set()
            await asyncio.wait_for(run_task, timeout=5.0)


class TestPollFailureLiveness:
    def test_withholds_liveness_after_threshold_consecutive_failures(self):
        # Without the trip, a pod whose every poll fails passes liveness forever.
        calls: list[int] = []
        consumer = _make_consumer(poll_failure_liveness_threshold=2)
        consumer._health_reporter = lambda: calls.append(1)

        consumer._report_health()
        consumer._note_poll_failure("timeout", duration=1.0)
        consumer._report_health()
        assert len(calls) == 2  # one failure is below the threshold

        consumer._note_poll_failure("timeout", duration=1.0)
        consumer._report_health()
        consumer._report_health()
        assert len(calls) == 2  # tripped: heartbeat and poll-loop reports both withhold

    @pytest.mark.asyncio
    async def test_successful_poll_resets_the_failure_count(self):
        # Only consecutive failures may trip the probe; without the reset a pod
        # restarts after N failures spread across weeks of healthy operation.
        config = ConsumerConfig(
            database_url="postgres://unused:unused@localhost/unused",
            poll_interval_seconds=0.01,
            poll_timeout_seconds=0.05,
        )
        consumer = BatchConsumer(config=config, process_batch=AsyncMock())

        succeeded = asyncio.Event()
        fetch_calls = 0

        async def fetch(*args: Any, **kwargs: Any) -> list[PendingBatch]:
            nonlocal fetch_calls
            fetch_calls += 1
            if fetch_calls <= 2:
                await asyncio.sleep(3600)  # times out
            succeeded.set()
            return []

        with (
            patch.object(
                consumer, "_connect", new_callable=AsyncMock, side_effect=lambda **kwargs: _make_healthy_conn()
            ),
            patch.object(consumer, "_install_signal_handlers"),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_unprocessed_and_lock",
                side_effect=fetch,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.release_all_owned_leases",
                new_callable=AsyncMock,
            ),
        ):
            run_task = asyncio.create_task(consumer.run())
            await asyncio.wait_for(succeeded.wait(), timeout=2.0)
            assert consumer._consecutive_poll_failures == 0
            consumer._shutdown.set()
            await asyncio.wait_for(run_task, timeout=5.0)


class TestStatementTimeoutBackstop:
    @pytest.mark.parametrize(
        "client_timeout,expected",
        [
            (180.0, 210000),  # 180s + 30s margin, in ms
            (None, None),  # disabled client ceiling disables the backstop too
            (0, None),
        ],
    )
    def test_timeout_ms_tracks_client_timeout(self, client_timeout, expected):
        consumer = _make_consumer(statement_timeout_margin_seconds=30.0)
        assert consumer._statement_timeout_ms(client_timeout) == expected

    @pytest.mark.asyncio
    async def test_poll_reconnect_applies_statement_timeout(self):
        # A reconnect that drops the backstop lets an abandoned query keep
        # burning queue-DB CPU — the exact failure the timeout guards against.
        # The timeout must arrive as a SET statement after connect, never as a
        # libpq startup option: PgBouncer rejects the latter and the whole
        # loader crash-loops at startup.
        consumer = _make_consumer(poll_timeout_seconds=180.0, statement_timeout_margin_seconds=30.0)
        consumer._poll_conn = _make_healthy_conn(closed=True)  # force the reconnect branch
        fresh = _make_healthy_conn()

        with patch.object(
            psycopg.AsyncConnection, "connect", new_callable=AsyncMock, return_value=fresh
        ) as mock_connect:
            await consumer._ensure_poll_conn()

        assert "options" not in mock_connect.call_args.kwargs
        fresh.execute.assert_awaited_once_with("SET statement_timeout = 210000")


class TestPollBackoff:
    def test_delay_grows_exponentially_and_caps(self):
        # Losing the backoff means lockstep fleet retries; losing the cap means
        # unbounded delays.
        consumer = _make_consumer(poll_interval_seconds=2.0)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.batch_consumer.random.uniform",
            return_value=0.0,
        ):
            consumer._consecutive_poll_failures = 1
            assert consumer._poll_retry_delay() == 2.0
            consumer._consecutive_poll_failures = 2
            assert consumer._poll_retry_delay() == 4.0
            consumer._consecutive_poll_failures = 3
            assert consumer._poll_retry_delay() == 8.0
            consumer._consecutive_poll_failures = 20  # far past the cap
            assert consumer._poll_retry_delay() == 30.0  # POLL_BACKOFF_MAX_SECONDS

    def test_jitter_is_added_within_one_interval(self):
        consumer = _make_consumer(poll_interval_seconds=2.0)
        consumer._consecutive_poll_failures = 1
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.batch_consumer.random.uniform",
            return_value=1.5,
        ):
            assert consumer._poll_retry_delay() == 3.5  # 2.0 backoff + 1.5 jitter


class TestFailRun:
    @pytest.mark.asyncio
    async def test_does_not_raise_when_job_status_update_fails(self):
        # A dropped app-DB connection while marking the job Failed must not propagate out of _fail_run.
        consumer = _make_consumer()
        batch = _make_batch()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.fail_run",
                new_callable=AsyncMock,
            ) as mock_fail_run,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer._update_job_status_to_failed",
                side_effect=Exception("the connection is closed"),
            ),
        ):
            await consumer._fail_run(
                batch, reason="max retries exceeded: the connection is closed", conn=consumer._poll_conn
            )

        mock_fail_run.assert_called_once()  # queue batches still marked failed

    @pytest.mark.asyncio
    async def test_attempts_job_status_update_even_when_queue_update_fails(self):
        consumer = _make_consumer()
        batch = _make_batch()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.fail_run",
                new_callable=AsyncMock,
                side_effect=Exception("the connection is closed"),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer._update_job_status_to_failed",
            ) as mock_status,
        ):
            await consumer._fail_run(batch, reason="boom", conn=consumer._poll_conn)

        mock_status.assert_called_once()


class TestReconcileFailedRuns:
    @pytest.mark.asyncio
    async def test_reconcile_reports_queue_freshness_gauge(self):
        # The gauge feeds the loader's data-freshness alert; if a reconcile
        # refactor drops the probe, the alert goes silently blind.
        consumer = _make_consumer()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_failed_runs",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_oldest_unclaimed_batch_age_seconds",
                new_callable=AsyncMock,
                return_value=1234.5,
            ) as mock_probe,
        ):
            await consumer._reconcile_failed_runs()
        assert OLDEST_UNCLAIMED_BATCH_SECONDS._value.get() == 1234.5

        mock_probe.return_value = None  # empty queue -> gauge resets to 0
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_failed_runs",
            new_callable=AsyncMock,
            return_value=[],
        ):
            with patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_oldest_unclaimed_batch_age_seconds",
                mock_probe,
            ):
                await consumer._reconcile_failed_runs()
        assert OLDEST_UNCLAIMED_BATCH_SECONDS._value.get() == 0.0

    @pytest.mark.asyncio
    async def test_hung_freshness_probe_saturates_gauge_and_reconcile_still_runs(self):
        # A queue DB too degraded to measure freshness must read as stale, not
        # pin the last good value — and the probe must not eat the sweep's budget.
        consumer = _make_consumer()

        async def hung_probe(*args: Any, **kwargs: Any) -> float:
            await asyncio.sleep(3600)
            return 0.0

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.FRESHNESS_PROBE_TIMEOUT_SECONDS",
                0.05,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_oldest_unclaimed_batch_age_seconds",
                side_effect=hung_probe,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_failed_runs",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_failed_runs,
        ):
            await asyncio.wait_for(consumer._reconcile_failed_runs(), timeout=2.0)

        assert OLDEST_UNCLAIMED_BATCH_SECONDS._value.get() == FRESHNESS_WINDOW_SECONDS
        mock_failed_runs.assert_called_once()

    @pytest.mark.asyncio
    async def test_marks_non_terminal_run_failed(self):
        consumer = _make_consumer()
        ref = _make_failed_run_ref()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_failed_runs",
                new_callable=AsyncMock,
                return_value=[ref],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.mark_job_failed_if_not_terminal",
                return_value=True,
            ) as mock_mark,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.release_v3_pipeline_lock",
            ) as mock_release,
        ):
            await consumer._reconcile_failed_runs()

        mock_mark.assert_called_once_with(job_id=ref.job_id, team_id=ref.team_id, error=ref.reason)
        mock_release.assert_called_once_with(team_id=ref.team_id, schema_id=ref.schema_id, token=ref.workflow_run_id)

    @pytest.mark.asyncio
    async def test_skips_already_terminal_run(self):
        consumer = _make_consumer()
        ref = _make_failed_run_ref()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_failed_runs",
                new_callable=AsyncMock,
                return_value=[ref],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.mark_job_failed_if_not_terminal",
                return_value=False,
            ) as mock_mark,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.release_v3_pipeline_lock",
            ) as mock_release,
        ):
            await consumer._reconcile_failed_runs()

        mock_mark.assert_called_once()  # no-op for an already-terminal job, no error
        mock_release.assert_not_called()  # don't release the lock for a job we didn't reconcile

    @pytest.mark.asyncio
    async def test_continues_after_error_on_one_ref(self):
        consumer = _make_consumer()
        ref_a = _make_failed_run_ref(run_uuid="run-a", job_id="job-a")
        ref_b = _make_failed_run_ref(run_uuid="run-b", job_id="job-b")

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_failed_runs",
                new_callable=AsyncMock,
                return_value=[ref_a, ref_b],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.mark_job_failed_if_not_terminal",
                side_effect=[Exception("db down"), True],
            ) as mock_mark,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.release_v3_pipeline_lock",
            ),
        ):
            await consumer._reconcile_failed_runs()

        assert mock_mark.call_count == 2  # error on the first ref does not abort the sweep


class TestConnectionRecovery:
    @pytest.mark.parametrize(
        "closed, broken, expect_reconnect",
        [
            (False, False, False),
            (True, False, True),
            (False, True, True),
        ],
        ids=["healthy", "closed", "broken"],
    )
    @pytest.mark.asyncio
    async def test_ensure_poll_conn_reconnects_only_when_dead(self, closed, broken, expect_reconnect):
        consumer = _make_consumer()
        original = _make_healthy_conn(closed=closed, broken=broken)
        consumer._poll_conn = original
        fresh = _make_healthy_conn()

        with patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=fresh) as mock_connect:
            conn = await consumer._ensure_poll_conn()

        if expect_reconnect:
            mock_connect.assert_awaited_once()
            assert conn is fresh
        else:
            mock_connect.assert_not_awaited()
            assert conn is original

    @pytest.mark.asyncio
    async def test_concurrent_ensure_poll_conn_dials_only_once(self):
        consumer = _make_consumer()
        consumer._poll_conn = _make_healthy_conn(closed=True)
        fresh = _make_healthy_conn()

        async def slow_connect(**kwargs: Any) -> AsyncMock:
            await asyncio.sleep(0)  # yield so the other coroutines reach the check while we're "dialing"
            return fresh

        with patch.object(consumer, "_connect", side_effect=slow_connect) as mock_connect:
            conns = await asyncio.gather(*[consumer._ensure_poll_conn() for _ in range(5)])

        assert mock_connect.call_count == 1
        assert all(conn is fresh for conn in conns)

    @pytest.mark.asyncio
    async def test_ensure_recovery_conn_reconnects_when_dead(self):
        consumer = _make_consumer()
        consumer._recovery_conn = _make_healthy_conn(closed=True)
        fresh = _make_healthy_conn()

        with patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=fresh) as mock_connect:
            conn = await consumer._ensure_recovery_conn()

        mock_connect.assert_awaited_once()
        assert conn is fresh

    @pytest.mark.asyncio
    async def test_process_group_does_not_raise_when_unlock_fails(self):
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
                side_effect=Exception("the connection is closed"),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.verify_advisory_lock",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=_make_healthy_conn()),
        ):
            await consumer._process_group((1, "schema-1"), [_make_batch()])

    @pytest.mark.asyncio
    async def test_process_group_does_not_raise_when_process_single_raises(self):
        consumer = _make_consumer()

        with (
            patch.object(
                consumer,
                "_process_single",
                new_callable=AsyncMock,
                side_effect=psycopg.OperationalError("the connection is closed"),
            ) as mock_single,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=_make_healthy_conn()),
        ):
            await consumer._process_group((1, "schema-1"), [_make_batch(), _make_batch(batch_index=1)])

        mock_single.assert_awaited_once()  # group halts after the failed batch
        mock_unlock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_recovery_sweep_uses_reconnected_conn(self):
        consumer = _make_consumer()
        consumer._recovery_conn = _make_healthy_conn(closed=True)
        fresh = _make_healthy_conn()

        with (
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=fresh),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_get_stale,
        ):
            await consumer._recovery_sweep()

        mock_get_stale.assert_awaited_once()
        assert mock_get_stale.call_args[0][0] is fresh


class TestPerGroupConnectionIsolation:
    @pytest.mark.asyncio
    async def test_each_group_gets_distinct_connection(self):
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock()
        conns_seen: list[Any] = []

        group_conn_a = _make_healthy_conn()
        group_conn_b = _make_healthy_conn()
        connect_returns = iter([group_conn_a, group_conn_b])

        async def mock_connect():
            return next(connect_returns)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.verify_advisory_lock",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(consumer, "_connect", side_effect=mock_connect),
        ):
            batch_a = _make_batch(team_id=1, schema_id="a")
            batch_b = _make_batch(team_id=1, schema_id="b")

            original_process_single = consumer._process_single

            async def track_conn(batch, lock_conn=None):
                conns_seen.append(lock_conn)
                return await original_process_single(batch, lock_conn=lock_conn)

            consumer._process_single = track_conn  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]

            await consumer._process_group((1, "a"), [batch_a])
            await consumer._process_group((1, "b"), [batch_b])

        assert conns_seen[0] is group_conn_a
        assert conns_seen[1] is group_conn_b
        assert conns_seen[0] is not conns_seen[1]

    @pytest.mark.asyncio
    async def test_group_connection_not_shared_with_poll(self):
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock()
        group_conn = _make_healthy_conn()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.verify_advisory_lock",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=group_conn),
        ):
            conn_used = None
            original = consumer._process_single

            async def capture_conn(batch, lock_conn=None):
                nonlocal conn_used
                conn_used = lock_conn
                return await original(batch, lock_conn=lock_conn)

            consumer._process_single = capture_conn  # type: ignore[method-assign]  # ty: ignore[invalid-assignment]
            await consumer._process_group((1, "schema-1"), [_make_batch()])

        assert conn_used is group_conn
        assert conn_used is not consumer._poll_conn

    @pytest.mark.asyncio
    async def test_group_connection_closed_after_processing(self):
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock()
        group_conn = _make_healthy_conn()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.verify_advisory_lock",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=group_conn),
        ):
            await consumer._process_group((1, "schema-1"), [_make_batch()])

        group_conn.close.assert_awaited_once()


class TestGroupByKey:
    def test_groups_by_team_and_schema(self):
        batches = [
            _make_batch(id="00000000-0000-0000-0000-000000000001", team_id=1, schema_id="a", batch_index=0),
            _make_batch(id="00000000-0000-0000-0000-000000000002", team_id=1, schema_id="b", batch_index=0),
            _make_batch(id="00000000-0000-0000-0000-000000000003", team_id=1, schema_id="a", batch_index=1),
            _make_batch(id="00000000-0000-0000-0000-000000000004", team_id=2, schema_id="a", batch_index=0),
        ]

        groups = _group_by_key(batches)

        assert len(groups) == 3
        assert len(groups[(1, "a")]) == 2
        assert len(groups[(1, "b")]) == 1
        assert len(groups[(2, "a")]) == 1

    def test_preserves_insertion_order(self):
        batches = [
            _make_batch(id="00000000-0000-0000-0000-000000000001", team_id=1, schema_id="a", batch_index=0),
            _make_batch(id="00000000-0000-0000-0000-000000000002", team_id=1, schema_id="a", batch_index=1),
            _make_batch(id="00000000-0000-0000-0000-000000000003", team_id=1, schema_id="a", batch_index=2),
        ]

        groups = _group_by_key(batches)

        assert [b.batch_index for b in groups[(1, "a")]] == [0, 1, 2]

    def test_empty_input(self):
        assert _group_by_key([]) == {}


class TestLogContextBinding:
    """Verify the consumer binds the structlog contextvars `LogMessagesRenderer` needs.

    The CDC Syncs UI panel queries log_entries by `(log_source='external_data_jobs',
    log_source_id=schema_id, instance_id=workflow_run_id)`. The renderer in
    `posthog.temporal.common.logger` reads these from the structlog event_dict, so they
    must be bound via contextvars BEFORE downstream loggers fire.
    """

    @pytest.mark.asyncio
    async def test_process_single_binds_log_context_for_syncs_panel(self):
        consumer = _make_consumer()
        batch = _make_batch(
            latest_attempt=0,
            metadata={"workflow_id": "cdc-extraction-source-123", "workflow_run_id": "wf-run-id-456"},
        )
        seen: dict[str, Any] = {}

        async def capture_context(b):
            seen.update(structlog.contextvars.get_contextvars())

        consumer._process_batch = capture_context

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            new_callable=AsyncMock,
        ):
            await consumer._process_single(batch)

        assert seen.get("workflow_type") == "cdc-extraction"
        assert seen.get("workflow_id") == "cdc-extraction-source-123"
        assert seen.get("workflow_run_id") == "wf-run-id-456"
        assert seen.get("team_id") == batch.team_id
        assert seen.get("log_source_id") == batch.schema_id
        assert seen.get("external_data_schema_id") == batch.schema_id
        assert seen.get("attempt") == 1

        # Cleared after the batch returns so context doesn't leak across batches.
        assert structlog.contextvars.get_contextvars().get("batch_id") is None

    @pytest.mark.asyncio
    async def test_process_single_binds_external_data_job_workflow_type_for_non_cdc(self):
        """Consumer also runs non-CDC syncs (`external-data-job` workflow_id prefix)."""
        consumer = _make_consumer()
        batch = _make_batch(
            latest_attempt=0,
            metadata={
                "workflow_id": "019df430-765a-0000-0523-040f9c48be64-2026-05-21T00:00:00",
                "workflow_run_id": "wf-run",
            },
        )
        seen: dict[str, Any] = {}

        async def capture_context(b):
            seen.update(structlog.contextvars.get_contextvars())

        consumer._process_batch = capture_context

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            new_callable=AsyncMock,
        ):
            await consumer._process_single(batch)

        assert seen.get("workflow_type") == "external-data-job"

    @pytest.mark.asyncio
    async def test_process_single_handles_missing_workflow_ids_in_metadata(self):
        """Old batches enqueued before this change have no workflow ids in metadata -- must not crash."""
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            new_callable=AsyncMock,
        ):
            await consumer._process_single(_make_batch(latest_attempt=0, metadata={}))

        consumer._process_batch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_single_clears_context_on_error(self):
        consumer = _make_consumer(max_attempts=3)
        consumer._process_batch = AsyncMock(side_effect=ValueError("boom"))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
            new_callable=AsyncMock,
        ):
            await consumer._process_single(_make_batch(latest_attempt=0))

        assert "batch_id" not in structlog.contextvars.get_contextvars()
        assert "workflow_run_id" not in structlog.contextvars.get_contextvars()


class TestHeartbeatLoop:
    @pytest.mark.asyncio
    async def test_reports_until_shutdown(self):
        consumer = _make_consumer(heartbeat_interval_seconds=0.01)
        calls = 0

        def reporter():
            nonlocal calls
            calls += 1

        consumer._health_reporter = reporter

        task = asyncio.create_task(consumer._heartbeat_loop())
        await asyncio.sleep(0.05)
        consumer._shutdown.set()
        await asyncio.wait_for(task, timeout=1.0)

        assert calls >= 2

    @pytest.mark.asyncio
    async def test_keeps_liveness_healthy_through_long_batch(self):
        # A poll cycle (large final-batch compaction) can run far longer than the
        # health timeout; the dedicated heartbeat must keep liveness green so
        # kubelet doesn't SIGTERM the pod mid-batch.
        health = HealthState(timeout_seconds=0.1)
        consumer = _make_consumer(heartbeat_interval_seconds=0.02)
        consumer._health_reporter = health.report_healthy

        task = asyncio.create_task(consumer._heartbeat_loop())
        await asyncio.sleep(0.3)  # simulate a batch ~3x the health timeout
        assert health.is_healthy() is True

        consumer._shutdown.set()
        await asyncio.wait_for(task, timeout=1.0)

        # Once the heartbeat stops, liveness correctly goes stale again.
        await asyncio.sleep(0.2)
        assert health.is_healthy() is False


class TestOwnershipVerification:
    @pytest.mark.asyncio
    async def test_ownership_lost_abandons_group(self):
        consumer = _make_consumer()
        processed: list[int] = []

        async def track_and_lose_lock(batch):
            processed.append(batch.batch_index)

        consumer._process_batch = track_and_lose_lock

        batches = [_make_batch(batch_index=i, id=f"00000000-0000-0000-0000-{i + 1:012d}") for i in range(3)]

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.verify_advisory_lock",
                new_callable=AsyncMock,
                side_effect=[True, True, False],
            ),
            patch.object(consumer, "_connect", new_callable=AsyncMock, return_value=_make_healthy_conn()),
        ):
            await consumer._process_group((1, "schema-1"), batches)

        # Batch 0 processes (verify returns True before batch 0, True before succeeded write),
        # batch 1 fails on verify (returns False) and the group is abandoned.
        assert len(processed) <= 2
        mock_unlock.assert_called_once()

    @pytest.mark.asyncio
    async def test_dead_lock_conn_raises_ownership_lost(self):
        consumer = _make_consumer()
        batch = _make_batch(latest_attempt=0)

        dead_conn = _make_healthy_conn(closed=True)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            pytest.raises(OwnershipLostError),
        ):
            await consumer._process_single(batch, lock_conn=dead_conn)

    @pytest.mark.asyncio
    async def test_process_single_without_lock_conn_skips_verification(self):
        consumer = _make_consumer()
        batch = _make_batch(latest_attempt=0)
        consumer._process_batch = AsyncMock()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.verify_advisory_lock",
                new_callable=AsyncMock,
            ) as mock_verify,
        ):
            result = await consumer._process_single(batch, lock_conn=None)

        assert result is True
        mock_verify.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_stops_when_lease_renewal_fails(self):
        # A lost lease (another pod reclaimed the group) must end the heartbeat so the
        # group isn't double-processed while still re-stamping executing.
        consumer = _make_consumer()
        consumer._config.recovery_grace_seconds = 30  # heartbeat interval -> max(30/3, 10) = 10s
        batch = _make_batch()
        lock_conn = _make_healthy_conn()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.renew_lease",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_renew,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
            ) as mock_status,
            patch("asyncio.sleep", new_callable=AsyncMock),  # don't wait the real interval
        ):
            await consumer._batch_heartbeat(lock_conn, batch, attempt=1)

        mock_renew.assert_awaited_once()
        # Lease lost -> heartbeat returns before re-stamping executing.
        mock_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_heartbeat_renews_lease_then_restamps_executing(self):
        # The success path: a held lease is renewed and the executing-status grace
        # window is refreshed on the same beat. update_status raising ends the loop.
        consumer = _make_consumer()
        consumer._config.recovery_grace_seconds = 30
        batch = _make_batch()
        lock_conn = _make_healthy_conn()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.renew_lease",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_renew,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.update_status",
                new_callable=AsyncMock,
                side_effect=Exception("stop the loop"),
            ) as mock_status,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await consumer._batch_heartbeat(lock_conn, batch, attempt=2)

        mock_renew.assert_awaited_once_with(
            lock_conn,
            team_id=batch.team_id,
            schema_id=batch.schema_id,
            owner_token=consumer._owner_token,
            lease_ttl_seconds=consumer._lease_ttl_seconds,
        )
        mock_status.assert_awaited_once()


class TestShutdown:
    @pytest.mark.asyncio
    async def test_close_releases_owned_leases(self):
        consumer = _make_consumer()
        main_conn = _make_healthy_conn()
        consumer._poll_conn = main_conn
        consumer._recovery_conn = _make_healthy_conn()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.release_all_owned_leases",
            new_callable=AsyncMock,
        ) as mock_release:
            await consumer._close()

        mock_release.assert_awaited_once_with(main_conn, owner_token=consumer._owner_token)
        main_conn.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_drains_in_flight_tasks(self):
        consumer = _make_consumer()
        consumer._poll_conn = _make_healthy_conn()
        consumer._recovery_conn = _make_healthy_conn()
        drained = asyncio.Event()

        async def slow_group():
            await asyncio.sleep(0.01)
            drained.set()

        task = asyncio.create_task(slow_group())
        consumer._in_flight[(1, "schema-1")] = task
        consumer._metrics.active_groups.inc()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.consumer.BatchQueue.release_all_owned_leases",
            new_callable=AsyncMock,
        ):
            await consumer._close()

        assert drained.is_set()
        assert len(consumer._in_flight) == 0


class TestDispatchGroups:
    def test_fetch_limit_caps_to_free_slots_and_poll_limit(self):
        consumer = _make_consumer(max_concurrency=16, poll_limit=50)
        # 1 free slot must not lease a whole 50-batch window (orphaned-lease regression).
        assert consumer._fetch_limit(1) == 3
        assert consumer._fetch_limit(4) == 12
        assert consumer._fetch_limit(16) == 48
        wide = _make_consumer(max_concurrency=64, poll_limit=50)
        assert wide._fetch_limit(64) == 50

    @pytest.mark.asyncio
    async def test_undispatched_groups_release_their_leases_in_the_same_cycle(self):
        consumer = _make_consumer(max_concurrency=2)
        consumer._in_flight[(1, "schema-0")] = AsyncMock()

        dispatched = _make_batch(id="00000000-0000-0000-0000-00000000000a", schema_id="schema-1", run_uuid="run-1")
        dropped_1 = _make_batch(id="00000000-0000-0000-0000-00000000000b", schema_id="schema-2", run_uuid="run-2")
        dropped_2 = _make_batch(
            id="00000000-0000-0000-0000-00000000000c", schema_id="schema-2", run_uuid="run-2", batch_index=1
        )

        with patch.object(consumer._adapter, "unlock", new=AsyncMock()) as mock_unlock:
            await consumer._dispatch_groups(_make_healthy_conn(), [dispatched, dropped_1, dropped_2])

            # One free slot: schema-1 dispatched; schema-2's lease must be released now,
            # not left dark until the 300s TTL expires (the fleet-throughput regression).
            assert (1, "schema-1") in consumer._in_flight
            assert (1, "schema-2") not in consumer._in_flight
            released = mock_unlock.call_args.kwargs["batches"]
            assert {b.id for b in released} == {dropped_1.id, dropped_2.id}

        task = consumer._in_flight.pop((1, "schema-1"))
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
