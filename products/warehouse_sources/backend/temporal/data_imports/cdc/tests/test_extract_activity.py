import uuid
from contextlib import nullcontext
from datetime import UTC, datetime
from typing import Literal

import pytest
from unittest.mock import MagicMock, patch

import pyarrow as pa
import psycopg.errors
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.cdc.activities import (
    CDC_MAX_CHANGES_PER_READ,
    SLOT_INVALIDATION_RECOVERY_MESSAGE,
    CDCExtractActivity,
    CDCExtractInput,
    cdc_extract_activity,
    cleanup_orphan_slots_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCErrorCategory, cdc_error_info
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.masking import mask_value
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException


def _make_event(
    op: Literal["I", "U", "D"] = "I",
    table: str = "users",
    position: str = "0/100",
    columns: dict | None = None,
) -> ChangeEvent:
    return ChangeEvent(
        operation=op,
        table_name=table,
        position_serialized=position,
        timestamp=datetime(2025, 6, 15, 12, 0, 0, tzinfo=UTC),
        columns=columns or {"id": 1, "name": "Alice"},
    )


def _make_source(source_id=None, job_inputs=None):
    source = MagicMock()
    source.id = source_id or uuid.uuid4()
    source.team_id = 1
    source.source_type = "Postgres"
    source.deleted = False
    source.created_at = datetime(2025, 1, 1, tzinfo=UTC)  # before the SSL cutoff unless overridden
    source.job_inputs = (
        job_inputs
        if job_inputs is not None
        else {
            "host": "localhost",
            "port": 5432,
            "database": "testdb",
            "user": "test",
            "password": "test",
            "cdc_slot_name": "posthog_slot",
            "cdc_publication_name": "posthog_pub",
        }
    )
    return source


def _make_schema(
    name,
    cdc_mode="streaming",
    cdc_table_mode="consolidated",
    source=None,
    schema_id=None,
    s3_folder_name=None,
    partitioning_enabled=False,
    partitioning_keys=None,
    partition_mode=None,
    partition_format=None,
    partition_count=None,
    partition_size=None,
):
    schema = MagicMock()
    schema.id = schema_id or uuid.uuid4()
    schema.name = name
    schema.team_id = 1
    schema.source = source
    schema.sync_type = "cdc"
    schema.sync_type_config = {"cdc_mode": cdc_mode, "cdc_table_mode": cdc_table_mode}
    schema.is_cdc = True
    schema.cdc_mode = cdc_mode
    schema.cdc_table_mode = cdc_table_mode
    schema.should_sync = True
    schema.deleted = False
    # Real values (not MagicMocks) so storage-name and partition helpers evaluate deterministically.
    schema.resolved_s3_folder_name = s3_folder_name
    schema.partitioning_enabled = partitioning_enabled
    schema.partitioning_keys = partitioning_keys
    schema.partition_mode = partition_mode
    schema.partition_format = partition_format
    schema.partition_count = partition_count
    schema.partition_size = partition_size
    schema.save = MagicMock()
    return schema


def _fake_update_schema_sync_type_config(schema, *, updates=None, removes=None, mutate=None, extra_model_fields=None):
    """Stand-in for CDCExtractActivity._update_schema_sync_type_config that merges onto the
    in-memory mock schema. The real helper re-reads the row from Postgres under a lock, which these
    mock-only tests don't have; this mirrors its merge order (updates, then removes, then mutate)
    and its post-merge application of `extra_model_fields` onto the schema."""
    config = schema.sync_type_config or {}
    if updates:
        config.update(updates)
    if removes:
        for key in removes:
            config.pop(key, None)
    if mutate is not None:
        mutate(config)
    schema.sync_type_config = config
    if extra_model_fields:
        for field, value in extra_model_fields.items():
            setattr(schema, field, value)


@pytest.fixture(autouse=True)
def _stub_sync_type_config_merge():
    """Route every activity sync_type_config write onto the in-memory mock schema (no DB)."""
    with patch.object(
        CDCExtractActivity,
        "_update_schema_sync_type_config",
        side_effect=_fake_update_schema_sync_type_config,
    ):
        yield


# Shared patch decorator for CDC activity tests
_CDC_ACTIVITY_PATCHES = [
    "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections",
    "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob",
    "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource",
    "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.CDCExtractActivity._get_cdc_schemas",
    "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter",
    "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter",
    "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer",
    "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity",
]


def _setup_mocks(
    mock_activity,
    MockProducer,
    MockS3Writer,
    mock_get_adapter,
    mock_get_schemas,
    MockSourceModel,
    MockJob,
    mock_close_conns,
    source,
    schemas,
    events,
):
    """Wire up the standard mocks for CDC activity tests."""
    MockSourceModel.objects.get.return_value = source
    mock_get_schemas.return_value = schemas

    mock_reader = MagicMock()
    mock_reader.read_changes.return_value = iter(events)
    mock_reader.truncated_tables = []
    # Below CDC_MAX_CHANGES_PER_READ so the bounded read loop treats this as a single drained pass.
    mock_reader.last_rows_consumed = len(events)
    mock_reader.get_decoder_key_columns.return_value = []
    mock_adapter = MagicMock()
    mock_adapter.create_reader.return_value = mock_reader
    mock_adapter.is_slot_invalidation_error.return_value = False
    mock_adapter.classify_error.return_value = None  # default: unrecognized -> unknown/retryable
    mock_get_adapter.return_value = mock_adapter

    mock_s3 = MagicMock()
    mock_batch_result = MagicMock()
    mock_batch_result.s3_path = "s3://bucket/data/part-0000.parquet"
    mock_batch_result.row_count = len(events)
    mock_batch_result.byte_size = 512
    mock_batch_result.batch_index = 0
    mock_batch_result.timestamp_ns = 123456
    mock_s3.write_batch.return_value = mock_batch_result
    mock_s3.write_schema.return_value = "s3://bucket/schema.json"
    mock_s3.get_data_folder.return_value = "s3://bucket/data/"
    MockS3Writer.return_value = mock_s3

    mock_producer = MagicMock()
    MockProducer.return_value = mock_producer

    mock_job = MagicMock()
    mock_job.id = uuid.uuid4()
    MockJob.objects.create.return_value = mock_job
    MockJob.PipelineVersion.V2 = "v2-non-dlt"
    MockJob.Status.RUNNING = "Running"
    MockJob.Status.COMPLETED = "Completed"
    MockJob.Status.FAILED = "Failed"

    mock_activity.heartbeat = MagicMock()
    mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1")

    return mock_reader, mock_s3, mock_producer, mock_job


class TestGetCDCAdapter:
    def test_returns_postgres_adapter(self):
        from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import get_cdc_adapter
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import (
            PostgresCDCAdapter,
        )

        source = _make_source()
        adapter = get_cdc_adapter(source)
        assert isinstance(adapter, PostgresCDCAdapter)

    def test_raises_for_unsupported_source(self):
        from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import get_cdc_adapter

        source = _make_source()
        source.source_type = "UnsupportedDB"
        with pytest.raises(ValueError, match="CDC is not supported"):
            get_cdc_adapter(source)

    def test_create_reader_extracts_params(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import (
            PostgresCDCAdapter,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader import (
            PgCDCStreamReader,
        )

        adapter = PostgresCDCAdapter()
        source = _make_source()
        reader = adapter.create_reader(source)
        assert isinstance(reader, PgCDCStreamReader)

        assert reader._params.host == "localhost"
        assert reader._params.port == 5432
        assert reader._params.database == "testdb"
        assert reader._params.slot_name == "posthog_slot"
        assert reader._params.publication_name == "posthog_pub"

    def test_create_reader_defaults_when_missing(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import (
            PostgresCDCAdapter,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader import (
            PgCDCStreamReader,
        )

        adapter = PostgresCDCAdapter()
        # Minimal connection inputs, omitting the cdc/slot fields to exercise their defaults.
        source = _make_source(
            job_inputs={"host": "localhost", "port": 5432, "database": "db", "user": "u", "password": "p"}
        )
        reader = adapter.create_reader(source)
        assert isinstance(reader, PgCDCStreamReader)

        assert reader._params.port == 5432
        assert reader._params.slot_name == ""
        assert reader._params.publication_name == ""

    def test_create_reader_requires_ssl_for_recent_source_without_tunnel(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import (
            PostgresCDCAdapter,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader import (
            PgCDCStreamReader,
        )

        adapter = PostgresCDCAdapter()
        source = _make_source()
        source.created_at = datetime(2026, 3, 1, tzinfo=UTC)  # after the SSL cutoff
        reader = adapter.create_reader(source)
        assert isinstance(reader, PgCDCStreamReader)
        assert reader._params.require_ssl is True

    def test_create_reader_honors_ssh_tunnel_tls_opt_out(self):
        # Two-arg source_requires_ssl: a recent source reached over an SSH tunnel that opted
        # out of TLS must NOT be force-upgraded on the data path (single-arg would return True).
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import (
            PostgresCDCAdapter,
        )
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.stream_reader import (
            PgCDCStreamReader,
        )

        adapter = PostgresCDCAdapter()
        source = _make_source()
        source.created_at = datetime(2026, 3, 1, tzinfo=UTC)  # after the SSL cutoff

        opted_out_config = MagicMock()
        opted_out_config.ssh_tunnel = MagicMock(enabled=True, require_tls=MagicMock(enabled=False))
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source.PostgresSource.parse_config",
            return_value=opted_out_config,
        ):
            reader = adapter.create_reader(source)
        assert isinstance(reader, PgCDCStreamReader)
        assert reader._params.require_ssl is False


def _make_extract_activity(source, log=None) -> CDCExtractActivity:
    """Build a CDCExtractActivity with source and log pre-injected for unit tests."""
    activity_obj = CDCExtractActivity(CDCExtractInput(team_id=1, source_id=source.id))
    activity_obj.source = source
    activity_obj.log = log or MagicMock()
    return activity_obj


class TestFlushDeferredRuns:
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    def test_sends_kafka_messages_for_deferred_runs(self, MockProducer):
        mock_producer = MagicMock()
        MockProducer.return_value = mock_producer

        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_deferred_runs"] = [
            {
                "job_id": "job-1",
                "run_uuid": "run-1",
                "data_folder": "s3://bucket/data/",
                "schema_path": "s3://bucket/schema.json",
                "total_batches": 1,
                "total_rows": 10,
                "batch_results": [
                    {
                        "s3_path": "s3://bucket/data/part-0000.parquet",
                        "row_count": 10,
                        "byte_size": 1024,
                        "batch_index": 0,
                        "timestamp_ns": 123456789,
                    }
                ],
            }
        ]

        _make_extract_activity(source)._flush_deferred_runs(schema)

        mock_producer.send_batch_notification.assert_called_once()
        mock_producer.flush.assert_called_once()

        assert schema.sync_type_config["cdc_deferred_runs"] == []

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    def test_no_op_when_no_deferred_runs(self, MockProducer):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config = {"cdc_mode": "streaming"}

        _make_extract_activity(source)._flush_deferred_runs(schema)

        MockProducer.assert_not_called()
        schema.save.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    def test_multiple_deferred_runs(self, MockProducer):
        mock_producer = MagicMock()
        MockProducer.return_value = mock_producer

        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_deferred_runs"] = [
            {
                "job_id": f"job-{i}",
                "run_uuid": f"run-{i}",
                "data_folder": f"s3://bucket/data-{i}/",
                "schema_path": f"s3://bucket/schema-{i}.json",
                "total_batches": 1,
                "total_rows": 5,
                "batch_results": [
                    {
                        "s3_path": f"s3://bucket/data-{i}/part-0000.parquet",
                        "row_count": 5,
                        "byte_size": 512,
                        "batch_index": 0,
                    }
                ],
            }
            for i in range(3)
        ]

        _make_extract_activity(source)._flush_deferred_runs(schema)

        # 3 deferred runs, each with 1 batch → 3 send calls, 3 flush calls (one per producer)
        assert mock_producer.send_batch_notification.call_count == 3
        assert mock_producer.flush.call_count == 3
        assert schema.sync_type_config["cdc_deferred_runs"] == []

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    def test_deferred_flush_uses_stored_resource_name_and_replays_partition_config(self, MockProducer):
        """Deferred flush targets the stored Delta resource and replays partition config."""
        mock_producer = MagicMock()
        MockProducer.return_value = mock_producer

        source = _make_source()
        # Folder pinned bare while `name` is qualified, plus partitioning — exercises both fixes.
        schema = _make_schema(
            "public.users",
            cdc_mode="streaming",
            source=source,
            s3_folder_name="users",
            partitioning_enabled=True,
            partitioning_keys=["id"],
            partition_mode="numerical",
            partition_size=1_000_000,
        )
        schema.sync_type_config["cdc_deferred_runs"] = [
            {
                "job_id": "job-1",
                "run_uuid": "run-1",
                "resource_name": "users",
                "data_folder": "s3://bucket/data/",
                "schema_path": "s3://bucket/schema.json",
                "total_batches": 1,
                "total_rows": 10,
                "batch_results": [
                    {
                        "s3_path": "s3://bucket/data/part-0000.parquet",
                        "row_count": 10,
                        "byte_size": 1024,
                        "batch_index": 0,
                        "timestamp_ns": 123456789,
                    }
                ],
            }
        ]

        _make_extract_activity(source)._flush_deferred_runs(schema)

        kwargs = MockProducer.call_args.kwargs
        assert kwargs["resource_name"] == "users"
        assert kwargs["partition_keys"] == ["id"]
        assert kwargs["partition_mode"] == "numerical"
        assert kwargs["partition_size"] == 1_000_000


class TestBuildEventNameMap:
    @pytest.mark.parametrize(
        "schema_name,schema_metadata,source_schema_config,wal_event_name,expected_canonical",
        [
            # Path 1: schema_metadata resolves the source-qualified name.
            ("orders", {"source_schema": "public", "source_table_name": "orders"}, None, "public.orders", "orders"),
            # Path 2: no metadata, but `name` is already schema-qualified.
            ("public.orders", None, None, "public.orders", "public.orders"),
            # Path 3: no metadata, bare name — falls back to the source's default schema.
            ("orders", None, "analytics", "analytics.orders", "orders"),
            # Path 3: no metadata, bare name, no default schema — falls back to "public".
            ("orders", None, None, "public.orders", "orders"),
        ],
    )
    def test_resolves_wal_event_name_to_canonical_schema_name(
        self, schema_name, schema_metadata, source_schema_config, wal_event_name, expected_canonical
    ):
        source = _make_source(job_inputs={"schema": source_schema_config} if source_schema_config else {})
        schema = _make_schema(schema_name, cdc_mode="streaming", source=source)
        schema.sync_type_config = {"cdc_mode": "streaming", "cdc_table_mode": "consolidated"}
        if schema_metadata is not None:
            schema.sync_type_config["schema_metadata"] = schema_metadata

        activity_obj = _make_extract_activity(source)
        activity_obj.cdc_schemas = [schema]

        assert activity_obj._build_event_name_map().get(wal_event_name) == expected_canonical


class TestCDCExtractActivity:
    """Integration tests for cdc_extract_activity with mocked external deps."""

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_streaming_schema_writes_s3_and_sends_kafka(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"}),
            _make_event(op="U", table="users", position="0/200", columns={"id": 1, "name": "Bob"}),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        mock_reader.connect.assert_called_once()
        mock_s3.write_batch.assert_called_once()
        mock_producer.send_batch_notification.assert_called_once()
        mock_producer.flush.assert_called_once()
        mock_reader.confirm_position.assert_called_once_with("0/200")
        mock_reader.close.assert_called_once()

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_bare_named_schema_matches_schema_qualified_wal_events(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        """A schema whose `name` is stored bare (no `public.` prefix) must still match the
        schema-qualified table name the WAL stream emits. Otherwise every change is silently
        dropped and the table goes stale despite a healthy slot."""
        source = _make_source()
        # `name` is bare, but schema_metadata resolves the real source location.
        schema = _make_schema("product_productintegrationevent", cdc_mode="streaming", source=source)
        schema.sync_type_config["schema_metadata"] = {
            "source_schema": "public",
            "source_table_name": "product_productintegrationevent",
        }
        schema.sync_type_config["primary_key_columns"] = ["id"]
        # WAL events arrive schema-qualified, as Postgres logical decoding always emits them.
        events = [
            _make_event(op="I", table="public.product_productintegrationevent", position="0/100"),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # The change was captured, not dropped by the table-name filter.
        mock_s3.write_batch.assert_called()
        mock_producer.send_batch_notification.assert_called()
        mock_reader.confirm_position.assert_called_once_with("0/100")

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_streaming_job_not_marked_completed_by_activity(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        """For streaming schemas, the activity should NOT mark the job as COMPLETED.
        The Kafka consumer marks it after loading to DeltaLake."""
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # No save call for the job should include "status" in update_fields
        mock_job.save.assert_called()
        for call in mock_job.save.call_args_list:
            assert "status" not in call.kwargs.get("update_fields", [])

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_snapshot_schema_writes_s3_defers_kafka_and_marks_job_completed(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        """Snapshot schemas write to S3 and defer the Kafka notification (stored in
        sync_type_config) until the schema transitions to streaming. The job is marked
        COMPLETED immediately since no Kafka consumer will process it."""
        source = _make_source()
        schema = _make_schema("users", cdc_mode="snapshot", source=source)
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        mock_s3.write_batch.assert_called_once()
        MockProducer.assert_not_called()

        deferred = schema.sync_type_config.get("cdc_deferred_runs", [])
        assert len(deferred) == 1
        assert deferred[0]["run_uuid"] is not None
        assert deferred[0]["total_rows"] == 1

        mock_reader.confirm_position.assert_called_once_with("0/100")

        # Job is completed by the activity (no Kafka consumer to do it)
        assert any("status" in call.kwargs.get("update_fields", []) for call in mock_job.save.call_args_list)

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_no_changes_returns_early_with_completed_status(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source

        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock()
        mock_reader.read_changes.return_value = iter([])
        mock_reader.truncated_tables = []
        mock_reader.last_rows_consumed = 0
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_get_adapter.return_value = mock_adapter

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # No slot advance and reader still cleaned up
        mock_reader.confirm_position.assert_not_called()
        mock_reader.close.assert_called_once()

        # Schema marked completed even with no changes
        schema.save.assert_called()
        assert schema.status == "Completed"
        assert schema.latest_error is None
        assert schema.last_synced_at is not None

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_no_cdc_schemas_returns_early(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source
        mock_get_schemas.return_value = []

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        mock_get_adapter.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_events_for_unknown_tables_are_filtered(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", table="users", position="0/100"),
            _make_event(op="I", table="other_table", position="0/200"),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Only 1 S3 write (for "users"), not for "other_table"
        mock_s3.write_batch.assert_called_once()
        call_args = mock_s3.write_batch.call_args
        pa_table = call_args[0][0]
        assert pa_table.num_rows == 1

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_reader_closed_on_error(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source

        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock()
        mock_reader.read_changes.side_effect = RuntimeError("connection lost")
        mock_reader.truncated_tables = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_adapter.is_slot_invalidation_error.return_value = False
        mock_adapter.classify_error.return_value = None
        mock_get_adapter.return_value = mock_adapter

        # Retryable on a non-final attempt: no failure-visibility row, so ExternalDataJob is untouched.
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1", attempt=1)

        inputs = CDCExtractInput(team_id=1, source_id=source.id)

        with pytest.raises(RuntimeError, match="connection lost"):
            cdc_extract_activity(inputs)

        mock_reader.close.assert_called_once()

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_schema_status_set_to_failed_on_error(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        # Make S3 write fail
        mock_s3.write_batch.side_effect = RuntimeError("S3 write failed")

        inputs = CDCExtractInput(team_id=1, source_id=source.id)

        with pytest.raises(RuntimeError, match="S3 write failed"):
            cdc_extract_activity(inputs)

        # Schema is marked FAILED with the friendly message — the raw error never reaches the user.
        assert schema.status == "Failed"
        assert schema.latest_error == cdc_error_info(CDCErrorCategory.UNKNOWN).friendly_message
        assert "S3 write failed" not in schema.latest_error

        # A RUNNING job already exists (created before the flush failed), so the failure path must
        # NOT add a second failure-visibility row — only the original job is created and then failed.
        MockJob.objects.create.assert_called_once()

        # Slot should NOT have been advanced
        mock_reader.confirm_position.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_unmergeable_schema_fails_non_retryably(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        # A cross-batch Arrow merge conflict (a column that drifted type mid-stream) surfaces
        # from write_batch as ArrowTypeError. Replaying re-fails identically, so the run must
        # stop rather than loop the schedule.
        mock_s3.write_batch.side_effect = pa.ArrowTypeError(
            "Unable to merge: Field seats has incompatible types: int64 vs string"
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)

        with pytest.raises(NonRetryableException):
            cdc_extract_activity(inputs)

        assert schema.status == "Failed"
        assert schema.latest_error == cdc_error_info(CDCErrorCategory.SCHEMA_MERGE_INCOMPATIBLE).friendly_message
        # The raw column/type detail never reaches the user-facing message.
        assert "int64" not in schema.latest_error
        mock_reader.confirm_position.assert_not_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_cdc_last_log_position_updated_per_schema(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", table="users", position="0/100"),
            _make_event(op="U", table="users", position="0/200"),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # cdc_last_log_position should be updated to the last event's position
        assert schema.sync_type_config["cdc_last_log_position"] == "0/200"

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.unpause_external_data_schedule",
        create=True,
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_truncate_only_batch_sets_snapshot_and_advances_slot(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
        mock_unpause,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source

        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock()
        mock_reader.read_changes.return_value = iter([])  # no DML events
        mock_reader.truncated_tables = ["users"]
        mock_reader.last_rows_consumed = 0
        mock_reader.last_commit_end_lsn = "0/500"
        mock_reader.get_decoder_key_columns.return_value = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_get_adapter.return_value = mock_adapter

        mock_activity.heartbeat = MagicMock()
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1")

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        assert schema.sync_type_config["cdc_mode"] == "snapshot"
        assert schema.sync_type_config["reset_pipeline"] is True
        assert schema.initial_sync_complete is False
        mock_reader.confirm_position.assert_called_once_with("0/500")

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.unpause_external_data_schedule",
        create=True,
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_truncate_sets_snapshot_mode(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
        mock_unpause,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        # Simulate a truncate for the "users" table
        mock_reader.truncated_tables = ["users"]

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Schema should be set back to snapshot mode and forced to re-snapshot from scratch
        assert schema.sync_type_config["cdc_mode"] == "snapshot"
        assert schema.sync_type_config["reset_pipeline"] is True
        assert schema.initial_sync_complete is False
        assert "cdc_last_log_position" not in schema.sync_type_config

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_multi_table_events_grouped_correctly(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        users_schema = _make_schema("users", cdc_mode="streaming", source=source)
        orders_schema = _make_schema("orders", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"}),
            _make_event(op="I", table="orders", position="0/200", columns={"id": 10, "total": 99}),
            _make_event(op="U", table="users", position="0/300", columns={"id": 1, "name": "Bob"}),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [users_schema, orders_schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Should have 2 S3 writes (one for users, one for orders)
        assert mock_s3.write_batch.call_count == 2

        # Should have 2 Kafka producers (one for each table)
        assert MockProducer.call_count == 2

        # Slot should advance to the last event's position
        mock_reader.confirm_position.assert_called_once_with("0/300")

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_unchanged_sibling_table_logs_no_changes_breadcrumb(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        users_schema = _make_schema("users", cdc_mode="streaming", source=source)
        orders_schema = _make_schema("orders", cdc_mode="streaming", source=source)
        # Only `users` changes this run; `orders` is idle.
        events = [_make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"})]

        _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [users_schema, orders_schema],
            events,
        )

        schema_loggers: dict[str, MagicMock] = {}

        def fake_schema_log(schema):
            return schema_loggers.setdefault(schema.name, MagicMock())

        with patch.object(CDCExtractActivity, "_schema_log", side_effect=fake_schema_log):
            cdc_extract_activity(CDCExtractInput(team_id=1, source_id=source.id))

        def logged_events(name: str) -> list[str]:
            return [call.args[0] for call in schema_loggers[name].info.call_args_list]

        assert "cdc_extract_no_changes" in logged_events("orders")
        assert "cdc_extract_no_changes" not in logged_events("users")

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.unpause_external_data_schedule",
        create=True,
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_truncated_schema_log_position_not_updated(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
        mock_unpause,
    ):
        """A schema reset to snapshot mode by a TRUNCATE should not have
        cdc_last_log_position updated — it will re-snapshot from scratch."""
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_last_log_position"] = "0/OLD"
        events = [_make_event(op="I", table="users", position="0/100")]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )
        mock_reader.truncated_tables = ["users"]

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        assert schema.sync_type_config.get("cdc_mode") == "snapshot"
        assert schema.sync_type_config.get("reset_pipeline") is True
        assert schema.sync_type_config.get("cdc_last_log_position") is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_both_mode_creates_two_trackers(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_table_mode"] = "both"
        schema.cdc_table_mode = "both"
        events = [_make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"})]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Two S3 writes: one for the consolidated table, one for the _cdc table
        assert mock_s3.write_batch.call_count == 2

        written_tables = [call[0][0] for call in mock_s3.write_batch.call_args_list]
        consolidated_table = written_tables[0]
        cdc_table = written_tables[1]

        # Consolidated table: 1 row (deduplicated INSERT), no valid_from/valid_to
        assert consolidated_table.num_rows == 1
        assert "valid_from" not in consolidated_table.column_names
        assert "valid_to" not in consolidated_table.column_names

        # _cdc table: 1 row with SCD2 columns
        assert cdc_table.num_rows == 1
        assert "valid_from" in cdc_table.column_names
        assert "valid_to" in cdc_table.column_names

        # Two Kafka producers: one with incremental_merge, one with scd2_append
        assert MockProducer.call_count == 2
        write_modes = {call.kwargs["cdc_write_mode"] for call in MockProducer.call_args_list}
        assert write_modes == {"incremental_merge", "scd2_append"}

        resource_names = {call.kwargs["resource_name"] for call in MockProducer.call_args_list}
        assert resource_names == {"users", "users_cdc"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_consolidated_table_uses_pinned_folder_name_not_schema_name(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        """Consolidated CDC writes use the pinned folder for bare→qualified schemas."""
        source = _make_source()
        # `name` is qualified, but the folder was pinned to the original bare path during migration.
        schema = _make_schema("public.users", cdc_mode="streaming", source=source, s3_folder_name="users")
        events = [_make_event(op="I", table="public.users", position="0/100", columns={"id": 1, "name": "Alice"})]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        mock_s3.write_batch.assert_called_once()
        assert MockProducer.call_count == 1
        # The fix: storage resource name is the pinned folder ("users"), not "public.users".
        assert MockProducer.call_args.kwargs["resource_name"] == "users"

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_partition_config_replayed_to_loader_when_snapshot_partitioned(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        """Partitioned snapshots replay their partition config to CDC batch notifications."""
        source = _make_source()
        schema = _make_schema(
            "users",
            cdc_mode="streaming",
            source=source,
            partitioning_enabled=True,
            partitioning_keys=["id"],
            partition_mode="numerical",
            partition_size=1_000_000,
        )
        events = [_make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"})]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        assert MockProducer.call_count == 1
        kwargs = MockProducer.call_args.kwargs
        assert kwargs["partition_keys"] == ["id"]
        assert kwargs["partition_mode"] == "numerical"
        assert kwargs["partition_size"] == 1_000_000

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_partition_config_omitted_when_snapshot_unpartitioned(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        """Unpartitioned snapshots do not send partition config to CDC batch notifications."""
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source, partitioning_enabled=False)
        events = [_make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"})]

        _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        assert MockProducer.call_count == 1
        kwargs = MockProducer.call_args.kwargs
        assert kwargs.get("partition_keys") is None
        assert kwargs.get("partition_mode") is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_cdc_only_mode_creates_single_cdc_tracker(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_table_mode"] = "cdc_only"
        schema.cdc_table_mode = "cdc_only"
        events = [_make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"})]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Only one S3 write for the _cdc resource
        mock_s3.write_batch.assert_called_once()
        written_table = mock_s3.write_batch.call_args[0][0]
        assert written_table.num_rows == 1
        assert "valid_from" in written_table.column_names
        assert "valid_to" in written_table.column_names

        # Only one Kafka producer with scd2_append and _cdc resource name
        assert MockProducer.call_count == 1
        producer_kwargs = MockProducer.call_args.kwargs
        assert producer_kwargs["resource_name"] == "users_cdc"
        assert producer_kwargs["cdc_write_mode"] == "scd2_append"

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ChangeEventBatcher")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_micro_batch_flush_sends_kafka_immediately(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
        MockBatcher,
    ):
        from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
            ChangeEventBatcher as RealBatcher,
        )

        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_table_mode"] = "consolidated"
        schema.cdc_table_mode = "consolidated"
        events = [
            _make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"}),
            _make_event(op="I", table="users", position="0/200", columns={"id": 2, "name": "Bob"}),
            _make_event(op="I", table="users", position="0/300", columns={"id": 3, "name": "Charlie"}),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        # Use a real batcher with max_events=2 so after the 2nd event should_flush is True
        MockBatcher.return_value = RealBatcher(max_events=2)

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # 2 events trigger a micro-batch flush (non-final), then 1 event triggers the final flush
        # Each flush produces one S3 write and one Kafka send
        assert mock_s3.write_batch.call_count == 2
        assert mock_producer.send_batch_notification.call_count == 2

        # Micro-batch (first call) is NOT the final batch; final flush IS
        send_calls = mock_producer.send_batch_notification.call_args_list
        assert send_calls[0].kwargs["is_final_batch"] is False
        assert send_calls[1].kwargs["is_final_batch"] is True

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_deferred_run_stored_per_batch_for_snapshot_schema(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="snapshot", source=source)
        schema.sync_type_config["cdc_table_mode"] = "consolidated"
        schema.cdc_table_mode = "consolidated"
        events = [
            _make_event(op="I", table="users", position="0/100", columns={"id": 1, "name": "Alice"}),
            _make_event(op="I", table="users", position="0/200", columns={"id": 2, "name": "Bob"}),
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        # Snapshot mode defers Kafka — no producer should be created during extraction
        MockProducer.assert_not_called()

        # Exactly one deferred run entry (one tracker for the consolidated table)
        deferred = schema.sync_type_config.get("cdc_deferred_runs", [])
        assert len(deferred) == 1

        entry = deferred[0]
        assert entry["run_uuid"] is not None
        assert len(entry["batch_results"]) == 1
        batch = entry["batch_results"][0]
        assert batch["s3_path"] == "s3://bucket/data/part-0000.parquet"
        assert batch["row_count"] == len(events)

        # Job should be marked COMPLETED by the activity (no Kafka consumer will do it)
        assert any("status" in call.kwargs.get("update_fields", []) for call in mock_job.save.call_args_list)


class TestSlotAdvanceTransactionSafety:
    """The slot must only advance past FULLY-yielded transactions.

    A micro-flush can fire mid-transaction (the batcher threshold is per-event).
    Since every event of a transaction shares its commit end LSN, advancing to that
    LSN while the transaction's tail is still un-yielded would lose the tail on crash.
    """

    @pytest.mark.parametrize(
        "event_positions,max_events,crashes,expected_advances",
        [
            # Mid-transaction flush: txn-1 (0/100) ×2 then txn-2 (0/200) ×3, flush after
            # 4 events lands mid txn-2. The micro-flush advances only to txn-1's end LSN;
            # the final flush advances to txn-2's.
            (["0/100", "0/100", "0/200", "0/200", "0/200"], 4, False, ["0/100", "0/200"]),
            # Single transaction (one commit LSN): a threshold of 2 forces a mid-transaction
            # micro-flush, but the transaction never completes during the loop, so no
            # micro-advance may happen — only the final flush advances, once.
            (["0/100", "0/100", "0/100"], 2, False, ["0/100"]),
            # Crash mid txn-2 (after the micro-flush at 4 events, before txn-2 finishes):
            # the slot stays at txn-1's end and must never reach txn-2's LSN.
            (["0/100", "0/100", "0/200", "0/200"], 4, True, ["0/100"]),
        ],
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ChangeEventBatcher")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_slot_advances_only_past_completed_transactions(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
        MockBatcher,
        event_positions,
        max_events,
        crashes,
        expected_advances,
    ):
        from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
            ChangeEventBatcher as RealBatcher,
        )

        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", table="users", position=pos, columns={"id": i}) for i, pos in enumerate(event_positions)
        ]

        mock_reader, mock_s3, mock_producer, mock_job = _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        if crashes:
            # The source dies after yielding the listed events but before txn-2 finishes.
            def _dying_changes():
                yield from events
                raise RuntimeError("pod killed mid-transaction")

            mock_reader.read_changes.return_value = _dying_changes()

        MockBatcher.return_value = RealBatcher(max_events=max_events)

        run_ctx = pytest.raises(RuntimeError, match="pod killed mid-transaction") if crashes else nullcontext()
        with run_ctx:
            cdc_extract_activity(CDCExtractInput(team_id=1, source_id=source.id))

        advanced_positions = [c.args[0] for c in mock_reader.confirm_position.call_args_list]
        assert advanced_positions == expected_advances


class TestErrorClassification:
    """Failures store a friendly, credential-safe message; non-retryable ones stop Temporal retries."""

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_machine_id",
        return_value="machine-1",
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.posthoganalytics")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_non_retryable_error_raises_nonretryable_and_captures(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
        mock_posthoganalytics,
        mock_get_machine_id,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock()
        mock_reader.read_changes.side_effect = psycopg.errors.InvalidPassword(
            'password authentication failed for user "test"'
        )
        mock_reader.truncated_tables = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_adapter.is_slot_invalidation_error.return_value = False
        mock_adapter.classify_error = PostgresCDCAdapter().classify_error  # exercise real classification
        mock_get_adapter.return_value = mock_adapter

        mock_activity.heartbeat = MagicMock()
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1", attempt=1)

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        with pytest.raises(NonRetryableException):
            cdc_extract_activity(inputs)

        assert schema.status == "Failed"
        assert schema.latest_error == cdc_error_info(CDCErrorCategory.AUTH_FAILED).friendly_message

        mock_posthoganalytics.capture.assert_called_once()
        captured = mock_posthoganalytics.capture.call_args.kwargs
        assert captured["event"] == "cdc extraction non-retryable error"
        assert captured["properties"]["category"] == "auth_failed"
        assert captured["properties"]["source_id"] == str(source.id)
        mock_reader.close.assert_called_once()

    @parameterized.expand(
        [
            (
                "slot_missing",
                psycopg.errors.UndefinedObject,
                'replication slot "posthog_slot" does not exist',
                "slot_missing",
            ),
            (
                "publication_missing",
                psycopg.errors.UndefinedObject,
                'publication "posthog_pub" does not exist',
                "publication_missing",
            ),
            ("auth_failed", psycopg.errors.InvalidPassword, 'password authentication failed for user "test"', None),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.mark_cdc_broken")
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_machine_id",
        return_value="machine-1",
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.posthoganalytics")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_missing_slot_or_publication_marks_cdc_broken(
        self,
        _name,
        exc_cls,
        exc_message,
        expected_reason,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
        mock_posthoganalytics,
        mock_get_machine_id,
        mock_mark_broken,
    ):
        # A missing slot/publication is non-retryable and must trip mark_cdc_broken (pause + persist
        # the broken marker) so the schedule stops firing against a resource that no longer exists.
        # A transient auth failure, equally non-retryable, must NOT — it could recover.
        source = _make_source()
        MockSourceModel.objects.get.return_value = source
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock()
        mock_reader.read_changes.side_effect = exc_cls(exc_message)
        mock_reader.truncated_tables = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_adapter.is_slot_invalidation_error.return_value = False
        mock_adapter.classify_error = PostgresCDCAdapter().classify_error
        mock_get_adapter.return_value = mock_adapter

        mock_activity.heartbeat = MagicMock()
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1", attempt=1)

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        with pytest.raises(NonRetryableException):
            cdc_extract_activity(inputs)

        if expected_reason is None:
            mock_mark_broken.assert_not_called()
        else:
            mock_mark_broken.assert_called_once()
            assert mock_mark_broken.call_args.args[0] is source
            assert mock_mark_broken.call_args.args[1] == expected_reason

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_machine_id",
        return_value="machine-1",
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.posthoganalytics")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_analytics_failure_does_not_mask_nonretryable(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
        mock_posthoganalytics,
        mock_get_machine_id,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock()
        mock_reader.read_changes.side_effect = psycopg.errors.InvalidPassword(
            'password authentication failed for user "test"'
        )
        mock_reader.truncated_tables = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_adapter.is_slot_invalidation_error.return_value = False
        mock_adapter.classify_error = PostgresCDCAdapter().classify_error
        mock_get_adapter.return_value = mock_adapter

        mock_activity.heartbeat = MagicMock()
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1", attempt=1)

        # Analytics is down — it must not swallow or replace the NonRetryableException.
        mock_posthoganalytics.capture.side_effect = RuntimeError("analytics down")

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        with pytest.raises(NonRetryableException):
            cdc_extract_activity(inputs)

        assert schema.latest_error == cdc_error_info(CDCErrorCategory.AUTH_FAILED).friendly_message

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_machine_id",
        return_value="machine-1",
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.posthoganalytics")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_retryable_error_reraises_original_and_does_not_capture(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
        mock_posthoganalytics,
        mock_get_machine_id,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock()
        mock_reader.read_changes.side_effect = psycopg.OperationalError(
            'connection to server at "db" failed: Connection refused'
        )
        mock_reader.truncated_tables = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_adapter.is_slot_invalidation_error.return_value = False
        mock_adapter.classify_error = PostgresCDCAdapter().classify_error
        mock_get_adapter.return_value = mock_adapter

        mock_activity.heartbeat = MagicMock()
        # Non-final attempt + retryable: no failure-visibility row, ExternalDataJob stays untouched.
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1", attempt=1)

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        # Retryable: the ORIGINAL error propagates so Temporal retries — not NonRetryableException.
        with pytest.raises(psycopg.OperationalError, match="Connection refused"):
            cdc_extract_activity(inputs)

        assert schema.latest_error == cdc_error_info(CDCErrorCategory.CONNECTION_FAILED).friendly_message
        mock_posthoganalytics.capture.assert_not_called()


class TestSlotInvalidationRecovery:
    """When the replication slot is invalidated/dropped on the source DB, the activity
    must recreate it and reset all CDC schemas to snapshot mode instead of failing forever."""

    def _setup(self, mock_get_schemas, mock_get_adapter, MockSourceModel, mock_activity):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source

        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_last_log_position"] = "0/OLD"
        schema.sync_type_config["cdc_deferred_runs"] = [{"run_uuid": "stale"}]
        mock_get_schemas.return_value = [schema]

        invalidation_error = psycopg.errors.ObjectNotInPrerequisiteState(
            'can no longer get changes from replication slot "posthog_slot"\n'
            "DETAIL:  This slot has been invalidated because it exceeded the maximum reserved size."
        )
        mock_reader = MagicMock()
        mock_reader.read_changes.side_effect = invalidation_error
        mock_reader.truncated_tables = []

        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_adapter.is_slot_invalidation_error.return_value = True
        mock_adapter.classify_error.return_value = None
        mock_get_adapter.return_value = mock_adapter

        mock_activity.heartbeat = MagicMock()
        # attempt=1 so the retryable recovery-failure paths don't create failure-visibility rows
        # (which would need ExternalDataJob mocked); job creation is covered in TestFailureVisibilityJobs.
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1", attempt=1)

        return source, schema, mock_reader, mock_adapter

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_invalidated_slot_is_recreated_and_schemas_reset_to_snapshot(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        source, schema, mock_reader, mock_adapter = self._setup(
            mock_get_schemas, mock_get_adapter, MockSourceModel, mock_activity
        )

        def _recreate_slot(source_arg, tables):
            # Schemas must already be reset when the slot is recreated — if recreation
            # fails, no schema may keep streaming across the gap on the next run.
            assert schema.sync_type_config["cdc_mode"] == "snapshot"
            return {"cdc_consistent_point": "0/AA"}

        mock_adapter.recreate_slot.side_effect = _recreate_slot

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        # Recovery handles the error — the activity must not raise (no pointless Temporal retries).
        cdc_extract_activity(inputs)

        mock_adapter.recreate_slot.assert_called_once_with(source, tables=["public.users"])
        assert source.job_inputs["cdc_consistent_point"] == "0/AA"
        source.save.assert_called()

        assert schema.sync_type_config["cdc_mode"] == "snapshot"
        assert schema.sync_type_config["reset_pipeline"] is True
        assert "cdc_last_log_position" not in schema.sync_type_config
        assert "cdc_deferred_runs" not in schema.sync_type_config
        assert schema.initial_sync_complete is False
        assert schema.status == "Failed"
        assert schema.latest_error == SLOT_INVALIDATION_RECOVERY_MESSAGE

        mock_reader.close.assert_called_once()

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_recreate_passes_source_qualified_table_names(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        # Recovery must resolve each schema's real source location from its metadata,
        # not assume every table lives in the source's default schema. Otherwise a table
        # in a non-default schema gets jammed under `public` and the publication rebuild
        # fails with `relation "public.tll.students" does not exist`.
        source, schema, mock_reader, mock_adapter = self._setup(
            mock_get_schemas, mock_get_adapter, MockSourceModel, mock_activity
        )
        schema.name = "students"
        schema.sync_type_config["schema_metadata"] = {"source_schema": "tll", "source_table_name": "students"}
        mock_adapter.recreate_slot.return_value = {"cdc_consistent_point": "0/AA"}

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        cdc_extract_activity(inputs)

        mock_adapter.recreate_slot.assert_called_once_with(source, tables=["tll.students"])
        assert source.job_inputs["cdc_consistent_point"] == "0/AA"
        source.save.assert_called()

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_recovery_failure_marks_schemas_failed_and_raises(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        source, schema, mock_reader, mock_adapter = self._setup(
            mock_get_schemas, mock_get_adapter, MockSourceModel, mock_activity
        )
        mock_adapter.recreate_slot.side_effect = RuntimeError("cannot recreate slot")

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        with pytest.raises(RuntimeError, match="cannot recreate slot"):
            cdc_extract_activity(inputs)

        assert schema.status == "Failed"
        # The raw recovery error stays in the logs; the user-facing column gets friendly copy.
        assert schema.latest_error == cdc_error_info(CDCErrorCategory.UNKNOWN).friendly_message
        assert "cannot recreate slot" not in schema.latest_error
        mock_reader.close.assert_called_once()

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_non_invalidation_errors_do_not_trigger_recovery(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        source, schema, mock_reader, mock_adapter = self._setup(
            mock_get_schemas, mock_get_adapter, MockSourceModel, mock_activity
        )
        mock_reader.read_changes.side_effect = RuntimeError("connection lost")
        mock_adapter.is_slot_invalidation_error.return_value = False

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        with pytest.raises(RuntimeError, match="connection lost"):
            cdc_extract_activity(inputs)

        mock_adapter.recreate_slot.assert_not_called()
        assert schema.sync_type_config["cdc_mode"] == "streaming"


class TestCleanupOrphanSlotsRetentionCap:
    """The sweeper's auto-drop must fire below the engine's own retention cap
    (max_slot_wal_keep_size), otherwise the engine invalidates the slot first."""

    def _setup(self, mock_get_adapter, MockSourceModel, lag_mb, cap_mb):
        source = _make_source()
        MockSourceModel.objects.filter.return_value.iterator.return_value = [source]

        cdc_config = MagicMock()
        cdc_config.enabled = True
        cdc_config.slot_name = "posthog_slot"
        cdc_config.publication_name = "posthog_pub"
        cdc_config.management_mode = "posthog"
        cdc_config.auto_drop_slot = True
        cdc_config.lag_warning_threshold_mb = 1024
        cdc_config.lag_critical_threshold_mb = 10240

        mock_adapter = MagicMock()
        mock_adapter.parse_cdc_config.return_value = cdc_config
        mock_adapter.get_lag_bytes.return_value = lag_mb * 1024 * 1024
        mock_adapter.get_retention_cap_mb.return_value = cap_mb
        mock_get_adapter.return_value = mock_adapter
        return source, mock_adapter

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.HeartbeaterSync")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.mark_cdc_broken")
    def test_retention_cap_lowers_critical_threshold(
        self, mock_mark_broken, mock_close_conns, MockSourceModel, mock_get_adapter, mock_activity, mock_heartbeater
    ):
        # Configured critical is 10240 MB, but the engine caps retention at 1000 MB:
        # at 900 MB of lag (>= 80% of the cap) the sweeper must already act.
        _source, mock_adapter = self._setup(mock_get_adapter, MockSourceModel, lag_mb=900, cap_mb=1000)

        cleanup_orphan_slots_activity()

        # Dropping + marking broken is the "act" — the broken-state details are covered in test_broken.
        mock_adapter.drop_resources.assert_called_once()
        mock_mark_broken.assert_called_once()

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.HeartbeaterSync")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.mark_cdc_broken")
    def test_unlimited_retention_keeps_configured_threshold(
        self, mock_mark_broken, mock_close_conns, MockSourceModel, mock_get_adapter, mock_activity, mock_heartbeater
    ):
        source, mock_adapter = self._setup(mock_get_adapter, MockSourceModel, lag_mb=900, cap_mb=None)

        cleanup_orphan_slots_activity()

        mock_adapter.drop_resources.assert_not_called()
        mock_mark_broken.assert_not_called()


class TestExtractionHeartbeat:
    """Every run records a per-schema last-run heartbeat in sync_type_config so a quiet (zero-event)
    source still proves extraction is alive — without an ExternalDataJob row per idle hourly run."""

    @parameterized.expand(
        [
            ("no_changes_records_zero", [], 0),
            (
                "with_events_records_count",
                [
                    _make_event(op="I", table="users", position="0/100"),
                    _make_event(op="U", table="users", position="0/200"),
                ],
                2,
            ),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_records_last_run_heartbeat(
        self,
        _name,
        events,
        expected_count,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            events,
        )

        cdc_extract_activity(CDCExtractInput(team_id=1, source_id=source.id))

        config = schema.sync_type_config
        assert config["cdc_last_run_event_count"] == expected_count
        # Stored as an ISO-8601 string so the health check and cdc_status can parse it back.
        assert isinstance(config["cdc_last_run_at"], str)
        datetime.fromisoformat(config["cdc_last_run_at"])


class TestFailureVisibilityJobs:
    """A run that fails before the first micro-flush creates no job in the normal path, leaving the
    Syncs tab blank while the schema reads FAILED. The activity backfills a terminal FAILED row —
    but only once retries are exhausted or the error is non-retryable, never per transient retry."""

    def _drive_failure(
        self,
        *,
        error,
        attempt,
        schemas,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        source = _make_source()
        MockSourceModel.objects.get.return_value = source
        mock_get_schemas.return_value = schemas

        mock_reader = MagicMock()
        mock_reader.read_changes.side_effect = error
        mock_reader.truncated_tables = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_adapter.is_slot_invalidation_error.return_value = False
        mock_adapter.classify_error = PostgresCDCAdapter().classify_error  # exercise real classification
        mock_get_adapter.return_value = mock_adapter

        MockJob.Status.FAILED = "Failed"
        MockJob.PipelineVersion.V3 = "v3-kafka-s3"
        MockJob.objects.create.return_value = MagicMock(id=uuid.uuid4())

        mock_activity.heartbeat = MagicMock()
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1", attempt=attempt)

        with pytest.raises((NonRetryableException, psycopg.OperationalError)):
            cdc_extract_activity(CDCExtractInput(team_id=1, source_id=source.id))

    @parameterized.expand(
        [
            (
                "non_retryable_creates_even_on_first_attempt",
                psycopg.errors.InvalidPassword("password authentication failed"),
                1,
                True,
                CDCErrorCategory.AUTH_FAILED,
            ),
            ("retryable_skips_on_non_final_attempt", psycopg.OperationalError("connection refused"), 1, False, None),
            (
                "retryable_creates_on_final_attempt",
                psycopg.OperationalError("connection refused"),
                3,
                True,
                CDCErrorCategory.CONNECTION_FAILED,
            ),
        ]
    )
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_failure_visibility_job_creation(
        self,
        _name,
        error,
        attempt,
        expect_created,
        expected_category,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        schema = _make_schema("users", cdc_mode="streaming")
        self._drive_failure(
            error=error,
            attempt=attempt,
            schemas=[schema],
            MockJob=MockJob,
            MockSourceModel=MockSourceModel,
            mock_get_schemas=mock_get_schemas,
            mock_get_adapter=mock_get_adapter,
            mock_activity=mock_activity,
        )

        if not expect_created:
            MockJob.objects.create.assert_not_called()
            return

        MockJob.objects.create.assert_called_once()
        kwargs = MockJob.objects.create.call_args.kwargs
        assert kwargs["status"] == "Failed"
        assert kwargs["rows_synced"] == 0
        assert kwargs["pipeline_version"] == "v3-kafka-s3"
        assert kwargs["workflow_id"] == "wf-1"
        assert kwargs["schema"] is schema
        # User-facing column carries the friendly, credential-safe copy — never the raw exception.
        assert kwargs["latest_error"] == cdc_error_info(expected_category).friendly_message

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_one_failure_row_per_schema(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        schema_a = _make_schema("users", cdc_mode="streaming")
        schema_b = _make_schema("orders", cdc_mode="streaming")
        self._drive_failure(
            error=psycopg.errors.InvalidPassword("password authentication failed"),
            attempt=1,
            schemas=[schema_a, schema_b],
            MockJob=MockJob,
            MockSourceModel=MockSourceModel,
            mock_get_schemas=mock_get_schemas,
            mock_get_adapter=mock_get_adapter,
            mock_activity=mock_activity,
        )

        assert MockJob.objects.create.call_count == 2
        created_for = {call.kwargs["schema"] for call in MockJob.objects.create.call_args_list}
        assert created_for == {schema_a, schema_b}


class _ScriptedReader:
    """Reader stub that serves preconfigured WAL pages to the bounded read loop.

    Each page is (events, rows_consumed, commit_end_lsn). read_changes() exposes that page's
    rows_consumed / last_commit_end_lsn exactly as the real reader does after a peek, so the
    multi-pass loop sees a full page (rows_consumed >= cap) followed by a drained one (< cap).
    """

    def __init__(self, pages):
        self._pages = list(pages)
        self._idx = 0
        self.last_rows_consumed = 0
        self.last_commit_end_lsn = None
        self.truncated_tables: list[str] = []
        self.confirmed_positions: list[str] = []
        self.on_row_calls = 0
        self.upto_nchanges_calls: list[int | None] = []

    def connect(self):
        pass

    def get_primary_key_columns(self, schema, tables):
        return {}

    def get_decoder_key_columns(self, table):
        return []

    def clear_truncated_tables(self):
        self.truncated_tables = []

    def read_changes(self, upto_nchanges=None, on_row=None):
        self.upto_nchanges_calls.append(upto_nchanges)
        events, rows_consumed, commit_end_lsn = self._pages[self._idx]
        self._idx += 1
        self.last_rows_consumed = rows_consumed
        self.last_commit_end_lsn = commit_end_lsn

        def gen():
            for ev in events:
                if on_row is not None:
                    on_row()
                    self.on_row_calls += 1
                yield ev

        return gen()

    def confirm_position(self, lsn):
        self.confirmed_positions.append(lsn)

    def close(self):
        pass


class TestCDCBoundedReadLoop:
    """The read loop peeks at most CDC_MAX_CHANGES_PER_READ changes per pass, advancing the slot
    between passes so a large backlog drains over several passes (and, if needed, runs)."""

    def _run_with_reader(
        self,
        mock_activity,
        MockProducer,
        MockS3Writer,
        mock_get_adapter,
        mock_get_schemas,
        MockSourceModel,
        MockJob,
        mock_close_conns,
        reader,
    ):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["primary_key_columns"] = ["id"]
        _setup_mocks(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            source,
            [schema],
            [],
        )
        # Replace the default MagicMock reader with the scripted multi-pass reader.
        mock_get_adapter.return_value.create_reader.return_value = reader

        cdc_extract_activity(CDCExtractInput(team_id=1, source_id=source.id))
        return schema

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_full_page_then_drained_advances_slot_between_passes(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        reader = _ScriptedReader(
            [
                ([_make_event(op="I", table="users", position="0/100")], CDC_MAX_CHANGES_PER_READ, "0/100"),
                ([_make_event(op="I", table="users", position="0/200")], 5, "0/200"),
            ]
        )

        self._run_with_reader(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            reader,
        )

        # Two peeks: a full page, then a drained one. The first pass advances the slot to its last
        # commit before re-peeking; the final flush advances to the second pass's last event.
        assert len(reader.upto_nchanges_calls) == 2
        assert reader.confirmed_positions == ["0/100", "0/200"]
        # The per-row heartbeat callback was wired through read_changes and fired during the reads.
        assert reader.on_row_calls == 2

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_soft_deadline_stops_starting_new_passes(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
        monkeypatch,
    ):
        # Deadline already elapsed: a full first page must not start a second pass.
        monkeypatch.setattr(
            "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.CDC_READ_SOFT_DEADLINE_SECONDS", 0
        )
        reader = _ScriptedReader(
            [([_make_event(op="I", table="users", position="0/100")], CDC_MAX_CHANGES_PER_READ, "0/100")]
        )

        schema = self._run_with_reader(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            reader,
        )

        assert len(reader.upto_nchanges_calls) == 1  # no second peek despite a full page
        assert schema.status == "Completed"  # the run still finalizes what it read

    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.PostgresProducer")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.S3BatchWriter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataJob")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_full_page_with_no_committed_progress_doubles_the_limit(
        self,
        mock_close_conns,
        MockJob,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        MockS3Writer,
        MockProducer,
        mock_activity,
    ):
        # Defensive backstop: a full page that commits nothing (so the slot can't advance) grows
        # the window instead of re-peeking the identical page forever.
        reader = _ScriptedReader(
            [
                ([], CDC_MAX_CHANGES_PER_READ, None),
                ([_make_event(op="I", table="users", position="0/300")], 5, "0/300"),
            ]
        )

        self._run_with_reader(
            mock_activity,
            MockProducer,
            MockS3Writer,
            mock_get_adapter,
            mock_get_schemas,
            MockSourceModel,
            MockJob,
            mock_close_conns,
            reader,
        )

        assert reader.upto_nchanges_calls == [CDC_MAX_CHANGES_PER_READ, CDC_MAX_CHANGES_PER_READ * 2]
        assert reader.confirmed_positions == ["0/300"]  # nothing to advance on pass 1; pass 2 drains


class TestMaskEventColumns:
    def test_masks_configured_columns_and_passes_rest_through(self):
        source = _make_source()
        activity_obj = _make_extract_activity(source)
        activity_obj.masked_columns_by_table = {"users": {"email"}}

        event = _make_event(columns={"id": 1, "email": "a@x.com", "name": None})
        out = activity_obj._mask_event_columns(event)

        # Masked column digests match the shared engine (snapshot/CDC consistency for equal text);
        # unmasked columns and nulls pass through untouched.
        assert out.columns["email"] == mask_value(1, "a@x.com")
        assert out.columns["id"] == 1
        assert out.columns["name"] is None

    def test_folds_event_column_names_before_matching(self):
        source = _make_source()
        activity_obj = _make_extract_activity(source)
        activity_obj.masked_columns_by_table = {"users": {"email"}}

        # A cased event column must still match the folded mask set — otherwise PII streams plaintext.
        event = _make_event(columns={"id": 1, "Email": "a@x.com"})
        out = activity_obj._mask_event_columns(event)
        assert out.columns["Email"] == mask_value(1, "a@x.com")

    def test_unconfigured_table_is_untouched(self):
        source = _make_source()
        activity_obj = _make_extract_activity(source)
        activity_obj.masked_columns_by_table = {}

        event = _make_event(columns={"id": 1, "email": "a@x.com"})
        assert activity_obj._mask_event_columns(event) is event
