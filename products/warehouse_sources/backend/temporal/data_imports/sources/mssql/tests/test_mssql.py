import pytest
from unittest.mock import MagicMock

import pymssql

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import Table, TableStats
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MSSQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql import (
    _SSH_HANDSHAKE_EOF_ERROR,
    MSSQLColumn,
    MSSQLImplementation,
    _build_query,
    _is_deadlock_victim_error,
    _is_transient_connection_error,
    filter_mssql_incremental_fields,
    retry_on_deadlock,
    retry_on_transient_connection_error,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mssql.source import MSSQLSource
from products.warehouse_sources.backend.types import IncrementalFieldType


def _make_config(**overrides) -> MSSQLSourceConfig:
    defaults: dict = {
        "host": "localhost",
        "port": 1433,
        "database": "d",
        "user": "u",
        "password": "p",
        "schema": "dbo",
    }
    defaults.update(overrides)
    return MSSQLSourceConfig.from_dict(defaults)


def _make_inputs(schema_name: str = "messages", **overrides) -> SourceInputs:
    defaults: dict = {
        "schema_name": schema_name,
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestFilterMSSQLIncrementalFields:
    @pytest.mark.parametrize(
        "col_type,expected",
        [
            ("date", IncrementalFieldType.Date),
            ("datetime", IncrementalFieldType.DateTime),
            ("datetime2", IncrementalFieldType.DateTime),
            ("smalldatetime", IncrementalFieldType.DateTime),
            ("tinyint", IncrementalFieldType.Integer),
            ("smallint", IncrementalFieldType.Integer),
            ("int", IncrementalFieldType.Integer),
            ("bigint", IncrementalFieldType.Integer),
        ],
    )
    def test_recognized_types(self, col_type, expected):
        result = filter_mssql_incremental_fields([("col", col_type, True)])
        assert result == [("col", expected, True)]

    def test_drops_unsupported(self):
        result = filter_mssql_incremental_fields([("col", "varchar", False)])
        assert result == []


class TestMSSQLColumnToArrowField:
    def test_decimal_requires_precision(self):
        col = MSSQLColumn(name="x", data_type="decimal", nullable=True)
        with pytest.raises(TypeError, match="numeric_precision"):
            col.to_arrow_field()


class TestBuildQuery:
    def test_full_refresh_no_incremental(self):
        query, args = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
        )
        assert "SELECT" in query
        assert "[dbo].[users]" in query
        assert "TOP" not in query
        assert args == {}

    def test_incremental_adds_where(self):
        query, args = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
        )
        assert "WHERE [created_at]" in query
        assert "%(incremental_value)s" in query
        assert args == {"incremental_value": "2025-01-01"}

    def test_row_filters_full_refresh(self):
        query, args = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        assert "WHERE [age] > %(row_filter_0)s" in query
        assert args == {"row_filter_0": 21}

    def test_in_filter_expands_to_named_placeholders(self):
        query, args = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            row_filters=[
                ValidatedRowFilter(column="age", operator="IN", value=[21, 30], category=ColumnTypeCategory.INTEGER)
            ],
        )
        assert "WHERE [age] IN (%(row_filter_0_0)s, %(row_filter_0_1)s)" in query
        assert args == {"row_filter_0_0": 21, "row_filter_0_1": 30}

    def test_row_filters_compose_with_incremental(self):
        query, args = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        assert "WHERE [created_at] > %(incremental_value)s AND [age] > %(row_filter_0)s" in query
        assert args == {"incremental_value": "2025-01-01", "row_filter_0": 21}

    def test_row_filter_value_never_interpolated(self):
        query, args = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            row_filters=[
                ValidatedRowFilter(
                    column="name", operator="=", value="x'; DROP TABLE y; --", category=ColumnTypeCategory.STRING
                )
            ],
        )
        assert "DROP TABLE" not in query
        assert args == {"row_filter_0": "x'; DROP TABLE y; --"}

    def test_add_limit_uses_top_100(self):
        query, _ = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            add_limit=True,
        )
        assert "TOP 100" in query

    def test_incremental_requires_field(self):
        with pytest.raises(ValueError, match="incremental_field"):
            _build_query(
                schema="dbo",
                table_name="users",
                should_use_incremental_field=True,
                incremental_field=None,
                incremental_field_type=None,
                db_incremental_field_last_value=None,
            )

    @pytest.mark.parametrize(
        "schema,table_name,expected_from",
        [
            # Injection payloads are neutralised by bracket-quoting (a literal `]`
            # is doubled), so the whole payload stays inside one quoted identifier.
            ("dbo]; DROP TABLE foo; --", "users", "FROM [dbo]]; DROP TABLE foo; --].[users]"),
            ("dbo", "users]; DROP TABLE foo; --", "FROM [dbo].[users]]; DROP TABLE foo; --]"),
            # Legal SQL Server names the old allowlist wrongly rejected.
            ("dbo with space", "users", "FROM [dbo with space].[users]"),
            ("dbo", "users'name", "FROM [dbo].[users'name]"),
            ("dbo", "Orden#", "FROM [dbo].[Orden#]"),
        ],
    )
    def test_quotes_schema_or_table_safely(self, schema, table_name, expected_from):
        query, _ = _build_query(
            schema=schema,
            table_name=table_name,
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
        )
        assert expected_from in query

    def test_rejects_control_char_in_table(self):
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _build_query(
                schema="dbo",
                table_name="users\nname",
                should_use_incremental_field=False,
                incremental_field=None,
                incremental_field_type=None,
                db_incremental_field_last_value=None,
            )

    def test_quotes_unsafe_incremental_field_safely(self):
        query, _ = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=True,
            incremental_field="created_at]; DROP TABLE foo; --",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
        )
        assert "WHERE [created_at]]; DROP TABLE foo; --]" in query


