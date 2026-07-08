import datetime
from collections.abc import Generator
from typing import cast

import pytest
from unittest.mock import MagicMock

import pymysql

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import Table, TableStats
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MySQLSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql import (
    _MAX_CONNECT_ATTEMPTS,
    _SSH_HANDSHAKE_EOF_ERROR,
    STATEMENT_TIMEOUT_SECONDS,
    MySQLColumn,
    MySQLImplementation,
    _build_query,
    _is_bad_plan_error,
    _is_transient_connect_drop,
    _is_transient_connect_timeout,
    _is_transient_packet_sequence_error,
    _is_transient_tablet_unavailable,
    _is_transient_vitess_dial_timeout,
    _release_streaming_cursor,
    _retry_on_transient_tablet_unavailable,
    _safe_convert_date,
    _safe_convert_datetime,
    _sanitize_identifier,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.source import MySQLSource
from products.warehouse_sources.backend.types import IncrementalFieldType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> MySQLSourceConfig:
    """Build a MySQLSourceConfig for tests that drive `build_pipeline`.

    pymysql.connect is mocked in every test that uses this, so the host/port
    never have to resolve. `ssh_tunnel` is left unset so the default `None`
    is preserved — the str-coercing `from_dict` turns explicit Nones into
    "None" strings otherwise.
    """
    defaults: dict = {
        "host": "localhost",
        "port": 3306,
        "database": "d",
        "user": "u",
        "password": "p",
        "schema": "mydb",
        "using_ssl": "false",
    }
    defaults.update(overrides)
    return MySQLSourceConfig.from_dict(defaults)


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


def _connection_for_cursor(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    return conn


# ---------------------------------------------------------------------------
# Pure helper tests (unchanged — these are module-scope primitives)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "identifier,expected",
    [
        ("mydb", "`mydb`"),
        ("851", "`851`"),
        ("$col", "`$col`"),
        ("db@prod", "`db@prod`"),
    ],
)
def test_sanitize_identifier_valid(identifier, expected):
    assert _sanitize_identifier(identifier) == expected


@pytest.mark.parametrize(
    "identifier",
    [
        "bad;id",
        "$bad!",
    ],
)
def test_sanitize_identifier_invalid(identifier):
    with pytest.raises(ValueError, match="Invalid SQL identifier"):
        _sanitize_identifier(identifier)


class TestSafeConvertDate:
    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("2024-03-15", datetime.date(2024, 3, 15)),
            ("1970-01-01", datetime.date(1970, 1, 1)),
            ("9999-12-31", datetime.date(9999, 12, 31)),
            (b"2024-03-15", datetime.date(2024, 3, 15)),
        ],
    )
    def test_valid_dates(self, input_val, expected):
        assert _safe_convert_date(input_val) == expected

    @pytest.mark.parametrize(
        "input_val",
        [
            "0000-00-00",
            b"0000-00-00",
            "invalid",
            "",
        ],
    )
    def test_invalid_dates_return_none(self, input_val):
        assert _safe_convert_date(input_val) is None


class TestSafeConvertDatetime:
    @pytest.mark.parametrize(
        "input_val,expected",
        [
            ("2024-03-15 10:30:45", datetime.datetime(2024, 3, 15, 10, 30, 45)),
            ("2024-03-15 10:30:45.123456", datetime.datetime(2024, 3, 15, 10, 30, 45, 123456)),
            ("1970-01-01 00:00:00", datetime.datetime(1970, 1, 1, 0, 0, 0)),
            (b"2024-03-15 10:30:45", datetime.datetime(2024, 3, 15, 10, 30, 45)),
        ],
    )
    def test_valid_datetimes(self, input_val, expected):
        assert _safe_convert_datetime(input_val) == expected

    @pytest.mark.parametrize(
        "input_val",
        [
            "0000-00-00 00:00:00",
            b"0000-00-00 00:00:00",
            "invalid",
            "",
        ],
    )
    def test_invalid_datetimes_return_none(self, input_val):
        assert _safe_convert_datetime(input_val) is None


class TestMySQLColumnDateNullability:
    @pytest.mark.parametrize(
        "data_type",
        [
            "date",
            "datetime",
            "timestamp",
        ],
    )
    def test_date_columns_always_nullable(self, data_type):
        column = MySQLColumn(
            name="test_col",
            data_type=data_type,
            column_type=data_type,
            nullable=False,
        )
        field = column.to_arrow_field()
        assert field.nullable is True

    def test_non_date_column_respects_nullable_flag(self):
        column = MySQLColumn(
            name="test_col",
            data_type="int",
            column_type="int",
            nullable=False,
        )
        field = column.to_arrow_field()
        assert field.nullable is False


class TestMySQLColumnToArrowField:
    def test_decimal_requires_precision(self):
        col = MySQLColumn(name="x", data_type="decimal", column_type="decimal", nullable=True)
        with pytest.raises(TypeError, match="numeric_precision"):
            col.to_arrow_field()

    def test_unsigned_int_widens(self):
        col = MySQLColumn(name="x", data_type="int", column_type="int(10) unsigned", nullable=False)
        field = col.to_arrow_field()
        # Unsigned integers widen to the next signed type that can hold their range.
        assert "uint" in str(field.type)


# ---------------------------------------------------------------------------
# Per-cursor metadata queries — test MySQLImplementation methods directly
# ---------------------------------------------------------------------------


@pytest.fixture
def impl() -> MySQLImplementation:
    return MySQLImplementation()


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


