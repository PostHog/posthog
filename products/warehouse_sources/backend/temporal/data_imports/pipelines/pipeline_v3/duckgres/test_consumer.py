import time
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import psycopg

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.batch_consumer import (
    OwnershipLostError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer import (
    DuckgresBatchConsumer,
    DuckgresBatchConsumerAdapter,
    DuckgresConsumerConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.postgres_queue.jobs_db import (
    PendingBatch,
)
from products.warehouse_sources_queue.backend.models import SourceBatchDuckgresStatus


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


def _make_consumer(max_attempts: int = 3, **kwargs) -> DuckgresBatchConsumer:
    config = DuckgresConsumerConfig(
        database_url="postgres://unused:unused@localhost/unused",
        max_attempts=max_attempts,
        **kwargs,
    )
    consumer = DuckgresBatchConsumer(config=config, process_batch=AsyncMock())
    consumer._poll_conn = _make_healthy_conn()
    consumer._recovery_conn = _make_healthy_conn()
    return consumer


def _make_healthy_conn(closed: bool = False, broken: bool = False) -> AsyncMock:
    # closed/broken must be real booleans, otherwise _ensure_*_conn sees a dead conn and dials the fake database_url.
    conn = AsyncMock()
    conn.closed = closed
    conn.broken = broken
    return conn


class TestDuckgresProcessSingle:
    @pytest.mark.asyncio
    async def test_adapter_forwards_empty_error_response_explicitly(self):
        consumer = _make_consumer()
        update_status_calls: list[dict[str, Any]] = []

        async def track_status(conn, **kwargs):
            update_status_calls.append(kwargs)
            return True

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status",
                side_effect=track_status,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status_unless_failed",
                side_effect=track_status,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.is_failed",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.has_applied",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            await consumer._process_single(_make_batch(is_final_batch=True))

        assert update_status_calls[0]["error_response"] is None
        assert update_status_calls[1]["error_response"] is None

    @pytest.mark.asyncio
    async def test_success_updates_status_and_marks_applied(self):
        consumer = _make_consumer()
        states: list[str] = []

        async def track_status(conn, *, batch_id, job_state, attempt, error_response=None):
            states.append(job_state)
            return True

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status",
                side_effect=track_status,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status_unless_failed",
                side_effect=track_status,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.is_failed",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.has_applied",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.mark_applied",
                new_callable=AsyncMock,
            ) as mock_mark,
        ):
            await consumer._process_single(_make_batch())

        assert states == [SourceBatchDuckgresStatus.State.EXECUTING, SourceBatchDuckgresStatus.State.SUCCEEDED]
        mock_mark.assert_called_once()

    @pytest.mark.asyncio
    async def test_final_marker_requires_existing_apply_and_does_not_process(self):
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status",
                new_callable=AsyncMock,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status_unless_failed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.is_failed",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.has_applied",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.mark_applied",
                new_callable=AsyncMock,
            ) as mock_mark,
        ):
            await consumer._process_single(_make_batch(is_final_batch=True))

        consumer._process_batch.assert_not_called()
        mock_mark.assert_not_called()

    @pytest.mark.asyncio
    async def test_error_sets_waiting_retry(self):
        consumer = _make_consumer(max_attempts=3)
        consumer._process_batch = AsyncMock(side_effect=ValueError("boom"))
        states: list[str] = []

        async def track_status(conn, *, batch_id, job_state, attempt, error_response=None):
            states.append(job_state)
            return True

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status",
                side_effect=track_status,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status_unless_failed",
                side_effect=track_status,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.is_failed",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.has_applied",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            await consumer._process_single(_make_batch())

        assert states == [SourceBatchDuckgresStatus.State.EXECUTING, SourceBatchDuckgresStatus.State.WAITING_RETRY]

    @pytest.mark.asyncio
    async def test_max_attempts_exceeded_fails_duckgres_run_only(self):
        consumer = _make_consumer(max_attempts=3)

        with patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_fail:
            await consumer._process_single(_make_batch(latest_attempt=3))

        mock_fail.assert_called_once()


