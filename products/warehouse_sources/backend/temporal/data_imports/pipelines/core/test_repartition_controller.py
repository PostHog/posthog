import json
import uuid
import asyncio
import datetime
import tempfile
import contextlib
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import OperationalError
from django.test import override_settings
from django.utils import timezone

import pyarrow as pa
import deltalake as deltalake
import structlog
from asgiref.sync import async_to_sync
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.models.team import Team

from products.warehouse_sources.backend.models import external_data_schema
from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import (
    ExternalDataSchema,
    save_repartition_checkpoint_if_claimed,
    save_repartition_swap_phase_if_claimed,
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.oom_event import ExternalDataSchemaOOMEvent
from products.warehouse_sources.backend.temporal.data_imports import schema_flags, workload_report
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core import repartition_controller as ctrl
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition import (
    RepartitionAttemptsExhausted,
    RepartitionSupersededError,
    RepartitionTooLargeForBudgetError,
    RepartitionUnpartitionableError,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition_controller import (
    MAX_REPARTITION_ATTEMPTS,
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


_NOMINATION = {"requested_at": "2026-08-03T00:00:00+00:00", "requested_by": "danielc"}


def _days_ago_iso(days: float) -> str:
    return (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days)).isoformat()


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

    def test_transient_db_error_during_measurement_save_is_not_captured(self, team):
        # A pgbouncer pooler drop (or its server_login_retry cooldown outliving the single retry in
        # retry_on_db_connection_drop) must not mint an error-tracking issue for a condition nobody
        # can act on — only a genuine detection bug should reach capture_exception.
        schema = _make_schema(
            team,
            {"partitioning_enabled": True, "partition_mode": "md5", "partition_count": 2, "partitioning_keys": ["id"]},
        )
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "0", "1", "1"])
            with (
                patch.object(
                    ExternalDataSchema,
                    "record_partition_measurement",
                    side_effect=OperationalError(
                        "server login has been failing, cached error: server conn crashed? (server_login_retry)"
                    ),
                ),
                patch.object(ctrl, "capture_exception") as mock_capture_exception,
            ):
                self._detect(team, schema, delta)

        mock_capture_exception.assert_not_called()

    def test_unpartitioned_table_flags_auto_target_scheme(self, team):
        # An unpartitioned table's target legitimately has mode None (auto-detect at rewrite time),
        # but the flagged event must report "auto" — a null here NULL-poisons dashboard strings —
        # while the pending target must keep mode None so the rewrite still auto-detects.
        schema = _make_schema(team, {"primary_key_columns": ["id"]})
        with tempfile.TemporaryDirectory() as d:
            delta = _write_unpartitioned_delta(f"{d}/t")
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=1),
                patch.object(ctrl, "capture_repartition_event") as capture,
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        pending = schema.repartition_pending
        assert pending is not None
        assert pending["partition_mode"] is None
        assert capture.call_args.args[0] == "warehouse_repartition_flagged"
        assert capture.call_args.args[1]["partition_mode_after"] == "auto"

    def test_within_budget_records_size_but_does_not_flag(self, team):
        schema = _make_schema(team, {"partitioning_enabled": True, "partition_mode": "md5", "partition_count": 2})
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "1"])
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=10**12),
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
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.repartition_pending is None

    @pytest.mark.parametrize(
        "sync_type_config,expected_reason,alerts",
        [
            ({}, "unpartitionable_no_keys", False),
            (
                {
                    "partitioning_enabled": True,
                    "partition_mode": "datetime",
                    "partition_format": "hour",
                    "partitioning_keys": ["ts"],
                },
                "datetime_at_finest_tier",
                False,
            ),
            (
                {"partitioning_enabled": True, "partition_mode": "numerical", "partitioning_keys": ["id"]},
                "numerical_no_size",
                True,
            ),
        ],
    )
    def test_over_budget_without_target_skips_and_alerts_only_when_unexpected(
        self, team, sync_type_config, expected_reason, alerts
    ):
        # A table with no usable key, and one already at the finest datetime tier, are facts about the
        # customer's data that nobody can act on, so they must stay out of error tracking while still
        # being counted on the skip event. A numerical schema with no partition_size is our own row
        # contradicting itself, so that one must still alert.
        schema = _make_schema(team, sync_type_config)
        with tempfile.TemporaryDirectory() as d:
            delta = _write_unpartitioned_delta(f"{d}/u")
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=1),
                patch.object(ctrl, "capture_repartition_event") as capture,
                patch.object(ctrl, "capture_exception") as mock_capture_exception,
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.repartition_pending is None
        assert capture.call_args.args[0] == "warehouse_repartition_skipped"
        assert capture.call_args.args[1]["reason"] == expected_reason
        assert mock_capture_exception.call_count == (1 if alerts else 0)
        # A table with no usable partition target must engage the cooldown, otherwise detection
        # re-measures and re-emits the skip on every 5-minute sync forever (the loop we're fixing).
        assert schema.last_repartition_at is not None

    def test_unpartitionable_skip_does_not_reflag_next_sync(self, team):
        # Regression: the terminal skip stamps the cooldown so the immediately-following sync is a
        # no-op instead of re-emitting flagged/skipped — this is the every-5-minute loop guard.
        schema = _make_schema(team, {})
        with tempfile.TemporaryDirectory() as d:
            delta = _write_unpartitioned_delta(f"{d}/u")
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=1),
                patch.object(ctrl, "capture_repartition_event") as capture,
            ):
                self._detect(team, schema, delta)
                first_pass_events = [c.args[0] for c in capture.call_args_list]
                capture.reset_mock()
                schema.refresh_from_db()
                self._detect(team, schema, delta)
                second_pass_events = [c.args[0] for c in capture.call_args_list]

        assert "warehouse_repartition_skipped" in first_pass_events
        assert second_pass_events == []

    def test_unpartitioned_over_budget_with_keys_enables_partitioning(self, team):
        # An unpartitioned table that's over budget but HAS a usable key must be flagged to become
        # partitioned (partition_mode=None → auto-detect on the rewrite), not skipped — this is the
        # not-partitioned → partitioned transition.
        schema = _make_schema(team, {"primary_key_columns": ["id"]})
        with tempfile.TemporaryDirectory() as d:
            delta = _write_unpartitioned_delta(f"{d}/u")
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=1),
                patch.object(ctrl, "capture_repartition_event"),
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["partition_mode"] is None
        assert schema.repartition_pending["partition_keys"] == ["id"]

    @pytest.mark.parametrize("trigger", ["over_budget", "oom_history"])
    def test_an_append_table_is_never_split(self, team, trigger):
        schema = _make_schema(
            team,
            {
                "partitioning_enabled": True,
                "partition_mode": "datetime",
                "partition_format": "day",
                "partitioning_keys": ["ts"],
            },
        )
        schema.sync_type = ExternalDataSchema.SyncType.APPEND
        schema.save()
        if trigger == "oom_history":
            for _ in range(3):
                ExternalDataSchemaOOMEvent.objects.for_team(schema.team_id).create(
                    team_id=schema.team_id, schema=schema
                )

        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["2026-10-01", "2026-10-01", "2026-10-02"])
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=1 if trigger == "over_budget" else 10**12),
                patch.object(ctrl, "repartition_oom_threshold", return_value=3),
                patch.object(ctrl, "min_splittable_partition_bytes", return_value=1),
                patch.object(ctrl, "capture_repartition_event") as capture,
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.repartition_pending is None
        assert schema.last_repartition_at is None
        assert capture.call_count == 0

    @pytest.mark.parametrize(
        "sync_type, base_budget, merge_budget, recent_ooms, expected_trigger",
        [
            (ExternalDataSchema.SyncType.INCREMENTAL, 1, 10**12, 0, None),
            (ExternalDataSchema.SyncType.WEBHOOK, 1, 10**12, 0, None),
            (ExternalDataSchema.SyncType.XMIN, 1, 10**12, 0, None),
            (ExternalDataSchema.SyncType.INCREMENTAL, 1, 2, 0, "proactive_threshold"),
            (ExternalDataSchema.SyncType.INCREMENTAL, 1, 0, 0, "proactive_threshold"),
            (ExternalDataSchema.SyncType.INCREMENTAL, 1, 10**12, 3, "oom_history"),
            (ExternalDataSchema.SyncType.FULL_REFRESH, 1, 10**12, 0, "proactive_threshold"),
            (None, 1, 10**12, 0, "proactive_threshold"),
        ],
        ids=[
            "incremental_over_base_budget_is_not_split",
            "webhook_over_base_budget_is_not_split",
            "xmin_over_base_budget_is_not_split",
            "merge_table_over_its_fallback_cap_still_splits",
            "merge_cap_below_base_budget_falls_back_to_base",
            "merge_table_with_repeated_ooms_still_splits",
            "full_refresh_keeps_the_base_budget",
            "unknown_sync_type_keeps_the_base_budget",
        ],
    )
    def test_keyed_merge_tables_split_on_size_only_past_the_merge_budget(
        self,
        team,
        sync_type: str | None,
        base_budget: int,
        merge_budget: int,
        recent_ooms: int,
        expected_trigger: str | None,
    ):
        schema = _make_schema(
            team,
            {"partitioning_enabled": True, "partition_mode": "md5", "partition_count": 2, "partitioning_keys": ["id"]},
        )
        schema.sync_type = sync_type
        schema.save()
        for _ in range(recent_ooms):
            ExternalDataSchemaOOMEvent.objects.for_team(schema.team_id).create(team_id=schema.team_id, schema=schema)

        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "0", "1", "1"])
            with (
                override_settings(
                    DATA_WAREHOUSE_TARGET_PARTITION_BYTES=base_budget,
                    DATA_WAREHOUSE_MERGE_TARGET_PARTITION_BYTES=merge_budget,
                ),
                patch.object(ctrl, "repartition_oom_threshold", return_value=3),
                patch.object(ctrl, "min_splittable_partition_bytes", return_value=1),
                patch.object(ctrl, "capture_repartition_event"),
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        pending = schema.repartition_pending
        if expected_trigger is None:
            assert pending is None
            assert schema.partition_measurement is not None
            assert schema.partition_measurement["healthy"] is True
        else:
            assert pending is not None
            assert pending["trigger_reason"] == expected_trigger
            assert pending["partition_mode"] == "md5"
            assert pending["partition_count"] > 2


class TestPartitionMeasurementRecord:
    @pytest.mark.parametrize(
        "budget, phase, healthy",
        [(10**12, "post_load", True), (10**12, "pre_extraction", True), (1, "post_load", False)],
        ids=["within_budget_after_load", "within_budget_before_extraction", "over_budget"],
    )
    def test_detection_records_who_measured_and_the_verdict(
        self, team, budget: int, phase: ctrl.MeasurementPhase, healthy: bool
    ):
        schema = _make_schema(
            team,
            {"partitioning_enabled": True, "partition_mode": "md5", "partition_count": 2, "partitioning_keys": ["id"]},
        )
        job = _make_job(team, schema)
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "0", "1", "1"])
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=budget),
                patch.object(ctrl, "capture_repartition_event"),
            ):
                async_to_sync(ctrl.maybe_flag_for_repartition)(schema, schema.source, job, delta, logger, phase=phase)

        schema.refresh_from_db()
        assert schema.partition_measurement == {
            "job_id": str(job.id),
            "phase": phase,
            "budget": budget,
            "split_budget": budget,
            "coarsen_budget": budget,
            "healthy": healthy,
        }

    def test_reset_invalidates_the_measurement(self, team):
        schema = _make_schema(
            team,
            {
                "partition_measurement": {
                    "job_id": "previous-job",
                    "phase": "post_load",
                    "budget": 500,
                    "healthy": True,
                }
            },
        )

        schema.update_sync_type_config_for_reset_pipeline()

        assert schema.partition_measurement is None

    def test_a_table_that_coarsening_can_pick_up_is_measured_on_each_run(self, team):
        schema = _make_schema(
            team,
            {"partitioning_enabled": True, "partition_mode": "md5", "partition_count": 32, "partitioning_keys": ["id"]},
        )
        job = _make_job(team, schema)
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", [str(bucket) for bucket in range(ctrl.COARSEN_MIN_PARTITIONS)])
            with patch.object(ctrl, "capture_repartition_event"):
                async_to_sync(ctrl.maybe_flag_for_repartition)(
                    schema, schema.source, job, delta, logger, phase="post_load"
                )

        schema.refresh_from_db()
        measurement = schema.partition_measurement
        assert measurement is not None and measurement["healthy"] is False

    @pytest.mark.parametrize(
        "previous_status, nominated, sync_type, measured_budget, measured_split_budget, recent_ooms, auto_coarsen, "
        "measured_coarsen_budget, redundant",
        [
            (ExternalDataJob.Status.COMPLETED, False, None, 500, 500, 0, False, None, True),
            (ExternalDataJob.Status.FAILED, False, None, 500, 500, 0, False, None, False),
            (ExternalDataJob.Status.COMPLETED, True, None, 500, 500, 0, False, None, False),
            (ExternalDataJob.Status.COMPLETED, False, None, 400, 500, 0, False, None, False),
            (ExternalDataJob.Status.COMPLETED, False, None, 500, 500, 3, False, None, False),
            (
                ExternalDataJob.Status.COMPLETED,
                False,
                ExternalDataSchema.SyncType.INCREMENTAL,
                500,
                2000,
                0,
                False,
                None,
                True,
            ),
            (
                ExternalDataJob.Status.COMPLETED,
                False,
                ExternalDataSchema.SyncType.INCREMENTAL,
                500,
                3000,
                0,
                False,
                None,
                False,
            ),
            (ExternalDataJob.Status.COMPLETED, False, None, 500, None, 0, False, None, False),
            (
                ExternalDataJob.Status.COMPLETED,
                False,
                ExternalDataSchema.SyncType.INCREMENTAL,
                500,
                2000,
                0,
                True,
                None,
                False,
            ),
            (
                ExternalDataJob.Status.COMPLETED,
                False,
                ExternalDataSchema.SyncType.INCREMENTAL,
                500,
                2000,
                0,
                True,
                2000,
                True,
            ),
        ],
        ids=[
            "previous_run_completed",
            "previous_run_failed",
            "operator_nomination_waits",
            "budget_changed_since_the_measurement",
            "repeated_oom_kills_since_the_measurement",
            "merge_table_measured_against_its_split_budget",
            "split_budget_changed_since_the_measurement",
            "measurement_without_a_split_budget",
            "auto_coarsen_flag_turned_on_since_the_measurement",
            "merge_table_measured_against_its_coarsen_budget",
        ],
    )
    def test_gate_reads_what_can_change_without_a_write(
        self,
        team,
        previous_status: str,
        nominated: bool,
        sync_type: str | None,
        measured_budget: int,
        measured_split_budget: int | None,
        recent_ooms: int,
        auto_coarsen: bool,
        measured_coarsen_budget: int | None,
        redundant: bool,
    ):
        schema = _make_schema(team, {})
        schema.sync_type = sync_type
        other_schema = ExternalDataSchema.objects.create(
            name="other", team=team, source=schema.source, sync_type_config={}
        )
        now = datetime.datetime.now(datetime.UTC)
        previous = _make_job(team, schema)
        ExternalDataJob.objects.filter(id=previous.id).update(
            status=previous_status, rows_synced=10, created_at=now - datetime.timedelta(minutes=10)
        )
        # A failed job of another schema of the same source must not break this schema's chain.
        ExternalDataJob.objects.filter(id=_make_job(team, other_schema).id).update(
            status=ExternalDataJob.Status.FAILED, created_at=now - datetime.timedelta(minutes=5)
        )
        current = _make_job(team, schema)
        ExternalDataJob.objects.filter(id=current.id).update(created_at=now)
        current.refresh_from_db()
        schema.sync_type_config = {
            "partition_measurement": {
                "job_id": str(previous.id),
                "phase": "post_load",
                "budget": measured_budget,
                "split_budget": measured_split_budget,
                **({"coarsen_budget": measured_coarsen_budget} if measured_coarsen_budget else {}),
                "healthy": True,
            },
            "partition_mode": "md5",
            "partition_count": ctrl.COARSEN_MIN_PARTITIONS,
            **({"coarsen_requested": _NOMINATION} if nominated else {}),
        }

        with (
            override_settings(
                DATA_WAREHOUSE_TARGET_PARTITION_BYTES=500,
                DATA_WAREHOUSE_MERGE_TARGET_PARTITION_BYTES=2000,
            ),
            patch.object(ctrl, "is_schema_flag_enabled", return_value=auto_coarsen),
            patch.object(ctrl.ExternalDataSchemaOOMEvent, "recent_count", return_value=recent_ooms),
        ):
            assert ctrl.pre_extraction_measurement_is_redundant(schema, current) is redundant