class TestSchemaDiscovery:
    def test_schema_field_is_optional(self):
        field = next(field for field in MySQLSource().get_source_config.fields if field.name == "schema")

        assert isinstance(field, SourceFieldInputConfig)
        assert field.required is False
        assert (
            MySQLSourceConfig.from_dict(
                {
                    "host": "localhost",
                    "port": 3306,
                    "database": "d",
                    "user": "u",
                    "password": "p",
                    "using_ssl": "false",
                }
            ).schema
            is None
        )

    def test_get_columns_uses_plain_table_names_when_schema_configured(self, impl, cursor):
        cursor.fetchall.return_value = [
            ("app", "users", "id", "int", "NO"),
            ("app", "users", "email", "varchar", "YES"),
        ]

        columns = impl.get_columns(_connection_for_cursor(cursor), _make_config(schema="app"), names=None)

        assert columns == {"users": [("id", "int", False), ("email", "varchar", True)]}
        sql, params = cursor.execute.call_args.args
        assert "table_schema = %(schema)s" in sql
        assert params["schema"] == "app"

    def test_get_columns_uses_qualified_table_names_when_schema_blank(self, impl, cursor):
        cursor.fetchall.return_value = [
            ("app", "users", "id", "int", "NO"),
            ("billing", "users", "id", "bigint", "NO"),
            ("billing", "invoices", "amount", "decimal", "YES"),
        ]

        columns = impl.get_columns(_connection_for_cursor(cursor), _make_config(schema=""), names=None)

        assert columns == {
            "app.users": [("id", "int", False)],
            "billing.users": [("id", "bigint", False)],
            "billing.invoices": [("amount", "decimal", True)],
        }
        sql, params = cursor.execute.call_args.args
        assert "table_schema NOT IN %(system_schemas)s" in sql
        assert params["system_schemas"] == ("information_schema", "mysql", "performance_schema", "sys")

    def test_get_columns_filters_qualified_names_when_schema_blank(self, impl, cursor):
        cursor.fetchall.return_value = [
            ("app", "users", "id", "int", "NO"),
            ("billing", "users", "id", "bigint", "NO"),
        ]

        columns = impl.get_columns(
            _connection_for_cursor(cursor),
            _make_config(schema=""),
            names=["billing.users"],
        )

        assert columns == {"billing.users": [("id", "bigint", False)]}
        _, params = cursor.execute.call_args.args
        assert params["names"] == ("users",)

    def test_get_primary_keys_maps_duplicate_table_names_to_qualified_names(self, impl, cursor):
        cursor.fetchall.return_value = [
            ("app", "users", "id"),
            ("billing", "users", "billing_id"),
        ]

        primary_keys = impl.get_primary_keys(
            _connection_for_cursor(cursor),
            _make_config(schema=""),
            ["app.users", "billing.users"],
        )

        assert primary_keys == {"app.users": ["id"], "billing.users": ["billing_id"]}

    def test_get_leading_index_columns_maps_duplicate_table_names_to_qualified_names(self, impl, cursor):
        cursor.fetchall.return_value = [
            ("app", "users", "created_at"),
            ("billing", "users", "updated_at"),
        ]

        indexed_columns = impl.get_leading_index_columns(
            _connection_for_cursor(cursor),
            _make_config(schema=""),
            ["app.users", "billing.users"],
        )

        assert indexed_columns == {"app.users": {"created_at"}, "billing.users": {"updated_at"}}

    def test_get_source_metadata_records_source_location(self, impl):
        metadata = impl.get_source_metadata(MagicMock(), _make_config(schema=""), ["app.users", "billing.invoices"])

        assert metadata.schema_by_table == {"app.users": "app", "billing.invoices": "billing"}
        assert metadata.table_name_by_table == {"app.users": "users", "billing.invoices": "invoices"}


class TestGetPrimaryKeysForTable:
    def test_returns_none_when_no_rows(self, impl, cursor):
        cursor.fetchall.return_value = []
        assert impl.get_primary_keys_for_table(cursor, "db", "t") is None

    def test_returns_pk_column_names(self, impl, cursor):
        cursor.fetchall.return_value = [("id",), ("email",)]
        assert impl.get_primary_keys_for_table(cursor, "db", "t") == ["id", "email"]

    def test_uses_parameterized_query(self, impl, cursor):
        impl.get_primary_keys_for_table(cursor, "mydb", "mytable")
        # Must pass params as a dict, not inline the schema/table name.
        sql, params = cursor.execute.call_args.args
        assert "%(schema)s" in sql
        assert "%(table_name)s" in sql
        assert params == {"schema": "mydb", "table_name": "mytable"}
        assert "mydb" not in sql
        assert "mytable" not in sql


class TestGetTableMetadata:
    def test_builds_table_with_non_numeric_columns(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("id", "int", "int", True, None, None),
                ("email", "varchar", "varchar(255)", False, None, None),
            ]
        )
        table = impl.get_table_metadata(cursor, "mydb", "users")
        assert isinstance(table, Table)
        assert table.name == "users"
        assert table.parents == ("mydb",)
        assert len(table.columns) == 2
        assert all(isinstance(c, MySQLColumn) for c in table.columns)
        assert table.columns[0].numeric_precision is None

    def test_populates_numeric_precision_and_scale_for_decimals(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", "decimal(10,2)", False, 10, 2),
            ]
        )
        table = impl.get_table_metadata(cursor, "mydb", "orders")
        assert table.columns[0].numeric_precision == 10
        assert table.columns[0].numeric_scale == 2

    def test_falls_back_to_defaults_when_decimal_missing_precision(self, impl, cursor):
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", "decimal", False, None, None),
            ]
        )
        table = impl.get_table_metadata(cursor, "mydb", "orders")
        assert isinstance(table.columns[0].numeric_precision, int)
        assert isinstance(table.columns[0].numeric_scale, int)


class TestGetRowsToSync:
    def test_returns_count_from_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = (123,)
        result = impl.get_rows_to_sync(cursor, "SELECT * FROM t", {}, logger)
        assert result == 123

    def test_returns_zero_on_none_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.get_rows_to_sync(cursor, "SELECT * FROM t", {}, logger) == 0

    def test_returns_zero_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        # Swallows the error rather than propagating — matches pre-refactor behavior.
        assert impl.get_rows_to_sync(cursor, "SELECT * FROM t", {}, logger) == 0

    @pytest.mark.parametrize(
        "error",
        [
            pymysql.err.OperationalError(1054, "Unknown column 'favoritor_id' in 'where clause'"),
            pymysql.err.OperationalError(
                3024, "Query execution was interrupted, maximum statement execution time exceeded"
            ),
            RuntimeError("boom"),
        ],
    )
    def test_does_not_capture_handled_probe_failures(self, impl, cursor, logger, error, mocker):
        # The COUNT(*) probe is best-effort: it falls back to 0 and must not flood error
        # tracking with handled failures (e.g. a bad incremental field or the MAX_EXECUTION_TIME
        # timeout). Genuine problems resurface in the real streaming query and are classified there.
        cursor.execute.side_effect = error
        capture = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.capture_exception"
        )

        assert impl.get_rows_to_sync(cursor, "SELECT * FROM t", {}, logger) == 0
        capture.assert_not_called()

    def test_wraps_inner_query_as_subselect(self, impl, cursor, logger):
        cursor.fetchone.return_value = (5,)
        impl.get_rows_to_sync(cursor, "SELECT x FROM y WHERE a = %(a)s", {"a": 1}, logger)
        sql, params = cursor.execute.call_args.args
        assert "SELECT x FROM y WHERE a = %(a)s" in sql
        assert "COUNT(*)" in sql
        assert params == {"a": 1}


class TestFetchTableStats:
    def test_returns_none_when_no_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.fetch_table_stats(cursor, "db", "t", logger) is None

    def test_returns_none_when_either_value_is_none(self, impl, cursor, logger):
        cursor.fetchone.return_value = (None, 100)
        assert impl.fetch_table_stats(cursor, "db", "t", logger) is None
        cursor.fetchone.return_value = (100, None)
        assert impl.fetch_table_stats(cursor, "db", "t", logger) is None

    def test_returns_table_stats_dataclass(self, impl, cursor, logger):
        cursor.fetchone.return_value = (1024, 42)
        stats = impl.fetch_table_stats(cursor, "db", "t", logger)
        assert stats == TableStats(table_size_bytes=1024, row_count=42)

    def test_uses_parameterized_query(self, impl, cursor, logger):
        cursor.fetchone.return_value = (1, 1)
        impl.fetch_table_stats(cursor, "mydb", "mytable", logger)
        sql, params = cursor.execute.call_args.args
        assert params == {"schema": "mydb", "table_name": "mytable"}
        assert "mydb" not in sql
        assert "mytable" not in sql