class TestBuildQueryEnabledColumns:
    @pytest.mark.parametrize(
        "enabled_columns,primary_keys,expected_select",
        [
            (None, ["id"], "SELECT * FROM"),
            (["email"], ["id"], "SELECT [email], [id] FROM"),
            ([], None, "SELECT * FROM"),
            ([], ["id"], "SELECT [id] FROM"),
        ],
    )
    def test_full_refresh_projection(self, enabled_columns, primary_keys, expected_select):
        query, _ = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            enabled_columns=enabled_columns,
            primary_keys=primary_keys,
        )
        assert query.startswith(expected_select)

    def test_incremental_projection_retains_incremental_field(self):
        query, args = _build_query(
            schema="dbo",
            table_name="users",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
            enabled_columns=["email"],
            primary_keys=["id"],
        )
        assert query.startswith("SELECT [email], [id], [created_at] FROM")
        assert "WHERE [created_at] > %(incremental_value)s" in query
        assert args == {"incremental_value": "2025-01-01"}


# ---------------------------------------------------------------------------
# Per-cursor metadata queries
# ---------------------------------------------------------------------------


@pytest.fixture
def impl() -> MSSQLImplementation:
    return MSSQLImplementation()


@pytest.fixture
def logger() -> MagicMock:
    return MagicMock()


@pytest.fixture
def cursor() -> MagicMock:
    c = MagicMock()
    c.fetchall.return_value = []
    c.fetchone.return_value = None
    c.description = None
    return c


class TestGetPrimaryKeysForTable:
    def test_returns_none_when_no_rows(self, impl, cursor):
        cursor.fetchall.return_value = []
        assert impl.get_primary_keys_for_table(cursor, "dbo", "t") is None

    def test_returns_pk_column_names(self, impl, cursor):
        cursor.fetchall.return_value = [("id",), ("email",)]
        assert impl.get_primary_keys_for_table(cursor, "dbo", "t") == ["id", "email"]

    def test_uses_parameterized_query(self, impl, cursor):
        impl.get_primary_keys_for_table(cursor, "dbo", "mytable")
        sql, params = cursor.execute.call_args.args
        assert "%(schema)s" in sql
        assert "%(table_name)s" in sql
        assert params == {"schema": "dbo", "table_name": "mytable"}