class TestIsRepartitionHoldEnabled:
    def test_retries_once_on_transient_db_connection_drop(self, team):
        # The Team lookup runs on a long-lived Temporal worker thread; a pooler-dropped connection
        # raises OperationalError on first use. Without a retry this propagates out of
        # is_repartition_hold_enabled uncaught (it's outside the function's Team.DoesNotExist/
        # feature_enabled try blocks) instead of resolving the flag.
        schema = _make_schema(team, {})
        mock_queryset = MagicMock()
        mock_queryset.get.side_effect = [OperationalError("server closed the connection unexpectedly"), team]

        with (
            patch("posthog.models.Team.objects.only", return_value=mock_queryset),
            patch.object(ctrl.posthoganalytics, "feature_enabled", return_value=True),
        ):
            assert ctrl.is_repartition_hold_enabled(schema) is True

        assert mock_queryset.get.call_count == 2

    def test_returns_false_when_db_connection_stays_down(self, team):
        # If the connection is still down on the retry, the flag helper must not raise — an uncaught
        # OperationalError here crashes the whole activity instead of just leaving the flag resolved
        # as disabled.
        schema = _make_schema(team, {})
        mock_queryset = MagicMock()
        mock_queryset.get.side_effect = OperationalError("server closed the connection unexpectedly")

        with (
            patch("posthog.models.Team.objects.only", return_value=mock_queryset),
            patch.object(schema_flags, "capture_exception") as mock_capture_exception,
        ):
            assert ctrl.is_repartition_hold_enabled(schema) is False

        assert mock_queryset.get.call_count == 2
        mock_capture_exception.assert_called_once()


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
                patch.object(ctrl, "target_partition_bytes", return_value=10_000),
                patch.object(ctrl, "repartition_oom_threshold", return_value=3),
                # The split floor is exercised by its own test below; neutralize it here so this one
                # fails only if the OOM trigger itself stops working.
                patch.object(ctrl, "min_splittable_partition_bytes", return_value=1),
                patch.object(ctrl, "capture_repartition_event"),
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        if expect_flag:
            assert schema.repartition_pending is not None
            assert schema.repartition_pending["trigger_reason"] == "oom_history"
        else:
            assert schema.repartition_pending is None

    def test_pending_revive_skips_detection(self, team):
        # A table pending a corruption revive must not be flagged for repartition — the extract activity
        # heals it, and flagging here would re-arm the revive the moment the heal clears the marker.
        schema = _make_schema(
            team,
            {
                "partitioning_enabled": True,
                "partition_mode": "md5",
                "partition_count": 2,
                "partitioning_keys": ["id"],
                "delta_revive_required": {
                    "reason": "repartition_scan_missing_data_file",
                    "missing_path": "x/p.parquet",
                },
            },
        )
        for _ in range(3):  # enough OOMs to flag a within-budget table if the revive guard weren't there
            ExternalDataSchemaOOMEvent.objects.for_team(schema.team_id).create(team_id=schema.team_id, schema=schema)

        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "1"])
            with (
                # Small enough that the tiny-partition guard doesn't mask the revive guard under test.
                patch.object(ctrl, "target_partition_bytes", return_value=10_000),
                patch.object(ctrl, "repartition_oom_threshold", return_value=3),
                patch.object(ctrl, "capture_repartition_event"),
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.repartition_pending is None

    def test_tiny_partitions_do_not_flag_on_oom_history(self, team):
        # The loop this guard exists for: timeouts recorded as OOMs on a table whose largest partition
        # is KBs against a 500 MB budget. Splitting it would produce partitions far under the size the
        # coarsening path treats as over-fragmented, so partitioning cannot be the cause. Without the
        # floor the trigger steps the scheme finer until it bottoms out at hour, then emits skipped
        # plus capture_exception daily forever. The guard must be a quiet no-op: nothing pending, no
        # events at all.
        schema = _make_schema(
            team,
            {"partitioning_enabled": True, "partition_mode": "md5", "partition_count": 2, "partitioning_keys": ["id"]},
        )
        for _ in range(3):
            ExternalDataSchemaOOMEvent.objects.for_team(schema.team_id).create(team_id=schema.team_id, schema=schema)

        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", ["0", "1"])
            with (
                patch.object(
                    ctrl, "target_partition_bytes", return_value=10**12
                ),  # partitions orders of magnitude under
                patch.object(ctrl, "repartition_oom_threshold", return_value=3),
                patch.object(ctrl, "capture_repartition_event") as capture,
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.repartition_pending is None
        assert schema.max_partition_bytes is not None  # observability measurement still recorded
        assert capture.call_args_list == []


class TestCoarsenTrigger:
    def _detect(self, team, schema: ExternalDataSchema, delta: deltalake.DeltaTable) -> None:
        async_to_sync(ctrl.maybe_flag_for_repartition)(schema, schema.source, _make_job(team, schema), delta, logger)

    def _fragmented_schema(self, team, **overrides) -> ExternalDataSchema:
        return _make_schema(
            team,
            {
                "partitioning_enabled": True,
                "partition_mode": "md5",
                "partition_count": 16,
                "partitioning_keys": ["id"],
                "last_repartition_at": _days_ago_iso(30),
                **overrides,
            },
        )

    def _detect_over_fragmented(
        self, team, schema: ExternalDataSchema, *, buckets: list[str] | None = None
    ) -> MagicMock:
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", buckets or [str(bucket) for bucket in range(16)])
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=10**12),
                patch.object(ctrl, "capture_repartition_event") as capture,
            ):
                self._detect(team, schema, delta)
        schema.refresh_from_db()
        return capture

    def _record_oom(self, schema: ExternalDataSchema, *, days_ago: float = 0, **evidence) -> None:
        event = ExternalDataSchemaOOMEvent.objects.for_team(schema.team_id).create(
            team_id=schema.team_id, schema=schema, run_id="run-1", **evidence
        )
        if days_ago:
            ExternalDataSchemaOOMEvent.objects.for_team(schema.team_id).filter(pk=event.pk).update(
                created_at=timezone.now() - datetime.timedelta(days=days_ago)
            )

    def _record_fleet_wide_burst(self, team) -> None:
        for _ in range(3):
            other_team = Team.objects.create(organization=team.organization)
            self._record_oom(_make_schema(other_team, {}))

    def test_flags_an_over_fragmented_table_for_coarsening(self, team):
        # The reverse direction: a table split far below what memory safety needs pays for every one of
        # those pieces on each merge. Most tables in this state were put there by the finer path
        # reacting to failures that were never about size, and nothing else brings them back.
        schema = self._fragmented_schema(team)

        capture = self._detect_over_fragmented(team, schema)

        pending = schema.repartition_pending
        assert pending is not None
        assert pending["trigger_reason"] == "coarsening"
        assert pending["partition_mode"] == "md5"
        assert pending["partition_count"] < 16
        assert capture.call_args.args[0] == "warehouse_repartition_flagged"

    @pytest.mark.parametrize(
        "case",
        [
            # The cheap short-circuit on the split trigger's own count, ahead of the 14-day gate.
            "recent_oom",
            # A layout that was just rewritten hasn't had a chance to prove itself; undoing it within
            # the day is how the two directions would start handing the table back and forth.
            "fresh_layout",
        ],
    )
    def test_does_not_coarsen_when_a_guard_applies(self, team, case):
        schema = self._fragmented_schema(
            team, **({"last_repartition_at": _days_ago_iso(0)} if case == "fresh_layout" else {})
        )
        if case == "recent_oom":
            self._record_oom(schema)

        self._detect_over_fragmented(team, schema)

        assert schema.repartition_pending is None

    @override_settings(DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_SCHEMAS=3, DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_TEAMS=3)
    def test_a_death_the_rules_blame_on_infrastructure_does_not_block_coarsening(self, team):
        # A nightly restart takes out hundreds of unrelated schemas at once, which says nothing about
        # any one table's merge memory. Blocking on it froze the whole over-split backlog.
        schema = self._fragmented_schema(team)
        self._record_oom(schema, self_phase="merge", self_report_age_at_death_seconds=1.0, self_peak_buffer_bytes=1024)
        self._record_fleet_wide_burst(team)

        self._detect_over_fragmented(team, schema)

        assert schema.repartition_pending is not None
        assert schema.repartition_pending["trigger_reason"] == "coarsening"

    def test_an_oom_that_predates_the_last_rewrite_still_blocks_coarsening(self, team):
        # `recent_count` floors its window at `last_repartition_at`, which would hide this death.
        # Coarsening undoes that rewrite, so the OOM that justified it is the evidence that matters.
        schema = self._fragmented_schema(team, last_repartition_at=_days_ago_iso(8))
        self._record_oom(schema, days_ago=10)

        self._detect_over_fragmented(team, schema)

        assert schema.repartition_pending is None

    @override_settings(DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_SCHEMAS=3, DATA_WAREHOUSE_OOM_INFRA_BURST_MIN_TEAMS=3)
    @pytest.mark.parametrize(
        "phase,days_ago,blocks",
        [
            # A burst window is where a self-inflicted merge death hides, so the backstop looks past
            # the infrastructure verdict at the peak the merge itself reported.
            ("merge", 0, True),
            # Scoped to merges: an extract holding 200 MB says nothing about the merge working set.
            ("extract", 0, False),
            # Scoped to the window too, or one big merge death would freeze the layout forever.
            ("merge", 20, False),
        ],
    )
    def test_the_backstop_blocks_only_big_recent_merge_deaths(self, team, phase, days_ago, blocks):
        schema = self._fragmented_schema(team)
        self._record_oom(
            schema,
            days_ago=days_ago,
            self_phase=phase,
            self_report_age_at_death_seconds=1.0,
            self_peak_buffer_bytes=200 * 1024 * 1024,
        )
        self._record_fleet_wide_burst(team)

        self._detect_over_fragmented(team, schema)

        assert (schema.repartition_pending is None) is blocks

    @pytest.mark.parametrize(
        "case,expected_reason",
        [
            ("unexplained_oom", "oom_within_free_window"),
            ("fresh_layout", "layout_too_young"),
        ],
    )
    def test_declining_to_coarsen_records_which_gate_stopped_it(self, team, case, expected_reason):
        schema = self._fragmented_schema(
            team, **({"last_repartition_at": _days_ago_iso(0)} if case == "fresh_layout" else {})
        )
        if case == "unexplained_oom":
            # Past the split trigger's 7-day window, so its cheap short-circuit passes and the 14-day
            # coarsening gate is what stops it. Only a death in that gap reaches the longer window.
            self._record_oom(schema, days_ago=10)

        with patch.object(ctrl, "DELTA_COARSEN_DECLINE_TOTAL") as decline_metric:
            self._detect_over_fragmented(team, schema)

        assert decline_metric.labels.call_args.kwargs == {"reason": expected_reason}

    def test_operator_nomination_overrides_the_policy_gates(self, team):
        # The backlog of already-over-split tables is blocked by the OOM-free gate, because the signal
        # that over-split them keeps firing. A nomination is how an operator gets past that, so it has
        # to work with OOM history present and a layout younger than the age gate.
        schema = self._fragmented_schema(team, last_repartition_at=_days_ago_iso(0), coarsen_requested=_NOMINATION)
        self._record_oom(schema)

        self._detect_over_fragmented(team, schema)

        pending = schema.repartition_pending
        assert pending is not None
        assert pending["trigger_reason"] == "coarsening_requested"
        # Consumed either way, so a table the selector keeps refusing isn't re-measured every sync.
        assert schema.coarsen_requested is None

    def test_nomination_survives_a_failed_staging_write(self, team):
        # The clear and the pending write are separate commits. If the marker were consumed first, a
        # crash or DB failure between the two would silently drop the operator's nomination with
        # nothing left to restore it, so the marker must still be there after a failed staging.
        schema = self._fragmented_schema(team, coarsen_requested=_NOMINATION)

        with patch.object(ExternalDataSchema, "set_repartition_pending", side_effect=RuntimeError("pooler dropped")):
            self._detect_over_fragmented(team, schema)

        assert schema.repartition_pending is None
        assert schema.coarsen_requested is not None, "a failed staging must not consume the nomination"

    def test_operator_nomination_does_not_override_the_selector(self, team):
        # The one thing a nomination must never do. This table carries the unknown-date sentinel among
        # its hour keys, so the merged layout can't be derived and coarsening it would be a guess about
        # where those bytes land. An operator asking nicely does not make the guess safe.
        schema = self._fragmented_schema(
            team,
            partition_mode="datetime",
            partition_format="hour",
            partitioning_keys=["created_at"],
            coarsen_requested=_NOMINATION,
        )
        buckets = [f"2024-01-01T{hour:02d}" for hour in range(15)] + ["1970-01"]

        self._detect_over_fragmented(team, schema, buckets=buckets)

        assert schema.repartition_pending is None
        assert schema.coarsen_requested is None