class TestFetchAverageRowSize:
    def test_returns_none_when_no_columns(self, impl, cursor, logger):
        cursor.fetchall.return_value = []
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_none_when_sample_empty(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = None
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_returns_row_size_bytes(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = (256.4,)
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result == 256

    def test_clamps_to_at_least_one(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",)]
        cursor.fetchone.return_value = (0,)
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result == 1

    def test_quotes_column_names_in_length_sum(self, impl, cursor, logger):
        cursor.fetchall.return_value = [("id",), ("email",)]
        cursor.fetchone.return_value = (100,)
        impl.fetch_average_row_size(cursor, "db", "t", "SELECT * FROM x", {}, logger)
        # The second execute call is the size query — inspect it.
        second_call = cursor.execute.call_args_list[1]
        sql = second_call.args[0]
        assert "`id`" in sql
        assert "`email`" in sql
        assert "LENGTH(COALESCE(`id`" in sql

    def test_returns_none_when_no_columns_are_quotable(self, impl, cursor, logger):
        # A column name we can't safely quote is never spliced into SQL. When
        # it's the only column there's nothing left to estimate from, so we
        # return None rather than raising.
        cursor.fetchall.return_value = [("bad;col",)]
        cursor.fetchone.return_value = (1,)
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_skips_unquotable_columns_and_estimates_from_rest(self, impl, cursor, logger):
        # Real MySQL columns can contain characters the identifier allowlist
        # rejects (e.g. `:` in `Ach:CompanyId`). Row-size estimation is
        # best-effort: skip the columns we can't quote and estimate from the
        # rest instead of abandoning the whole query.
        cursor.fetchall.return_value = [("id",), ("Ach:CompanyId",), ("email",)]
        cursor.fetchone.return_value = (100,)
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT * FROM x", {}, logger)
        assert result == 100
        second_call = cursor.execute.call_args_list[1]
        sql = second_call.args[0]
        assert "`id`" in sql
        assert "`email`" in sql
        # The unquotable column is neither quoted nor spliced in raw.
        assert "Ach:CompanyId" not in sql

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        result = impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger)
        assert result is None

    def test_does_not_capture_handled_probe_failures(self, impl, cursor, logger, mocker):
        # Row-size sampling is best-effort: on failure the caller falls back to the default chunk
        # size, so handled failures must not flood error tracking. pymysql raises InterfaceError(0, "")
        # when the connection socket was already closed (a transient drop). Mirrors the get_rows_to_sync
        # and explain_query probe guards.
        cursor.execute.side_effect = pymysql.err.InterfaceError(0, "")
        capture = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.capture_exception"
        )

        assert impl.fetch_average_row_size(cursor, "db", "t", "SELECT 1", {}, logger) is None
        capture.assert_not_called()


def _show_index_rows(*triples: tuple[str, str, int]) -> list[tuple]:
    """Build fake SHOW INDEX rows from (key_name, column_name, seq_in_index) triples."""
    return [
        (
            "message",  # Table
            1,  # Non_unique
            key_name,  # Key_name
            seq,  # Seq_in_index
            column,  # Column_name
            "A",  # Collation
            1000,  # Cardinality
            None,  # Sub_part
            None,  # Packed
            "",  # Null
            "BTREE",  # Index_type
            "",  # Comment
            "",  # Index_comment
            "YES",  # Visible
            None,  # Expression
        )
        for key_name, column, seq in triples
    ]


_SHOW_INDEX_COLUMNS = [
    ("Table",),
    ("Non_unique",),
    ("Key_name",),
    ("Seq_in_index",),
    ("Column_name",),
    ("Collation",),
    ("Cardinality",),
    ("Sub_part",),
    ("Packed",),
    ("Null",),
    ("Index_type",),
    ("Comment",),
    ("Index_comment",),
    ("Visible",),
    ("Expression",),
]


class TestFindIndexForCursor:
    def _make_cursor(self, rows):
        c = MagicMock()
        c.description = _SHOW_INDEX_COLUMNS
        c.fetchall.return_value = rows
        return c

    def test_returns_index_name_when_cursor_is_leading_column(self, impl, logger):
        c = self._make_cursor(_show_index_rows(("idx_created_at", "created_at", 1)))
        assert impl.find_index_for_cursor(c, "mydb", "message", "created_at", logger) == "idx_created_at"

    def test_returns_none_when_cursor_is_not_leading_column(self, impl, logger):
        # Composite index (user_id, created_at) — can't use for WHERE on created_at alone
        c = self._make_cursor(
            _show_index_rows(
                ("idx_composite", "user_id", 1),
                ("idx_composite", "created_at", 2),
            )
        )
        assert impl.find_index_for_cursor(c, "mydb", "message", "created_at", logger) is None

    def test_returns_none_when_no_index_mentions_cursor(self, impl, logger):
        c = self._make_cursor(_show_index_rows(("PRIMARY", "id", 1)))
        assert impl.find_index_for_cursor(c, "mydb", "message", "created_at", logger) is None

    def test_returns_first_matching_index_among_several(self, impl, logger):
        c = self._make_cursor(
            _show_index_rows(
                ("idx_a", "created_at", 1),
                ("idx_b", "created_at", 1),
            )
        )
        assert impl.find_index_for_cursor(c, "mydb", "message", "created_at", logger) == "idx_a"

    def test_returns_none_on_query_failure(self, impl, logger):
        c = MagicMock()
        c.execute.side_effect = Exception("SHOW INDEX failed")
        assert impl.find_index_for_cursor(c, "mydb", "message", "created_at", logger) is None

    def test_returns_none_on_unexpected_columns(self, impl, cursor, logger):
        cursor.description = [("foo",), ("bar",)]
        cursor.fetchall.return_value = []
        assert impl.find_index_for_cursor(cursor, "db", "t", "x", logger) is None

    def test_rejects_malformed_schema_or_table(self, impl, cursor, logger):
        # `SHOW INDEX FROM ...` has no parameterized form, so we MUST reject
        # malformed names before building the query.
        assert impl.find_index_for_cursor(cursor, "bad;schema", "t", "x", logger) is None


class TestExplainQuery:
    def test_prefixes_with_explain(self, impl, cursor, logger):
        cursor.fetchall.return_value = []
        cursor.description = []
        impl.explain_query(cursor, "SELECT 1", {}, logger)
        sql, _ = cursor.execute.call_args.args
        assert sql.startswith("EXPLAIN ")

    def test_swallows_exceptions(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        # Must not raise — diagnostic-only.
        impl.explain_query(cursor, "SELECT 1", {}, logger)

    def test_does_not_capture_exceptions(self, impl, cursor, logger, mocker):
        # EXPLAIN is best-effort diagnostics — a failure (e.g. MySQL 1345 when
        # EXPLAINing a view whose underlying tables the user can't SHOW VIEW on)
        # never affects the sync, so it must not be reported to error tracking.
        capture = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.capture_exception"
        )
        cursor.execute.side_effect = pymysql.err.OperationalError(
            1345, "EXPLAIN/SHOW can not be issued; lacking privileges for underlying table"
        )
        impl.explain_query(cursor, "SELECT 1", {}, logger)
        capture.assert_not_called()


class TestSafetyContract:
    """Verifies that driver-specific metadata queries never splice untrusted identifiers into SQL."""

    def test_quoter_rejects_bad_identifiers(self):
        # _sanitize_identifier wraps InvalidIdentifierError → ValueError for
        # back-compat with semgrep rules keyed on the legacy message shape.
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _sanitize_identifier("bad;id")

    @pytest.mark.parametrize("ident", ["users", "my_table", "$col", "851", "db@prod"])
    def test_quoter_accepts_common_identifier_shapes(self, ident):
        assert _sanitize_identifier(ident).startswith("`")


# ---------------------------------------------------------------------------
# End-to-end build_pipeline — wired through MySQLImplementation
# ---------------------------------------------------------------------------


@pytest.fixture
def build_pipeline_mocks(mocker):
    """Patch pymysql.connect + per-cursor metadata methods on MySQLImplementation
    so `build_pipeline` can run end-to-end without a real MySQL server.

    pymysql.connect is called twice: once for the metadata pass inside
    `build_pipeline`, and once inside `get_rows()` for the streaming
    connection we care about testing.
    """
    fake_table = Table(
        name="messages",
        parents=("mydb",),
        columns=[MySQLColumn(name="id", data_type="int", column_type="int", nullable=False)],
    )
    mocker.patch.object(MySQLImplementation, "get_table_metadata", return_value=fake_table)
    mocker.patch.object(MySQLImplementation, "get_primary_keys_for_table", return_value=["id"])
    mocker.patch.object(MySQLImplementation, "get_rows_to_sync", return_value=0)
    mocker.patch.object(MySQLImplementation, "get_chunk_size", return_value=1000)
    mocker.patch.object(MySQLImplementation, "get_partition_settings", return_value=None)
    mocker.patch.object(MySQLImplementation, "explain_query")

    setup_cursor = MagicMock()
    setup_cursor.__enter__.return_value = setup_cursor

    ss_cursor = MagicMock()
    ss_cursor.__enter__.return_value = ss_cursor
    ss_cursor.description = [("id",)]
    ss_cursor.fetchmany.return_value = []

    metadata_cursor = MagicMock()
    metadata_cursor.__enter__.return_value = metadata_cursor

    # connection.cursor() is called 3 times total: once for metadata (no args),
    # once for the SET SESSION setup on the streaming connection (no args),
    # and once with SSCursor for the streaming query.
    state = {"metadata_done": False}

    def cursor_factory(*args, **kwargs):
        if args or kwargs:
            return ss_cursor
        if not state["metadata_done"]:
            state["metadata_done"] = True
            return metadata_cursor
        return setup_cursor

    mock_connection = MagicMock()
    mock_connection.__enter__.return_value = mock_connection
    mock_connection.cursor.side_effect = cursor_factory

    mock_connect = mocker.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
        return_value=mock_connection,
    )
    return mock_connect, setup_cursor, ss_cursor


