import time
import uuid
import dataclasses
from collections.abc import AsyncIterator
from contextlib import contextmanager, nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from temporalio.common import MetricMeter
from temporalio.runtime import BUFFERED_METRIC_KIND_HISTOGRAM, MetricBuffer, Runtime, TelemetryConfig
from temporalio.testing import ActivityEnvironment

from products.warehouse_sources.backend.models.external_data_schema import CDC_SNAPSHOT_LANE_KEY
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc import metrics
from products.warehouse_sources.backend.temporal.data_imports.cdc.activities import (
    CDCExtractActivity,
    CDCExtractInput,
    cdc_extract_activity,
    cleanup_orphan_slots_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import ChangeEventBatcher
from products.warehouse_sources.backend.temporal.data_imports.cdc.buffer import (
    build_buffer_file_name,
    get_buffer_prefix,
    measures_backlog_this_run,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane import BUFFER_LANE
from products.warehouse_sources.backend.temporal.data_imports.cdc.tests.conformance_kit import MemoryObjectStore
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import CDCLag, ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.s3.common import strip_s3_protocol
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.config import PostgresCDCConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.position import PgLSN

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
        metrics.get_extraction_duration_metric("completed").record(1.5)
        metrics.get_sweeper_duration_metric().record(2.0)

    def test_gauges_set_without_raising(self):
        metrics.record_wal_lag(1, "s", 1024)
        metrics.record_buffer_backlog(1, "s", files=1, size_bytes=2, oldest_age_seconds=3)
        metrics.record_sweep_started(sources_total=1, timeout_seconds=1800)
        metrics.record_sweep_completed()


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


def _last_values(updates) -> dict[str, int | float]:
    return {update.metric.name: update.value for update in updates}


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


def _make_schema(cdc_mode="streaming", name="users"):
    schema = MagicMock()
    schema.id = uuid.uuid4()
    schema.name = name
    schema.team_id = 1
    schema.sync_type_config = {"cdc_mode": cdc_mode, "cdc_table_mode": "consolidated", "primary_key_columns": ["id"]}
    schema.cdc_mode = cdc_mode
    schema.cdc_table_mode = "consolidated"
    schema.enabled_columns = None
    schema.sync_frequency_interval = timedelta(minutes=5)
    schema.incremental_field = None
    schema.save = MagicMock()
    return schema


class _UnreachableStore(MemoryObjectStore):
    async def _iterdir(self, bucket: str, delimiter: str = "/", prefix: str = "") -> AsyncIterator[dict[str, Any]]:
        entries: tuple[dict[str, Any], ...] = ()
        for entry in entries:
            yield entry
        raise OSError("S3 is unreachable")


def _put_buffer_file(store: MemoryObjectStore, schema, *, seq: int, size: int, age: timedelta) -> None:
    key = (
        f"{strip_s3_protocol(get_buffer_prefix(schema.team_id, str(schema.id)))}/{build_buffer_file_name(seq, seq, 0)}"
    )
    store.objects[key] = b"x" * size
    store.modified[key] = datetime.now(tz=UTC) - age


@contextmanager
def _extract_patches(source, schemas, events, store=None, lag_bytes=0):
    reader = MagicMock()
    reader.read_changes.return_value = iter(events)
    reader.truncated_tables = []
    # Below CDC_MAX_CHANGES_PER_READ so the bounded read loop treats this as a single drained pass.
    reader.last_rows_consumed = len(events)
    reader.get_decoder_key_columns.return_value = []

    adapter = MagicMock()
    adapter.create_reader.return_value = reader
    adapter.is_slot_invalidation_error.return_value = False
    adapter.position_to_seq.side_effect = lambda position: PgLSN.deserialize(position).value
    adapter.get_lag.return_value = CDCLag(behind_bytes=lag_bytes, retention_cap_mb=None)

    with (
        patch(f"{_ACTIVITIES}.close_old_connections"),
        patch(f"{_ACTIVITIES}.ExternalDataSource") as MockSource,
        patch.object(CDCExtractActivity, "_get_cdc_schemas", return_value=schemas),
        patch.object(CDCExtractActivity, "_update_schema_sync_type_config"),
        patch(f"{_ACTIVITIES}.get_cdc_adapter", return_value=adapter),
        patch(f"{_ACTIVITIES}.CDCBufferWriter") as MockBufferWriter,
        patch(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.buffer.get_s3_client",
            return_value=store or MemoryObjectStore(),
        ),
    ):
        MockSource.objects.get.return_value = source
        # The real meter records only a float.
        MockBufferWriter.return_value.write_batch.return_value.write_duration_seconds = 0.01
        yield reader


class TestExtractionMetricsSmoke:
    def test_success_run_emits_events_advance_and_duration(self, metric_env):
        env, buffer = metric_env
        source = _make_source()
        events = [_make_event(position="0/100"), _make_event(op="U", position="0/200")]
        with _extract_patches(source, [_make_schema()], events):
            env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        updates = buffer.retrieve_updates()
        names = {update.metric.name for update in updates}
        assert "cdc_events_extracted_total" in names
        assert "cdc_slot_advance_total" in names
        histograms = [u for u in updates if u.metric.kind == BUFFERED_METRIC_KIND_HISTOGRAM]
        assert {u.metric.name for u in histograms} == {
            "cdc_extraction_duration_seconds",
            "cdc_buffer_write_duration_seconds",
        }
        assert not any({"team_id", "source_id"} & set(u.attributes) for u in histograms)
        runs = [u for u in updates if u.metric.name == "cdc_extraction_runs_total"]
        assert [(u.attributes["source_id"], u.attributes["status"], u.value) for u in runs] == [
            (str(source.id), "completed", 1)
        ]
        # Dashboards filter the buffer metrics on this label.
        assert {
            (u.metric.name, u.attributes.get("lane"))
            for u in updates
            if u.metric.name in {"cdc_buffer_files_written_total", "cdc_buffer_write_duration_seconds"}
        } == {
            ("cdc_buffer_files_written_total", "ingress"),
            ("cdc_buffer_write_duration_seconds", "ingress"),
        }

    @pytest.mark.parametrize("fails", [False, True], ids=["completed", "failed"])
    def test_run_records_lag_and_streaming_backlog(self, metric_env, fails):
        env, buffer = metric_env
        source = _make_source()
        streaming = _make_schema()
        snapshotting = _make_schema(cdc_mode="snapshot", name="orders")
        snapshotting.sync_type_config[CDC_SNAPSHOT_LANE_KEY] = BUFFER_LANE
        store = MemoryObjectStore()
        _put_buffer_file(store, streaming, seq=1, size=10, age=timedelta(hours=2))
        _put_buffer_file(store, streaming, seq=2, size=5, age=timedelta(minutes=1))
        _put_buffer_file(store, snapshotting, seq=1, size=100, age=timedelta(days=1))
        observed_from = int(time.time())

        with _extract_patches(source, [streaming, snapshotting], [], store=store, lag_bytes=4096) as reader:
            if fails:
                reader.read_changes.side_effect = RuntimeError("boom")
            with pytest.raises(RuntimeError) if fails else nullcontext():
                env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        values = _last_values(buffer.retrieve_updates())
        assert values["cdc_wal_lag_bytes"] == 4096
        assert (values["cdc_buffer_backlog_files"], values["cdc_buffer_backlog_bytes"]) == (2, 15)
        assert 7200 <= values["cdc_buffer_backlog_oldest_age_seconds"] < 7260
        assert values["cdc_wal_lag_observed_at_seconds"] >= observed_from
        assert values["cdc_buffer_backlog_observed_at_seconds"] >= observed_from

    @pytest.mark.parametrize("stopped_by", ["unreachable_source", "worker_shutdown"])
    def test_run_skips_the_lag_login_it_cannot_use(self, metric_env, stopped_by):
        env, buffer = metric_env
        source = _make_source()
        inputs = CDCExtractInput(team_id=1, source_id=source.id)

        with _extract_patches(source, [_make_schema()], [], lag_bytes=4096) as reader:
            if stopped_by == "unreachable_source":
                reader.connect.side_effect = RuntimeError("connection refused")
                with pytest.raises(RuntimeError):
                    env.run(cdc_extract_activity, inputs)
            else:
                env.run(lambda: CDCExtractActivity(inputs, should_stop=lambda: True).run())

        values = _last_values(buffer.retrieve_updates())
        assert "cdc_wal_lag_bytes" not in values
        # The backlog needs no source login, so only a shutdown skips it.
        assert ("cdc_buffer_backlog_files" in values) == (stopped_by == "unreachable_source")

    @pytest.mark.parametrize("in_slot", [True, False], ids=["in_its_slot", "outside_its_slot"])
    def test_run_measures_the_backlog_only_in_its_slot(self, metric_env, in_slot):
        env, buffer = metric_env
        source = _make_source()
        interval = timedelta(minutes=5)
        starts = [datetime(2026, 1, 1, tzinfo=UTC) + k * interval for k in range(6)]
        start = next(s for s in starts if measures_backlog_this_run(str(source.id), s, interval) == in_slot)
        env.info = dataclasses.replace(env.info, workflow_id=f"cdc-extraction-{source.id}-{start:%Y-%m-%dT%H:%M:%SZ}")

        with _extract_patches(source, [_make_schema()], [], lag_bytes=4096):
            env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        values = _last_values(buffer.retrieve_updates())
        assert values["cdc_wal_lag_bytes"] == 4096
        assert ("cdc_buffer_backlog_observed_at_seconds" in values) == in_slot

    def test_failed_backlog_listing_keeps_the_run_and_its_lag(self, metric_env):
        env, buffer = metric_env
        source = _make_source()
        store = _UnreachableStore()

        with _extract_patches(source, [_make_schema()], [], store=store, lag_bytes=4096):
            env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        values = _last_values(buffer.retrieve_updates())
        assert values["cdc_wal_lag_bytes"] == 4096
        assert "cdc_buffer_backlog_observed_at_seconds" not in values

    def test_no_changes_run_emits_duration(self, metric_env):
        env, buffer = metric_env
        source = _make_source()
        with _extract_patches(source, [_make_schema()], []):
            env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        assert "cdc_extraction_duration_seconds" in _emitted_names(buffer)

    def test_failure_run_emits_duration_and_reraises(self, metric_env):
        env, buffer = metric_env
        source = _make_source()
        with _extract_patches(source, [_make_schema()], []) as reader:
            reader.read_changes.side_effect = RuntimeError("boom")
            with pytest.raises(RuntimeError, match="boom"):
                env.run(cdc_extract_activity, CDCExtractInput(team_id=1, source_id=source.id))

        assert "cdc_extraction_duration_seconds" in _emitted_names(buffer)

    def test_slot_advance_failure_emits_failure_metric(self, metric_env):
        env, buffer = metric_env
        source = _make_source()
        events = [_make_event(position="0/100")]
        with _extract_patches(source, [_make_schema()], events) as reader:
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
    adapter.get_lag.return_value = (
        None if lag_bytes is None else CDCLag(behind_bytes=lag_bytes, retention_cap_mb=retention_cap_mb)
    )
    adapter.stream_exists.return_value = False
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

        values = _last_values(buffer.retrieve_updates())
        assert values["cdc_wal_lag_bytes"] == 10 * 1024 * 1024
        assert "cdc_wal_lag_observed_at_seconds" in values
        assert "cdc_sweeper_sources_checked_total" in values
        assert "cdc_sweeper_duration_seconds" in values
        assert (values["cdc_sweeper_sources_total"], values["cdc_sweeper_sources_processed"]) == (1, 1)
        assert values["cdc_sweeper_completed_at_seconds"] >= values["cdc_sweeper_started_at_seconds"] > 0

    def test_auto_drop_emits_metric(self, metric_env, team):
        env, buffer = metric_env
        _create_cdc_source(team, auto_drop_slot=True)
        with _sweeper_patches(_sweeper_adapter(lag_bytes=5000 * 1024 * 1024)):
            env.run(cleanup_orphan_slots_activity)

        assert "cdc_auto_drop_total" in _emitted_names(buffer)
