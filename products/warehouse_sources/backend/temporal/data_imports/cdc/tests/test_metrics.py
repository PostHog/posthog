import uuid
from contextlib import contextmanager
from datetime import UTC, datetime

import pytest
from unittest.mock import MagicMock, patch

from temporalio.common import MetricMeter
from temporalio.runtime import MetricBuffer, Runtime, TelemetryConfig
from temporalio.testing import ActivityEnvironment

from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc import metrics
from products.warehouse_sources.backend.temporal.data_imports.cdc.activities import (
    CDCExtractActivity,
    CDCExtractInput,
    cdc_extract_activity,
    cleanup_orphan_slots_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import ChangeEventBatcher
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig

_ACTIVITIES = "products.warehouse_sources.backend.temporal.data_imports.cdc.activities"


class TestMetricsOutsideActivityContext:
    """Outside an activity context the meter is a no-op, so every factory must build a
    usable metric and its emit call must not raise — this is the branch the direct-
    instantiation activity tests rely on."""

    def test_meter_falls_back_to_noop(self):
        assert metrics._meter() is MetricMeter.noop

    def test_counters_record_without_raising(self):
        metrics.get_events_extracted_metric(1, "s").add(5)
        metrics.get_micro_batches_flushed_metric(1, "s").add(1)
        metrics.get_slot_advance_metric(1, "s").add(1)
        metrics.get_slot_advance_failures_metric(1, "s").add(1)
        metrics.get_auto_drop_metric(1, "s").add(1)
        metrics.get_sweeper_sources_checked_metric().add(3)
        metrics.get_sweeper_source_errors_metric().add(1)

    def test_histograms_record_without_raising(self):
        metrics.get_extraction_duration_metric(1, "s", "completed").record(1.5)
        metrics.get_sweeper_duration_metric().record(2.0)

    def test_gauges_set_without_raising(self):
        metrics.get_deferred_runs_depth_metric(1, "s").set(2)
        metrics.get_wal_lag_metric(1, "s").set(1024)


# ---------------------------------------------------------------------------
# ActivityEnvironment smoke tests — run instrumented paths against a real
# (Rust-backed) meter so emission is exercised end-to-end. No value assertions.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _runtime_buffer():
    buffer = MetricBuffer(10_000)
    runtime = Runtime(telemetry=TelemetryConfig(metrics=buffer))
    return runtime, buffer


@pytest.fixture
def metric_env(_runtime_buffer):
    runtime, buffer = _runtime_buffer
    buffer.retrieve_updates()  # drop anything emitted by an earlier test
    env = ActivityEnvironment()
    env.metric_meter = runtime.metric_meter
    return env, buffer


def _emitted_names(buffer: MetricBuffer) -> set[str]:
    return {update.metric.name for update in buffer.retrieve_updates()}


def _make_event(op="I", table="public.users", position="0/100"):
    return ChangeEvent(
        operation=op,
        table_name=table,
        position_serialized=position,
        timestamp=datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC),
        columns={"id": 1, "name": "Alice"},
    )


def _make_source():
    source = MagicMock()
    source.id = uuid.uuid4()
    source.team_id = 1
    source.source_type = "Postgres"
    source.deleted = False
    source.job_inputs = {"schema": "public", "cdc_slot_name": "s", "cdc_publication_name": "p"}
    return source


def _make_schema(cdc_mode="streaming"):
    schema = MagicMock()
    schema.id = uuid.uuid4()
    schema.name = "users"
    schema.team_id = 1
    schema.sync_type_config = {"cdc_mode": cdc_mode, "cdc_table_mode": "consolidated", "primary_key_columns": ["id"]}
    schema.cdc_mode = cdc_mode
    schema.cdc_table_mode = "consolidated"
    schema.enabled_columns = None
    schema.incremental_field = None
    schema.resolved_s3_folder_name = None
    schema.save = MagicMock()
    return schema


@contextmanager
def _extract_patches(source, schemas, events):
    reader = MagicMock()
    reader.read_changes.return_value = iter(events)
    reader.truncated_tables = []
    # Below CDC_MAX_CHANGES_PER_READ so the bounded read loop treats this as a single drained pass.
    reader.last_rows_consumed = len(events)
    reader.get_decoder_key_columns.return_value = []

    adapter = MagicMock()
    adapter.create_reader.return_value = reader
    adapter.is_slot_invalidation_error.return_value = False

    s3 = MagicMock()
    batch_result = MagicMock(
        s3_path="s3://b/p.parquet", row_count=len(events), byte_size=512, batch_index=0, timestamp_ns=1
    )
    s3.write_batch.return_value = batch_result
    s3.write_schema.return_value = "s3://b/schema.json"
    s3.get_data_folder.return_value = "s3://b/"

    job = MagicMock()
    job.id = uuid.uuid4()

    with (
        patch(f"{_ACTIVITIES}.close_old_connections"),
        patch(f"{_ACTIVITIES}.ExternalDataSource") as MockSource,
        patch.object(CDCExtractActivity, "_get_cdc_schemas", return_value=schemas),
        patch.object(CDCExtractActivity, "_update_schema_sync_type_config"),
        patch(f"{_ACTIVITIES}.get_cdc_adapter", return_value=adapter),
        patch(f"{_ACTIVITIES}.S3BatchWriter", return_value=s3),
        patch(f"{_ACTIVITIES}.PostgresProducer"),
        patch(f"{_ACTIVITIES}.ExternalDataJob") as MockJob,
    ):
        MockSource.objects.get.return_value = source
        MockJob.objects.create.return_value = job
        yield adapter, reader, s3