class TestDuckgresEnablementGating:
    @pytest.mark.asyncio
    async def test_fetch_returns_empty_without_querying_when_no_teams_enabled(self):
        adapter = DuckgresBatchConsumerAdapter()
        adapter._team_ids = []
        adapter._team_ids_fetched_at = time.monotonic()
        conn = _make_healthy_conn()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.get_delta_succeeded_and_lock",
            new_callable=AsyncMock,
        ) as mock_fetch:
            batches = await adapter.fetch_and_lock(
                conn,
                limit=50,
                retry_backoff_base_seconds=0,
                owner_token="test-owner",
                lease_ttl_seconds=300,
                max_groups=16,
                exclude_groups=[],
            )

        assert batches == []
        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_passes_team_ids_and_runs_maintenance(self):
        adapter = DuckgresBatchConsumerAdapter()
        adapter._team_ids = [1, 2]
        adapter._team_ids_fetched_at = time.monotonic()
        conn = _make_healthy_conn()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.get_delta_succeeded_and_lock",
                new_callable=AsyncMock,
                return_value=[],
            ) as mock_fetch,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.supersede_replaced_runs",
                new_callable=AsyncMock,
                return_value=0,
            ) as mock_supersede,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.get_backlog_stats",
                new_callable=AsyncMock,
                return_value=(0, None, 0, None, 0),
            ) as mock_backlog,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.run_backfill_planner",
            ) as mock_planner,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.compute_blocked_schema_ids",
                return_value=["blocked-schema"],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.compute_failing_schema_ids",
                return_value=[],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.compute_eligible_schema_ids",
                return_value=["eligible-schema"],
            ),
        ):
            await adapter.fetch_and_lock(
                conn,
                limit=50,
                retry_backoff_base_seconds=30,
                owner_token="test-owner",
                lease_ttl_seconds=300,
                max_groups=16,
                exclude_groups=[],
            )

        assert mock_fetch.call_args[1]["team_ids"] == [1, 2]
        assert mock_fetch.call_args[1]["retry_backoff_base_seconds"] == 30
        assert mock_fetch.call_args[1]["blocked_schema_ids"] == ["blocked-schema"]
        assert mock_fetch.call_args[1]["eligible_schema_ids"] == ["eligible-schema"]
        assert mock_fetch.call_args[1]["owner_token"] == "test-owner"
        assert mock_fetch.call_args[1]["lease_ttl_seconds"] == 300
        assert mock_fetch.call_args[1]["max_groups"] == 16
        mock_supersede.assert_called_once()
        mock_backlog.assert_called_once()
        mock_planner.assert_called_once_with([1, 2])

    @pytest.mark.asyncio
    async def test_fetch_claims_nothing_until_planner_succeeds(self):
        adapter = DuckgresBatchConsumerAdapter()
        adapter._team_ids = [1]
        adapter._team_ids_fetched_at = time.monotonic()
        conn = _make_healthy_conn()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.get_delta_succeeded_and_lock",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.supersede_replaced_runs",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.get_backlog_stats",
                new_callable=AsyncMock,
                return_value=(0, None, 0, None, 0),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.run_backfill_planner",
                side_effect=RuntimeError("app DB down"),
            ),
        ):
            batches = await adapter.fetch_and_lock(
                conn,
                limit=50,
                retry_backoff_base_seconds=0,
                owner_token="test-owner",
                lease_ttl_seconds=300,
                max_groups=16,
                exclude_groups=[],
            )

        assert batches == []
        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_claims_nothing_until_eligible_list_ready(self):
        # Prod fail-closed: even with the block list computed, an uncomputed v3
        # allow-list must halt claiming so non-v3 source types can't be applied.
        adapter = DuckgresBatchConsumerAdapter()
        adapter._team_ids = [1]
        adapter._team_ids_fetched_at = time.monotonic()
        conn = _make_healthy_conn()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.get_delta_succeeded_and_lock",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.supersede_replaced_runs",
                new_callable=AsyncMock,
                return_value=0,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.get_backlog_stats",
                new_callable=AsyncMock,
                return_value=(0, None, 0, None, 0),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.run_backfill_planner",
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.compute_blocked_schema_ids",
                return_value=["blocked-schema"],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.compute_failing_schema_ids",
                return_value=[],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.compute_eligible_schema_ids",
                side_effect=RuntimeError("flag eval down"),
            ),
        ):
            batches = await adapter.fetch_and_lock(
                conn,
                limit=50,
                retry_backoff_base_seconds=0,
                owner_token="test-owner",
                lease_ttl_seconds=300,
                max_groups=16,
                exclude_groups=[],
            )

        assert batches == []
        mock_fetch.assert_not_called()

    @pytest.mark.asyncio
    async def test_fetch_swallows_maintenance_query_timeout_and_skips_planner(self):
        # The eligibility-CTE maintenance queries are statement-timeout bounded;
        # a timeout (or any transient queue-DB error) must be swallowed so the
        # poll loop is neither wedged nor crashed — the planner is skipped and
        # nothing is claimed this tick, and the next poll just retries.
        adapter = DuckgresBatchConsumerAdapter()
        adapter._team_ids = [1, 2]
        adapter._team_ids_fetched_at = time.monotonic()
        conn = _make_healthy_conn()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.get_delta_succeeded_and_lock",
                new_callable=AsyncMock,
            ) as mock_fetch,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.supersede_replaced_runs",
                new_callable=AsyncMock,
                side_effect=psycopg.errors.QueryCanceled("canceling statement due to statement timeout"),
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.run_backfill_planner",
            ) as mock_planner,
        ):
            batches = await adapter.fetch_and_lock(
                conn, limit=50, retry_backoff_base_seconds=0, owner_token="test-owner", lease_ttl_seconds=300
            )

        assert batches == []
        mock_planner.assert_not_called()
        mock_fetch.assert_not_called()