class TestGetTableMetadata:
    def test_builds_table_with_non_numeric_columns(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("id", "int", True, None, None),
                ("email", "varchar", False, None, None),
            ]
        )
        table = impl.get_table_metadata(cursor, "dbo", "users")
        assert isinstance(table, Table)
        assert table.name == "users"
        assert table.parents == ("dbo",)
        assert len(table.columns) == 2
        assert all(isinstance(c, MSSQLColumn) for c in table.columns)
        assert table.columns[0].numeric_precision is None

    def test_populates_numeric_precision_and_scale_for_decimals(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", False, 10, 2),
            ]
        )
        table = impl.get_table_metadata(cursor, "dbo", "orders")
        assert table.columns[0].numeric_precision == 10
        assert table.columns[0].numeric_scale == 2

    def test_falls_back_to_defaults_when_decimal_missing_precision(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", False, None, None),
            ]
        )
        table = impl.get_table_metadata(cursor, "dbo", "orders")
        assert isinstance(table.columns[0].numeric_precision, int)
        assert isinstance(table.columns[0].numeric_scale, int)

    def test_raises_when_no_columns(self, impl, cursor):
        cursor.__iter__.return_value = iter([])
        with pytest.raises(ValueError, match="not found"):
            impl.get_table_metadata(cursor, "dbo", "missing")


class TestFetchTableStats:
    def test_returns_none_when_no_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.fetch_table_stats(cursor, "dbo", "t", logger) is None

    def test_returns_table_stats_dataclass(self, impl, cursor, logger):
        # sp_spaceused result shape: name, rows, reserved, data, index_size, unused
        cursor.fetchone.return_value = ("t", "1000", "40 KB", "32 KB", "8 KB", "0 KB")
        stats = impl.fetch_table_stats(cursor, "dbo", "t", logger)
        assert stats == TableStats(table_size_bytes=32 * 1024, row_count=1000)

    def test_returns_none_on_unknown_unit(self, impl, cursor, logger):
        cursor.fetchone.return_value = ("t", "1000", "40 ZB", "32 ZB", "8 ZB", "0 ZB")
        assert impl.fetch_table_stats(cursor, "dbo", "t", logger) is None

    def test_returns_none_when_view_returns_null_stats(self, impl, cursor, logger, mocker):
        # sp_spaceused on a view returns NULL for rows/reserved/data. This must be a graceful
        # skip — not an int(None) crash routed through capture_exception (which floods error tracking).
        capture = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.capture_exception"
        )
        cursor.fetchone.return_value = ("vw_thing", None, None, None, "0 KB", "0 KB")
        assert impl.fetch_table_stats(cursor, "dbo", "vw_thing", logger) is None
        capture.assert_not_called()

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        assert impl.fetch_table_stats(cursor, "dbo", "t", logger) is None