def _drain_source():
    source = MySQLImplementation().build_pipeline(_make_config(), _make_inputs())
    list(source.items())  # type: ignore[arg-type]  # MySQL source is always sync


class TestBuildPipelineSourceLocation:
    def test_uses_schema_metadata_when_schema_is_blank(self, build_pipeline_mocks):
        source = MySQLImplementation().build_pipeline(
            _make_config(schema=""),
            _make_inputs(
                schema_name="analytics.users",
                schema_metadata={"source_schema": "analytics", "source_table_name": "users"},
            ),
        )

        assert source.name == "analytics_users"
        assert cast(MagicMock, MySQLImplementation.get_primary_keys_for_table).call_args.args[-2:] == (
            "analytics",
            "users",
        )
        assert cast(MagicMock, MySQLImplementation.get_table_metadata).call_args.args[-2:] == ("analytics", "users")


class TestStreamingConnectionTimeouts:
    def test_read_timeout_is_passed_to_streaming_connection(self, build_pipeline_mocks):
        mock_connect, _, _ = build_pipeline_mocks
        _drain_source()
        streaming_kwargs = mock_connect.call_args_list[1].kwargs
        assert streaming_kwargs["read_timeout"] == STATEMENT_TIMEOUT_SECONDS

    def test_set_session_timeouts_are_executed(self, build_pipeline_mocks):
        _, setup_cursor, _ = build_pipeline_mocks
        _drain_source()
        executed = [c.args[0] for c in setup_cursor.execute.call_args_list if c.args]
        set_session = next((sql for sql in executed if "SET SESSION" in sql), None)
        assert set_session is not None
        assert f"net_write_timeout = {STATEMENT_TIMEOUT_SECONDS}" in set_session
        assert f"net_read_timeout = {STATEMENT_TIMEOUT_SECONDS}" in set_session

    def test_sync_continues_when_set_session_raises(self, build_pipeline_mocks):
        _, setup_cursor, ss_cursor = build_pipeline_mocks
        setup_cursor.execute.side_effect = Exception("SET SESSION denied")

        _drain_source()

        assert ss_cursor.execute.called


class TestReleaseStreamingCursor:
    def test_detaches_cursor_without_closing(self):
        cursor = MagicMock()
        _release_streaming_cursor(cursor)
        assert cursor.connection is None
        cursor.close.assert_not_called()


class TestStreamingCursorTeardown:
    """The streaming SSCursor must be torn down without draining its unbuffered
    result set, so an early exit can't resurface a lost-connection error over
    the real reason iteration stopped."""

    def test_early_close_does_not_drain_or_raise(self, build_pipeline_mocks):
        _, _, ss_cursor = build_pipeline_mocks
        # Every fetch returns a row, so the generator stays suspended at a yield
        # until we close it — mimicking a sync cancelled mid-stream.
        ss_cursor.fetchmany.return_value = [(1,)]
        ss_cursor.close.side_effect = pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query")

        source = MySQLImplementation().build_pipeline(_make_config(), _make_inputs())
        # MySQL source is always sync, so items() yields a plain generator.
        rows = cast(Generator, source.items())
        next(rows)  # pull the first batch, suspend at the yield

        # A cancelled activity closes the generator early — this must not raise.
        rows.close()

        ss_cursor.close.assert_not_called()
        assert ss_cursor.connection is None

    def test_midstream_error_propagates_without_draining(self, build_pipeline_mocks):
        _, _, ss_cursor = build_pipeline_mocks
        # First fetch yields a batch, the second loses the connection mid-stream.
        ss_cursor.fetchmany.side_effect = [
            [(1,)],
            pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query"),
        ]
        ss_cursor.close.side_effect = AssertionError("cursor must not be drained on teardown")

        source = MySQLImplementation().build_pipeline(_make_config(), _make_inputs())
        with pytest.raises(pymysql.err.OperationalError):
            list(source.items())  # type: ignore[arg-type]  # MySQL source is always sync

        ss_cursor.close.assert_not_called()
        assert ss_cursor.connection is None


