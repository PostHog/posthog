import uuid
import asyncio
import datetime
import tempfile

import pytest
from unittest.mock import AsyncMock, patch

import pyarrow as pa
import deltalake as deltalake
import structlog
from asgiref.sync import async_to_sync
from temporalio.exceptions import CancelledError as TemporalCancelledError
from temporalio.testing import ActivityEnvironment

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline import repartition_controller as ctrl
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.repartition import (
    RepartitionUnpartitionableError,
)
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities import repartition_table
from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table import (
    RepartitionActivityInputs,
    maybe_repartition_table_activity,
)

logger = structlog.get_logger(__name__)

# transaction=True: the detection path and the (thread-pool) sync activity write to the DB from worker
# threads with their own connections, which can't see an atomic TestCase's uncommitted rows.
pytestmark = pytest.mark.django_db(transaction=True)


def _write_partitioned_delta(path: str, buckets: list[str]) -> deltalake.DeltaTable:
    table = pa.table(
        {
            "id": pa.array(list(range(len(buckets))), type=pa.int64()),
            PARTITION_KEY: pa.array(buckets, type=pa.string()),
        }
    )
    deltalake.write_deltalake(path, table, partition_by=PARTITION_KEY)
    return deltalake.DeltaTable(path)


def _write_unpartitioned_delta(path: str) -> deltalake.DeltaTable:
    deltalake.write_deltalake(path, pa.table({"id": pa.array([1, 2, 3], type=pa.int64())}))
    return deltalake.DeltaTable(path)


def _make_schema(team, sync_type_config: dict) -> ExternalDataSchema:
    source = ExternalDataSource.objects.create(
        source_id=str(uuid.uuid4()), connection_id=str(uuid.uuid4()), team=team, source_type="Stripe"
    )
    return ExternalDataSchema.objects.create(name="repart", team=team, source=source, sync_type_config=sync_type_config)


def _make_job(team, schema: ExternalDataSchema) -> ExternalDataJob:
    return ExternalDataJob.objects.create(
        team=team, pipeline=schema.source, schema=schema, status=ExternalDataJob.Status.RUNNING, rows_synced=0
    )


class TestRepartitionDetection:
    def _detect(self, team, schema: ExternalDataSchema, delta: deltalake.DeltaTable) -> None:
        async_to_sync(ctrl.maybe_flag_for_repartition)(schema, schema.source, _make_job(team, schema), delta, logger)

    def test_flags_over_budget_table_with_target(self, team):
        # An md5 table whose largest partition exceeds the budget must be queued with a grown count, and
        # the measured size recorded — this is the core trigger that stops OOMs before the next merge.
        schema = _make_schema(
            team,
            {"partitioning_enabled": True, "partition_mode": "md5", "partition_count": 2, "partitioning_keys": ["id"]},
        )
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "0", "1", "1"])
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=1),
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
                patch.object(ctrl, "capture_repartition_event") as capture,
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.max_partition_bytes is not None and schema.max_partition_bytes > 0
        pending = schema.repartition_pending
        assert pending is not None
        assert pending["partition_mode"] == "md5"
        assert pending["partition_count"] > 2
        assert pending["trigger_reason"] == "proactive_threshold"
        assert capture.call_args.args[0] == "warehouse_repartition_flagged"

    def test_within_budget_records_size_but_does_not_flag(self, team):
        schema = _make_schema(team, {"partitioning_enabled": True, "partition_mode": "md5", "partition_count": 2})
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "1"])
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=10**12),
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.max_partition_bytes is not None
        assert schema.repartition_pending is None

    def test_disabled_flag_records_size_but_does_not_flag(self, team):
        schema = _make_schema(team, {"partitioning_enabled": True, "partition_mode": "md5", "partition_count": 2})
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "1"])
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=1),
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=False),
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.max_partition_bytes is not None
        assert schema.repartition_pending is None

    def test_cooldown_blocks_flagging(self, team):
        recent = datetime.datetime.now(datetime.UTC).isoformat()
        schema = _make_schema(
            team,
            {
                "partitioning_enabled": True,
                "partition_mode": "md5",
                "partition_count": 2,
                "partitioning_keys": ["id"],
                "last_repartition_at": recent,
            },
        )
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "1"])
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=1),
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.repartition_pending is None

    def test_unpartitionable_over_budget_skips_with_reason(self, team):
        # An unpartitioned table with no usable key can't be repartitioned — we must surface the specific
        # reason (so a human is alerted) rather than silently flag a target that would fail.
        schema = _make_schema(team, {})
        with tempfile.TemporaryDirectory() as d:
            delta = _write_unpartitioned_delta(f"{d}/u")
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=1),
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
                patch.object(ctrl, "capture_repartition_event") as capture,
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.repartition_pending is None
        assert capture.call_args.args[0] == "warehouse_repartition_skipped"
        assert capture.call_args.args[1]["reason"] == "unpartitionable_no_keys"


