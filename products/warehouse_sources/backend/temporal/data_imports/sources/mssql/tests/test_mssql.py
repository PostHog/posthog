import threading

import pytest
from unittest.mock import MagicMock

import pymssql

from products.warehouse_sources.backend.temporal.data_imports.discover_schemas_workflow import (
    DISCOVER_SCHEMAS_ACTIVITY_TIMEOUT,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import error_message_matches
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import Table, TableStats
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mssql import MSSQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql import (
    _SSH_HANDSHAKE_EOF_ERROR,
    MSSQL_SCHEMA_DISCOVERY_DEADLINE_SECONDS,
    MSSQLColumn,
    MSSQLImplementation,
    MSSQLMetadataTimeoutError,
    _build_query,
    filter_mssql_incremental_fields,
    retry_on_deadlock,
    retry_on_transient_connection_error,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mssql.source import (
    _FIREWALL_BLOCKED_ERROR,
    MSSQLSource,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

_MSSQL_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql"


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


class TestMSSQLColumnToArrowField:
    def test_decimal_requires_precision(self):
        col = MSSQLColumn(name="x", data_type="decimal", nullable=True)
        with pytest.raises(TypeError, match="numeric_precision"):
            col.to_arrow_field()


class TestBuildQuery:
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

    def test_transient_connection_death_skips_retry_and_capture(self, impl, cursor, logger, mocker):
        # A dead connection (DB-Lib 20047) must not retry sp_spaceused on the same dead cursor
        # (which raises a confusing secondary InterfaceError) or get captured as tracked noise —
        # it's the same self-recovering error `retry_on_transient_connection_error` already
        # handles at the schema-discovery layer.
        capture = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.capture_exception"
        )
        cursor.execute.side_effect = pymssql.OperationalError(
            20047, b"DB-Lib error message 20047, severity 9:\nDBPROCESS is dead or not enabled\n"
        )
        assert impl.fetch_table_stats(cursor, "dbo", "t", logger) is None
        assert cursor.execute.call_count == 1
        capture.assert_not_called()


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

    def test_clamps_to_at_least_one(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",)]
        cursor.fetchone.return_value = (0,)
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result == 1

    def test_rejects_control_char_column_names(self, impl, cursor, logger):
        # A column name with a control character can't be made safe by
        # bracket-quoting, so the quoter rejects it; the method catches
        # and returns None.
        cursor.fetchall.return_value = [("bad\ncol",)]
        cursor.fetchone.return_value = (1,)
        result = impl.fetch_average_row_size(cursor, "dbo", "t", "SELECT 1", {}, logger)
        assert result is None


class TestGetRowsToSync:
    def _deadlock_victim(self) -> pymssql.OperationalError:
        return pymssql.OperationalError(
            1205,
            b"Transaction (Process ID 116) was deadlocked on lock resources with another process and has been "
            b"chosen as the deadlock victim. Rerun the transaction.",
        )

    def test_retries_deadlock_and_recovers_count(self, impl, cursor, logger, mocker):
        # Runs before any rows stream, so a 1205 here is exactly as safe to rerun as the
        # main read query — this used to fall straight to 0 instead of retrying.
        mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.time.sleep")
        cursor.execute.side_effect = [self._deadlock_victim(), None]
        cursor.fetchone.return_value = (7,)
        assert impl.get_rows_to_sync(cursor, "SELECT id FROM t", {}, logger) == 7
        assert cursor.execute.call_count == 2

    def test_falls_back_to_zero_without_capturing_on_persistent_error(self, impl, cursor, logger, mocker):
        # This COUNT(*) shares its FROM/WHERE with the real streaming query, so a genuine
        # problem resurfaces (and is captured) there. Capturing it here too would flood
        # error tracking with a handled duplicate of a transient/benign probe failure.
        capture = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.mssql.capture_exception"
        )
        cursor.execute.side_effect = RuntimeError("boom")
        assert impl.get_rows_to_sync(cursor, "SELECT id FROM t", {}, logger) == 0
        capture.assert_not_called()


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


class TestBuildPipeline:
    def test_setup_that_hangs_at_connect_raises_a_non_retryable_timeout(self, build_pipeline_mocks, mocker):
        mock_connect, _ = build_pipeline_mocks
        release = threading.Event()
        mock_connect.side_effect = lambda **kwargs: release.wait()
        mocker.patch(f"{_MSSQL_MODULE}.MSSQL_TABLE_SETUP_DEADLINE_SECONDS", 0.05)

        try:
            with pytest.raises(MSSQLMetadataTimeoutError) as error:
                MSSQLImplementation().build_pipeline(_make_config(), _make_inputs())
        finally:
            release.set()

        assert error_message_matches(str(error.value), MSSQLSource().get_non_retryable_errors())

    @pytest.mark.parametrize("fails", [False, True], ids=["count_hangs", "count_connection_fails"])
    def test_row_count_fault_costs_the_estimate_and_not_the_import(self, build_pipeline_mocks, mocker, fails):
        release = threading.Event()

        def _count(*args):
            if fails:
                raise pymssql.OperationalError(20009, b"Adaptive Server is unavailable or does not exist")
            release.wait()

        mocker.patch.object(MSSQLImplementation, "get_rows_to_sync", side_effect=_count)
        mocker.patch(f"{_MSSQL_MODULE}.MSSQL_ROW_COUNT_DEADLINE_SECONDS", 0.05)

        try:
            source = MSSQLImplementation().build_pipeline(_make_config(), _make_inputs())
        finally:
            release.set()

        assert source.rows_to_sync == 0


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
            # Azure SQL error 40615 — the server firewall rejected the client IP. Redacted shape;
            # the server name / client IP are volatile, the matched phrase is not.
            "Cannot open server 'example' requested by the login. Client with IP address "
            "'203.0.113.10' is not allowed to access the server.",
        ],
    )
    def test_firewall_block_is_non_retryable(self, error_msg):
        non_retryable = MSSQLSource().get_non_retryable_errors()
        matches = [msg for pattern, msg in non_retryable.items() if pattern in error_msg]
        assert matches, error_msg
        # The actionable firewall guidance must win over the generic catch-all, so the first match
        # can't be the message-less entry.
        assert matches[0] is not None

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
            # SQL Server error 230 — the column-level counterpart of 229: some access to the
            # object, but a column-level GRANT/DENY blocks SELECT on one specific column.
            "SQL Server message 230, severity 14, state 1, procedure b'', line 1:\n"
            "b\"The SELECT permission was denied on the column 'Salary', of the object "
            "'Employees', database 'mydb', schema 'dbo'.DB-Lib error message 20018, severity 14:\n"
            'General SQL Server error: Check messages from the SQL Server\n"',
            # Different column/object/database names must still match the stable substring.
            "The SELECT permission was denied on the column 'Notes', of the object 'Tickets', "
            "database 'otherdb', schema 'dbo'.",
        ],
    )
    def test_column_permission_denied_errors_are_non_retryable(self, error_msg):
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