class TestMidClaimRetire:
    @pytest.mark.asyncio
    async def test_terminally_retired_batch_aborts_group_without_any_status_write(self):
        # A chunk retired mid-claim must abort the whole group with NO status
        # write — even an 'executing' row would mask the terminal 'failed'.
        consumer = _make_consumer()
        consumer._process_batch = AsyncMock()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.is_failed",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status",
                new_callable=AsyncMock,
            ) as mock_status,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status_unless_failed",
                new_callable=AsyncMock,
            ) as mock_status_unless_failed,
            pytest.raises(OwnershipLostError),
        ):
            await consumer._process_single(_make_batch())

        consumer._process_batch.assert_not_called()
        mock_status.assert_not_called()
        mock_status_unless_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_status_write_blocked_by_terminal_failed_aborts_group(self):
        # Any status write blocked by a terminal 'failed' means the batch was
        # retired while claimed; stamping a later status would un-retire it.
        adapter = DuckgresBatchConsumerAdapter()
        conn = _make_healthy_conn()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status_unless_failed",
            new_callable=AsyncMock,
            return_value=False,
        ):
            with pytest.raises(OwnershipLostError):
                await adapter.update_status(
                    conn,
                    batch_id="00000000-0000-0000-0000-000000000001",
                    job_state=SourceBatchDuckgresStatus.State.SUCCEEDED.value,
                    attempt=1,
                )


class TestGroupLeaseRenewal:
    @pytest.mark.asyncio
    async def test_boundary_ownership_check_extends_the_lease(self):
        # Quick chunks never trigger in-batch heartbeats, so the per-batch
        # ownership check must renew the lease or a long group loses it mid-run.
        adapter = DuckgresBatchConsumerAdapter(lease_ttl_seconds=900)
        conn = _make_healthy_conn()

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.renew_lease",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_renew:
            owns = await adapter.verify_advisory_lock(conn, team_id=1, schema_id="schema-1", owner_token="owner-a")

        assert owns is True
        assert mock_renew.call_args[1]["lease_ttl_seconds"] == 900


