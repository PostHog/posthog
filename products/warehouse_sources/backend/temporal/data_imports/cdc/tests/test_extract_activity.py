import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Literal

import pytest
from unittest.mock import ANY, DEFAULT, MagicMock, patch

from django.db.utils import InterfaceError, OperationalError

import pyarrow as pa
import psycopg.errors
from parameterized import parameterized
from temporalio.service import RPCError, RPCStatusCode

from posthog.temporal.common.errors import NonReportableError

from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob
from products.warehouse_sources.backend.models.external_data_schema import CDC_SNAPSHOT_LANE_KEY, ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.cdc.activities import (
    CDC_MAX_CHANGES_PER_READ,
    CDC_MAX_EXTRACTION_ATTEMPTS,
    SLOT_INVALIDATION_RECOVERY_MESSAGE,
    CDCExtractActivity,
    CDCExtractInput,
    cdc_extract_activity,
    cleanup_orphan_slots_activity,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import (
    CDC_SEQ_COLUMN,
    CDC_SEQ_PROVENANCE,
    ChangeEventBatcher,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.errors import CDCErrorCategory, cdc_error_info
from products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane import cancel_running_sync
from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.position import PgLSN
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException

_ACTIVITIES = "products.warehouse_sources.backend.temporal.data_imports.cdc.activities"


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


def _make_schema(name, cdc_mode="streaming", cdc_table_mode="consolidated", source=None, schema_id=None):
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
def _stub_app_db_writes():
    # The real sync_type_config merge and the legacy-state conversion both go to the app DB, which
    # these mock-only tests don't have. The conversion has its own tests.
    with (
        patch.object(
            CDCExtractActivity,
            "_update_schema_sync_type_config",
            side_effect=_fake_update_schema_sync_type_config,
        ),
        patch(f"{_ACTIVITIES}.convert_legacy_cdc_state"),
        patch(f"{_ACTIVITIES}.cancel_running_sync", return_value=None),
    ):
        yield


@contextmanager
def _capture_harness(source, schemas, events=()) -> Iterator[SimpleNamespace]:
    reader = MagicMock(last_commit_end_lsn=None)
    reader.read_changes.return_value = iter(events)
    reader.truncated_tables = []
    # Below CDC_MAX_CHANGES_PER_READ so the bounded read loop treats this as a single drained pass.
    reader.last_rows_consumed = len(events)
    reader.get_decoder_key_columns.return_value = []

    with (
        patch(f"{_ACTIVITIES}.close_old_connections") as close_old_connections,
        patch(f"{_ACTIVITIES}.ExternalDataSource") as MockSourceModel,
        patch(f"{_ACTIVITIES}.ExternalDataJob"),
        patch.object(CDCExtractActivity, "_get_cdc_schemas", return_value=list(schemas)),
        patch(f"{_ACTIVITIES}.get_cdc_adapter") as mock_get_adapter,
        patch(f"{_ACTIVITIES}.CDCBufferWriter") as MockBufferWriter,
        patch(f"{_ACTIVITIES}.purge_buffer_prefix") as purge,
        patch(f"{_ACTIVITIES}.activity") as mock_activity,
        # The reset and failure paths call Temporal and Celery, which these tests must not reach.
        patch("products.data_warehouse.backend.facade.api.unpause_external_data_schedule"),
        patch("products.data_warehouse.backend.facade.api.pause_cdc_extraction_schedule"),
        patch("products.data_warehouse.backend.facade.tasks.schedule_external_data_failure_digest"),
    ):
        MockSourceModel.objects.get.return_value = source
        adapter = mock_get_adapter.return_value
        adapter.create_reader.return_value = reader
        adapter.is_slot_invalidation_error.return_value = False
        adapter.classify_error.return_value = None  # default: unrecognized -> unknown/retryable
        # Real converter, not a MagicMock return: the batcher feeds its output into a typed pa.array.
        adapter.position_to_seq.side_effect = lambda position: PgLSN.deserialize(position).value
        MockBufferWriter.return_value.write_batch.return_value.write_duration_seconds = 0.01
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1", attempt=1)
        yield SimpleNamespace(
            reader=reader,
            adapter=adapter,
            buffer=MockBufferWriter.return_value,
            purge=purge,
            activity=mock_activity,
            close_old_connections=close_old_connections,
            extract=lambda: cdc_extract_activity(CDCExtractInput(team_id=1, source_id=source.id)),
        )


class TestGetCDCAdapter:
    def test_returns_postgres_adapter(self):
        from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import get_cdc_adapter
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import (
            PostgresCDCAdapter,
        )

        source = _make_source()
        adapter = get_cdc_adapter(source)
        assert isinstance(adapter, PostgresCDCAdapter)

    @parameterized.expand([("no_adapter_for_the_type", "MySQL"), ("not_a_source_type_at_all", "UnsupportedDB")])
    def test_raises_a_typed_error_for_an_unsupported_source(self, _name, source_type):
        from products.warehouse_sources.backend.temporal.data_imports.cdc.adapters import (
            CDCUnsupportedSourceTypeError,
            get_cdc_adapter,
        )

        source = _make_source()
        source.source_type = source_type
        with pytest.raises(CDCUnsupportedSourceTypeError, match="CDC is not supported"):
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

    def test_position_to_seq_matches_lsn_value_and_preserves_order(self):
        from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import (
            PostgresCDCAdapter,
        )

        adapter = PostgresCDCAdapter()
        assert adapter.position_to_seq("0/100") == 0x100
        assert adapter.position_to_seq("0/200") > adapter.position_to_seq("0/100")
        assert adapter.position_to_seq("1/0") > adapter.position_to_seq("0/FFFFFFFF")


def _make_extract_activity(source, log=None) -> CDCExtractActivity:
    """Build a CDCExtractActivity with source and log pre-injected for unit tests."""
    activity_obj = CDCExtractActivity(CDCExtractInput(team_id=1, source_id=source.id))
    activity_obj.source = source
    activity_obj.log = log or MagicMock()
    return activity_obj


class TestSetupSelfCleansUnrunnableSchedules:
    @parameterized.expand([("no_adapter_for_the_type", "MySQL"), ("not_a_source_type_at_all", "UnsupportedDB")])
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_a_source_type_without_cdc_deletes_the_schedule_instead_of_failing(
        self, _name, source_type, _mock_close_conns, MockSourceModel, mock_get_adapter
    ):
        source = _make_source()
        source.source_type = source_type
        MockSourceModel.objects.get.return_value = source
        MockSourceModel.DoesNotExist = ExternalDataSource.DoesNotExist

        act = _make_extract_activity(source)
        with patch.object(act, "_delete_own_schedule") as mock_delete:
            assert act._setup() is False

        mock_delete.assert_called_once()
        mock_get_adapter.assert_not_called()


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


class TestWriteBufferFile:
    def _table(self, seq, *, trailing_column=False):
        table = pa.table({"id": pa.array([1], type=pa.int64())}).append_column(
            pa.field(CDC_SEQ_COLUMN, pa.int64(), metadata=CDC_SEQ_PROVENANCE),
            pa.array([seq], type=pa.int64()),
        )
        if trailing_column:
            table = table.append_column(pa.field("added_later", pa.string()), pa.array(["x"], type=pa.string()))
        return table

    @patch(f"{_ACTIVITIES}.CDCBufferWriter")
    def test_the_restart_floor_is_read_from_the_seq_column_by_name(self, MockBufferWriter):
        # A lookup by index, which assumes the batcher appends the position last, would feed cleanup a
        # restart floor read off whichever column follows it.
        source = _make_source()
        schema = _make_schema("users", source=source)
        MockBufferWriter.return_value.write_batch.return_value.write_duration_seconds = 0.01

        _make_extract_activity(source)._write_buffer_file(schema, "users", self._table(256, trailing_column=True))

        MockBufferWriter.return_value.write_batch.assert_called_once()
        assert MockBufferWriter.return_value.cleanup_superseded_files.call_args.kwargs["restart_seq"] == 256

    @patch(f"{_ACTIVITIES}.CDCBufferWriter")
    def test_each_schema_cleans_superseded_files_once_before_its_first_write(self, MockBufferWriter):
        # A later batch can start at a position an earlier file of this run already holds, so cleaning
        # again before it would delete that file.
        source = _make_source()
        users = _make_schema("users", source=source)
        orders = _make_schema("orders", source=source)
        buffer = MockBufferWriter.return_value
        buffer.write_batch.return_value.write_duration_seconds = 0.01
        act = _make_extract_activity(source)

        act._write_buffer_file(users, "users", self._table(256))
        act._write_buffer_file(users, "users", self._table(512))
        act._write_buffer_file(orders, "orders", self._table(768))

        assert [(name, kwargs["schema_id"]) for name, _args, kwargs in buffer.mock_calls] == [
            ("cleanup_superseded_files", str(users.id)),
            ("write_batch", str(users.id)),
            ("write_batch", str(users.id)),
            ("cleanup_superseded_files", str(orders.id)),
            ("write_batch", str(orders.id)),
        ]
        assert [c.kwargs["restart_seq"] for c in buffer.cleanup_superseded_files.call_args_list] == [256, 768]


class TestCDCExtractActivity:
    """Integration tests for cdc_extract_activity with mocked external deps."""

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

    @parameterized.expand([("operational", OperationalError), ("interface", InterfaceError)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.get_cdc_adapter")
    @patch.object(CDCExtractActivity, "_get_cdc_schemas")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.ExternalDataSource")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.close_old_connections")
    def test_setup_app_db_connection_blip_is_not_reported(
        self,
        _name,
        exception_cls,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
    ):
        # `_setup` only reads our own app DB (never a customer's), so a dropped connection here
        # (e.g. PgBouncer closing an idle connection) is a transient blip, not a broken sync. It
        # must still be retried by Temporal, but shouldn't page as a fresh, reportable bug on
        # every attempt.
        MockSourceModel.DoesNotExist = ExternalDataSource.DoesNotExist
        MockSourceModel.objects.get.side_effect = exception_cls("server closed the connection unexpectedly")

        inputs = CDCExtractInput(team_id=1, source_id=uuid.uuid4())

        with pytest.raises(NonReportableError, match="server closed the connection unexpectedly"):
            cdc_extract_activity(inputs)

        mock_get_schemas.assert_not_called()
        mock_get_adapter.assert_not_called()

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

        mock_reader = MagicMock(last_commit_end_lsn=None)
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


class TestSlotAdvanceTransactionSafety:
    """The slot must only advance past FULLY-yielded transactions.

    A micro-flush can fire mid-transaction (the batcher threshold is per-event).
    Since every event of a transaction shares its commit end LSN, advancing to that
    LSN while the transaction's tail is still un-yielded would lose the tail on crash.
    """

    @parameterized.expand(
        [
            # Mid-transaction flush: txn-1 (0/100) ×2 then txn-2 (0/200) ×3, flush after
            # 4 events lands mid txn-2. The micro-flush advances only to txn-1's end LSN;
            # the final flush advances to txn-2's.
            (
                "flush_mid_second_transaction",
                ["0/100", "0/100", "0/200", "0/200", "0/200"],
                4,
                [("write", 0), ("advance", "0/100"), ("write", 1), ("advance", "0/200")],
            ),
            # Single transaction (one commit LSN): a threshold of 2 forces a mid-transaction
            # micro-flush, but the transaction never completes during the loop, so no
            # micro-advance may happen. Only the final flush advances, once. Both files cover the
            # same positions, so only the file index stops the second from replacing the first.
            (
                "flush_inside_one_transaction",
                ["0/100", "0/100", "0/100"],
                2,
                [("write", 0), ("write", 1), ("advance", "0/100")],
            ),
        ]
    )
    def test_slot_advances_only_past_completed_transactions(self, _name, event_positions, max_events, expected_order):
        source = _make_source()
        schema = _make_schema("users", source=source)
        events = [
            _make_event(op="I", table="users", position=pos, columns={"id": i}) for i, pos in enumerate(event_positions)
        ]
        order: list[tuple[str, int | str]] = []

        def _write(**kwargs):
            order.append(("write", kwargs["file_index"]))
            return DEFAULT

        with (
            _capture_harness(source, [schema], events) as capture,
            patch(
                f"{_ACTIVITIES}.ChangeEventBatcher",
                side_effect=lambda **kwargs: ChangeEventBatcher(max_events=max_events, **kwargs),
            ),
        ):
            capture.buffer.write_batch.side_effect = _write
            capture.reader.confirm_position.side_effect = lambda lsn: order.append(("advance", lsn))
            capture.extract()

        # Every advance comes after the write of the changes it releases.
        assert order == expected_order


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
    @patch.object(CDCExtractActivity, "_pause_cdc_extraction_schedule")
    def test_non_retryable_error_raises_nonretryable_and_captures(
        self,
        _mock_pause_schedule,
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

        mock_reader = MagicMock(last_commit_end_lsn=None)
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
        with (
            patch("products.data_warehouse.backend.facade.tasks.schedule_external_data_failure_digest") as mock_digest,
            pytest.raises(NonRetryableException),
        ):
            cdc_extract_activity(inputs)

        assert schema.status == "Failed"
        assert schema.latest_error == cdc_error_info(CDCErrorCategory.AUTH_FAILED).friendly_message
        # The schedule pause leaves no DB trace of its own; this marker is what tells the failure
        # digest email "paused, action required" instead of "will retry".
        assert schema.sync_type_config["cdc_extraction_paused"]["reason"] == "auth_failed"
        mock_digest.assert_called_once_with(1, trigger="cdc")

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
    @patch.object(CDCExtractActivity, "_pause_cdc_extraction_schedule")
    def test_missing_slot_or_publication_marks_cdc_broken(
        self,
        _name,
        exc_cls,
        exc_message,
        expected_reason,
        mock_pause,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
        mock_posthoganalytics,
        mock_get_machine_id,
        mock_mark_broken,
    ):
        # Slot/publication errors mark_cdc_broken (pause + broken marker); an auth failure has an
        # intact slot, so it pauses the schedule directly without the broken marker.
        source = _make_source()
        MockSourceModel.objects.get.return_value = source
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock(last_commit_end_lsn=None)
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
            mock_pause.assert_called_once()
        else:
            mock_mark_broken.assert_called_once()
            assert mock_mark_broken.call_args.args[0] is source
            assert mock_mark_broken.call_args.args[1] == expected_reason
            # This run backfills its own FAILED rows; mark_cdc_broken adding a second set would
            # show every incident as two identical failed runs.
            assert mock_mark_broken.call_args.kwargs["create_visibility_jobs"] is False
            mock_pause.assert_not_called()

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
    def test_missing_slot_name_fails_before_streaming_without_recovery(
        self,
        mock_close_conns,
        MockSourceModel,
        mock_get_schemas,
        mock_get_adapter,
        mock_activity,
        mock_posthoganalytics,
        mock_get_machine_id,
        mock_mark_broken,
    ):
        # A CDC-enabled source whose stored slot name is empty must fail fast and non-retryably:
        # streaming an empty slot name reads as a recoverable slot drop, so recovery / Repair CDC
        # run only to dead-end with no slot name to recreate. Guard before streaming instead.
        source = _make_source(
            job_inputs={
                "host": "localhost",
                "port": 5432,
                "database": "testdb",
                "user": "test",
                "password": "test",
                "cdc_publication_name": "posthog_pub",
            }
        )
        MockSourceModel.objects.get.return_value = source
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock(last_commit_end_lsn=None)
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_adapter.is_slot_invalidation_error.return_value = False
        mock_adapter.parse_cdc_config = PostgresCDCAdapter().parse_cdc_config  # reads the empty slot name
        mock_get_adapter.return_value = mock_adapter

        mock_activity.heartbeat = MagicMock()
        mock_activity.info.return_value = MagicMock(workflow_id="wf-1", workflow_run_id="run-1", attempt=1)

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        with pytest.raises(NonRetryableException) as exc_info:
            cdc_extract_activity(inputs)

        assert str(exc_info.value) == cdc_error_info(CDCErrorCategory.SLOT_NOT_CONFIGURED).friendly_message
        # Never streamed and never tried to recover — the guard fired first.
        mock_reader.connect.assert_not_called()
        mock_reader.read_changes.assert_not_called()
        mock_adapter.recreate_slot.assert_not_called()
        # Broken state persisted so the schedule stops firing against an unconfigured slot.
        mock_mark_broken.assert_called_once()
        assert mock_mark_broken.call_args.args[0] is source
        assert mock_mark_broken.call_args.args[1] == "slot_not_configured"

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
    @patch.object(CDCExtractActivity, "_pause_cdc_extraction_schedule")
    def test_analytics_failure_does_not_mask_nonretryable(
        self,
        _mock_pause_schedule,
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

        mock_reader = MagicMock(last_commit_end_lsn=None)
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

        mock_reader = MagicMock(last_commit_end_lsn=None)
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
    def test_terminal_unclassified_error_is_captured_for_triage(
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
        # An unclassified failure stays retryable and never pauses the schedule, so a deterministic one
        # re-fails every scheduled run forever. Only the non-retryable path emits analytics, so without
        # this capture these highest-volume retry loops stay invisible to error triage.
        source = _make_source()
        MockSourceModel.objects.get.return_value = source
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        # A non-psycopg error the adapter can't classify falls back to retryable UNKNOWN.
        mock_reader = MagicMock(last_commit_end_lsn=None)
        mock_reader.read_changes.side_effect = RuntimeError("arrow merge blew up")
        mock_reader.truncated_tables = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_adapter.is_slot_invalidation_error.return_value = False
        mock_adapter.classify_error = PostgresCDCAdapter().classify_error
        mock_get_adapter.return_value = mock_adapter

        mock_activity.heartbeat = MagicMock()
        # Retries exhausted: the failure is terminal, so the capture fires (unlike a mid-retry attempt).
        mock_activity.info.return_value = MagicMock(
            workflow_id="wf-1", workflow_run_id="run-1", attempt=CDC_MAX_EXTRACTION_ATTEMPTS
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        with (
            patch("products.data_warehouse.backend.facade.tasks.schedule_external_data_failure_digest"),
            pytest.raises(RuntimeError, match="arrow merge blew up"),
        ):
            cdc_extract_activity(inputs)

        assert schema.latest_error == cdc_error_info(CDCErrorCategory.UNKNOWN).friendly_message
        mock_posthoganalytics.capture.assert_called_once()
        captured = mock_posthoganalytics.capture.call_args.kwargs
        assert captured["event"] == "cdc extraction unclassified error"
        assert captured["properties"]["source_id"] == str(source.id)
        # The exception type — not str(exc), which could embed customer host/table names — is what a
        # human needs to teach the taxonomy to recognise this failure.
        assert "RuntimeError" in captured["properties"]["exception_types"]

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
    def test_terminal_unclassified_error_captures_sqlstate_for_triage(
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
        # Preserve coverage for unknown psycopg failures now that insufficient privileges have a
        # dedicated category. The SQLSTATE distinguishes an unclassified syntax error from other
        # ProgrammingError subclasses without capturing potentially sensitive exception text.
        source = _make_source()
        MockSourceModel.objects.get.return_value = source
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        mock_get_schemas.return_value = [schema]

        mock_reader = MagicMock(last_commit_end_lsn=None)
        mock_reader.read_changes.side_effect = psycopg.errors.SyntaxError("invalid syntax")
        mock_reader.truncated_tables = []
        mock_adapter = MagicMock()
        mock_adapter.create_reader.return_value = mock_reader
        mock_adapter.is_slot_invalidation_error.return_value = False
        mock_adapter.classify_error = PostgresCDCAdapter().classify_error
        mock_get_adapter.return_value = mock_adapter

        mock_activity.heartbeat = MagicMock()
        mock_activity.info.return_value = MagicMock(
            workflow_id="wf-1", workflow_run_id="run-1", attempt=CDC_MAX_EXTRACTION_ATTEMPTS
        )

        inputs = CDCExtractInput(team_id=1, source_id=source.id)
        with (
            patch("products.data_warehouse.backend.facade.tasks.schedule_external_data_failure_digest"),
            pytest.raises(psycopg.errors.SyntaxError),
        ):
            cdc_extract_activity(inputs)

        captured = mock_posthoganalytics.capture.call_args.kwargs
        assert captured["event"] == "cdc extraction unclassified error"
        assert "42601" in captured["properties"]["sqlstates"]


class TestSlotInvalidationRecovery:
    """When the replication slot is invalidated/dropped on the source DB, the activity
    must recreate it and reset all CDC schemas to snapshot mode instead of failing forever."""

    @contextmanager
    def _invalidated_slot(self, source, schema) -> Iterator[SimpleNamespace]:
        with _capture_harness(source, [schema]) as capture:
            capture.reader.read_changes.side_effect = psycopg.errors.ObjectNotInPrerequisiteState(
                'can no longer get changes from replication slot "posthog_slot"\n'
                "DETAIL:  This slot has been invalidated because it exceeded the maximum reserved size."
            )
            capture.adapter.is_slot_invalidation_error.return_value = True
            capture.adapter.recreate_slot.return_value = {"cdc_consistent_point": "0/AA"}
            yield capture

    def test_invalidated_slot_is_recreated_and_schemas_reset_to_snapshot(self):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_last_log_position"] = "0/OLD"

        with self._invalidated_slot(source, schema) as capture:

            def _recreate_slot(source_arg, tables):
                # The reset, its buffer purge included, must be complete before the slot is recreated.
                # Once the new slot exists, no run hits the invalidation error again, so a reset that
                # failed after that point would never repeat and the schema would stream across the gap.
                assert schema.sync_type_config["cdc_mode"] == "snapshot"
                capture.purge.assert_called_once_with(schema.team_id, str(schema.id), ANY, strict=True)
                return {"cdc_consistent_point": "0/AA"}

            capture.adapter.recreate_slot.side_effect = _recreate_slot
            # Recovery handles the error — the activity must not raise (no pointless Temporal retries).
            capture.extract()

        capture.adapter.recreate_slot.assert_called_once_with(source, tables=["public.users"])
        assert source.job_inputs["cdc_consistent_point"] == "0/AA"
        source.save.assert_called()

        assert schema.sync_type_config["cdc_mode"] == "snapshot"
        assert schema.sync_type_config["reset_pipeline"] is True
        assert "cdc_last_log_position" not in schema.sync_type_config
        assert schema.initial_sync_complete is False
        assert schema.status == "Failed"
        assert schema.latest_error == SLOT_INVALIDATION_RECOVERY_MESSAGE

        capture.reader.close.assert_called_once()

    def test_recreate_passes_source_qualified_table_names(self):
        # Recovery must resolve each schema's real source location from its metadata,
        # not assume every table lives in the source's default schema. Otherwise a table
        # in a non-default schema gets jammed under `public` and the publication rebuild
        # fails with `relation "public.tll.students" does not exist`.
        source = _make_source()
        schema = _make_schema("students", cdc_mode="streaming", source=source)
        schema.sync_type_config["schema_metadata"] = {"source_schema": "tll", "source_table_name": "students"}

        with self._invalidated_slot(source, schema) as capture:
            capture.extract()

        capture.adapter.recreate_slot.assert_called_once_with(source, tables=["tll.students"])
        assert source.job_inputs["cdc_consistent_point"] == "0/AA"
        source.save.assert_called()

    def test_recovery_failure_marks_schemas_failed_and_raises(self):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)

        with self._invalidated_slot(source, schema) as capture:
            capture.adapter.recreate_slot.side_effect = RuntimeError("cannot recreate slot")
            with pytest.raises(RuntimeError, match="cannot recreate slot"):
                capture.extract()

        assert schema.status == "Failed"
        # The raw recovery error stays in the logs; the user-facing column gets friendly copy.
        assert schema.latest_error == cdc_error_info(CDCErrorCategory.UNKNOWN).friendly_message
        assert "cannot recreate slot" not in schema.latest_error
        capture.reader.close.assert_called_once()

    def test_non_invalidation_errors_do_not_trigger_recovery(self):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)

        with self._invalidated_slot(source, schema) as capture:
            capture.reader.read_changes.side_effect = RuntimeError("connection lost")
            capture.adapter.is_slot_invalidation_error.return_value = False
            with pytest.raises(RuntimeError, match="connection lost"):
                capture.extract()

        capture.adapter.recreate_slot.assert_not_called()
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


class TestFailureVisibilityJobs:
    """Capture creates no job of its own, so a failed run would leave the Syncs tab blank while the
    schema reads FAILED. The activity writes a terminal FAILED row — but only once retries are
    exhausted or the error is non-retryable, never per transient retry."""

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

        mock_reader = MagicMock(last_commit_end_lsn=None)
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

        # The non-retryable pause hits Temporal (sync_connect); stub it so these stay off the network.
        with (
            patch.object(CDCExtractActivity, "_pause_cdc_extraction_schedule"),
            pytest.raises((NonRetryableException, psycopg.OperationalError)),
        ):
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


class TestPKColumnLoading:
    def _activity(self, schemas, queried_pks=None, default_namespace="public"):
        source = _make_source()
        source.job_inputs = {**source.job_inputs, "schema": default_namespace}
        act = _make_extract_activity(source)
        act.cdc_schemas = schemas
        for schema in schemas:
            schema.source = source
        act.reader = MagicMock()
        act.reader.get_primary_key_columns.side_effect = lambda namespace, relations: {
            relation: pks for relation, pks in (queried_pks or {}).get(namespace, {}).items() if relation in relations
        }
        return act

    def test_qualified_name_is_split_for_the_query_and_rejoined_for_the_result(self):
        # The catalog filters on the bare relation name inside one namespace, so a qualified
        # ExternalDataSchema.name matched nothing and the table synced with no merge key.
        schema = _make_schema("cdc_test.orders")
        act = self._activity([schema], queried_pks={"cdc_test": {"orders": ["id"]}})

        act._load_pk_columns()

        assert act.reader.get_primary_key_columns.call_args.args == ("cdc_test", ["orders"])
        assert act.pk_columns_by_table == {"cdc_test.orders": ["id"]}
        assert schema.sync_type_config["primary_key_columns"] == ["id"]
        warnings = [call.args[0] for call in act.log.bind.return_value.warning.call_args_list]
        assert "cdc_pk_columns_first_write" in warnings

    def test_bare_name_falls_back_to_the_source_namespace(self):
        schema = _make_schema("orders")
        act = self._activity([schema], queried_pks={"analytics": {"orders": ["id"]}}, default_namespace="analytics")

        act._load_pk_columns()

        assert act.reader.get_primary_key_columns.call_args.args == ("analytics", ["orders"])
        assert act.pk_columns_by_table == {"orders": ["id"]}

    def test_tables_are_grouped_by_namespace(self):
        # One query per namespace, and two tables sharing a relation name stay distinct.
        act = self._activity(
            [_make_schema("cdc_test.orders"), _make_schema("public.orders")],
            queried_pks={"cdc_test": {"orders": ["id"]}, "public": {"orders": ["uuid"]}},
        )

        act._load_pk_columns()

        queried_namespaces = {call.args[0] for call in act.reader.get_primary_key_columns.call_args_list}
        assert queried_namespaces == {"cdc_test", "public"}
        assert act.pk_columns_by_table == {"cdc_test.orders": ["id"], "public.orders": ["uuid"]}

    def test_stored_keys_are_not_requeried(self):
        schema = _make_schema("cdc_test.orders")
        schema.sync_type_config["primary_key_columns"] = ["id"]
        act = self._activity([schema])

        act._load_pk_columns()

        act.reader.get_primary_key_columns.assert_not_called()
        assert act.pk_columns_by_table == {"cdc_test.orders": ["id"]}


class TestPKDivergenceDetection:
    def _activity(self, decoder_pks, stored_pks, table="cdc_test.orders"):
        source = _make_source()
        schema = _make_schema(table, source=source)
        act = _make_extract_activity(source)
        act.cdc_schemas = [schema]
        act.schema_by_name = {table: schema}
        act.all_table_names = {table}
        act.pk_columns_by_table = {table: stored_pks}
        act.reader = MagicMock()
        act.reader.get_decoder_key_columns.return_value = decoder_pks
        return act, schema

    @parameterized.expand(
        [
            # The qualified name is the whole point: it is what ExternalDataSchema.name holds, and
            # the decoder used to match only the bare relation name, so this never fired.
            ("key_gained_a_column", ["id", "tenant_id"], ["id"], True),
            ("key_replaced", ["uuid"], ["id"], True),
            # pg_catalog orders by index position, the decoder by column position.
            ("same_key_different_order", ["tenant_id", "id"], ["id", "tenant_id"], False),
            ("unchanged", ["id"], ["id"], False),
            # What REPLICA IDENTITY FULL and NOTHING both report.
            ("no_key_in_wal", [], ["id"], False),
        ]
    )
    def test_divergence_warns_only_on_a_real_change(self, _name, decoder_pks, stored_pks, expect_warning):
        act, _schema = self._activity(decoder_pks, stored_pks)

        act._detect_pk_changes_post_wal()

        warnings = [call.args[0] for call in act.log.bind.return_value.warning.call_args_list]
        assert ("cdc_pk_columns_diverged" in warnings) is expect_warning

    def test_diverged_key_is_not_persisted_over_the_merge_key(self):
        # Re-keying a live Delta table duplicates every row already merged under the old key, so a
        # detected change stays a signal until an operator re-snapshots the table.
        act, schema = self._activity(["id", "tenant_id"], ["id"])

        act._detect_pk_changes_post_wal()

        assert "primary_key_columns" not in schema.sync_type_config
        assert act.pk_columns_by_table["cdc_test.orders"] == ["id"]


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
        self.pre_read_position = "0/900"

    def connect(self):
        pass

    def current_position(self):
        return self.pre_read_position

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


class TestQuietRunSlotAdvance:
    """A run that decodes nothing releases the WAL it examined, so a quiet publication on a busy
    source stops retaining WAL until the lag safety net drops the slot. The peek must have reached
    the end of the backlog first: a short read leaves records below that position unexamined."""

    @pytest.mark.parametrize(
        "drained,pre_read,already_confirmed,expected_advances",
        [
            (True, "0/900", None, ["0/900"]),
            (False, "0/900", None, []),
            (True, None, None, []),
            (True, "0/900", "0/500", []),
        ],
    )
    def test_quiet_run_advance_conditions(self, drained, pre_read, already_confirmed, expected_advances):
        source = _make_source()
        act = _make_extract_activity(source)
        act.cdc_schemas = [_make_schema("users", source=source)]
        act.reader = MagicMock(last_commit_end_lsn=None)
        act._pre_read_position = pre_read
        act._backlog_drained = drained
        act.last_confirmed_lsn = already_confirmed

        act._handle_no_changes([])

        assert [c.args[0] for c in act.reader.confirm_position.call_args_list] == expected_advances

    def test_a_failed_quiet_advance_does_not_fail_the_run(self):
        source = _make_source()
        act = _make_extract_activity(source)
        act.cdc_schemas = [_make_schema("users", source=source)]
        act.reader = MagicMock(last_commit_end_lsn=None)
        act.reader.confirm_position.side_effect = RuntimeError("slot is active for PID 42")
        act._pre_read_position = "0/900"
        act._backlog_drained = True

        act._handle_no_changes([])

        assert "cdc_last_run_at" in act.cdc_schemas[0].sync_type_config

    def test_a_quiet_run_releases_the_wal_up_to_where_its_peek_began(self):
        # WAL committed after the peek began was never examined, so the release must stop at the
        # position taken before the peek.
        source = _make_source()
        schema = _make_schema("users", source=source)

        with _capture_harness(source, [schema]) as capture:
            capture.reader.current_position.side_effect = lambda: (
                "0/A00" if capture.reader.read_changes.called else "0/900"
            )
            capture.extract()

        capture.reader.confirm_position.assert_called_once_with("0/900")
        capture.reader.close.assert_called_once()


class TestCDCBoundedReadLoop:
    """The read loop peeks at most CDC_MAX_CHANGES_PER_READ changes per pass, advancing the slot
    between passes so a large backlog drains over several passes (and, if needed, runs)."""

    def _run_with_reader(self, reader) -> SimpleNamespace:
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["primary_key_columns"] = ["id"]
        with _capture_harness(source, [schema]) as capture:
            # Replace the default MagicMock reader with the scripted multi-pass reader.
            capture.adapter.create_reader.return_value = reader
            capture.extract()
        return capture

    def test_full_page_then_drained_advances_slot_between_passes(self):
        reader = _ScriptedReader(
            [
                ([_make_event(op="I", table="users", position="0/100")], CDC_MAX_CHANGES_PER_READ, "0/100"),
                ([_make_event(op="I", table="users", position="0/200")], 5, "0/200"),
            ]
        )

        capture = self._run_with_reader(reader)

        # Two peeks: a full page, then a drained one. The first pass advances the slot to its last
        # commit before re-peeking; the final flush advances to the second pass's last event.
        assert len(reader.upto_nchanges_calls) == 2
        assert reader.confirmed_positions == ["0/100", "0/200"]
        # The first pass is written before the second peek, so the advance between them releases
        # nothing that exists only in memory.
        written = [
            c.kwargs["table"].column(CDC_SEQ_COLUMN).to_pylist() for c in capture.buffer.write_batch.call_args_list
        ]
        assert written == [[0x100], [0x200]]
        # The per-row heartbeat callback was wired through read_changes and fired during the reads.
        assert reader.on_row_calls == 2

    def test_soft_deadline_stops_starting_new_passes(self, monkeypatch):
        # Deadline already elapsed: a full first page must not start a second pass.
        monkeypatch.setattr(f"{_ACTIVITIES}.CDC_READ_SOFT_DEADLINE_SECONDS", 0)
        reader = _ScriptedReader(
            [([_make_event(op="I", table="users", position="0/100")], CDC_MAX_CHANGES_PER_READ, "0/100")]
        )

        capture = self._run_with_reader(reader)

        assert len(reader.upto_nchanges_calls) == 1  # no second peek despite a full page
        # The run still delivers what it read.
        capture.buffer.write_batch.assert_called_once()
        assert reader.confirmed_positions == ["0/100"]

    def test_full_page_with_no_committed_progress_doubles_the_limit(self):
        # Defensive backstop: a full page that commits nothing (so the slot can't advance) grows
        # the window instead of re-peeking the identical page forever.
        reader = _ScriptedReader(
            [
                ([], CDC_MAX_CHANGES_PER_READ, None),
                ([_make_event(op="I", table="users", position="0/300")], 5, "0/300"),
            ]
        )

        self._run_with_reader(reader)

        assert reader.upto_nchanges_calls == [CDC_MAX_CHANGES_PER_READ, CDC_MAX_CHANGES_PER_READ * 2]
        assert reader.confirmed_positions == ["0/300"]  # nothing to advance on pass 1; pass 2 drains

    def test_heartbeat_timeout_does_not_abort_the_read_loop(self):
        # The Temporal SDK relays a sync activity's heartbeat through the worker's event loop
        # with its own short internal timeout, which can trip transiently under load. That must
        # never fail an otherwise-healthy extraction.
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["primary_key_columns"] = ["id"]
        events = [_make_event(op="I", table="users", position="0/100")]

        with _capture_harness(source, [schema], events) as capture:
            capture.activity.heartbeat.side_effect = TimeoutError()
            capture.extract()

        assert capture.activity.heartbeat.called
        capture.buffer.write_batch.assert_called_once()
        capture.reader.confirm_position.assert_called_once_with("0/100")


@pytest.mark.django_db
class TestFailureVisibilityCooldown:
    """A source that stays unreachable re-fails on every tick, and the schedule retries each failed
    tick at the workflow level on top of that. Without a cooldown one outage stamps the same row per
    schema many times an hour, for days — burying the runs that actually differ."""

    CONNECTION_FAILED = cdc_error_info(CDCErrorCategory.CONNECTION_FAILED).friendly_message
    AUTH_FAILED = cdc_error_info(CDCErrorCategory.AUTH_FAILED).friendly_message

    @pytest.mark.parametrize(
        "previous_error,previous_age_minutes,scheduled_sync_since,expect_new_row",
        [
            # Nothing has changed since the last extraction row said exactly this — no new row.
            pytest.param(CONNECTION_FAILED, 0, False, False, id="identical_failure_within_cooldown"),
            # The table's own scheduled sync runs alongside capture; its rows say nothing about
            # whether this failure has been reported, so they don't reopen it.
            pytest.param(CONNECTION_FAILED, 0, True, False, id="unrelated_scheduled_sync_since"),
            # Everything below is news, so the outage gets a fresh row.
            pytest.param(CONNECTION_FAILED, 90, False, True, id="identical_failure_past_cooldown"),
            pytest.param(AUTH_FAILED, 0, False, True, id="different_error_since"),
        ],
    )
    def test_repeat_failure_rows_collapse_until_something_changes(
        self,
        previous_error,
        previous_age_minutes,
        scheduled_sync_since,
        expect_new_row,
        team,
    ):
        source = ExternalDataSource.objects.create(
            team_id=team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            status="Running",
            source_type="Postgres",
        )
        schema = ExternalDataSchema.objects.create(
            team_id=team.pk,
            source=source,
            name="users",
            sync_type=ExternalDataSchema.SyncType.CDC,
            sync_type_config={"cdc_mode": "streaming"},
        )

        previous = ExternalDataJob.objects.create(
            team_id=team.pk,
            pipeline_id=source.pk,
            schema=schema,
            status=ExternalDataJob.Status.FAILED,
            rows_synced=0,
            latest_error=previous_error,
            workflow_id=f"cdc-extraction-{source.pk}-2026-08-04T18:15:00Z",
            workflow_run_id="run-1",
            pipeline_version=ExternalDataJob.PipelineVersion.V3,
        )
        # created_at is auto_now_add; backdate via update to control the cooldown window.
        ExternalDataJob.objects.filter(id=previous.id).update(
            created_at=datetime.now(UTC) - timedelta(minutes=previous_age_minutes)
        )

        if scheduled_sync_since:
            ExternalDataJob.objects.create(
                team_id=team.pk,
                pipeline_id=source.pk,
                schema=schema,
                status=ExternalDataJob.Status.COMPLETED,
                rows_synced=0,
                workflow_id=f"{schema.pk}-2026-08-04T18:20:00Z",
                workflow_run_id="run-scheduled-sync",
                pipeline_version=ExternalDataJob.PipelineVersion.V3,
            )

        activity_obj = CDCExtractActivity(CDCExtractInput(team_id=team.pk, source_id=source.pk))
        activity_obj.log = MagicMock()
        activity_obj.cdc_schemas = [schema]

        with patch("products.warehouse_sources.backend.temporal.data_imports.cdc.activities.activity") as mock_activity:
            mock_activity.info.return_value = MagicMock(
                workflow_id=f"cdc-extraction-{source.pk}-2026-08-04T18:25:00Z", workflow_run_id="run-2"
            )
            activity_obj._create_failure_visibility_jobs(self.CONNECTION_FAILED)

        rows_this_run = ExternalDataJob.objects.filter(schema=schema, workflow_run_id="run-2").count()
        assert rows_this_run == (1 if expect_new_row else 0)


class TestBufferedIngressCapture:
    # The buffer is the only delivery of a table's changes, and the table's scheduled sync consumes
    # it. A buffer failure must fail the run, because the slot is about to advance past those changes.

    def test_a_run_buffers_the_raw_change_stream_and_records_its_position(self):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", position="0/100", columns={"id": 1, "name": "Alice"}),
            _make_event(op="U", position="0/200", columns={"id": 1, "name": "Bob"}),
        ]

        with _capture_harness(source, [schema], events) as capture:
            capture.extract()

        buffered = capture.buffer.write_batch.call_args.kwargs["table"]
        # Raw stream, seq intact — the loader dedupes and resolves positions.
        assert buffered.column(CDC_SEQ_COLUMN).to_pylist() == [0x100, 0x200]
        # The point of the whole design: durable buffer releases the customer's WAL immediately.
        capture.reader.confirm_position.assert_called_once_with("0/200")
        assert schema.sync_type_config["cdc_last_log_position"] == "0/200"

    def test_wal_events_reach_the_schema_they_belong_to(self):
        # WAL events are always schema-qualified, but a schema's `name` may be stored bare. An exact
        # name match would drop every change for that schema, and the table would go stale despite a
        # healthy slot. Events for a table no schema covers are dropped.
        source = _make_source()
        schema = _make_schema("orders", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", table="public.orders", position="0/100", columns={"id": 1}),
            _make_event(op="I", table="public.not_synced", position="0/200", columns={"id": 2}),
        ]

        with _capture_harness(source, [schema], events) as capture:
            capture.extract()

        written = [
            (c.kwargs["schema_id"], c.kwargs["table"].num_rows) for c in capture.buffer.write_batch.call_args_list
        ]
        assert written == [(str(schema.id), 1)]

    @parameterized.expand(
        [
            ("known_mode_captured", "consolidated", True),
            # No lane consumes an unrecognized mode, so the buffer could never deliver its changes.
            ("unrecognized_mode_skipped", "not_a_table_mode", False),
        ]
    )
    def test_each_captured_table_gets_its_own_file(self, _name, orders_table_mode, orders_captured):
        source = _make_source()
        users = _make_schema("users", cdc_mode="streaming", source=source)
        orders = _make_schema("orders", cdc_mode="streaming", cdc_table_mode=orders_table_mode, source=source)
        events = [
            _make_event(op="I", table="users", position="0/100", columns={"id": 1}),
            _make_event(op="I", table="orders", position="0/200", columns={"id": 10}),
            _make_event(op="U", table="users", position="0/300", columns={"id": 1}),
        ]

        with _capture_harness(source, [users, orders], events) as capture:
            capture.extract()

        written = sorted(
            (c.kwargs["schema_id"], c.kwargs["table"].num_rows) for c in capture.buffer.write_batch.call_args_list
        )
        expected = [(str(users.id), 2), *([(str(orders.id), 1)] if orders_captured else [])]
        assert written == sorted(expected)
        capture.reader.confirm_position.assert_called_once_with("0/300")

    @parameterized.expand(
        [
            ("unmarked_snapshot_starts_in_an_emptied_buffer", {}, True),
            ("marked_snapshot_keeps_its_buffer", {CDC_SNAPSHOT_LANE_KEY: "buffer"}, False),
        ]
    )
    def test_a_snapshotting_tables_changes_wait_in_the_buffer(self, _name, config, purged):
        source = _make_source()
        seeding = _make_schema("events", cdc_mode="snapshot", source=source)
        seeding.initial_sync_complete = False
        seeding.sync_type_config.update(config)
        events = [_make_event(op="I", position="0/100", table="events", columns={"id": 1})]
        at_read: dict = {}

        with _capture_harness(source, [seeding], events) as capture:

            def _read_changes(**_kwargs):
                at_read["purges"] = [(c.args[1], c.kwargs["strict"]) for c in capture.purge.call_args_list]
                at_read["lane"] = seeding.sync_type_config.get(CDC_SNAPSHOT_LANE_KEY)
                return iter(events)

            capture.reader.read_changes.side_effect = _read_changes
            capture.extract()

        # Emptied before the read, and strictly: files from before a gap in capture must not replay
        # over the snapshot. Marked before the read too. Otherwise a crash after the first write would
        # have the next run empty the buffer again and drop changes the slot already released.
        expected_purges = [(str(seeding.id), True)] if purged else []
        assert at_read == {"purges": expected_purges, "lane": "buffer"}
        assert capture.purge.call_count == len(expected_purges)
        capture.buffer.write_batch.assert_called_once()

    def test_a_snapshot_that_hands_over_first_is_left_unmarked(self):
        # The hand-over clears the marker when it flips the table. A marker set after the flip would
        # outlive the snapshot it described.
        source = _make_source()
        schema = _make_schema("users", cdc_mode="snapshot", source=source)
        act = _make_extract_activity(source)

        with patch(
            f"{_ACTIVITIES}.purge_buffer_prefix",
            side_effect=lambda *_a, **_k: schema.sync_type_config.update(cdc_mode="streaming"),
        ):
            act._start_snapshot_in_buffer(schema)

        assert CDC_SNAPSHOT_LANE_KEY not in schema.sync_type_config

    def test_a_truncate_is_handled_before_the_slot_advances_past_it(self):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        act = _make_extract_activity(source)
        act.cdc_schemas = [schema]
        act.schema_by_name = {"users": schema}
        act._buffered_table_names = {"users"}
        act.batcher = MagicMock(event_count=0)
        act.reader = MagicMock(truncated_tables=["users"], last_commit_end_lsn="0/300")
        order = MagicMock()

        with (
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.cdc.activities.purge_buffer_prefix",
                side_effect=lambda *_a, **_k: order.purge(),
            ),
            patch.object(act, "_confirm_position", side_effect=lambda *_a: order.confirm()),
            patch.object(act, "_unpause_schema_schedule"),
        ):
            act._drain_and_advance_page()

        assert [call[0] for call in order.mock_calls] == ["purge", "confirm"]

    @parameterized.expand(
        [
            # The re-snapshot covers the changes read before the TRUNCATE, and buffering them would
            # bring the truncated rows back.
            ("after_changes_in_the_same_run", [_make_event(op="I", position="0/100", columns={"id": 1})], "users"),
            ("with_no_other_changes", [], "users"),
            # The decoder reports a truncated table qualified, even when the schema is stored bare.
            ("reported_qualified_for_a_bare_schema", [], "public.users"),
        ]
    )
    def test_a_truncate_resets_the_table_to_a_snapshot_in_an_emptied_buffer(self, _name, events, truncated_name):
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.sync_type_config["cdc_last_log_position"] = "0/OLD"

        with _capture_harness(source, [schema], events) as capture:
            capture.reader.truncated_tables = [truncated_name]
            capture.reader.last_commit_end_lsn = "0/500"
            capture.extract()

        capture.buffer.write_batch.assert_not_called()
        # Strict, because a stale file that survives the run would be replayed over the re-snapshot.
        assert [(c.args[1], c.kwargs["strict"]) for c in capture.purge.call_args_list] == [(str(schema.id), True)]
        assert schema.sync_type_config["cdc_mode"] == "snapshot"
        assert schema.sync_type_config["reset_pipeline"] is True
        assert schema.sync_type_config[CDC_SNAPSHOT_LANE_KEY] == "buffer"
        assert "cdc_last_log_position" not in schema.sync_type_config
        assert schema.initial_sync_complete is False
        # The TRUNCATE commits after the last row event, in a transaction of its own. Confirming only that
        # event's position would read the TRUNCATE again and reset the table a second time.
        capture.reader.confirm_position.assert_called_once_with("0/500")

    @parameterized.expand(
        [
            ("cancelled", None),
            ("already_finished", RPCError("workflow not found", RPCStatusCode.NOT_FOUND, b"")),
            ("temporal_unavailable", RPCError("unavailable", RPCStatusCode.UNAVAILABLE, b"")),
        ]
    )
    @patch(f"{_ACTIVITIES}.purge_buffer_prefix")
    @patch("products.warehouse_sources.backend.temporal.data_imports.cdc.snapshot_lane.ExternalDataJob")
    def test_a_reset_stops_the_tables_running_sync_first(self, _name, cancel_error, MockJob, mock_purge):
        # A snapshot that started before a repeated reset missed the changes the reset drops, so it
        # must not reach its hand-over.
        source = _make_source()
        schema = _make_schema("users", cdc_mode="snapshot", source=source)
        act = _make_extract_activity(source)
        running = MockJob.objects.filter.return_value.exclude.return_value.exclude.return_value
        running.order_by.return_value.first.return_value = MagicMock(workflow_id="users-snapshot")
        fails = cancel_error is not None and cancel_error.status != RPCStatusCode.NOT_FOUND

        with (
            patch(f"{_ACTIVITIES}.cancel_running_sync", cancel_running_sync),
            patch(
                "products.data_warehouse.backend.facade.api.cancel_external_data_workflow",
                side_effect=cancel_error,
            ) as cancel,
        ):
            if fails:
                with pytest.raises(RPCError):
                    act._reset_schema_to_snapshot(schema)
            else:
                act._reset_schema_to_snapshot(schema)

        cancel.assert_called_once_with("users-snapshot")
        # A cancel that did not go through fails the run before the reset, so the retry repeats both.
        assert mock_purge.called is not fails
        assert schema.sync_type_config.get("reset_pipeline") is (None if fails else True)

    @parameterized.expand(
        [
            ("s3_error_on_write", "streaming", [], lambda c: c.buffer.write_batch, RuntimeError("s3 down")),
            # The dropped connection stays in Django's pool. The failure handler must evict it before
            # it records the failure, or that write fails too and the friendly message is lost.
            (
                "dropped_app_db_connection_on_write",
                "streaming",
                [],
                lambda c: c.buffer.write_batch,
                OperationalError("the connection is closed"),
            ),
            # Runs before the WAL read, outside the read loop's own error handling.
            ("purge_that_starts_a_snapshot", "snapshot", [], lambda c: c.purge, RuntimeError("s3 down")),
            # The hand-over keeps every file of a marked schema, so a marker left by a failed purge
            # would replay the pre-TRUNCATE files over the re-snapshot.
            ("purge_after_a_truncate", "streaming", ["users"], lambda c: c.purge, RuntimeError("s3 down")),
        ]
    )
    def test_a_buffer_failure_fails_the_run_and_leaves_the_slot(
        self, _name, cdc_mode, truncated_tables, failing_call, error
    ):
        # Swallowing here would advance the slot past changes that reached nothing, losing them for good.
        source = _make_source()
        schema = _make_schema("users", cdc_mode=cdc_mode, source=source)
        events = [_make_event(op="I", position="0/100", columns={"id": 1})]

        with _capture_harness(source, [schema], events) as capture:
            capture.reader.truncated_tables = truncated_tables
            failing_call(capture).side_effect = error
            with pytest.raises(type(error), match=str(error)):
                capture.extract()

        capture.reader.confirm_position.assert_not_called()
        # The schema shows the friendly message, never the raw error.
        assert schema.status == "Failed"
        assert schema.latest_error == cdc_error_info(CDCErrorCategory.UNKNOWN).friendly_message
        assert schema.sync_type_config["cdc_mode"] == cdc_mode
        assert CDC_SNAPSHOT_LANE_KEY not in schema.sync_type_config
        # Once when the run starts, and once in the failure handler before it writes the failure.
        assert capture.close_old_connections.call_count == 2

    def test_a_crash_mid_transaction_leaves_a_file_straddling_the_restart(self):
        class _DyingStream:
            def __init__(self, events):
                self._events = events

            def __len__(self):
                return len(self._events)

            def __iter__(self):
                yield from self._events
                raise RuntimeError("pod killed mid-transaction")

        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [
            _make_event(op="I", position="0/100", columns={"id": 1}),
            _make_event(op="I", position="0/100", columns={"id": 2}),
            _make_event(op="I", position="0/200", columns={"id": 3}),
            _make_event(op="I", position="0/200", columns={"id": 4}),
        ]

        with (
            _capture_harness(source, [schema], _DyingStream(events)) as capture,
            patch(
                f"{_ACTIVITIES}.ChangeEventBatcher",
                side_effect=lambda **kwargs: ChangeEventBatcher(max_events=4, **kwargs),
            ),
            pytest.raises(RuntimeError, match="pod killed mid-transaction"),
        ):
            capture.extract()

        written = capture.buffer.write_batch.call_args.kwargs["table"]
        assert written.column(CDC_SEQ_COLUMN).to_pylist() == [0x100, 0x100, 0x200, 0x200]
        capture.reader.confirm_position.assert_called_once_with("0/100")
        capture.buffer.cleanup_superseded_files.assert_called_once_with(
            team_id=schema.team_id, schema_id=str(schema.id), restart_seq=0x100
        )

    def test_a_source_column_named_like_seq_fails_the_buffered_run(self):
        # The batcher skips its append on the collision, so the file's name, ordering, and retry
        # cleanup would all derive from customer data — cleanup can then delete unconsumed files.
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        events = [_make_event(op="I", position="0/100", columns={"id": 1, CDC_SEQ_COLUMN: 42})]

        with (
            _capture_harness(source, [schema], events) as capture,
            pytest.raises(NonRetryableException, match=CDC_SEQ_COLUMN),
        ):
            capture.extract()

        capture.buffer.write_batch.assert_not_called()
        capture.reader.confirm_position.assert_not_called()

    @parameterized.expand(
        [
            ("quiet_run", [], 0),
            (
                "run_with_changes",
                [_make_event(op="I", position="0/100"), _make_event(op="U", position="0/200")],
                2,
            ),
        ]
    )
    def test_a_completed_run_records_a_heartbeat_but_leaves_the_status_to_the_consumer(
        self, _name, events, expected_event_count
    ):
        # The scheduled sync that consumes the buffer owns the schema's status. Capture repainting it
        # every tick would erase a failing consumer run within minutes and hide a buffer backlog until
        # its files expire.
        source = _make_source()
        schema = _make_schema("users", cdc_mode="streaming", source=source)
        schema.status = ExternalDataSchema.Status.FAILED
        schema.latest_error = "The consumer's own failure"
        schema.sync_type_config["cdc_extraction_paused"] = {"reason": "transaction_too_large"}

        with _capture_harness(source, [schema], events) as capture:
            capture.extract()

        config = schema.sync_type_config
        # The heartbeat proves a quiet source's extraction is alive, as an ISO-8601 string the
        # health check parses back.
        assert config["cdc_last_run_event_count"] == expected_event_count
        datetime.fromisoformat(config["cdc_last_run_at"])
        # A completed run proves extraction runs again, and the consumer cannot clear this marker.
        assert "cdc_extraction_paused" not in config
        assert schema.status == ExternalDataSchema.Status.FAILED
        assert schema.latest_error == "The consumer's own failure"