class TestFetchAverageRowSize:
    """MSSQL's `fetch_average_row_size` samples a separate `TOP 100` query
    rather than the live inner_query, so the `inner_query` / `inner_query_args`
    arguments are accepted for API parity but unused."""

    def test_returns_none_when_no_columns(self, impl, cursor, logger):
        cursor.fetchall.return_value = []
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_none_when_sample_empty(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = None
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_row_size_bytes(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = (256.4,)
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result == 256

    def test_clamps_to_at_least_one(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",)]
        cursor.fetchone.return_value = (0,)
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result == 1

    def test_uses_separate_top_100_sample(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",)]
        cursor.fetchone.return_value = (10,)
        impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        size_query = cursor.execute.call_args_list[1].args[0]
        assert "TOP 100" in size_query
        assert "DATALENGTH([id])" in size_query

    def test_handles_column_names_with_special_chars(self, impl, cursor, logger):
        # Real SQL Server columns like `Orden#` are legal under bracket-quoting;
        # they must be sampled, not crash the quoter (the bug this fixes).
        cursor.fetchall.return_value = [("Orden#",), ("Forma Pago",)]
        cursor.fetchone.return_value = (42,)
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result == 42
        size_query = cursor.execute.call_args_list[1].args[0]
        assert "DATALENGTH([Orden#])" in size_query
        assert "DATALENGTH([Forma Pago])" in size_query

    def test_rejects_control_char_column_names(self, impl, cursor, logger):
        # A column name with a control character can't be made safe by
        # bracket-quoting, so the quoter rejects it; the method catches
        # and returns None.
        cursor.fetchall.return_value = [("bad\ncol",)]
        cursor.fetchone.return_value = (1,)
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result is None


# ---------------------------------------------------------------------------
# End-to-end build_pipeline — wired through MSSQLImplementation
# ---------------------------------------------------------------------------


@pytest.fixture
def build_pipeline_mocks(mocker):
    """Patch pymssql.connect + per-cursor metadata methods on MSSQLImplementation
    so `build_pipeline` can run end-to-end without a real MSSQL server."""
    fake_table = Table(
        name="messages",
        parents=("dbo",),
        columns=[MSSQLColumn(name="id", data_type="int", nullable=False)],
    )
    mocker.patch.object(MSSQLImplementation, "get_table_metadata", return_value=fake_table)
    mocker.patch.object(MSSQLImplementation, "get_primary_keys_for_table", return_value=["id"])
    mocker.patch.object(MSSQLImplementation, "get_rows_to_sync", return_value=0)
    mocker.patch.object(MSSQLImplementation, "get_chunk_size", return_value=1000)
    mocker.patch.object(MSSQLImplementation, "get_partition_settings", return_value=None)

    streaming_cursor = MagicMock()
    streaming_cursor.__enter__.return_value = streaming_cursor
    streaming_cursor.description = [("id",)]
    streaming_cursor.fetchmany.return_value = []

    metadata_cursor = MagicMock()
    metadata_cursor.__enter__.return_value = metadata_cursor

    state = {"metadata_done": False}

    def cursor_factory(*args, **kwargs):
        if not state["metadata_done"]:
            state["metadata_done"] = True
            return metadata_cursor
        return streaming_cursor

    mock_connection = MagicMock()
    mock_connection.__enter__.return_value = mock_connection
    mock_connection.cursor.side_effect = cursor_factory

    mock_connect = mocker.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.pymssql.connect",
        return_value=mock_connection,
    )
    return mock_connect, streaming_cursor


def _drain_source():
    source = MSSQLImplementation().build_pipeline(_make_config(), _make_inputs())
    list(source.items())  # type: ignore[arg-type]


class TestBuildPipeline:
    def test_streams_through_separate_connection(self, build_pipeline_mocks):
        mock_connect, streaming_cursor = build_pipeline_mocks
        _drain_source()
        # Two connect calls: one for metadata, one for streaming.
        assert mock_connect.call_count == 2
        assert streaming_cursor.execute.called


class _RaisingTunnel:
    """Context manager whose `__enter__` raises, standing in for paramiko's handshake EOFError."""

    def __enter__(self):
        raise EOFError()

    def __exit__(self, *args):
        return False


class TestConnectSSHTunnel:
    def test_bare_handshake_eof_is_translated_and_non_retryable(self, mocker):
        mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.open_ssh_tunnel",
            return_value=_RaisingTunnel(),
        )
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.pymssql.connect"
        )

        with pytest.raises(Exception, match=_SSH_HANDSHAKE_EOF_ERROR) as exc_info:
            with MSSQLImplementation().connect(_make_config()):
                pass

        # Cause preserved, the database connection is never attempted, and the translated
        # message is classified non-retryable so the sync stops instead of retrying forever.
        assert isinstance(exc_info.value.__cause__, EOFError)
        mock_connect.assert_not_called()
        non_retryable = MSSQLSource().get_non_retryable_errors()
        assert any(pattern in str(exc_info.value) for pattern in non_retryable.keys())


class TestMSSQLSourceNonRetryableErrors:
    @pytest.mark.parametrize(
        "error_msg",
        [
            "Cannot build decimal array from values",
            "ValueError: Cannot build decimal array from values",
            "Source column type changed",
            "SchemaColumnTypeChangedException: Source column type changed: 'id' no longer fits",
        ],
    )
    def test_data_shape_errors_are_non_retryable(self, error_msg):
        non_retryable = MSSQLSource().get_non_retryable_errors()
        assert any(pattern in error_msg for pattern in non_retryable.keys()), error_msg

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Real pymssql DB-Lib error 20009 for an unreachable host.
            "DB-Lib error message 20009, severity 9:\nUnable to connect: Adaptive Server is "
            "unavailable or does not exist (cplapps.example.us-east-2.rds.amazonaws.com)",
            "Login failed for user 'reporting'.",
            # Raised by the sshtunnel library when the customer's SSH bastion can't be reached
            # (wrong host/port, rejected key, firewall) — the import goes through `open_ssh_tunnel`.
            "BaseSSHTunnelForwarderError: Could not establish session to SSH gateway",
            # `connect` translates paramiko's bare handshake EOFError into this message.
            _SSH_HANDSHAKE_EOF_ERROR,
        ],
    )
    def test_connection_errors_are_non_retryable(self, error_msg):
        non_retryable = MSSQLSource().get_non_retryable_errors()
        assert any(pattern in error_msg for pattern in non_retryable.keys()), error_msg

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Real pymssql MSSQLDatabaseException for SQL Server error 229 on a table.
            "SQL Server message 229, severity 14, state 5, procedure b'', line 1:\n"
            "b\"The SELECT permission was denied on the object 'ExistenciasProductoMagiQ', "
            "database 'VirtualMedios', schema 'dbo'.DB-Lib error message 20018, severity 14:\n"
            'General SQL Server error: Check messages from the SQL Server\n"',
            # Different object/database names must still match the stable substring.
            "The SELECT permission was denied on the object 'zzz_segtieint', database 'VirtualMedios', schema 'dbo'.",
        ],
    )
    def test_permission_denied_errors_are_non_retryable(self, error_msg):
        non_retryable = MSSQLSource().get_non_retryable_errors()
        assert any(pattern in error_msg for pattern in non_retryable.keys()), error_msg

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Real pymssql MSSQLDatabaseException for SQL Server error 208 raised mid-sync when the
            # view being selected references an object the login can't resolve.
            "SQL Server message 208, severity 16, state 1, procedure b'VentasAsesorMes', line 8: "
            "b\"Invalid object name 'Imagiq.dbo.inv_cuedoc'.DB-Lib error message 20018, severity 16:\\n"
            'General SQL Server error: Check messages from the SQL Server\\n"',
            # The table being synced was dropped/renamed after schema discovery.
            "Invalid object name 'dbo.orders'.",
        ],
    )
    def test_invalid_object_name_is_non_retryable(self, error_msg):
        non_retryable = MSSQLSource().get_non_retryable_errors()
        assert any(pattern in error_msg for pattern in non_retryable.keys()), error_msg

    @pytest.mark.parametrize(
        "error_msg",
        [
            # SQL Server error 207 — a referenced column no longer exists (dropped/renamed at the
            # source, or a view body that selects a column that's gone). Real pymssql message.
            "SQL Server message 207, severity 16, state 1, procedure b'\\xb0z\\x16,\\xff\\xff', line 39:\n"
            "Invalid column name 'usr_modelo'.DB-Lib error message 20018, severity 16:\n"
            "General SQL Server error: Check messages from the SQL Server",
            # Different column name must still match the stable substring.
            "Invalid column name 'created_at'.",
        ],
    )
    def test_invalid_column_name_is_non_retryable(self, error_msg):
        non_retryable = MSSQLSource().get_non_retryable_errors()
        assert any(pattern in error_msg for pattern in non_retryable.keys()), error_msg

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Real pymssql MSSQLDatabaseException for SQL Server error 245 raised mid-fetch when a
            # view body implicitly converts a varchar value to int.
            "SQL Server message 245, severity 16, state 1, procedure b'@\\x88[\\xd4\\xfe\\xff', line 1:\n"
            "b\"Conversion failed when converting the varchar value 'SFDR' to data type int."
            'DB-Lib error message 20018, severity 16:\\nGeneral SQL Server error: Check messages from the SQL Server\\n"',
            # Different value / target type must still match the stable substring.
            "Conversion failed when converting the nvarchar value 'N/A' to data type bigint.",
        ],
    )
    def test_conversion_failed_is_non_retryable(self, error_msg):
        non_retryable = MSSQLSource().get_non_retryable_errors()
        assert any(pattern in error_msg for pattern in non_retryable.keys()), error_msg

    def test_table_not_found_is_non_retryable(self, impl, cursor):
        # Drive the real raise site so the message and the rule can't drift apart: a table dropped
        # after schema discovery yields no columns from INFORMATION_SCHEMA and must stop retrying.
        cursor.__iter__.return_value = iter([])
        with pytest.raises(ValueError) as exc_info:
            impl.get_table_metadata(cursor, "dbo", "dropped_table")

        non_retryable = MSSQLSource().get_non_retryable_errors()
        assert any(pattern in str(exc_info.value) for pattern in non_retryable.keys())