class TestErrorPathOwnershipFencing:
    @pytest.mark.asyncio
    async def test_error_status_suppressed_when_ownership_lost_mid_batch(self):
        # A worker that outlived its lease must abandon with no write, not
        # stamp waiting_retry (or fail the run) over the new owner's lifecycle.
        consumer = _make_consumer(max_attempts=3)
        consumer._process_batch = AsyncMock(side_effect=ValueError("boom"))
        lock_conn = _make_healthy_conn()
        states: list[str] = []

        async def track_status(conn, *, batch_id, job_state, attempt, error_response=None):
            states.append(job_state)
            return True

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.update_status_unless_failed",
                side_effect=track_status,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.renew_lease",
                new_callable=AsyncMock,
                side_effect=[True, False],  # start-of-batch check passes; error-path check fails
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.is_failed",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.has_applied",
                new_callable=AsyncMock,
                return_value=False,
            ),
            patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_fail,
            pytest.raises(OwnershipLostError),
        ):
            await consumer._process_single(_make_batch(), lock_conn=lock_conn)

        mock_fail.assert_not_called()
        assert SourceBatchDuckgresStatus.State.WAITING_RETRY not in states


class TestGroupConnectionFailure:
    @pytest.mark.asyncio
    async def test_leases_released_when_group_connection_fails(self):
        # A failed group-connection open must still release the fetch-time
        # leases via the poll conn, or every poll renews them indefinitely.
        consumer = _make_consumer()
        batches = [_make_batch()]

        with (
            patch.object(consumer, "_connect", new_callable=AsyncMock, side_effect=psycopg.OperationalError("no conn")),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
        ):
            await consumer._process_group_tracked((1, "schema-1"), batches)

        mock_unlock.assert_called_once_with(consumer._poll_conn, batches=batches, owner_token=consumer._owner_token)


class TestFencedRecoverySweep:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("fenced_result", [True, False])
    async def test_stale_batch_requeued_only_through_the_fenced_write(self, fenced_result):
        # The sweep must requeue via the write-time fence and never release
        # leases afterwards (the poll loop can reclaim a group mid-sweep).
        consumer = _make_consumer(max_attempts=3)
        stale_batch = _make_batch(latest_attempt=1)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[stale_batch],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.requeue_stale_executing",
                new_callable=AsyncMock,
                return_value=fenced_result,
            ) as mock_requeue,
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.unlock_for_batches",
                new_callable=AsyncMock,
            ) as mock_unlock,
        ):
            await consumer._recovery_sweep()

        mock_requeue.assert_called_once()
        assert mock_requeue.call_args[1]["grace_seconds"] == consumer._config.recovery_grace_seconds
        mock_unlock.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fenced_result", [True, False])
    async def test_exhausted_stale_batch_failed_only_through_the_fenced_write(self, fenced_result):
        consumer = _make_consumer(max_attempts=3)
        stale_batch = _make_batch(latest_attempt=3)

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.get_stale_executing",
                new_callable=AsyncMock,
                return_value=[stale_batch],
            ),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.duckgres.consumer.DuckgresBatchQueue.fail_run_if_stale",
                new_callable=AsyncMock,
                return_value=fenced_result,
            ) as mock_fenced_fail,
            patch.object(consumer, "_fail_run", new_callable=AsyncMock) as mock_unfenced,
        ):
            await consumer._recovery_sweep()

        mock_fenced_fail.assert_called_once()
        assert "max retries exceeded" in mock_fenced_fail.call_args[1]["reason"]
        mock_unfenced.assert_not_called()


class TestStuckBatchWatchdog:
    @pytest.mark.asyncio
    async def test_health_withheld_while_a_batch_is_stuck(self):
        reporter = MagicMock()
        consumer = _make_consumer(stuck_batch_timeout_seconds=10.0)
        consumer._health_reporter = reporter
        consumer._inflight_started = {"batch-1": time.monotonic() - 60}

        consumer._report_health()

        reporter.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_reported_when_batches_are_fresh_or_absent(self):
        reporter = MagicMock()
        consumer = _make_consumer(stuck_batch_timeout_seconds=10.0)
        consumer._health_reporter = reporter

        consumer._report_health()
        consumer._inflight_started = {"batch-1": time.monotonic()}
        consumer._report_health()

        assert reporter.call_count == 2