class TestRepartitionActivity:
    def _inputs(self, team, schema: ExternalDataSchema) -> RepartitionActivityInputs:
        job = _make_job(team, schema)
        return RepartitionActivityInputs(
            team_id=team.id, schema_id=str(schema.id), job_id=str(job.id), source_id=str(schema.source_id)
        )

    def _run(self, inputs: RepartitionActivityInputs, repartition_mock: AsyncMock):
        # Mock HeartbeaterSync (no real heartbeat thread / activity context needed) and the primitive,
        # so these exercise the activity's decision + bookkeeping, not the rewrite itself.
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=repartition_mock),
            patch.object(repartition_table, "capture_repartition_event") as capture,
        ):
            # ActivityEnvironment.run is synchronous for a sync activity — call it directly.
            ActivityEnvironment().run(maybe_repartition_table_activity, inputs)
        return capture

    def test_noop_when_flag_disabled(self, team):
        # Healthy no-op: the rollout flag being off short-circuits the gate before any on-disk I/O — no
        # job fetch, no delta read, no detection, no rewrite — regardless of any recorded size. Guards
        # the gate that keeps unflagged syncs free of the extra pre-extraction work.
        schema = _make_schema(team, {"max_partition_bytes": 5})
        mocked = AsyncMock()
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=mocked),
            patch.object(repartition_table, "capture_repartition_event"),
            patch.object(repartition_table, "is_auto_repartition_enabled", return_value=False),
            patch.object(repartition_table, "maybe_flag_for_repartition") as flag,
        ):
            ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))
        mocked.assert_not_called()
        flag.assert_not_called()

    @pytest.mark.parametrize("recorded_max_partition_bytes", [None, 5])
    def test_pre_extraction_flags_over_budget_live_table(self, team, recorded_max_partition_bytes):
        # Nothing queued, flag on: the activity reads the LIVE on-disk size and repartitions when it's
        # over budget. The `recorded_max_partition_bytes=5` case is the fix's core regression: a stale,
        # within-budget recorded value (from a merge that OOMed before it could refresh) must NOT
        # short-circuit detection — the gate now trusts the live size, not the recorded one.
        config: dict = {
            "partitioning_enabled": True,
            "partition_mode": "md5",
            "partition_count": 2,
            "partitioning_keys": ["id"],
        }
        if recorded_max_partition_bytes is not None:
            config["max_partition_bytes"] = recorded_max_partition_bytes
        schema = _make_schema(team, config)
        mocked = AsyncMock(return_value={"outcome": "completed", "row_count": 4, "partition_mode_after": "md5"})
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "0", "1", "1"])
            with (
                patch.object(repartition_table, "HeartbeaterSync"),
                patch.object(repartition_table, "repartition_table_in_place", new=mocked),
                patch.object(repartition_table, "capture_repartition_event") as capture,
                patch.object(repartition_table.DeltaTableHelper, "get_delta_table", new=AsyncMock(return_value=delta)),
                patch.object(ctrl, "target_partition_bytes", return_value=1),
                # The activity evaluates the rollout flag once and threads the verdict into detection,
                # so patch the binding the activity reads from (not the controller's).
                patch.object(repartition_table, "is_auto_repartition_enabled", return_value=True),
                patch.object(ctrl, "capture_repartition_event"),
            ):
                ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))

        mocked.assert_awaited_once()
        emitted = [c.args[0] for c in capture.call_args_list]
        assert "warehouse_repartition_started" in emitted
        assert "warehouse_repartition_completed" in emitted

    def test_success_emits_completed(self, team):
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "test",
                "attempts": 0,
            }
        )
        mocked = AsyncMock(return_value={"outcome": "completed", "row_count": 6, "partition_mode_after": "md5"})
        capture = self._run(self._inputs(team, schema), mocked)
        mocked.assert_awaited_once()
        emitted = [c.args[0] for c in capture.call_args_list]
        assert "warehouse_repartition_started" in emitted
        assert "warehouse_repartition_completed" in emitted

    def test_unpartitionable_clears_pending(self, team):
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {"partition_mode": None, "partition_keys": [], "trigger_reason": "test", "attempts": 0}
        )
        mocked = AsyncMock(side_effect=RepartitionUnpartitionableError("no keys"))
        capture = self._run(self._inputs(team, schema), mocked)
        schema.refresh_from_db()
        assert schema.repartition_pending is None
        assert "warehouse_repartition_skipped" in [c.args[0] for c in capture.call_args_list]

    def test_failure_increments_attempts_without_clearing(self, team):
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "test",
                "attempts": 0,
            }
        )
        mocked = AsyncMock(side_effect=ValueError("boom"))
        capture = self._run(self._inputs(team, schema), mocked)
        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["attempts"] == 1
        assert "warehouse_repartition_failed" in [c.args[0] for c in capture.call_args_list]

    def test_failure_gives_up_after_max_attempts(self, team):
        schema = _make_schema(team, {})
        # One short of the cap — this attempt pushes it over and the pending flag is cleared.
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "test",
                "attempts": ctrl.MAX_REPARTITION_ATTEMPTS - 1,
            }
        )
        self._run(self._inputs(team, schema), AsyncMock(side_effect=ValueError("boom")))
        schema.refresh_from_db()
        assert schema.repartition_pending is None

    # Temporal's own CancelledError subclasses Exception (asyncio's subclasses BaseException), so a
    # worker-shutdown cancel would land in the broad failure handler unless explicitly re-raised.
    @pytest.mark.parametrize("cancel_error", [TemporalCancelledError("cancelled"), asyncio.CancelledError()])
    def test_cancellation_propagates_without_recording_failure(self, team, cancel_error):
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "test",
                "attempts": 0,
            }
        )
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=AsyncMock(side_effect=cancel_error)),
            patch.object(repartition_table, "capture_repartition_event") as capture,
            patch.object(repartition_table, "capture_exception") as capture_exc,
            pytest.raises(type(cancel_error)),
        ):
            ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))
        # Cancellation must reschedule cleanly: no failed attempt recorded, nothing sent to error tracking.
        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["attempts"] == 0
        assert "warehouse_repartition_failed" not in [c.args[0] for c in capture.call_args_list]
        capture_exc.assert_not_called()
