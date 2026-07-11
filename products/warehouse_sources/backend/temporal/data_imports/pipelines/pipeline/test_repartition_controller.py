import uuid
import asyncio
import datetime
import tempfile

import pytest
from unittest.mock import AsyncMock, patch

from django.db import OperationalError

import pyarrow as pa
import deltalake as deltalake
import structlog
from asgiref.sync import async_to_sync
from temporalio.testing import ActivityEnvironment

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.oom_event import ExternalDataSchemaOOMEvent
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

    def test_unpartitioned_over_budget_with_keys_enables_partitioning(self, team):
        # An unpartitioned table that's over budget but HAS a usable key must be flagged to become
        # partitioned (partition_mode=None → auto-detect on the rewrite), not skipped — this is the
        # not-partitioned → partitioned transition.
        schema = _make_schema(team, {"primary_key_columns": ["id"]})
        with tempfile.TemporaryDirectory() as d:
            delta = _write_unpartitioned_delta(f"{d}/u")
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=1),
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
                patch.object(ctrl, "capture_repartition_event"),
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["partition_mode"] is None
        assert schema.repartition_pending["partition_keys"] == ["id"]


class TestRepartitionOOMHistoryTrigger:
    def _detect(self, team, schema: ExternalDataSchema, delta: deltalake.DeltaTable) -> None:
        async_to_sync(ctrl.maybe_flag_for_repartition)(schema, schema.source, _make_job(team, schema), delta, logger)

    @pytest.mark.parametrize("oom_count,expect_flag", [(3, True), (2, False)])
    def test_repeated_ooms_flag_a_within_budget_table(self, team, oom_count, expect_flag):
        # The hybrid trigger's reason for existing: a table whose compressed partition looks within
        # budget but that keeps OOMing (its real working set is bigger — e.g. wide nested JSON) must be
        # repartitioned once it crosses the OOM threshold, and left alone below it.
        schema = _make_schema(
            team,
            {"partitioning_enabled": True, "partition_mode": "md5", "partition_count": 2, "partitioning_keys": ["id"]},
        )
        for _ in range(oom_count):
            ExternalDataSchemaOOMEvent.objects.for_team(schema.team_id).create(team_id=schema.team_id, schema=schema)

        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "1"])
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=10**12),  # well within the size budget
                patch.object(ctrl, "repartition_oom_threshold", return_value=3),
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
                patch.object(ctrl, "capture_repartition_event"),
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        if expect_flag:
            assert schema.repartition_pending is not None
            assert schema.repartition_pending["trigger_reason"] == "oom_history"
        else:
            assert schema.repartition_pending is None


# An Exception-derived cancellation, named exactly `CancelledError`: models how `async_to_sync` can
# surface a worker-shutdown cancel so it slips past a plain BaseException catch. `_is_cancellation`
# keys on the type name, so this must be named `CancelledError`.
class CancelledError(Exception):
    pass


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

    @pytest.mark.parametrize("cancel_exc", [asyncio.CancelledError(), CancelledError()])
    def test_cancellation_propagates_and_is_not_recorded(self, team, cancel_exc):
        # A worker-shutdown cancellation — whether it arrives as a real asyncio.CancelledError or wrapped
        # Exception-derived through async_to_sync — must propagate so Temporal reschedules, and must never
        # be recorded as a failure or consume an attempt. Otherwise every deploy floods error tracking
        # with warehouse_repartition_failed and burns the table's finite attempt budget on non-failures.
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "t",
                "attempts": 0,
            }
        )
        mocked = AsyncMock(side_effect=cancel_exc)
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=mocked),
            patch.object(repartition_table, "capture_repartition_event") as capture,
        ):
            with pytest.raises((asyncio.CancelledError, CancelledError)):
                ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))
        assert "warehouse_repartition_failed" not in [c.args[0] for c in capture.call_args_list]
        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["attempts"] == 0

    def test_transient_db_error_not_recorded_as_failure(self, team):
        # A pooler drop mid-repartition (OperationalError) is infra noise, not a repartition bug: the swap
        # is marker-idempotent and the next sync retries. It must not emit warehouse_repartition_failed or
        # consume an attempt, else transient DB blips spam error tracking and exhaust the attempt budget.
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "t",
                "attempts": 0,
            }
        )
        mocked = AsyncMock(side_effect=OperationalError("server closed the connection unexpectedly"))
        capture = self._run(self._inputs(team, schema), mocked)
        emitted = [c.args[0] for c in capture.call_args_list]
        assert "warehouse_repartition_started" in emitted
        assert "warehouse_repartition_failed" not in emitted
        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["attempts"] == 0

    @pytest.mark.parametrize(
        "rewrite_error,forbidden_event",
        [
            (ValueError("boom"), "warehouse_repartition_failed"),
            (RepartitionUnpartitionableError("no keys"), "warehouse_repartition_skipped"),
        ],
    )
    def test_transient_db_error_in_failure_handler_not_recorded(self, team, rewrite_error, forbidden_event):
        # The rewrite fails (a real failure, or an unpartitionable table), and then the pooler drops the
        # connection while we re-read the schema to record the outcome. That refresh raising
        # OperationalError is transient infra noise, not a repartition bug: it must be swallowed, never
        # escape to fail the activity, and never record an outcome or consume an attempt. Guards the
        # failure-handler refresh_from_db that used to be unguarded — an escaped OperationalError there
        # broke the module's "a repartition failure never fails the workflow" invariant.
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "t",
                "attempts": 0,
            }
        )
        mocked = AsyncMock(side_effect=rewrite_error)
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=mocked),
            patch.object(repartition_table, "capture_repartition_event") as capture,
            patch.object(
                ExternalDataSchema,
                "refresh_from_db",
                side_effect=OperationalError("server closed the connection unexpectedly"),
            ),
        ):
            # Must not raise — the transient drop is swallowed, not propagated up to fail the activity.
            ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))
        emitted = [c.args[0] for c in capture.call_args_list]
        assert "warehouse_repartition_started" in emitted
        assert forbidden_event not in emitted
        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["attempts"] == 0