class TestExtractionMetricsSmoke:
    def test_success_run_emits_events_advance_and_duration(self, metric_env):
        env, buffer = metric_env
        source = _make_source()
        events = [_make_event(position="0/100"), _make_event(op="U", position="0/200")]
        with _extract_patches(source, [_make_schema()], events):
            env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        names = _emitted_names(buffer)
        assert "cdc_events_extracted_total" in names
        assert "cdc_slot_advance_total" in names
        assert "cdc_extraction_duration_seconds" in names

    def test_no_changes_run_emits_duration(self, metric_env):
        env, buffer = metric_env
        source = _make_source()
        with _extract_patches(source, [_make_schema()], []):
            env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        assert "cdc_extraction_duration_seconds" in _emitted_names(buffer)

    def test_failure_run_emits_duration_and_reraises(self, metric_env):
        env, buffer = metric_env
        source = _make_source()
        with _extract_patches(source, [_make_schema()], []) as (_, reader, _s3):
            reader.read_changes.side_effect = RuntimeError("boom")
            with pytest.raises(RuntimeError, match="boom"):
                env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        assert "cdc_extraction_duration_seconds" in _emitted_names(buffer)

    def test_slot_advance_failure_emits_failure_metric(self, metric_env):
        env, buffer = metric_env
        source = _make_source()
        events = [_make_event(position="0/100")]
        with _extract_patches(source, [_make_schema()], events) as (_, reader, _s3):
            reader.confirm_position.side_effect = RuntimeError("advance failed")
            with pytest.raises(RuntimeError, match="advance failed"):
                env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        assert "cdc_slot_advance_failures_total" in _emitted_names(buffer)

    def test_micro_flush_emits_micro_batch_metric(self, metric_env):
        env, buffer = metric_env
        source = _make_source()
        events = [_make_event(position="0/100"), _make_event(op="U", position="0/200")]
        # Force a mid-run flush so the read loop's micro-batch path runs.
        with _extract_patches(source, [_make_schema()], events):
            with patch.object(ChangeEventBatcher, "should_flush", property(lambda self: self.event_count > 0)):
                env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        assert "cdc_micro_batches_flushed_total" in _emitted_names(buffer)


def _sweeper_adapter(*, lag_bytes=0, retention_cap_mb=None):
    adapter = MagicMock()
    adapter.parse_cdc_config.side_effect = lambda source: PostgresCDCConfig.from_source(source)

    @contextmanager
    def _conn(source, connect_timeout=15):
        yield MagicMock()

    adapter.management_connection.side_effect = _conn
    adapter.get_lag_bytes.return_value = lag_bytes
    adapter.get_retention_cap_mb.return_value = retention_cap_mb
    return adapter


def _create_cdc_source(team, *, auto_drop_slot=True):
    return ExternalDataSource.objects.create(
        team_id=team.pk,
        source_id=str(uuid.uuid4()),
        connection_id=str(uuid.uuid4()),
        status="Completed",
        source_type="Postgres",
        job_inputs={
            "cdc_enabled": True,
            "cdc_management_mode": "posthog",
            "cdc_auto_drop_slot": auto_drop_slot,
            "cdc_slot_name": "posthog_slot",
            "cdc_publication_name": "posthog_pub",
        },
    )


@contextmanager
def _sweeper_patches(adapter):
    with (
        patch(f"{_ACTIVITIES}.HeartbeaterSync"),
        patch(f"{_ACTIVITIES}.close_old_connections"),
        patch(f"{_ACTIVITIES}.get_cdc_adapter", return_value=adapter),
        patch("products.data_warehouse.backend.logic.data_load.service.delete_cdc_extraction_schedule"),
    ):
        yield


@pytest.mark.django_db
class TestSweeperMetricsSmoke:
    def test_sweep_emits_lag_and_sweep_metrics(self, metric_env, team):
        env, buffer = metric_env
        _create_cdc_source(team)
        with _sweeper_patches(_sweeper_adapter(lag_bytes=10 * 1024 * 1024)):
            env.run(cleanup_orphan_slots_activity)

        names = _emitted_names(buffer)
        assert "cdc_wal_lag_bytes" in names
        assert "cdc_sweeper_sources_checked_total" in names
        assert "cdc_sweeper_duration_seconds" in names

    def test_auto_drop_emits_metric(self, metric_env, team):
        env, buffer = metric_env
        _create_cdc_source(team, auto_drop_slot=True)
        with _sweeper_patches(_sweeper_adapter(lag_bytes=5000 * 1024 * 1024)):
            env.run(cleanup_orphan_slots_activity)

        assert "cdc_auto_drop_total" in _emitted_names(buffer)