class TestIsTransientConnectionError:
    @pytest.mark.parametrize(
        "error",
        [
            # Real pymssql shape: DB-Lib error 20047 carried as (code, bytes) args.
            pymssql.OperationalError(
                20047, b"DB-Lib error message 20047, severity 9:\nDBPROCESS is dead or not enabled\n"
            ),
            # The SQL-Server-message rendering of the same drop.
            pymssql.OperationalError(
                "SQL Server message 20047, severity 9, state 0, procedure b'\\xc0\\xaa\\x12\\x08\\xff\\xff', "
                "line 0:\nb'DB-Lib error message 20047, severity 9:\nDBPROCESS is dead or not enabled\n'"
            ),
        ],
    )
    def test_matches_dbprocess_dead(self, error):
        assert _is_transient_connection_error(error)

    @pytest.mark.parametrize(
        "error",
        [
            # Persistent failures must stay non-retryable, not be absorbed as transient.
            pymssql.OperationalError("Login failed for user 'reporting'."),
            pymssql.OperationalError("Invalid object name 'dbo.orders'."),
            pymssql.OperationalError("The SELECT permission was denied on the object 'X'."),
            pymssql.OperationalError(
                "DB-Lib error message 20009, severity 9:\nUnable to connect: Adaptive Server is "
                "unavailable or does not exist (db.example.com)"
            ),
            pymssql.OperationalError(),
        ],
    )
    def test_does_not_match_other_errors(self, error):
        assert not _is_transient_connection_error(error)