class TestIsBadPlanError:
    def test_matches_error_2013(self):
        assert _is_bad_plan_error(pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query"))

    def test_matches_error_1038_out_of_sort_memory(self):
        # Out of sort memory is the same bad plan (filesort over the incremental
        # field) seen from the other side — the FORCE INDEX fallback resolves it.
        assert _is_bad_plan_error(
            pymysql.err.OperationalError(1038, "Out of sort memory, consider increasing server sort buffer size")
        )

    @pytest.mark.parametrize(
        "code,message",
        [
            (2003, "Can't connect to MySQL server"),
            (1045, "Access denied for user"),
        ],
    )
    def test_does_not_match_other_error_codes(self, code, message):
        assert not _is_bad_plan_error(pymysql.err.OperationalError(code, message))

    def test_does_not_match_error_without_args(self):
        assert not _is_bad_plan_error(pymysql.err.OperationalError())


class TestIsTransientConnectDrop:
    @pytest.mark.parametrize(
        "message",
        [
            "Lost connection to MySQL server during query",
            "Lost connection to MySQL server during query ([Errno 104] Connection reset by peer)",
        ],
    )
    def test_matches_lost_connection(self, message):
        assert _is_transient_connect_drop(pymysql.err.OperationalError(2013, message))

    def test_does_not_match_ssl_version_mismatch(self):
        # SSL wrong-version arrives wrapped in 2013 but is a deterministic config error
        # (already non-retryable) — retrying just delays the friendly message.
        assert not _is_transient_connect_drop(
            pymysql.err.OperationalError(
                2013,
                "Lost connection to MySQL server during query "
                "([SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:2657))",
            )
        )

    def test_matches_ssl_unexpected_eof_on_connect(self):
        # The peer aborted the TLS handshake with an unexpected EOF, wrapped by pymysql as the
        # 2003 connect failure. A transient drop (overloaded server, proxy idle cull, failover) —
        # the in-process retry must catch it instead of letting the first blip surface as noise.
        assert _is_transient_connect_drop(
            pymysql.err.OperationalError(
                2003,
                "Can't connect to MySQL server on 'db.example.com' "
                "([SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1032))",
            )
        )

    @pytest.mark.parametrize(
        "code,message",
        [
            # The generic 2003 (wrong host/port, firewall) is a deterministic config error and
            # stays non-retryable — only the SSL unexpected-EOF flavour above is transient.
            (2003, "Can't connect to MySQL server on 'db.example.com'"),
            (1045, "Access denied for user"),
        ],
    )
    def test_does_not_match_other_error_codes(self, code, message):
        assert not _is_transient_connect_drop(pymysql.err.OperationalError(code, message))

    def test_does_not_match_error_without_args(self):
        assert not _is_transient_connect_drop(pymysql.err.OperationalError())


class TestIsTransientConnectTimeout:
    @pytest.mark.parametrize(
        "message",
        [
            "Can't connect to MySQL server on 'gcp.connect.psdb.cloud' (timed out)",
            "Can't connect to MySQL server on 'db.example.com' ([Errno 110] Connection timed out)",
        ],
    )
    def test_matches_connect_timeout(self, message):
        assert _is_transient_connect_timeout(pymysql.err.OperationalError(2003, message))

    @pytest.mark.parametrize(
        "message",
        [
            # Refused connection and failed DNS lookup are also 2003 but deterministic
            # host/port misconfig — they must stay non-retryable, not be absorbed here.
            "Can't connect to MySQL server on 'db.example.com' ([Errno 111] Connection refused)",
            "Can't connect to MySQL server on 'nope.example.com' ([Errno -2] Name or service not known)",
        ],
    )
    def test_does_not_match_non_timeout_connect_errors(self, message):
        assert not _is_transient_connect_timeout(pymysql.err.OperationalError(2003, message))

    @pytest.mark.parametrize(
        "code,message",
        [
            (2013, "Lost connection to MySQL server during query"),
            (1045, "Access denied for user"),
        ],
    )
    def test_does_not_match_other_error_codes(self, code, message):
        assert not _is_transient_connect_timeout(pymysql.err.OperationalError(code, message))

    def test_does_not_match_error_without_args(self):
        assert not _is_transient_connect_timeout(pymysql.err.OperationalError())


class TestIsTransientPacketSequenceError:
    @pytest.mark.parametrize(
        "message",
        [
            "Packet sequence number wrong - got 2 expected 3",
            "Packet sequence number wrong - got 0 expected 1",
        ],
    )
    def test_matches_packet_sequence_error(self, message):
        assert _is_transient_packet_sequence_error(pymysql.err.InternalError(message))

    def test_does_not_match_other_internal_error(self):
        assert not _is_transient_packet_sequence_error(pymysql.err.InternalError("some other internal error"))

    def test_does_not_match_operational_error(self):
        # The packet-sequence error is an `InternalError`; a 2013 drop is an `OperationalError`
        # handled by `_is_transient_connect_drop`, so this predicate must not also claim it.
        assert not _is_transient_packet_sequence_error(
            pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query")
        )

    def test_does_not_match_error_without_args(self):
        assert not _is_transient_packet_sequence_error(pymysql.err.InternalError())


class TestIsTransientVitessDialTimeout:
    @pytest.mark.parametrize(
        "message",
        [
            # The shape a Vitess/PlanetScale vtgate surfaces at connect time when it can't dial the
            # backend tablet in time — the tablet address, attempt count, and reqid all vary, the
            # Go `dial tcp ... connection timed out` signature is the stable signal.
            "internal connection error: dial tcp 10.0.0.1:8083: connect: connection timed out, "
            "after 1 attempts, reqid=csYTzBMNB2hB8111yzcg4A",
            "internal connection error: dial tcp 192.0.2.5:3306: connect: connection timed out",
        ],
    )
    def test_matches_dial_timeout(self, message):
        assert _is_transient_vitess_dial_timeout(pymysql.err.OperationalError(1815, message))

    @pytest.mark.parametrize(
        "code,message",
        [
            # A refused dial returns immediately and is more often a persistent config problem, so
            # it must not be absorbed here — only the timeout flavour above is treated as transient.
            (1815, "internal connection error: dial tcp 10.0.0.1:8083: connect: connection refused"),
            # Config/credential errors stay untouched, even when they mention a timeout.
            (2003, "Can't connect to MySQL server on 'db.example.com' (timed out)"),
            (1045, "Access denied for user"),
        ],
    )
    def test_does_not_match_non_dial_timeout_errors(self, code, message):
        assert not _is_transient_vitess_dial_timeout(pymysql.err.OperationalError(code, message))

    def test_does_not_match_error_without_args(self):
        assert not _is_transient_vitess_dial_timeout(pymysql.err.OperationalError())

    def test_does_not_match_non_operational_error(self):
        assert not _is_transient_vitess_dial_timeout(ValueError("dial tcp 10.0.0.1: connection timed out"))


class TestConnectTransientRetry:
    @pytest.mark.parametrize(
        "fail_count,expected_sleeps",
        [
            # A single blip recovers on the second attempt.
            (1, [2]),
            # A drop that recovers on the 4th attempt — past the old 3-attempt window — must still
            # be absorbed in-process rather than surfacing as error-tracking noise.
            (3, [2, 4, 6]),
        ],
    )
    def test_retries_transient_drop_then_succeeds(self, mocker, fail_count, expected_sleeps):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        conn = MagicMock()
        conn.__enter__.return_value = conn
        drop = pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query")
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
            side_effect=[drop] * fail_count + [conn],
        )

        with MySQLImplementation().connect(_make_config()) as yielded:
            assert yielded is conn

        assert mock_connect.call_count == fail_count + 1
        assert [c.args[0] for c in sleep.call_args_list] == expected_sleeps

    def test_retries_ssl_unexpected_eof_then_succeeds(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        conn = MagicMock()
        conn.__enter__.return_value = conn
        drop = pymysql.err.OperationalError(
            2003,
            "Can't connect to MySQL server on 'db.example.com' "
            "([SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1032))",
        )
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
            side_effect=[drop, conn],
        )

        with MySQLImplementation().connect(_make_config()) as yielded:
            assert yielded is conn

        assert mock_connect.call_count == 2
        sleep.assert_called_once_with(2)

    def test_retries_connect_timeout_then_succeeds(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        conn = MagicMock()
        conn.__enter__.return_value = conn
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
            side_effect=[
                pymysql.err.OperationalError(2003, "Can't connect to MySQL server on 'host' (timed out)"),
                conn,
            ],
        )

        with MySQLImplementation().connect(_make_config()) as yielded:
            assert yielded is conn

        assert mock_connect.call_count == 2
        sleep.assert_called_once_with(2)

    def test_retries_vitess_dial_timeout_then_succeeds(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        conn = MagicMock()
        conn.__enter__.return_value = conn
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
            side_effect=[
                pymysql.err.OperationalError(
                    1815,
                    "internal connection error: dial tcp 10.0.0.1:8083: connect: connection timed out, "
                    "after 1 attempts, reqid=csYTzBMNB2hB8111yzcg4A",
                ),
                conn,
            ],
        )

        with MySQLImplementation().connect(_make_config()) as yielded:
            assert yielded is conn

        assert mock_connect.call_count == 2
        sleep.assert_called_once_with(2)

    def test_retries_packet_sequence_error_then_succeeds(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        conn = MagicMock()
        conn.__enter__.return_value = conn
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
            side_effect=[
                pymysql.err.InternalError("Packet sequence number wrong - got 2 expected 3"),
                conn,
            ],
        )

        with MySQLImplementation().connect(_make_config()) as yielded:
            assert yielded is conn

        assert mock_connect.call_count == 2
        sleep.assert_called_once_with(2)

    def test_does_not_retry_connection_refused(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
            side_effect=pymysql.err.OperationalError(
                2003, "Can't connect to MySQL server on 'host' ([Errno 111] Connection refused)"
            ),
        )

        with pytest.raises(pymysql.err.OperationalError):
            with MySQLImplementation().connect(_make_config()):
                pass

        assert mock_connect.call_count == 1
        sleep.assert_not_called()

    def test_does_not_retry_non_transient_internal_error(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
            side_effect=pymysql.err.InternalError("some other internal error"),
        )

        with pytest.raises(pymysql.err.InternalError):
            with MySQLImplementation().connect(_make_config()):
                pass

        assert mock_connect.call_count == 1
        sleep.assert_not_called()

    def test_gives_up_after_max_attempts(self, mocker):
        mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
            side_effect=pymysql.err.OperationalError(2013, "Lost connection to MySQL server during query"),
        )

        with pytest.raises(pymysql.err.OperationalError):
            with MySQLImplementation().connect(_make_config()):
                pass

        assert mock_connect.call_count == _MAX_CONNECT_ATTEMPTS

    def test_does_not_retry_ssl_version_mismatch(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect",
            side_effect=pymysql.err.OperationalError(
                2013,
                "Lost connection to MySQL server during query "
                "([SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:2657))",
            ),
        )

        with pytest.raises(pymysql.err.OperationalError):
            with MySQLImplementation().connect(_make_config()):
                pass

        assert mock_connect.call_count == 1
        sleep.assert_not_called()