_KEYED = ExternalDataSchema.SyncType.INCREMENTAL
_FULL_REFRESH = ExternalDataSchema.SyncType.FULL_REFRESH


class TestMergeCoarsenPolicy:
    # Budgets in bytes, small enough to state partition sizes directly: the merge policy caps a coarse
    # partition at 1500 (0.75 of the merge budget), and its automatic trigger fires at 250 or less.
    _BUDGETS = {"DATA_WAREHOUSE_TARGET_PARTITION_BYTES": 500, "DATA_WAREHOUSE_MERGE_TARGET_PARTITION_BYTES": 2000}

    def _schema(
        self, team, sync_type: str, *, partition_count: int, nominated: bool, **overrides
    ) -> ExternalDataSchema:
        schema = _make_schema(
            team,
            {
                "partitioning_enabled": True,
                "partition_mode": "md5",
                "partition_count": partition_count,
                "partitioning_keys": ["id"],
                "last_repartition_at": _days_ago_iso(30),
                **({"coarsen_requested": _NOMINATION} if nominated else {}),
                **overrides,
            },
        )
        schema.sync_type = sync_type
        schema.save()
        return schema

    def _detect(
        self,
        team,
        schema: ExternalDataSchema,
        partition_bytes: dict[str | None, int],
        *,
        flag_enabled: bool = False,
        **settings,
    ) -> MagicMock:
        with (
            override_settings(**{**self._BUDGETS, **settings}),
            patch.object(ctrl, "is_schema_flag_enabled", return_value=flag_enabled) as flag_check,
            patch.object(ctrl, "measure_partition_bytes", return_value=partition_bytes),
            patch.object(ctrl, "capture_repartition_event"),
        ):
            async_to_sync(ctrl.maybe_flag_for_repartition)(
                schema, schema.source, _make_job(team, schema), MagicMock(), logger
            )
        schema.refresh_from_db()
        return flag_check

    @staticmethod
    def _md5_layout(count: int, each: int) -> dict[str | None, int]:
        return {str(bucket): each for bucket in range(count)}

    @pytest.mark.parametrize(
        "sync_type, count, each, settings, expected_count, expected_reason",
        [
            (_KEYED, 85, 60, {}, 5, None),
            (ExternalDataSchema.SyncType.WEBHOOK, 85, 60, {}, 5, None),
            (ExternalDataSchema.SyncType.XMIN, 85, 60, {}, 5, None),
            (_KEYED, 64, 20, {}, 8, None),
            (_KEYED, 85, 100, {}, 17, None),
            (_KEYED, 85, 480, {}, None, "no_coarser_layout_fits"),
            (_KEYED, 16, 10, {}, 4, None),
            (_KEYED, 6, 10, {}, None, "md5_at_partition_floor"),
            (_KEYED, 64, 20, {"DATA_WAREHOUSE_MERGE_MD5_PARTITION_MIN": 16}, 16, None),
            (_FULL_REFRESH, 85, 60, {}, None, "no_coarser_layout_fits"),
            (_FULL_REFRESH, 16, 10, {}, 1, None),
        ],
        ids=[
            "incremental_picks_the_divisor_nearest_the_target",
            "webhook_uses_the_merge_policy",
            "xmin_uses_the_merge_policy",
            "an_exact_divisor_hits_the_target",
            "a_divisor_over_the_headroom_is_skipped_for_a_finer_one",
            "refuses_when_no_divisor_fits_under_the_merge_budget",
            "stops_at_the_floor_where_the_base_policy_goes_to_one",
            "a_table_at_the_floor_has_no_coarser_layout",
            "the_floor_setting_wins_over_the_target",
            "full_refresh_keeps_the_base_budget",
            "full_refresh_still_goes_to_the_coarsest_fit",
        ],
    )
    def test_a_nomination_sizes_keyed_md5_tables_by_merge_parallelism(
        self,
        team,
        sync_type: str,
        count: int,
        each: int,
        settings: dict[str, Any],
        expected_count: int | None,
        expected_reason: str | None,
    ):
        schema = self._schema(
            team, sync_type, partition_count=count, nominated=True, last_repartition_at=_days_ago_iso(0)
        )

        with patch.object(ctrl, "DELTA_COARSEN_DECLINE_TOTAL") as decline_metric:
            self._detect(team, schema, self._md5_layout(count, each), **settings)

        assert schema.coarsen_requested is None
        pending = schema.repartition_pending
        if expected_count is None:
            assert pending is None
            assert decline_metric.labels.call_args.kwargs == {"reason": expected_reason}
        else:
            assert pending is not None
            assert pending["trigger_reason"] == "coarsening_requested"
            assert pending["partition_mode"] == "md5"
            assert pending["partition_count"] == expected_count

    @pytest.mark.parametrize(
        "sync_type, flag_state, each, expected_count",
        [
            (_KEYED, "off", 100, None),
            (_KEYED, "on", 100, 17),
            (_KEYED, "errors", 100, None),
            (_KEYED, "off", 20, 17),
            (_KEYED, "errors", 20, 17),
            (_KEYED, "on", 20, 5),
            (_FULL_REFRESH, "on", 100, None),
        ],
        ids=[
            "off_leaves_a_table_only_the_merge_budget_can_coarsen",
            "on_coarsens_against_the_merge_budget",
            "an_erroring_flag_counts_as_off",
            "off_keeps_the_base_policy",
            "an_erroring_flag_keeps_the_base_policy",
            "on_stops_near_the_target",
            "on_does_not_reach_full_refresh_tables",
        ],
    )
    def test_automatic_merge_coarsening_is_behind_a_flag(
        self, team, sync_type: str, flag_state: str, each: int, expected_count: int | None
    ):
        schema = self._schema(team, sync_type, partition_count=85, nominated=False)
        layout = self._md5_layout(85, each)

        if flag_state == "errors":
            with (
                patch.object(schema_flags.posthoganalytics, "feature_enabled", side_effect=RuntimeError("flags down")),
                patch.object(schema_flags, "capture_exception"),
                override_settings(**self._BUDGETS),
                patch.object(ctrl, "measure_partition_bytes", return_value=layout),
                patch.object(ctrl, "capture_repartition_event"),
            ):
                async_to_sync(ctrl.maybe_flag_for_repartition)(
                    schema, schema.source, _make_job(team, schema), MagicMock(), logger
                )
            schema.refresh_from_db()
        else:
            self._detect(team, schema, layout, flag_enabled=flag_state == "on")

        pending = schema.repartition_pending
        if expected_count is None:
            assert pending is None
        else:
            assert pending is not None
            assert pending["trigger_reason"] == "coarsening"
            assert pending["partition_count"] == expected_count

    @pytest.mark.parametrize(
        "sync_type, nominated, count, expected_calls",
        [
            (_KEYED, False, 85, 1),
            (_KEYED, True, 85, 0),
            (_FULL_REFRESH, False, 85, 0),
            (_KEYED, False, 8, 0),
        ],
        ids=[
            "a_keyed_md5_table_evaluates_the_flag_once",
            "a_nomination_skips_the_flag",
            "a_table_the_policy_cannot_reach_skips_the_flag",
            "a_table_too_fine_to_coarsen_skips_the_flag",
        ],
    )
    def test_the_flag_is_evaluated_only_when_it_can_change_the_policy(
        self, team, sync_type: str, nominated: bool, count: int, expected_calls: int
    ):
        schema = self._schema(team, sync_type, partition_count=count, nominated=nominated)

        flag_check = self._detect(team, schema, self._md5_layout(count, 20))

        assert flag_check.call_count == expected_calls
        if expected_calls:
            assert flag_check.call_args.args == (schema, ctrl.WAREHOUSE_MERGE_AUTO_COARSEN_FLAG)

    @pytest.mark.parametrize("flag_enabled", [False, True], ids=["flag_off", "flag_on"])
    @pytest.mark.parametrize("layout_age_days", [0, 2], ids=["just_rewritten", "past_the_cooldown"])
    def test_a_coarsened_table_is_not_split_or_coarsened_again(self, team, flag_enabled: bool, layout_age_days: int):
        schema = self._schema(team, _KEYED, partition_count=64, nominated=True)
        self._detect(team, schema, self._md5_layout(64, 187))
        pending = schema.repartition_pending
        assert pending is not None
        coarse_count = pending["partition_count"]
        assert coarse_count == 8

        # The state a finished swap leaves behind.
        schema.sync_type_config = {
            **schema.sync_type_config,
            "partition_count": coarse_count,
            "last_repartition_at": _days_ago_iso(layout_age_days),
        }
        schema.sync_type_config.pop("repartition_pending")
        schema.save()

        self._detect(
            team,
            schema,
            self._md5_layout(coarse_count, 64 * 187 // coarse_count),
            flag_enabled=flag_enabled,
        )

        assert schema.repartition_pending is None
        measurement = schema.partition_measurement
        assert measurement is not None and measurement["healthy"] is True


# An Exception-derived cancellation, named exactly `CancelledError`: models how `async_to_sync` can
# surface a worker-shutdown cancel so it slips past a plain BaseException catch. `_is_cancellation`
# keys on the type name, so this must be named `CancelledError`.
class CancelledError(Exception):
    pass


class TestIsStaleSizeSplit:
    @pytest.mark.parametrize(
        "sync_type,trigger_reason,max_bytes_offset,expected",
        [
            pytest.param("incremental", "proactive_threshold", -1, True, id="under_budget"),
            pytest.param("incremental", "proactive_threshold", 0, True, id="at_budget"),
            pytest.param("incremental", "proactive_threshold", 1, False, id="over_budget"),
            pytest.param("incremental", "proactive_threshold", None, False, id="unmeasured"),
            pytest.param("webhook", "proactive_threshold", -1, True, id="webhook"),
            pytest.param("xmin", "proactive_threshold", -1, True, id="xmin"),
            pytest.param("incremental", "oom_history", -1, False, id="oom_history"),
            pytest.param("incremental", "admin", -1, False, id="admin"),
            pytest.param("incremental", "coarsening", -1, False, id="coarsening"),
            pytest.param("incremental", "resume", -1, False, id="resume"),
            pytest.param("full_refresh", "proactive_threshold", -1, False, id="full_refresh"),
            pytest.param("append", "proactive_threshold", -1, False, id="append"),
        ],
    )
    def test_only_a_proactive_split_of_a_keyed_table_under_budget_is_stale(
        self, sync_type, trigger_reason, max_bytes_offset, expected
    ):
        schema = ExternalDataSchema(sync_type=sync_type, sync_type_config={})
        if max_bytes_offset is not None:
            schema.sync_type_config = {"max_partition_bytes": ctrl.split_budget_bytes(schema) + max_bytes_offset}

        assert ctrl.is_stale_size_split(schema, trigger_reason) is expected


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

    def test_noop_for_cdc_table(self, team):
        # Healthy no-op: a CDC table short-circuits the gate before any on-disk I/O — no job fetch, no
        # delta read, no detection, no rewrite — regardless of any recorded size.
        schema = _make_schema(team, {"max_partition_bytes": 5})
        schema.sync_type = ExternalDataSchema.SyncType.CDC
        schema.save()
        mocked = AsyncMock()
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=mocked),
            patch.object(repartition_table, "capture_repartition_event"),
            patch.object(repartition_table, "maybe_flag_for_repartition") as flag,
        ):
            ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))
        mocked.assert_not_called()
        flag.assert_not_called()

    def test_noop_when_revive_pending(self, team):
        # A table pending a corruption revive skips the whole activity — no detection, no rewrite — even
        # with a repartition already queued, so it can't interleave with the extract's heal and re-arm
        # the non-billable revive loop.
        schema = _make_schema(
            team,
            {
                "repartition_pending": {
                    "partition_mode": "md5",
                    "partition_keys": ["id"],
                    "trigger_reason": "oom_history",
                },
                "delta_revive_required": {
                    "reason": "repartition_scan_missing_data_file",
                    "missing_path": "x/p.parquet",
                },
            },
        )
        mocked = AsyncMock()
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=mocked),
            patch.object(repartition_table, "capture_repartition_event"),
            patch.object(repartition_table, "maybe_flag_for_repartition") as flag,
        ):
            ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))
        mocked.assert_not_called()
        flag.assert_not_called()

    @pytest.mark.parametrize("recorded_max_partition_bytes", [None, 5])
    def test_pre_extraction_flags_over_budget_live_table(self, team, recorded_max_partition_bytes):
        # Nothing queued: the activity reads the LIVE on-disk size and repartitions when it's
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
                patch.object(repartition_table.DeltaTableRef, "get_delta_table", new=AsyncMock(return_value=delta)),
                patch.object(ctrl, "target_partition_bytes", return_value=1),
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

    def test_rewrite_reports_workload_under_its_own_run_key(self, team):
        # The import activity reports under the bare job id on this same pod; sharing that key would
        # let a death during the import read the rewrite's report as its own last words.
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
        inputs = self._inputs(team, schema)
        samples: list[dict] = []

        async def rewrite_reading_own_report(**kwargs):
            reporter = workload_report._current_reporter.get()
            assert reporter is not None, "rewrite must run inside a workload reporting span"
            redis = workload_report._redis_client()
            assert redis is not None
            reporter._write_sample(redis)
            samples.append(json.loads(redis.get(workload_report.run_key(f"repartition:{inputs.job_id}"))))
            return {"outcome": "completed", "row_count": 6, "partition_mode_after": "md5"}

        self._run(inputs, AsyncMock(side_effect=rewrite_reading_own_report))

        assert samples and samples[0]["phase"] == "repartition"
        assert samples[0]["schema_id"] == str(schema.id)

    def test_a_rewrite_whose_worker_dies_still_burns_an_attempt(self, team):
        # A worker OOM-killed mid-rewrite records nothing, so the cap never moved and these retried
        # forever.
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

        def killed_mid_rewrite(**kwargs):
            raise KeyboardInterrupt("worker killed")

        # Three attempts run and die; the next evaluation finds the cap spent and gives up.
        for _ in range(MAX_REPARTITION_ATTEMPTS + 1):
            with contextlib.suppress(BaseException):
                self._run(self._inputs(team, schema), AsyncMock(side_effect=killed_mid_rewrite))
            schema.refresh_from_db()

        assert schema.repartition_pending is None

    def test_retries_inside_one_sync_run_burn_a_single_attempt(self, team):
        # Temporal retries this activity up to MAX_REPARTITION_ATTEMPTS times inside one sync run. A
        # hard-killed attempt records no outcome, so charging every retry let a single bad run spend
        # the whole cap: the next run gave up and abandoned a table no later sync ever retried.
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
        inputs = self._inputs(team, schema)

        def killed_mid_rewrite(**kwargs):
            raise KeyboardInterrupt("worker killed")

        for _ in range(MAX_REPARTITION_ATTEMPTS):
            with contextlib.suppress(BaseException):
                self._run(inputs, AsyncMock(side_effect=killed_mid_rewrite))
            schema.refresh_from_db()

        pending = schema.repartition_pending
        assert pending is not None and pending["attempts"] == 1

    def test_a_retry_inside_the_run_that_spent_the_cap_still_rewrites(self, team):
        # The attempt is charged before the rewrite, so on the run that charges the last one the
        # persisted count already reads the cap when that run's own Temporal retry re-reads it. Giving
        # up there abandoned the table terminally on a heartbeat blip, before the retry ran the
        # rewrite at all, although the cap counts the sync runs that failed and not the retries
        # within one.
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "t",
                "attempts": MAX_REPARTITION_ATTEMPTS - 1,
            }
        )
        inputs = self._inputs(team, schema)

        def killed_mid_rewrite(**kwargs):
            raise KeyboardInterrupt("worker killed")

        with contextlib.suppress(BaseException):
            self._run(inputs, AsyncMock(side_effect=killed_mid_rewrite))

        rewrite = AsyncMock(return_value={"outcome": "completed", "row_count": 6, "partition_mode_after": "md5"})
        capture = self._run(inputs, rewrite)

        rewrite.assert_awaited_once()
        assert "warehouse_repartition_failed" not in [c.args[0] for c in capture.call_args_list]

    def test_an_overlapping_attempt_charge_survives_another_attempts_refund(self, team):
        # Overlapping attempts must not erase each other's charge, or the cap never counts up and the
        # retry loop this change exists to stop comes back.
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "t",
                "attempts": 2,
            }
        )
        # This attempt charged 0 -> 1; a concurrent one then charged 1 -> 2. Refunding to 0 here would
        # erase that second charge.
        repartition_table._refund_attempt(schema, 0, logger)

        schema.refresh_from_db()
        pending = schema.repartition_pending
        assert pending is not None and pending["attempts"] == 2

    def test_a_checkpoint_from_a_superseded_attempt_is_dropped(self, team):
        # The write carries the whole sync_type_config, so a stale worker saving here would restore
        # its own repartition_claim and un-fence itself.
        schema = _make_schema(team, {})
        schema.set_repartition_claim({"token": "newer-claim", "job_id": "j2", "claimed_at": _days_ago_iso(0)})

        wrote = save_repartition_checkpoint_if_claimed(
            schema, claim_token="stale-claim", checkpoint={"temp_uri": "s3://t", "rows_written": 5}
        )

        schema.refresh_from_db()
        assert wrote is False
        assert schema.repartition_rewrite is None
        claim = schema.repartition_claim
        assert claim is not None and claim["token"] == "newer-claim"

    def test_a_checkpoint_from_the_live_claim_is_written(self, team):
        schema = _make_schema(team, {})
        schema.set_repartition_claim({"token": "live-claim", "job_id": "j1", "claimed_at": _days_ago_iso(0)})

        wrote = save_repartition_checkpoint_if_claimed(
            schema, claim_token="live-claim", checkpoint={"temp_uri": "s3://t", "rows_written": 5}
        )

        schema.refresh_from_db()
        assert wrote is True
        rewrite = schema.repartition_rewrite
        assert rewrite is not None and rewrite["rows_written"] == 5

    @pytest.mark.parametrize(
        "claim_token, temp_uri, saved",
        [
            pytest.param("live-claim", "s3://b/t__repartitioned_aa", True, id="own_claim_own_temp"),
            # A stale worker that saved here would let its resume trust the wrong copy of the table.
            pytest.param("stale-claim", "s3://b/t__repartitioned_aa", False, id="superseded_claim"),
            pytest.param("live-claim", "s3://b/t__repartitioned_bb", False, id="swap_of_another_attempt"),
        ],
    )
    def test_a_swap_phase_is_recorded_only_by_the_claimant_on_its_own_swap(self, team, claim_token, temp_uri, saved):
        marker = {"state": "ready", "temp_uri": "s3://b/t__repartitioned_aa", "live_uri": "s3://b/t"}
        schema = _make_schema(team, {"repartition_swap": dict(marker)})
        schema.set_repartition_claim({"token": "live-claim", "job_id": "j1", "claimed_at": _days_ago_iso(0)})

        wrote = save_repartition_swap_phase_if_claimed(
            schema, claim_token=claim_token, temp_uri=temp_uri, phase="switch_log"
        )

        schema.refresh_from_db()
        assert wrote is saved
        assert schema.repartition_swap == ({**marker, "phase": "switch_log"} if saved else marker)
        claim = schema.repartition_claim
        assert claim is not None and claim["token"] == "live-claim"

    def test_the_checkpoint_claim_check_runs_inside_the_row_lock(self, team):
        # The predicate tests below pass against a plain refresh-then-write, which is the bug: the
        # check and the write have to share one locked critical section or a superseding claimant can
        # land between them. Pins that the write goes through the locked primitive.
        schema = _make_schema(team, {})
        schema.set_repartition_claim({"token": "live-claim", "job_id": "j1", "claimed_at": _days_ago_iso(0)})

        with patch.object(external_data_schema, "update_sync_type_config_keys") as locked_update:
            save_repartition_checkpoint_if_claimed(
                schema, claim_token="live-claim", checkpoint={"temp_uri": "s3://t", "rows_written": 5}
            )

        locked_update.assert_called_once()
        # The claim check must be the mutate callback, evaluated against the row read under the lock.
        assert locked_update.call_args.kwargs["mutate"] is not None

    def test_finalizing_a_swap_saves_the_scheme_and_retires_every_marker_at_once(self, team):
        # The swap has already re-bucketed the data in S3, so what is left is one write that has to be
        # all-or-nothing. Landing the settings but keeping the swap marker holds the schema's imports
        # forever; clearing the markers without the cooldown re-flags the table on the very next sync;
        # keeping the operator pin re-applies it on a later reset.
        schema = _make_schema(
            team,
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_count_override": 4,
                "partition_measurement": {
                    "job_id": "previous-job",
                    "phase": "post_load",
                    "budget": 500,
                    "healthy": True,
                },
            },
        )
        schema.set_repartition_claim({"token": "live-claim", "job_id": "j1", "claimed_at": _days_ago_iso(0)})
        schema.set_repartition_pending(
            {"partition_mode": "md5", "partition_count": 8, "partition_keys": ["id"], "trigger_reason": "t"}
        )
        schema.set_repartition_swap({"state": "ready", "temp_uri": "s3://t", "live_uri": "s3://l"})
        schema.set_repartition_rewrite({"temp_uri": "s3://t", "rows_written": 5})

        wrote = external_data_schema.finalize_repartition_scheme(
            schema,
            partitioning_keys=["id"],
            partition_count=8,
            partition_size=None,
            partition_mode="md5",
            partition_format=None,
            claim_token="live-claim",
        )

        schema.refresh_from_db()
        assert wrote is True
        assert schema.partitioning_enabled is True
        assert schema.partition_count == 8
        assert schema.partition_count_override is None
        assert schema.repartition_swap is None
        assert schema.repartition_pending is None
        assert schema.repartition_rewrite is None
        assert schema.partition_measurement is None
        assert schema.last_repartition_at is not None

    @pytest.mark.parametrize(
        "target,expected",
        [
            pytest.param(
                {"partitioning_keys": ["id"], "partition_count": 8, "partition_size": None, "partition_mode": "md5"},
                {"partition_count": 8, "partition_size": None, "partition_mode": "md5", "partitioning_keys": ["id"]},
                id="fewer_hash_buckets",
            ),
            pytest.param(
                {
                    "partitioning_keys": ["created_at"],
                    "partition_count": None,
                    "partition_size": None,
                    "partition_mode": "datetime",
                    "partition_format": "month",
                },
                {"partition_mode": "datetime", "partitioning_keys": ["created_at"], "partition_format": "month"},
                id="coarser_datetime_format",
            ),
            pytest.param(
                {
                    "partitioning_keys": ["id"],
                    "partition_count": None,
                    "partition_size": 4096,
                    "partition_mode": "numerical",
                },
                {"partition_size": 4096, "partition_mode": "numerical", "partitioning_keys": ["id"]},
                id="wider_numerical_ranges",
            ),
        ],
    )
    def test_a_scheme_staged_for_a_full_refresh_survives_that_syncs_reset(self, team, target, expected):
        # A full-refresh sync starts by wiping the plain partition settings, so a scheme saved as
        # plain settings would be discarded and the sync would write the old layout again.
        schema = _make_schema(
            team,
            {"partition_mode": "md5", "partition_count": 64, "partitioning_keys": ["id"], "partition_format": "hour"},
        )
        schema.set_repartition_pending({"partition_mode": "md5", "partition_keys": ["id"], "trigger_reason": "t"})
        schema.set_repartition_rewrite({"temp_uri": "s3://t", "rows_written": 5})

        external_data_schema.stage_partition_scheme_for_full_refresh(schema, **{"partition_format": None, **target})
        schema.refresh_from_db()
        schema.update_sync_type_config_for_reset_pipeline(clear_initial_sync_complete=False)
        schema.refresh_from_db()

        resolved = {
            "partition_count": schema.partition_count_override,
            "partition_size": schema.partition_size_override,
            "partition_mode": schema.partition_mode_override,
            "partitioning_keys": schema.partitioning_keys_override,
            "partition_format": schema.partition_format,
        }
        for key, value in expected.items():
            assert resolved[key] == value
        assert schema.repartition_pending is None
        assert schema.repartition_rewrite is None
        assert schema.last_repartition_at is not None

    def test_full_refresh_staging_stands_down_when_a_newer_attempt_owns_the_claim(self, team):
        schema = _make_schema(team, {"partition_mode": "md5", "partition_count": 4})
        schema.set_repartition_claim({"token": "newer-claim", "job_id": "j2", "claimed_at": _days_ago_iso(0)})
        schema.set_repartition_pending(
            {"partition_mode": "md5", "partition_count": 8, "partition_keys": ["id"], "trigger_reason": "t"}
        )

        wrote = external_data_schema.stage_partition_scheme_for_full_refresh(
            schema,
            partitioning_keys=["id"],
            partition_count=8,
            partition_size=None,
            partition_mode="md5",
            partition_format=None,
            claim_token="superseded-claim",
        )

        schema.refresh_from_db()
        assert wrote is False
        assert schema.partition_count_override is None
        assert schema.repartition_pending is not None
        assert schema.repartition_claim is not None
        assert schema.repartition_claim["token"] == "newer-claim"

    def test_full_refresh_staging_preserves_a_swap_that_appeared_after_claiming(self, team):
        schema = _make_schema(team, {"partition_mode": "md5", "partition_count": 4})
        schema.set_repartition_claim({"token": "ours", "job_id": "j1", "claimed_at": _days_ago_iso(0)})
        schema.set_repartition_swap({"state": "ready", "temp_uri": "s3://t", "live_uri": "s3://l"})

        wrote = external_data_schema.stage_partition_scheme_for_full_refresh(
            schema,
            partitioning_keys=["id"],
            partition_count=8,
            partition_size=None,
            partition_mode="md5",
            partition_format=None,
            claim_token="ours",
        )

        schema.refresh_from_db()
        assert wrote is False
        assert schema.partition_count_override is None
        assert schema.repartition_swap is not None

    def test_finalizing_stands_down_when_a_newer_attempt_owns_the_claim(self, team):
        # A zombie writing here would describe a layout the new claimant is in the middle of replacing.
        schema = _make_schema(team, {"partition_mode": "md5", "partition_count": 4})
        schema.set_repartition_claim({"token": "newer-claim", "job_id": "j2", "claimed_at": _days_ago_iso(0)})
        schema.set_repartition_swap({"state": "ready", "temp_uri": "s3://t", "live_uri": "s3://l"})

        wrote = external_data_schema.finalize_repartition_scheme(
            schema,
            partitioning_keys=["id"],
            partition_count=8,
            partition_size=None,
            partition_mode="md5",
            partition_format=None,
            claim_token="stale-claim",
        )

        schema.refresh_from_db()
        assert wrote is False
        assert schema.partition_count == 4
        assert schema.repartition_swap is not None

    def test_a_staged_swap_is_never_abandoned_by_the_attempt_cap(self, team):
        # An interrupted swap may already have deleted live, leaving temp the only intact copy. Giving
        # up clears the marker that points at it, so the next sync would bootstrap an empty table.
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "t",
                "attempts": MAX_REPARTITION_ATTEMPTS,
            }
        )
        schema.set_repartition_swap({"state": "ready", "temp_uri": "s3://t/__repartitioned", "live_uri": "s3://t"})

        mocked = AsyncMock(return_value={"outcome": "completed"})
        self._run(self._inputs(team, schema), mocked)

        # The rewrite runs and resumes the swap, rather than the cap short-circuiting it.
        mocked.assert_awaited_once()

    def test_a_superseded_attempt_costs_no_attempt(self, team):
        # A zombie displaced by a newer claim is not evidence the rewrite is doomed.
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

        self._run(self._inputs(team, schema), AsyncMock(side_effect=RepartitionSupersededError("newer claim")))

        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["attempts"] == 0

    @pytest.mark.parametrize(
        "error",
        [
            RepartitionUnpartitionableError("no keys"),
            RepartitionTooLargeForBudgetError("one budget cannot cover the table"),
        ],
    )
    def test_a_terminal_rewrite_error_clears_pending(self, team, error):
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {"partition_mode": None, "partition_keys": [], "trigger_reason": "test", "attempts": 0}
        )
        schema.set_repartition_rewrite({"temp_uri": "s3://bucket/t", "rows_written": 10, "budget_exhausted": True})
        mocked = AsyncMock(side_effect=error)
        capture = self._run(self._inputs(team, schema), mocked)
        schema.refresh_from_db()
        assert schema.repartition_pending is None
        # A checkpoint left behind would resume the rewrite the give-up just abandoned.
        assert schema.repartition_rewrite is None
        assert "warehouse_repartition_skipped" in [c.args[0] for c in capture.call_args_list]
        assert "warehouse_repartition_failed" not in [c.args[0] for c in capture.call_args_list]
        # Clearing pending alone re-arms the loop — detection re-flags the unchanged table next sync.
        # The cooldown stamp is what actually stops the flag → start → skip churn every 5 minutes.
        assert schema.last_repartition_at is not None

    @pytest.mark.parametrize(
        "trigger_reason,dropped",
        [("proactive_threshold", True), ("oom_history", True), ("admin", False), ("coarsening", False)],
    )
    def test_an_automatic_split_queued_on_an_append_table_is_dropped(self, team, trigger_reason, dropped):
        schema = _make_schema(team, {})
        schema.sync_type = ExternalDataSchema.SyncType.APPEND
        schema.save()
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": trigger_reason,
                "attempts": 0,
            }
        )
        schema.set_repartition_rewrite({"temp_uri": "s3://bucket/t__repartitioned_x", "rows_written": 10})
        mocked = AsyncMock(return_value={"outcome": "completed", "row_count": 6, "partition_mode_after": "md5"})
        purge = AsyncMock(return_value=True)
        with patch.object(repartition_table, "purge_abandoned_rewrite_temp", new=purge):
            capture = self._run(self._inputs(team, schema), mocked)

        schema.refresh_from_db()
        if dropped:
            mocked.assert_not_called()
            assert purge.await_args is not None
            assert purge.await_args.args[2] == "s3://bucket/t__repartitioned_x"
            assert schema.repartition_pending is None
            assert schema.repartition_rewrite is None
            skipped = [c.args[1] for c in capture.call_args_list if c.args[0] == "warehouse_repartition_skipped"]
            assert [props["reason"] for props in skipped] == ["append_never_merges"]
        else:
            mocked.assert_awaited_once()
            purge.assert_not_called()

    @pytest.mark.parametrize(
        "sync_type,trigger_reason,max_bytes_offset,swap,dropped",
        [
            pytest.param("incremental", "proactive_threshold", -1, False, True, id="incremental_under_budget"),
            pytest.param("webhook", "proactive_threshold", 0, False, True, id="webhook_at_budget"),
            pytest.param("xmin", "proactive_threshold", -1, False, True, id="xmin_under_budget"),
            pytest.param("incremental", "proactive_threshold", 1, False, False, id="over_budget_still_runs"),
            pytest.param("incremental", "proactive_threshold", None, False, False, id="unmeasured_still_runs"),
            pytest.param("incremental", "oom_history", -1, False, False, id="oom_history_still_runs"),
            pytest.param("incremental", "admin", -1, False, False, id="admin_still_runs"),
            pytest.param("incremental", "coarsening", -1, False, False, id="coarsening_still_runs"),
            pytest.param("incremental", "proactive_threshold", -1, True, False, id="staged_swap_is_kept"),
        ],
    )
    def test_a_queued_size_split_under_the_merge_budget_is_dropped(
        self, team, sync_type, trigger_reason, max_bytes_offset, swap, dropped
    ):
        schema = _make_schema(team, {})
        schema.sync_type = sync_type
        schema.save()
        if max_bytes_offset is not None:
            schema.record_partition_measurement(ctrl.split_budget_bytes(schema) + max_bytes_offset)
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": trigger_reason,
                "attempts": 0,
            }
        )
        schema.set_repartition_rewrite({"temp_uri": "s3://bucket/t__repartitioned_x", "rows_written": 10})
        if swap:
            schema.set_repartition_swap(
                {"state": "ready", "temp_uri": "s3://bucket/t__repartitioned_x", "live_uri": "s3://bucket/t"}
            )
        mocked = AsyncMock(return_value={"outcome": "completed", "row_count": 6, "partition_mode_after": "md5"})
        purge = AsyncMock(return_value=True)
        with patch.object(repartition_table, "purge_abandoned_rewrite_temp", new=purge):
            capture = self._run(self._inputs(team, schema), mocked)

        schema.refresh_from_db()
        skipped = [c.args[1] for c in capture.call_args_list if c.args[0] == "warehouse_repartition_skipped"]
        if dropped:
            mocked.assert_not_called()
            assert purge.await_args is not None
            assert purge.await_args.args[2] == "s3://bucket/t__repartitioned_x"
            assert schema.repartition_pending is None
            assert schema.repartition_rewrite is None
            assert [props["reason"] for props in skipped] == ["under_merge_split_budget"]
            assert schema.last_repartition_at is None
        else:
            assert "under_merge_split_budget" not in [props["reason"] for props in skipped]
            purge.assert_not_called()
            if swap:
                assert schema.repartition_swap is not None
            else:
                mocked.assert_awaited_once()

    @pytest.mark.parametrize("prior_attempts, gives_up", [(0, False), (MAX_REPARTITION_ATTEMPTS - 1, True)])
    def test_an_append_split_whose_temp_cannot_be_deleted_is_retried_a_bounded_number_of_times(
        self, team, prior_attempts, gives_up
    ):
        schema = _make_schema(team, {})
        schema.sync_type = ExternalDataSchema.SyncType.APPEND
        schema.save()
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "proactive_threshold",
                "drop_attempts": prior_attempts,
            }
        )
        schema.set_repartition_rewrite(
            {"temp_uri": "s3://bucket/t__repartitioned_x", "rows_written": 10, "held_at": "2026-01-01T00:00:00+00:00"}
        )
        mocked = AsyncMock()
        with (
            patch.object(repartition_table, "purge_abandoned_rewrite_temp", new=AsyncMock(side_effect=OSError("s3"))),
            patch.object(repartition_table, "capture_exception") as captured,
        ):
            self._run(self._inputs(team, schema), mocked)

        schema.refresh_from_db()
        mocked.assert_not_called()
        if gives_up:
            assert schema.repartition_pending is None
            assert schema.repartition_rewrite is None
            assert any("dropped queued split" in str(c.args[0]) for c in captured.call_args_list)
        else:
            assert schema.repartition_pending is not None
            assert schema.repartition_pending["dropping"] is True
            assert schema.repartition_pending["drop_attempts"] == 1
            # The checkpoint stays as the record of the temp table, and no longer holds the import.
            assert schema.repartition_rewrite == {"temp_uri": "s3://bucket/t__repartitioned_x", "rows_written": 10}
        # A dropped split changes no layout, so it must not start the cooldown or age the layout.
        assert schema.last_repartition_at is None

    def test_a_failed_append_split_drop_never_overwrites_a_newer_claim(self, team):
        schema = _make_schema(team, {})
        schema.sync_type = ExternalDataSchema.SyncType.APPEND
        schema.save()
        schema.set_repartition_pending(
            {"partition_mode": "md5", "partition_keys": ["id"], "trigger_reason": "proactive_threshold"}
        )
        schema.set_repartition_rewrite({"temp_uri": "s3://bucket/t__repartitioned_x", "rows_written": 10})
        newer_claim = {"token": "newer", "job_id": "other", "claimed_at": "2999-01-01T00:00:00+00:00"}

        async def newer_attempt_claims_then_delete_fails(*_args, **_kwargs):
            await asyncio.to_thread(
                external_data_schema.update_sync_type_config_keys,
                schema_id=schema.id,
                team_id=schema.team_id,
                updates={"repartition_claim": newer_claim},
            )
            raise OSError("s3")

        with patch.object(
            repartition_table,
            "purge_abandoned_rewrite_temp",
            new=AsyncMock(side_effect=newer_attempt_claims_then_delete_fails),
        ):
            self._run(self._inputs(team, schema), AsyncMock())

        schema.refresh_from_db()
        assert schema.repartition_claim == newer_claim
        assert "dropping" not in (schema.repartition_pending or {})

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

    @pytest.mark.parametrize("trigger_reason", ["coarsening", "admin"])
    def test_give_up_reports_to_error_tracking(self, team, trigger_reason):
        # The give-up path fires when the cap is already spent by attempts that were hard-killed before
        # they could record an outcome. It is the only terminal repartition path that never ran
        # `_handle_failure` (which captures), so without an explicit capture here the most severe
        # outcome — a table the controller has abandoned — is invisible in error tracking.
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": trigger_reason,
                "attempts": ctrl.MAX_REPARTITION_ATTEMPTS,
            }
        )
        rewrite = AsyncMock()
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=rewrite),
            patch.object(repartition_table, "capture_repartition_event") as capture,
            patch.object(repartition_table, "capture_exception") as capture_exception,
        ):
            ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))

        # The cap was already spent, so no rewrite is attempted — this is the pre-run give-up.
        rewrite.assert_not_called()
        capture_exception.assert_called_once()
        assert isinstance(capture_exception.call_args.args[0], RepartitionAttemptsExhausted)
        failed = [c.args[1] for c in capture.call_args_list if c.args[0] == "warehouse_repartition_failed"]
        assert len(failed) == 1
        assert failed[0]["final"] is True
        assert failed[0]["error_type"] == "RepartitionAttemptsExhausted"
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

    @pytest.mark.parametrize(
        "error",
        [
            pytest.param(OperationalError("server closed the connection unexpectedly"), id="db_pooler_drop"),
            pytest.param(OSError("[Errno 16] Please reduce your request rate."), id="s3_rate_limit"),
            pytest.param(OSError("Kernel error -> an error occurred while loading credentials"), id="credentials"),
            pytest.param(Exception("An HTTP Client raised an unhandled exception: Event loop is closed"), id="loop"),
        ],
    )
    def test_transient_infra_error_not_recorded_as_failure(self, team, error):
        # Infra noise mid-repartition (pooler drop, S3 throttle, credential timeout, dead-loop client) is
        # not a repartition bug: the swap is marker-idempotent and the next sync retries. It must not emit
        # warehouse_repartition_failed or consume an attempt, else infra blips spam error tracking and
        # exhaust the attempt budget.
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
        mocked = AsyncMock(side_effect=error)
        capture = self._run(self._inputs(team, schema), mocked)
        emitted = [c.args[0] for c in capture.call_args_list]
        assert "warehouse_repartition_started" in emitted
        assert "warehouse_repartition_failed" not in emitted
        # A started event with no closing event is indistinguishable from an attempt that vanished.
        skipped = [c.args[1] for c in capture.call_args_list if c.args[0] == "warehouse_repartition_skipped"]
        assert [p["reason"] for p in skipped] == ["transient_infra_error"]
        assert skipped[0]["terminal"] is False
        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["attempts"] == 0

    def test_admin_transient_infra_error_reraises_for_activity_retry(self, team):
        # An operator staged this rewrite (trigger_reason "admin") because syncing on the old layout is
        # pathological — deferring a transient blip to the next sync runs that crawl first. The activity
        # must re-raise retryable so Temporal re-runs the rewrite in this run, while still emitting no
        # failure event and consuming no attempt (in-run retries must not exhaust the budget on infra
        # noise). ActivityEnvironment bypasses the worker interceptor chain, so this does NOT cover the
        # error-tracking exemption for the re-raise — that lives in EXPECTED_CONTROL_FLOW_ERROR_TYPES
        # (posthog_client.py), keyed on the ApplicationError's type string.
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {
                "partition_mode": "md5",
                "partition_count": 4,
                "partition_keys": ["id"],
                "trigger_reason": "admin",
                "attempts": 0,
            }
        )
        mocked = AsyncMock(side_effect=OperationalError("server closed the connection unexpectedly"))
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=mocked),
            patch.object(repartition_table, "capture_repartition_event") as capture,
        ):
            with pytest.raises(ApplicationError):
                ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))
        assert "warehouse_repartition_failed" not in [c.args[0] for c in capture.call_args_list]
        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["attempts"] == 0

    @pytest.mark.parametrize(
        "error,still_claimant,expected_reason",
        [
            pytest.param(RepartitionSupersededError("claim lost"), True, "superseded", id="clean_abort"),
            pytest.param(
                ValueError("boom from clobbered temp"), False, "superseded_after_error", id="collateral_failure"
            ),
        ],
    )
    def test_superseded_attempt_is_silent_and_burns_no_attempt(self, team, error, still_claimant, expected_reason):
        # A zombie attempt (heartbeat-timed-out but still running) that either stands down cleanly or
        # crashes on state its replacement clobbered must not emit warehouse_repartition_failed or
        # consume an attempt — the newer claimant owns the run and reports for it. Without this, every
        # superseded zombie double-reports and can burn the whole attempt budget on one bad table.
        # It must still emit a terminal skip: a lone started event with pending left set is
        # indistinguishable from an attempt that vanished, which made a real incident undiagnosable.
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
        mocked = AsyncMock(side_effect=error)
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=mocked),
            patch.object(repartition_table, "capture_repartition_event") as capture,
            patch.object(repartition_table, "_still_claimant", return_value=still_claimant),
        ):
            ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))
        assert "warehouse_repartition_failed" not in [c.args[0] for c in capture.call_args_list]
        skipped = [c for c in capture.call_args_list if c.args[0] == "warehouse_repartition_skipped"]
        assert [c.args[1]["reason"] for c in skipped] == [expected_reason]
        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["attempts"] == 0
        # The activity minted a fencing claim before starting the rewrite.
        assert schema.repartition_claim is not None

    def test_stand_down_survives_a_failing_telemetry_capture(self, team):
        # The stand-down emitters run inside except-handlers whose contract is to swallow. A raising
        # capture must not escape: it would fail an activity that deliberately stood down, retrying
        # work the newer claimant already owns.
        schema = _make_schema(team, {})
        schema.set_repartition_pending(
            {"partition_mode": "md5", "partition_count": 4, "partition_keys": ["id"], "trigger_reason": "t"}
        )

        def _capture(event, props):
            if event == "warehouse_repartition_skipped":
                raise RuntimeError("analytics unavailable")

        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(
                repartition_table,
                "repartition_table_in_place",
                new=AsyncMock(side_effect=RepartitionSupersededError("claim lost")),
            ),
            patch.object(repartition_table, "capture_repartition_event", side_effect=_capture),
            patch.object(repartition_table, "_still_claimant", return_value=True),
        ):
            ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))

        schema.refresh_from_db()
        assert schema.repartition_pending is not None

    def test_schema_fetch_retries_once_on_transient_db_connection_drop(self, team):
        # The schema fetch runs on a long-lived Temporal worker thread, so a pooler-dropped
        # connection can raise OperationalError on first use. Unlike every DB read past this point,
        # this one sits outside the activity's transient-error handling (only ExternalDataSchema.
        # DoesNotExist is caught here), so without a retry it escaped uncaught as an activity
        # failure instead of resolving on a fresh connection.
        schema = _make_schema(team, {})
        mock_queryset = MagicMock()
        mock_queryset.get.side_effect = [OperationalError("server closed the connection unexpectedly"), schema]
        with (
            patch.object(ExternalDataSchema.objects, "select_related", return_value=mock_queryset),
            patch.object(repartition_table, "needs_pre_extraction_detection", return_value=False),
            patch.object(repartition_table, "capture_repartition_event"),
        ):
            ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))
        assert mock_queryset.get.call_count == 2

    def test_job_fetch_retries_once_on_transient_db_connection_drop(self, team):
        # Same failure mode as the schema fetch above, for the job fetch a few lines later: a
        # pooler-dropped connection must resolve on retry rather than escape as an activity failure.
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
        job = _make_job(team, schema)
        mock_get = MagicMock(side_effect=[OperationalError("server closed the connection unexpectedly"), job])
        mocked = AsyncMock(return_value={"outcome": "completed"})
        with (
            patch.object(ExternalDataJob.objects, "get", mock_get),
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=mocked),
            patch.object(repartition_table, "capture_repartition_event"),
        ):
            ActivityEnvironment().run(
                maybe_repartition_table_activity,
                RepartitionActivityInputs(
                    team_id=team.id, schema_id=str(schema.id), job_id=str(job.id), source_id=str(schema.source_id)
                ),
            )
        assert mock_get.call_count == 2
        mocked.assert_awaited_once()

    def test_superseded_after_claim_check_blip_is_not_recorded_as_failure(self, team):
        # _still_claimant is conservative and reports True on a transient DB read, so a zombie can reach
        # the failure handler even after a newer attempt took the claim. _handle_failure's authoritative
        # refresh is the fence that catches that: with _still_claimant forced True (the blip) but the DB
        # claim changed by a newer attempt, the zombie must record no failure and re-queue no attempt —
        # otherwise it double-reports and re-increments a run the newer claimant already owns.
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

        def _steal_claim_but_blip_reports_still_claimant(*args, **kwargs):
            # Model the transient blip: a newer attempt has already taken the claim in the DB, yet the
            # claim re-read here reports True anyway (conservative on doubt). The steal is written from
            # here rather than inside the rewrite mock because _still_claimant runs in the activity's sync
            # context, so its ORM write is safe — the rewrite runs under async_to_sync, where sync ORM
            # raises SynchronousOnlyOperation.
            other = ExternalDataSchema.objects.get(id=schema.id)
            other.set_repartition_claim({"token": "newer-token", "job_id": "j2", "claimed_at": "later"})
            return True

        mocked = AsyncMock(side_effect=ValueError("boom from clobbered temp"))
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=mocked),
            patch.object(repartition_table, "capture_repartition_event") as capture,
            patch.object(
                repartition_table, "_still_claimant", side_effect=_steal_claim_but_blip_reports_still_claimant
            ),
        ):
            ActivityEnvironment().run(maybe_repartition_table_activity, self._inputs(team, schema))
        assert "warehouse_repartition_failed" not in [c.args[0] for c in capture.call_args_list]
        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["attempts"] == 0
