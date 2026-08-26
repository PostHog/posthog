import json
import uuid
import asyncio
import datetime
import tempfile
import contextlib

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
)
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.models.oom_event import ExternalDataSchemaOOMEvent
from products.warehouse_sources.backend.temporal.data_imports import workload_report
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core import repartition_controller as ctrl
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.consts import PARTITION_KEY
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.repartition import (
    RepartitionAttemptsExhausted,
    RepartitionSupersededError,
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
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
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
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
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
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
                patch.object(ctrl, "capture_repartition_event"),
            ):
                self._detect(team, schema, delta)

        schema.refresh_from_db()
        assert schema.repartition_pending is not None
        assert schema.repartition_pending["partition_mode"] is None
        assert schema.repartition_pending["partition_keys"] == ["id"]


class TestIsAutoRepartitionEnabled:
    def test_retries_once_on_transient_db_connection_drop(self, team):
        # The Team lookup runs on a long-lived Temporal worker thread; a pooler-dropped connection
        # raises OperationalError on first use. Without a retry this propagates out of
        # is_auto_repartition_enabled uncaught (it's outside the function's Team.DoesNotExist/
        # feature_enabled try blocks) instead of resolving the flag.
        schema = _make_schema(team, {})
        mock_queryset = MagicMock()
        mock_queryset.get.side_effect = [OperationalError("server closed the connection unexpectedly"), team]

        with (
            patch("posthog.models.Team.objects.only", return_value=mock_queryset),
            patch.object(ctrl.posthoganalytics, "feature_enabled", return_value=True),
        ):
            assert ctrl.is_auto_repartition_enabled(schema) is True

        assert mock_queryset.get.call_count == 2

    def test_returns_false_when_db_connection_stays_down(self, team):
        # If the connection is still down on the retry, is_auto_repartition_enabled must not raise —
        # repartition_table.py calls it with no enclosing try/except, so an uncaught OperationalError
        # here crashes the whole activity instead of just leaving the flag resolved as disabled.
        schema = _make_schema(team, {})
        mock_queryset = MagicMock()
        mock_queryset.get.side_effect = OperationalError("server closed the connection unexpectedly")

        with (
            patch("posthog.models.Team.objects.only", return_value=mock_queryset),
            patch.object(ctrl, "capture_exception") as mock_capture_exception,
        ):
            assert ctrl.is_auto_repartition_enabled(schema) is False

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
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
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
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
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
        self, team, schema: ExternalDataSchema, *, coarsen_enabled: bool = True, buckets: list[str] | None = None
    ) -> MagicMock:
        with tempfile.TemporaryDirectory() as d:
            delta = _write_partitioned_delta(f"{d}/t", buckets or [str(bucket) for bucket in range(16)])
            with (
                patch.object(ctrl, "target_partition_bytes", return_value=10**12),
                patch.object(ctrl, "is_auto_repartition_enabled", return_value=True),
                patch.object(ctrl, "is_auto_coarsen_enabled", return_value=coarsen_enabled),
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
            # Enrolment is per-schema, like the finer path's.
            "flag_disabled",
        ],
    )
    def test_does_not_coarsen_when_a_guard_applies(self, team, case):
        schema = self._fragmented_schema(
            team, **({"last_repartition_at": _days_ago_iso(0)} if case == "fresh_layout" else {})
        )
        if case == "recent_oom":
            self._record_oom(schema)

        self._detect_over_fragmented(team, schema, coarsen_enabled=case != "flag_disabled")

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
            ("flag_disabled", "flag_disabled"),
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
            self._detect_over_fragmented(team, schema, coarsen_enabled=case != "flag_disabled")

        assert decline_metric.labels.call_args.kwargs == {"reason": expected_reason}

    def test_operator_nomination_overrides_the_policy_gates(self, team):
        # The backlog of already-over-split tables is blocked by the OOM-free gate, because the signal
        # that over-split them keeps firing. A nomination is how an operator gets past that, so it has
        # to work with OOM history present, the flag off, and a layout younger than the age gate.
        schema = self._fragmented_schema(team, last_repartition_at=_days_ago_iso(0), coarsen_requested=_NOMINATION)
        self._record_oom(schema)

        self._detect_over_fragmented(team, schema, coarsen_enabled=False)

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
            self._detect_over_fragmented(team, schema, coarsen_enabled=False)

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

        self._detect_over_fragmented(team, schema, coarsen_enabled=False, buckets=buckets)

        assert schema.repartition_pending is None
        assert schema.coarsen_requested is None


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
        # so these exercise the activity's decision + bookkeeping, not the rewrite itself. The rollout
        # flag is forced on because it now gates the queued rewrite as well as detection, so every
        # caller of this helper (all of which stage a pending target and expect it to be acted on)
        # would otherwise be released by the gate before reaching the bookkeeping under test.
        with (
            patch.object(repartition_table, "HeartbeaterSync"),
            patch.object(repartition_table, "repartition_table_in_place", new=repartition_mock),
            patch.object(repartition_table, "capture_repartition_event") as capture,
            patch.object(repartition_table, "is_auto_repartition_enabled", return_value=True),
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
            patch.object(repartition_table, "is_auto_repartition_enabled", return_value=True),
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
                patch.object(repartition_table.DeltaTableRef, "get_delta_table", new=AsyncMock(return_value=delta)),
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
        # Clearing pending alone re-arms the loop — detection re-flags the unchanged table next sync.
        # The cooldown stamp is what actually stops the flag → start → skip churn every 5 minutes.
        assert schema.last_repartition_at is not None

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
            patch.object(repartition_table, "is_auto_repartition_enabled", return_value=True),
            # A coarsening trigger answers to the coarsen flag, not the repartition one; without this the
            # activity releases the queued rewrite before reaching the give-up.
            patch.object(repartition_table, "is_auto_coarsen_enabled", return_value=True),
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
            patch.object(repartition_table, "is_auto_repartition_enabled", return_value=True),
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
            patch.object(repartition_table, "is_auto_repartition_enabled", return_value=True),
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
            patch.object(repartition_table, "is_auto_repartition_enabled", return_value=False),
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
            patch.object(repartition_table, "is_auto_repartition_enabled", return_value=True),
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