class TestIsTransientTabletUnavailable:
    @pytest.mark.parametrize(
        "message",
        [
            # The shape Vitess/PlanetScale vtgate surfaces when a backend tablet is briefly
            # unreachable (failover/restart) — the target keyspace, host, and port vary, the
            # `code = Unavailable` gRPC token is the stable signal.
            "unknown: target: keyspace.-.primary: vttablet: rpc error: code = Unavailable "
            'desc = connection error: desc = "transport: Error while dialing: dial tcp '
            '0.0.0.0:0: connect: connection refused"',
            "vttablet: rpc error: code = Unavailable desc = node is shutting down",
        ],
    )
    def test_matches_grpc_unavailable(self, message):
        assert _is_transient_tablet_unavailable(pymysql.err.OperationalError(1105, message))

    @pytest.mark.parametrize(
        "code,message",
        [
            # Other gRPC statuses ride the same 1105 ER_UNKNOWN_ERROR catch-all but are not the
            # transient "tablet briefly down" class, so they must not be absorbed here.
            (1105, "vttablet: rpc error: code = InvalidArgument desc = some bad request"),
            (1105, "vttablet: rpc error: code = ResourceExhausted desc = grpc: trying to send too large"),
            # Config/credential errors stay untouched.
            (1045, "Access denied for user"),
            (2003, "Can't connect to MySQL server on 'db.example.com'"),
        ],
    )
    def test_does_not_match_non_unavailable_errors(self, code, message):
        assert not _is_transient_tablet_unavailable(pymysql.err.OperationalError(code, message))

    def test_does_not_match_error_without_args(self):
        assert not _is_transient_tablet_unavailable(pymysql.err.OperationalError())

    def test_does_not_match_non_operational_error(self):
        assert not _is_transient_tablet_unavailable(ValueError("code = Unavailable"))


class TestRetryOnTransientTabletUnavailable:
    @staticmethod
    def _unavailable() -> pymysql.err.OperationalError:
        return pymysql.err.OperationalError(
            1105,
            "unknown: target: keyspace.-.primary: vttablet: rpc error: code = Unavailable "
            'desc = connection error: desc = "transport: Error while dialing: connect: connection refused"',
        )

    @pytest.mark.parametrize(
        "fail_count,expected_sleeps",
        [
            (1, [2]),
            (3, [2, 4, 6]),
        ],
    )
    def test_retries_then_succeeds(self, mocker, fail_count, expected_sleeps):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        operation = MagicMock(side_effect=[self._unavailable()] * fail_count + ["ok"])

        assert _retry_on_transient_tablet_unavailable(operation, MagicMock()) == "ok"

        assert operation.call_count == fail_count + 1
        assert [c.args[0] for c in sleep.call_args_list] == expected_sleeps

    def test_gives_up_after_max_attempts(self, mocker):
        mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        operation = MagicMock(side_effect=self._unavailable())

        with pytest.raises(pymysql.err.OperationalError):
            _retry_on_transient_tablet_unavailable(operation, MagicMock())

        assert operation.call_count == _MAX_CONNECT_ATTEMPTS

    def test_does_not_retry_non_transient_error(self, mocker):
        sleep = mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.time.sleep")
        operation = MagicMock(side_effect=pymysql.err.OperationalError(1045, "Access denied for user"))

        with pytest.raises(pymysql.err.OperationalError):
            _retry_on_transient_tablet_unavailable(operation, MagicMock())

        assert operation.call_count == 1
        sleep.assert_not_called()