class TestMSSQLSourceRetryableErrors:
    @pytest.mark.parametrize(
        "error",
        [
            pymssql.OperationalError(1222, b"Lock request time out period exceeded."),
            # Real pymssql shape: DB-Lib error 20017 carried as (code, bytes) args.
            pymssql.OperationalError(
                20017, b"DB-Lib error message 20017, severity 9:\nUnexpected EOF from the server\n"
            ),
            # The SQL-Server-message rendering of the same EOF.
            pymssql.OperationalError(
                "SQL Server message 20017, severity 9, state 0, procedure b'\\x00', line 0:\n"
                "b'DB-Lib error message 20017, severity 9:\\nUnexpected EOF from the server\\n'"
            ),
            # pymssql's own InterfaceError, raised when a query runs on a connection that died
            # between opening and use (see `MSSQLSource.get_retryable_errors`).
            pymssql.InterfaceError("Not connected to any MS SQL server"),
        ],
    )
    def test_transient_connection_errors_are_retryable(self, error):
        retryable = MSSQLSource().get_retryable_errors()
        assert any(pattern.lower() in str(error).lower() for pattern in retryable), str(error)


class TestMSSQLSourceValidateCredentials:
    @pytest.fixture
    def source(self):
        return MSSQLSource()

    def test_firewall_block_returns_actionable_message_without_capturing(self, source, mocker):
        capture = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.source.capture_exception"
        )
        mocker.patch.object(source, "is_database_host_valid", return_value=(True, None))
        # Redacted Azure SQL error 40615 — real server name and client IP are volatile.
        firewall_error = pymssql.OperationalError(
            "Cannot open server 'example' requested by the login. Client with IP address "
            "'203.0.113.10' is not allowed to access the server."
        )
        mocker.patch.object(source, "get_schemas", side_effect=firewall_error)

        valid, error = source.validate_credentials(_make_config(), team_id=1)

        assert valid is False
        assert error == _FIREWALL_BLOCKED_ERROR
        capture.assert_not_called()

    @pytest.mark.parametrize(
        ("driver_error", "expected_guidance"),
        [
            # Real pymssql DB-Lib error 20009 for a host it cannot reach. The driver says the same
            # thing for a wrong host or port, so the copy has to cover the values and the network.
            (
                "DB-Lib error message 20009, severity 9:\nUnable to connect: Adaptive Server is "
                "unavailable or does not exist (db.example.com)",
                ("host and port", "firewall"),
            ),
            (
                "DB-Lib error message 20003, severity 6:\nAdaptive Server connection timed out",
                ("public internet", "firewall", "SSH tunnel"),
            ),
        ],
    )
    def test_connect_failure_names_a_network_cause(self, source, mocker, driver_error, expected_guidance):
        mocker.patch.object(source, "is_database_host_valid", return_value=(True, None))
        mocker.patch.object(source, "get_schemas", side_effect=pymssql.OperationalError(driver_error))

        valid, error = source.validate_credentials(_make_config(), team_id=1)

        assert valid is False
        assert error is not None
        for fragment in expected_guidance:
            assert fragment in error
        assert "Adaptive Server" not in error