class TestRetryOnTransientConnectionError:
    def _dbprocess_dead(self) -> pymssql.OperationalError:
        return pymssql.OperationalError(
            20047, b"DB-Lib error message 20047, severity 9:\nDBPROCESS is dead or not enabled\n"
        )

    def test_retries_then_succeeds(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.time.sleep")
        operation = MagicMock(side_effect=[self._dbprocess_dead(), "ok"])

        assert retry_on_transient_connection_error(operation) == "ok"
        assert operation.call_count == 2
        sleep.assert_called_once()

    def test_does_not_retry_non_transient(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.time.sleep")
        operation = MagicMock(side_effect=pymssql.OperationalError("Login failed for user 'reporting'."))

        with pytest.raises(pymssql.OperationalError):
            retry_on_transient_connection_error(operation)
        assert operation.call_count == 1
        sleep.assert_not_called()

    def test_gives_up_after_max_attempts(self, mocker):
        mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.time.sleep")
        operation = MagicMock(side_effect=self._dbprocess_dead())

        with pytest.raises(pymssql.OperationalError):
            retry_on_transient_connection_error(operation, max_attempts=3)
        assert operation.call_count == 3


class TestGetSchemasRetriesTransientDrop:
    def test_get_schemas_retries_then_recovers(self, mocker):
        # A transient DBPROCESS death mid-discovery must retry the whole connect-and-discover cycle
        # in-process instead of failing the activity on the first blip.
        mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.time.sleep")
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.pymssql.connect",
            return_value=mock_conn,
        )
        get_columns = mocker.patch.object(
            MSSQLImplementation,
            "get_columns",
            side_effect=[
                pymssql.OperationalError(
                    20047, b"DB-Lib error message 20047, severity 9:\nDBPROCESS is dead or not enabled\n"
                ),
                {},
            ],
        )

        schemas = MSSQLSource().get_schemas(_make_config(), team_id=1)

        assert schemas == []
        assert get_columns.call_count == 2


class TestIsDeadlockVictimError:
    @pytest.mark.parametrize(
        "error",
        [
            # Real pymssql shape: SQL Server error 1205 carried as (code, bytes) args.
            pymssql.OperationalError(
                1205,
                b"Transaction (Process ID 116) was deadlocked on lock resources with another process and has "
                b"been chosen as the deadlock victim. Rerun the transaction.DB-Lib error message 20018, "
                b"severity 13:\nGeneral SQL Server error: Check messages from the SQL Server\n",
            ),
            # The SQL-Server-message rendering of the same deadlock.
            pymssql.OperationalError(
                "SQL Server message 1205, severity 13, state 52, procedure b'`\\x17\\x15\\xcc\\xfe\\xff', "
                "line 1:\nb'Transaction (Process ID 116) was deadlocked on lock resources with another process "
                "and has been chosen as the deadlock victim. Rerun the transaction."
            ),
        ],
    )
    def test_matches_deadlock_victim(self, error):
        assert _is_deadlock_victim_error(error)

    @pytest.mark.parametrize(
        "error",
        [
            # A connection death is transient too, but recovers via a fresh connect — not a rerun.
            pymssql.OperationalError(
                20047, b"DB-Lib error message 20047, severity 9:\nDBPROCESS is dead or not enabled\n"
            ),
            pymssql.OperationalError("Login failed for user 'reporting'."),
            pymssql.OperationalError("Invalid object name 'dbo.orders'."),
            pymssql.OperationalError(),
        ],
    )
    def test_does_not_match_other_errors(self, error):
        assert not _is_deadlock_victim_error(error)


class TestRetryOnDeadlock:
    def _deadlock_victim(self) -> pymssql.OperationalError:
        return pymssql.OperationalError(
            1205,
            b"Transaction (Process ID 116) was deadlocked on lock resources with another process and has been "
            b"chosen as the deadlock victim. Rerun the transaction.",
        )

    def test_retries_then_succeeds(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.time.sleep")
        operation = MagicMock(side_effect=[self._deadlock_victim(), "ok"])

        assert retry_on_deadlock(operation) == "ok"
        assert operation.call_count == 2
        sleep.assert_called_once()

    def test_does_not_retry_non_deadlock(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.time.sleep")
        operation = MagicMock(side_effect=pymssql.OperationalError("Login failed for user 'reporting'."))

        with pytest.raises(pymssql.OperationalError):
            retry_on_deadlock(operation)
        assert operation.call_count == 1
        sleep.assert_not_called()

    def test_gives_up_after_max_attempts(self, mocker):
        mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.time.sleep")
        operation = MagicMock(side_effect=self._deadlock_victim())

        with pytest.raises(pymssql.OperationalError):
            retry_on_deadlock(operation, max_attempts=3)
        assert operation.call_count == 3