class TestBuildQueryForceIndex:
    def test_force_index_hint_omitted_by_default(self):
        query, _ = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
        )
        assert "FORCE INDEX" not in query

    def test_force_index_hint_added_when_provided(self):
        query, _ = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
            force_index_name="idx_created_at",
        )
        assert "FORCE INDEX (`idx_created_at`)" in query
        # Hint goes between the table and the WHERE clause
        assert query.index("FORCE INDEX") < query.index("WHERE")

    def test_force_index_hint_applied_for_non_incremental_query_too(self):
        # Full refresh mode — the hint still attaches so callers can force a
        # specific scan order if they choose (no ORDER BY, but hint is still valid).
        query, _ = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            force_index_name="PRIMARY",
        )
        assert "FORCE INDEX (`PRIMARY`)" in query

    def test_force_index_identifier_is_sanitized(self):
        # Rejects invalid SQL identifiers to prevent injection via index name.
        with pytest.raises(ValueError, match="Invalid SQL identifier"):
            _build_query(
                schema="mydb",
                table_name="message",
                should_use_incremental_field=True,
                incremental_field="created_at",
                incremental_field_type=IncrementalFieldType.DateTime,
                db_incremental_field_last_value="2025-01-01",
                force_index_name="bad;injection",
            )


class TestBuildQueryEnabledColumns:
    @pytest.mark.parametrize(
        "enabled_columns,primary_keys,expected_prefix",
        [
            (None, ["id"], "SELECT * FROM"),
            (["email"], ["id"], "SELECT `email`, `id` FROM"),
            ([], None, "SELECT * FROM"),
            ([], ["id"], "SELECT `id` FROM"),
        ],
    )
    def test_full_refresh_projection(
        self,
        enabled_columns: list[str] | None,
        primary_keys: list[str] | None,
        expected_prefix: str,
    ):
        query, _ = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            enabled_columns=enabled_columns,
            primary_keys=primary_keys,
        )
        assert query.startswith(expected_prefix)

    def test_incremental_projection_retains_incremental_field(self):
        query, _ = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
            enabled_columns=["email"],
            primary_keys=["id"],
        )
        assert query.startswith("SELECT `email`, `id`, `created_at` FROM")
        assert "WHERE `created_at` > %(incremental_value)s" in query


class TestBuildQueryRowFilters:
    def test_full_refresh_row_filter(self):
        query, params = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        assert "WHERE `age` > %(row_filter_0)s" in query
        assert params == {"row_filter_0": 21}

    def test_in_filter_expands_to_named_placeholders(self):
        query, params = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            row_filters=[
                ValidatedRowFilter(column="age", operator="IN", value=[21, 30], category=ColumnTypeCategory.INTEGER)
            ],
        )
        assert "WHERE `age` IN (%(row_filter_0_0)s, %(row_filter_0_1)s)" in query
        assert params == {"row_filter_0_0": 21, "row_filter_0_1": 30}

    def test_row_filters_compose_with_incremental(self):
        query, params = _build_query(
            schema="mydb",
            table_name="message",
            should_use_incremental_field=True,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
            row_filters=[ValidatedRowFilter(column="age", operator=">", value=21, category=ColumnTypeCategory.INTEGER)],
        )
        assert "WHERE `created_at` > %(incremental_value)s AND `age` > %(row_filter_0)s" in query
        assert params == {"incremental_value": "2025-01-01", "row_filter_0": 21}

    def test_value_never_interpolated(self):
        query, params = _build_query(
            schema="mydb",
            table_name="message",
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
        assert params == {"row_filter_0": "x'; DROP TABLE y; --"}


class TestMySQLSourceNonRetryableErrors:
    @pytest.fixture
    def source(self):
        return MySQLSource()

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Cannot build decimal array from values",
            "ValueError: Cannot build decimal array from values",
        ],
    )
    def test_unrepresentable_decimal_values_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Unrepresentable decimal error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Source column type changed",
            "SchemaColumnTypeChangedException: Source column type changed: 'id' has values that no longer fit",
        ],
    )
    def test_widened_integer_column_errors_are_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Widened integer column error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "[SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:2657)",
            # The signature also arrives wrapped in pymysql's OperationalError(2013) — we must
            # still catch it without making the bare 2013/"Lost connection" text non-retryable.
            "OperationalError: (2013, 'Lost connection to MySQL server during query "
            "([SSL: WRONG_VERSION_NUMBER] wrong version number (_ssl.c:2657))')",
        ],
    )
    def test_ssl_wrong_version_number_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"SSL version mismatch should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "is blocked because of many connection errors",
            # MariaDB phrasing (suggests mariadb-admin) — what we actually observed in the wild.
            "OperationalError: (1129, \"Host '172.31.4.130' is blocked because of many connection "
            "errors; unblock with 'mariadb-admin flush-hosts'\")",
            # MySQL phrasing (suggests mysqladmin) — same root cause, different unblock hint.
            "OperationalError: (1129, \"Host '10.0.1.5' is blocked because of many connection "
            "errors; unblock with 'mysqladmin flush-hosts'\")",
        ],
    )
    def test_host_blocked_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Host-blocked error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            "Could not establish session to SSH gateway",
            # Temporal-wrapped form carrying the sshtunnel exception class name.
            "BaseSSHTunnelForwarderError: Could not establish session to SSH gateway",
        ],
    )
    def test_ssh_gateway_failure_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"SSH gateway failure should be non-retryable: {error_msg}"

    def test_ssh_handshake_eof_is_non_retryable(self, source):
        # `connect` translates paramiko's bare handshake EOFError into this message.
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in _SSH_HANDSHAKE_EOF_ERROR for pattern in non_retryable.keys())
        assert is_non_retryable, f"SSH handshake EOF should be non-retryable: {_SSH_HANDSHAKE_EOF_ERROR}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw pymysql str(error) form (classified in `_handle_import_error`).
            str(pymysql.err.OperationalError(1054, "Unknown column 'favoritor_id' in 'where clause'")),
            # Temporal-wrapped str(e.cause) form (classified in external_data_job).
            "OperationalError: (1054, \"Unknown column 'favoritor_id' in 'where clause'\")",
            # Other clause variants share the same 1054 code and "Unknown column" prefix.
            "OperationalError: (1054, \"Unknown column 'deleted_at' in 'order clause'\")",
        ],
    )
    def test_unknown_column_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Unknown-column error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw pymysql str(error) form the import/sync path classifies (`_handle_import_error`
            # matches `str(error)`, which has no class-name prefix).
            str(pymysql.err.ProgrammingError(1146, "Table 'defaultdb.wealth_insights' doesn't exist")),
            # Temporal-wrapped / refresh-schemas form that prepends the exception class name.
            "ProgrammingError: (1146, \"Table 'defaultdb.wealth_insights' doesn't exist\")",
        ],
    )
    def test_table_not_found_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Table-not-found error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw pymysql str(error) form the import/sync path classifies (`_handle_import_error`
            # matches `str(error)`, which has no class-name prefix).
            str(
                pymysql.err.OperationalError(
                    1356, "View 'defaultdb.wealth_view' references invalid table(s) or column(s)"
                )
            ),
            # Temporal-wrapped / refresh-schemas form that prepends the exception class name.
            "OperationalError: (1356, \"View 'defaultdb.wealth_view' references invalid table(s) or column(s)\")",
        ],
    )
    def test_invalid_view_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Invalid-view error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw pymysql str(error) form.
            str(
                pymysql.err.OperationalError(
                    1130,
                    "Host 'ec2-52-4-194-122.compute-1.amazonaws.com' is not allowed to connect to this MySQL server",
                )
            ),
            # Temporal-wrapped str(e.cause) form — different host, same stable phrase.
            "OperationalError: (1130, \"Host '10.0.1.5' is not allowed to connect to this MySQL server\")",
        ],
    )
    def test_host_not_privileged_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Host-not-privileged error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw pymysql str(error) form the import/sync path classifies (`_handle_import_error`
            # matches `str(error)`, which has no class-name prefix).
            str(
                pymysql.err.OperationalError(
                    1142, "SELECT command denied to user 'reader'@'10.0.1.5' for table 'orders'"
                )
            ),
            # Temporal-wrapped str(e.cause) form — different user/host/table, same stable code.
            "OperationalError: (1142, \"SELECT command denied to user 'ro'@'10.0.1.5' for table 'events'\")",
        ],
    )
    def test_table_access_denied_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Table-access-denied error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # Raw pymysql str(error) form (single-quoted tuple repr).
            str(pymysql.err.OperationalError(1038, "Out of sort memory, consider increasing server sort buffer size")),
            # Temporal-wrapped form (double-quoted).
            'OperationalError: (1038, "Out of sort memory, consider increasing server sort buffer size")',
        ],
    )
    def test_out_of_sort_memory_is_non_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable, f"Out-of-sort-memory error should be non-retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # A genuine transient connection drop (no SSL signature) must stay retryable.
            "OperationalError: (2013, 'Lost connection to MySQL server during query')",
            "Lost connection to MySQL server during query",
        ],
    )
    def test_transient_lost_connection_stays_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Transient lost-connection error should remain retryable: {error_msg}"

    @pytest.mark.parametrize(
        "error_msg",
        [
            # MySQL error 1135: the server reached the connection but couldn't spawn an OS thread
            # to service it (errno 11 EAGAIN). This is a transient, server-side resource exhaustion
            # — it clears as concurrent connections close — so it must keep retrying, just like
            # Postgres's "too many connections" / "max clients reached" capacity errors.
            "OperationalError: (1135, 'Can't create a new thread (errno 11 \"Resource temporarily "
            'unavailable"); if you are not out of available memory, you can consult the manual for '
            "a possible OS-dependent bug')",
            'Can\'t create a new thread (errno 11 "Resource temporarily unavailable")',
        ],
    )
    def test_cant_create_new_thread_stays_retryable(self, source, error_msg):
        non_retryable = source.get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert not is_non_retryable, f"Transient thread-exhaustion error should remain retryable: {error_msg}"