class TestRetryOnTransientConnectionError:
    def _dbprocess_dead(self) -> pymssql.OperationalError:
        return pymssql.OperationalError(
            20047, b"DB-Lib error message 20047, severity 9:\nDBPROCESS is dead or not enabled\n"
        )

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


class TestGetSchemasDeadline:
    def test_discovery_that_hangs_raises_before_the_activity_timeout(self, mocker):
        release = threading.Event()
        mocker.patch(f"{_MSSQL_MODULE}.open_ssh_tunnel").return_value.__enter__.return_value = ("localhost", 1433)
        mocker.patch(f"{_MSSQL_MODULE}.pymssql.connect", side_effect=lambda **kwargs: release.wait())
        mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mssql.source"
            ".MSSQL_SCHEMA_DISCOVERY_DEADLINE_SECONDS",
            0.05,
        )

        try:
            with pytest.raises(MSSQLMetadataTimeoutError, match="SQL Server did not answer in time"):
                MSSQLSource().get_schemas(_make_config(), team_id=1)
        finally:
            release.set()

    def test_discovery_deadline_is_inside_the_activity_timeout(self):
        assert MSSQL_SCHEMA_DISCOVERY_DEADLINE_SECONDS < DISCOVER_SCHEMAS_ACTIVITY_TIMEOUT.total_seconds()


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


class TestRetryOnDeadlock:
    def _deadlock_victim(self) -> pymssql.OperationalError:
        return pymssql.OperationalError(
            1205,
            b"Transaction (Process ID 116) was deadlocked on lock resources with another process and has been "
            b"chosen as the deadlock victim. Rerun the transaction.",
        )

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