class TestMySQLSourceValidateCredentials:
    @pytest.fixture
    def source(self, mocker):
        source = MySQLSource()
        mocker.patch.object(source, "ssh_tunnel_is_valid", return_value=(True, None))
        mocker.patch.object(source, "is_database_host_valid", return_value=(True, None))
        return source

    @pytest.mark.parametrize(
        "raised,expected_error",
        [
            # pymysql collapses every connect-level failure into OperationalError(2003)
            # wrapping an OSError; the OS detail is matched to give a specific, actionable
            # message instead of the generic "check connection details" fallback.
            (
                pymysql.err.OperationalError(
                    2003, "Can't connect to MySQL server on 'db.example.com' ([Errno -2] Name or service not known)"
                ),
                "Host could not be resolved. Check the host is spelled correctly and reachable from PostHog.",
            ),
            (
                pymysql.err.OperationalError(
                    2003, "Can't connect to MySQL server on 'db.example.com' ([Errno 111] Connection refused)"
                ),
                "Could not connect to the host on the port given. Check the host and port are correct and the MySQL server is accepting connections.",
            ),
            (
                pymysql.err.OperationalError(2003, "Can't connect to MySQL server on 'db.example.com' (timed out)"),
                "Connection timed out. Does your database have our IP addresses allowed?",
            ),
            (
                pymysql.err.OperationalError(
                    2003, "Can't connect to MySQL server on 'db.example.com' ([Errno 113] No route to host)"
                ),
                "Could not reach the host. Check the host is correct and that PostHog's IP addresses are allowed through your firewall.",
            ),
            (
                pymysql.err.OperationalError(
                    2003, "Can't connect to MySQL server on 'db.example.com' ([Errno 101] Network is unreachable)"
                ),
                "Could not reach the host. Check the host is correct and that PostHog's IP addresses are allowed through your firewall.",
            ),
            # Server error 1049: the host/port/credentials are fine but the named database
            # doesn't exist. Previously fell through to capture as an unexpected error.
            (
                pymysql.err.OperationalError(1049, "Unknown database 'nope'"),
                "Database does not exist. Check the database name is correct.",
            ),
            # An auth failure (error 1045) must name the credentials, not the generic message
            # that sends the user to inspect the host/port instead. Mirrors Postgres.
            (
                pymysql.err.OperationalError(1045, "Access denied for user 'u'@'1.2.3.4' (using password: YES)"),
                "Invalid user or password",
            ),
        ],
    )
    def test_known_connection_errors_are_not_captured(self, source, mocker, raised, expected_error):
        capture = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.source.capture_exception"
        )
        mocker.patch.object(source, "get_schemas", side_effect=raised)

        valid, error = source.validate_credentials(_make_config(), team_id=1)

        assert valid is False
        assert error == expected_error
        capture.assert_not_called()

    @pytest.mark.parametrize(
        "host",
        [
            "https://db.example.com/",
            "mysql://root:secret@db.example.com:3306/mydb",
        ],
    )
    def test_url_in_host_field_rejected_without_echoing_input(self, source, mocker, host):
        # If the guard is dropped, the raw host reaches host validation / DNS and the
        # message would echo it (leaking a pasted password), so assert it is never reached.
        mocker.patch.object(source, "is_database_host_valid", side_effect=AssertionError("should not resolve"))
        mocker.patch.object(source, "get_schemas", side_effect=AssertionError("should not connect"))

        valid, error = source.validate_credentials(_make_config(host=host), team_id=1)

        assert valid is False
        assert host not in (error or "")
        assert "hostname" in (error or "")

    def test_unexpected_errors_are_still_captured(self, source, mocker):
        capture = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.source.capture_exception"
        )
        mocker.patch.object(source, "get_schemas", side_effect=RuntimeError("something genuinely unexpected"))

        valid, error = source.validate_credentials(_make_config(), team_id=1)

        assert valid is False
        assert error is not None
        capture.assert_called_once()


class _RaisingTunnel:
    """Context manager whose `__enter__` raises, standing in for paramiko's handshake EOFError."""

    def __enter__(self):
        raise EOFError()

    def __exit__(self, *args):
        return False


class TestConnectSSHTunnel:
    def test_bare_handshake_eof_is_translated_and_non_retryable(self, mocker):
        mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.open_ssh_tunnel",
            return_value=_RaisingTunnel(),
        )
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.mysql.mysql.pymysql.connect"
        )

        with pytest.raises(Exception, match=_SSH_HANDSHAKE_EOF_ERROR) as exc_info:
            with MySQLImplementation().connect(_make_config()):
                pass

        # Cause preserved, the database connection is never attempted, and the translated
        # message is classified non-retryable so the sync stops instead of retrying forever.
        assert isinstance(exc_info.value.__cause__, EOFError)
        mock_connect.assert_not_called()
        non_retryable = MySQLSource().get_non_retryable_errors()
        assert any(pattern in str(exc_info.value) for pattern in non_retryable.keys())
