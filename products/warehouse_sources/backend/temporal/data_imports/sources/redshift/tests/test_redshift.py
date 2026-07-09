import pytest
from unittest.mock import MagicMock, patch

import psycopg
from psycopg import sql
from psycopg.pq import TransactionStatus

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    TemporaryFileSizeExceedsLimitException,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import Table, TableStats
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RedshiftSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift import (
    RedshiftColumn,
    RedshiftImplementation,
    _build_query,
    _explain_query,
    filter_redshift_incremental_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.source import (
    _REDSHIFT_IMPLEMENTATION,
    RedshiftSource,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides) -> RedshiftSourceConfig:
    defaults: dict = {
        "host": "localhost",
        "port": 5439,
        "database": "dev",
        "user": "u",
        "password": "p",
        "schema": "public",
    }
    defaults.update(overrides)
    return RedshiftSourceConfig.from_dict(defaults)


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


class TestFilterIncrementalFields:
    @pytest.mark.parametrize(
        "data_type,expected_type",
        [
            ("timestamp", IncrementalFieldType.Timestamp),
            ("timestamp without time zone", IncrementalFieldType.Timestamp),
            ("timestamp with time zone", IncrementalFieldType.Timestamp),
            ("date", IncrementalFieldType.Date),
            ("integer", IncrementalFieldType.Integer),
            ("bigint", IncrementalFieldType.Integer),
            ("smallint", IncrementalFieldType.Integer),
            ("int4", IncrementalFieldType.Integer),
            ("int8", IncrementalFieldType.Integer),
        ],
    )
    def test_includes_incremental_types(self, data_type, expected_type):
        result = filter_redshift_incremental_fields([("col", data_type, True)])
        assert result == [("col", expected_type, True)]

    @pytest.mark.parametrize("data_type", ["varchar", "text", "json", "super", "real"])
    def test_excludes_non_incremental_types(self, data_type):
        result = filter_redshift_incremental_fields([("col", data_type, True)])
        assert result == []


class TestBuildQueryEnabledColumns:
    @pytest.mark.parametrize(
        "enabled_columns,primary_keys,expected_select",
        [
            (None, ["id"], "SELECT * FROM"),
            (["email"], ["id"], 'SELECT "email", "id" FROM'),
            ([], None, "SELECT * FROM"),
            ([], ["id"], 'SELECT "id" FROM'),
        ],
    )
    def test_full_refresh_projection(self, enabled_columns, primary_keys, expected_select):
        composed = _build_query(
            schema="public",
            table_name="users",
            should_use_incremental_field=False,
            table_type=None,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            enabled_columns=enabled_columns,
            primary_keys=primary_keys,
        )
        rendered = composed.as_string()
        assert rendered.startswith(expected_select)

    def test_incremental_projection_retains_incremental_field(self):
        composed = _build_query(
            schema="public",
            table_name="users",
            should_use_incremental_field=True,
            table_type=None,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
            enabled_columns=["email"],
            primary_keys=["id"],
        )
        rendered = composed.as_string()
        assert rendered.startswith('SELECT "email", "id", "created_at" FROM')
        assert 'WHERE "created_at"' in rendered


class TestBuildQueryRowFilters:
    def _filter(self, column, operator, value, category=ColumnTypeCategory.INTEGER):
        return ValidatedRowFilter(column=column, operator=operator, value=value, category=category)

    def test_full_refresh_row_filter(self):
        composed = _build_query(
            schema="public",
            table_name="users",
            should_use_incremental_field=False,
            table_type=None,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            row_filters=[self._filter("age", ">", 21)],
        )
        rendered = composed.as_string()
        assert 'WHERE "age" > 21' in rendered

    def test_row_filters_compose_with_incremental(self):
        composed = _build_query(
            schema="public",
            table_name="users",
            should_use_incremental_field=True,
            table_type=None,
            incremental_field="created_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2025-01-01",
            row_filters=[self._filter("age", ">", 21)],
        )
        rendered = composed.as_string()
        assert 'WHERE "created_at"' in rendered
        assert 'AND "age" > 21' in rendered
        assert rendered.rstrip().endswith('ORDER BY "created_at" ASC')

    def test_sampling_query_is_not_filtered(self):
        # Row filters apply only to the real data path; the sampling/estimation query stays unfiltered.
        composed = _build_query(
            schema="public",
            table_name="users",
            should_use_incremental_field=False,
            table_type=None,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            add_sampling=True,
            row_filters=[self._filter("age", ">", 21)],
        )
        rendered = composed.as_string()
        assert '"age"' not in rendered

    def test_in_filter_renders_parenthesized_list(self):
        composed = _build_query(
            schema="public",
            table_name="users",
            should_use_incremental_field=False,
            table_type=None,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            row_filters=[self._filter("age", "IN", [21, 30, 40])],
        )
        rendered = composed.as_string()
        assert 'WHERE "age" IN (21, 30, 40)' in rendered

    def test_not_in_string_list_values_are_escaped_literals(self):
        composed = _build_query(
            schema="public",
            table_name="users",
            should_use_incremental_field=False,
            table_type=None,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            row_filters=[
                self._filter("name", "NOT IN", ["a", "'; DROP TABLE y; --"], category=ColumnTypeCategory.STRING)
            ],
        )
        rendered = composed.as_string()
        assert "\"name\" NOT IN ('a', '''; DROP TABLE y; --')" in rendered

    def test_string_value_is_escaped_literal_not_injectable(self):
        # psycopg's sql.Literal inlines values, but escapes them: the `;` stays inside a quoted
        # literal (single quote doubled), so it can't break out into executable SQL.
        composed = _build_query(
            schema="public",
            table_name="users",
            should_use_incremental_field=False,
            table_type=None,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            row_filters=[self._filter("name", "=", "x'; DROP TABLE y; --", category=ColumnTypeCategory.STRING)],
        )
        rendered = composed.as_string()
        assert "'x''; DROP TABLE y; --'" in rendered


class TestRedshiftColumnToArrowField:
    def test_decimal_requires_precision(self):
        col = RedshiftColumn(name="x", data_type="decimal", nullable=True)
        with pytest.raises(TypeError, match="numeric_precision"):
            col.to_arrow_field()

    def test_bigint_maps_to_int64(self):
        col = RedshiftColumn(name="x", data_type="bigint", nullable=False)
        field = col.to_arrow_field()
        assert "int64" in str(field.type)
        assert field.nullable is False

    def test_timestamptz_carries_utc_timezone(self):
        col = RedshiftColumn(name="x", data_type="timestamptz", nullable=True)
        field = col.to_arrow_field()
        assert "UTC" in str(field.type)


# ---------------------------------------------------------------------------
# Per-cursor metadata queries — exercise impl methods directly
# ---------------------------------------------------------------------------


@pytest.fixture
def impl() -> RedshiftImplementation:
    return RedshiftImplementation()


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
        assert impl.get_primary_keys_for_table(cursor, "public", "t") is None

    def test_returns_pk_column_names(self, impl, cursor):
        cursor.fetchall.return_value = [("id",), ("email",)]
        assert impl.get_primary_keys_for_table(cursor, "public", "t") == ["id", "email"]


class TestGetTableMetadata:
    def test_builds_table_with_columns(self, impl, cursor):
        cursor.execute.return_value = cursor
        # First fetchone for is-view check; iteration for columns
        cursor.fetchone.return_value = (False,)
        cursor.__iter__.return_value = iter(
            [
                ("id", "integer", "NO", None, None),
                ("email", "varchar", "YES", None, None),
            ]
        )
        table = impl.get_table_metadata(cursor, "public", "users")
        assert table.name == "users"
        assert table.parents == ("public",)
        assert len(table.columns) == 2
        assert table.type == "table"

    def test_marks_view_when_is_view_true(self, impl, cursor):
        cursor.execute.return_value = cursor
        cursor.fetchone.return_value = (True,)
        cursor.__iter__.return_value = iter([("id", "integer", "NO", None, None)])
        table = impl.get_table_metadata(cursor, "public", "myview")
        assert table.type == "view"

    def test_populates_numeric_precision_and_scale_for_decimals(self, impl, cursor):
        cursor.execute.return_value = cursor
        cursor.fetchone.return_value = (False,)
        cursor.__iter__.return_value = iter(
            [
                ("amount", "decimal", "NO", 10, 2),
            ]
        )
        table = impl.get_table_metadata(cursor, "public", "orders")
        assert table.columns[0].numeric_precision == 10
        assert table.columns[0].numeric_scale == 2

    def test_excludes_redshift_internal_columns_from_arrow_schema(self, impl, cursor):
        # Materialized views expose `padb_internal_*` bookkeeping columns in
        # `information_schema.columns`, but `SELECT *` never returns them. Leaving them in the
        # Arrow schema made `pa.Table.from_pydict` raise `KeyError: 'padb_internal_txn_id_col'`.
        cursor.execute.return_value = cursor
        cursor.fetchone.return_value = (False,)
        cursor.__iter__.return_value = iter([("id", "integer", "NO", None, None)])

        impl.get_table_metadata(cursor, "public", "my_mat_view")

        metadata_query = cursor.execute.call_args.args[0].as_string()
        assert "column_name NOT LIKE 'padb_internal%'" in metadata_query


class TestGetRowsToSync:
    def _inner(self):
        return sql.SQL("SELECT 1").format()

    def test_returns_count_from_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = (123,)
        result = impl.get_rows_to_sync(cursor, self._inner(), None, logger)
        assert result == 123

    def test_returns_zero_on_none_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.get_rows_to_sync(cursor, self._inner(), None, logger) == 0

    def test_returns_zero_on_generic_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        assert impl.get_rows_to_sync(cursor, self._inner(), None, logger) == 0

    def test_raises_on_temp_file_limit(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("temporary file size exceeds temp_file_limit")
        with pytest.raises(TemporaryFileSizeExceedsLimitException):
            impl.get_rows_to_sync(cursor, self._inner(), None, logger)


class TestFetchTableStats:
    def test_returns_none_when_no_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.fetch_table_stats(cursor, "public", "t", logger) is None

    def test_returns_none_when_size_zero(self, impl, cursor, logger):
        cursor.fetchone.return_value = (0, 100)
        assert impl.fetch_table_stats(cursor, "public", "t", logger) is None

    def test_returns_none_when_rows_zero(self, impl, cursor, logger):
        cursor.fetchone.return_value = (10, 0)
        assert impl.fetch_table_stats(cursor, "public", "t", logger) is None

    def test_converts_size_mb_to_bytes(self, impl, cursor, logger):
        cursor.fetchone.return_value = (2, 100)  # 2 MB, 100 rows
        stats = impl.fetch_table_stats(cursor, "public", "t", logger)
        assert stats == TableStats(table_size_bytes=2 * 1024 * 1024, row_count=100)

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ) as mock_capture:
            assert impl.fetch_table_stats(cursor, "public", "t", logger) is None
        mock_capture.assert_called_once()

    def test_permission_denied_on_svv_table_info_is_not_reported(self, impl, cursor, logger):
        # Some Redshift roles lack SELECT on `svv_table_info`. That's an expected customer
        # permission-config issue — stats are optional, so skip gracefully without reporting the
        # non-actionable error to error tracking (the source of the reported noise).
        cursor.execute.side_effect = psycopg.errors.InsufficientPrivilege(
            "permission denied for relation svv_table_info"
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ) as mock_capture:
            assert impl.fetch_table_stats(cursor, "public", "t", logger) is None
        mock_capture.assert_not_called()

    def test_failed_explain_does_not_poison_real_query(self, impl, logger):
        # Reproduces the reported incident: EXPLAIN on `svv_table_info` fails (Redshift can't
        # EXPLAIN leader-node-only system views), aborting the transaction. Without recovery the
        # real stats query would then die with `InFailedSqlTransaction` and stats would be lost.
        cursor = _fake_poisoning_cursor(real_query_result=(2, 100))

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ) as mock_capture:
            stats = impl.fetch_table_stats(cursor, "public", "t", logger)

        assert stats == TableStats(table_size_bytes=2 * 1024 * 1024, row_count=100)
        cursor.connection.rollback.assert_called_once()
        mock_capture.assert_not_called()


def _fake_poisoning_cursor(real_query_result):
    """A cursor mock whose EXPLAIN fails and aborts the transaction, mirroring Redshift.

    The real (non-EXPLAIN) query only succeeds once the aborted transaction has been rolled
    back — exactly the behaviour `_explain_query` must restore.
    """
    cursor = MagicMock()
    state = {"poisoned": False}

    def execute(stmt, *args, **kwargs):
        text = stmt.as_string() if hasattr(stmt, "as_string") else str(stmt)
        if text.strip().upper().startswith("EXPLAIN"):
            state["poisoned"] = True
            cursor.connection.info.transaction_status = TransactionStatus.INERROR
            raise psycopg.errors.UndefinedColumn('column "t" does not exist in t')
        if state["poisoned"]:
            raise psycopg.errors.InFailedSqlTransaction("current transaction is aborted")
        return cursor

    def rollback():
        state["poisoned"] = False
        cursor.connection.info.transaction_status = TransactionStatus.IDLE

    cursor.execute.side_effect = execute
    cursor.connection.rollback.side_effect = rollback
    cursor.connection.info.transaction_status = TransactionStatus.IDLE
    cursor.fetchone.return_value = real_query_result
    return cursor


class TestExplainQuery:
    def test_swallows_explain_failure_without_reporting(self, logger):
        # EXPLAIN failures are expected for system views and non-actionable, so they must not be
        # reported to error tracking (this is the source of the reported noise).
        cursor = MagicMock()
        cursor.execute.side_effect = psycopg.errors.UndefinedColumn('column "t" does not exist in t')
        cursor.connection.info.transaction_status = TransactionStatus.IDLE

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ) as mock_capture:
            _explain_query(cursor, sql.SQL("SELECT 1 FROM svv_table_info").format(), logger)

        mock_capture.assert_not_called()

    def test_rolls_back_aborted_transaction(self, logger):
        cursor = MagicMock()
        cursor.execute.side_effect = psycopg.errors.UndefinedColumn('column "t" does not exist in t')
        cursor.connection.info.transaction_status = TransactionStatus.INERROR

        _explain_query(cursor, sql.SQL("SELECT 1 FROM svv_table_info").format(), logger)

        cursor.connection.rollback.assert_called_once()

    def test_does_not_roll_back_when_transaction_healthy(self, logger):
        cursor = MagicMock()
        cursor.execute.side_effect = psycopg.errors.UndefinedColumn('column "t" does not exist in t')
        cursor.connection.info.transaction_status = TransactionStatus.IDLE

        _explain_query(cursor, sql.SQL("SELECT 1 FROM svv_table_info").format(), logger)

        cursor.connection.rollback.assert_not_called()


class TestFetchAverageRowSize:
    def _inner(self):
        return sql.SQL("SELECT 1").format()

    def test_returns_none_when_no_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger) is None

    def test_returns_none_when_row_value_is_none(self, impl, cursor, logger):
        cursor.fetchone.return_value = (None,)
        assert impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger) is None

    def test_returns_row_size_bytes(self, impl, cursor, logger):
        cursor.fetchone.return_value = (256.4,)
        result = impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger)
        assert result == 256

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = [None, RuntimeError("boom")]
        assert impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger) is None

    def test_does_not_report_whole_row_reference_failure(self, impl, cursor, logger):
        # Redshift rejects the `pg_column_size(t)` whole-row reference with this exact error on every
        # table. It's a best-effort probe that falls back to the default chunk size, so it must not be
        # reported to error tracking (the source of the noise this fix addresses).
        cursor.execute.side_effect = [None, psycopg.errors.UndefinedColumn('column "t" does not exist in t')]

        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ) as mock_capture:
            result = impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger)

        assert result is None
        mock_capture.assert_not_called()


class TestHasDuplicatePrimaryKeys:
    def test_returns_false_when_no_pks(self, impl, cursor, logger):
        assert impl.has_duplicate_primary_keys(cursor, "public", "t", None, logger) is False
        assert impl.has_duplicate_primary_keys(cursor, "public", "t", [], logger) is False

    def test_returns_true_when_row_found(self, impl, cursor, logger):
        cursor.fetchone.return_value = (1,)
        assert impl.has_duplicate_primary_keys(cursor, "public", "t", ["id"], logger) is True

    def test_returns_false_when_no_row(self, impl, cursor, logger):
        cursor.fetchone.return_value = None
        assert impl.has_duplicate_primary_keys(cursor, "public", "t", ["id"], logger) is False

    def test_returns_false_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ) as mock_capture:
            assert impl.has_duplicate_primary_keys(cursor, "public", "t", ["id"], logger) is False
        mock_capture.assert_called_once()

    def test_system_requested_abort_is_not_reported(self, impl, cursor, logger):
        # Redshift WLM/QMR aborts (code 1020, "system requested abort") surface as `InternalError_`
        # and are expected, non-actionable noise — skip gracefully without reporting to error tracking.
        abort_message = (
            "abort query\nDETAIL:  \n  error:  abort query\n  code:      1020\n"
            "  context:   system requested abort\n  location:  queryabort.hpp:103\n"
        )
        cursor.execute.side_effect = psycopg.errors.InternalError(abort_message)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ) as mock_capture:
            assert impl.has_duplicate_primary_keys(cursor, "public", "t", ["id"], logger) is False
        mock_capture.assert_not_called()


# ---------------------------------------------------------------------------
# Listing — exercise impl methods that take a real cursor mock
# ---------------------------------------------------------------------------


class TestGetColumns:
    def test_returns_columns_grouped_by_table(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [
            ("public", "users", "id", "integer", "NO"),
            ("public", "users", "email", "varchar", "YES"),
            ("public", "orders", "id", "bigint", "NO"),
        ]
        conn.cursor.return_value = cur

        result = impl.get_columns(conn, _make_config(), names=None)

        # Pinned schema → bare table keys (single-namespace fast path).
        assert result == {
            "users": [("id", "integer", False), ("email", "varchar", True)],
            "orders": [("id", "bigint", False)],
        }
        executed_sql = cur.execute.call_args.args[0]
        assert "table_schema = %(schema)s" in executed_sql

    def test_returns_empty_when_no_rows(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur

        assert impl.get_columns(conn, _make_config(), names=["foo"]) == {}

    def test_excludes_redshift_internal_columns(self, impl):
        # Discovery must drop the `padb_internal_*` columns Redshift stamps onto materialized
        # views — they never come back from `SELECT *`, so surfacing them desyncs the schema.
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur

        impl.get_columns(conn, _make_config(), names=None)

        executed_sql, executed_params = cur.execute.call_args.args
        assert "column_name NOT LIKE %(internal_column)s" in executed_sql
        assert executed_params["internal_column"] == "padb_internal%"

    def test_blank_schema_qualifies_and_excludes_system_schemas(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        # Same table name in two schemas must stay distinct.
        cur.fetchall.return_value = [
            ("analytics", "users", "id", "integer", "NO"),
            ("public", "users", "id", "bigint", "NO"),
        ]
        conn.cursor.return_value = cur

        result = impl.get_columns(conn, _make_config(schema=""), names=None)

        assert result == {
            "analytics.users": [("id", "integer", False)],
            "public.users": [("id", "bigint", False)],
        }
        executed_sql, executed_params = cur.execute.call_args.args
        assert "table_schema NOT IN" in executed_sql
        assert "pg_temp_%" in executed_sql
        assert set(executed_params.values()) >= {"pg_catalog", "information_schema", "pg_internal", "pg_automv"}

    def test_blank_schema_with_qualified_names_filters_by_pair(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [("analytics", "users", "id", "integer", "NO")]
        conn.cursor.return_value = cur

        result = impl.get_columns(conn, _make_config(schema=""), names=["analytics.users"])

        assert result == {"analytics.users": [("id", "integer", False)]}
        executed_sql, executed_params = cur.execute.call_args.args
        assert "table_schema = %(sch_0)s AND table_name = %(tbl_0)s" in executed_sql
        assert executed_params["sch_0"] == "analytics"
        assert executed_params["tbl_0"] == "users"


class TestGetPrimaryKeys:
    def test_returns_empty_for_no_tables(self, impl):
        result = impl.get_primary_keys(MagicMock(), _make_config(), [])
        assert result == {}

    def test_returns_pk_columns_grouped_by_table(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [
            ("public", "users", "id"),
            ("public", "users", "tenant_id"),
            ("public", "orders", "id"),
        ]
        conn.cursor.return_value = cur

        result = impl.get_primary_keys(conn, _make_config(), ["users", "orders", "items"])
        assert result == {"users": ["id", "tenant_id"], "orders": ["id"], "items": None}

    def test_blank_schema_keeps_same_table_name_distinct(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = [("analytics", "users", "id"), ("public", "users", "uid")]
        conn.cursor.return_value = cur

        result = impl.get_primary_keys(conn, _make_config(schema=""), ["analytics.users", "public.users"])
        assert result == {"analytics.users": ["id"], "public.users": ["uid"]}

    def test_blank_schema_bare_name_degrades_without_crashing(self, impl):
        # Unknown-schema key must not crash the batch query (None can't sort with str schemas).
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = []
        conn.cursor.return_value = cur

        result = impl.get_primary_keys(conn, _make_config(schema=""), ["users"])
        assert result == {"users": None}

    def test_swallows_errors_and_returns_none_per_table(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.execute.side_effect = Exception("denied")
        conn.cursor.return_value = cur

        result = impl.get_primary_keys(conn, _make_config(), ["users"])
        assert result == {"users": None}


class TestGetRowCounts:
    def test_returns_empty_for_no_tables(self, impl):
        assert impl.get_row_counts(MagicMock(), _make_config(), []) == {}

    def test_blank_schema_counts_tables_and_views_per_namespace(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        # 1: SET statement_timeout, 2: svv_table_info, 3: pg_views, 4: UNION ALL view counts.
        cur.fetchall.side_effect = [
            [("analytics", "events", 500)],  # svv_table_info (materialized tables)
            [("public", "events")],  # pg_views (views aren't in svv_table_info)
            [("public", "events", 42)],  # COUNT(*) per view
        ]
        conn.cursor.return_value = cur

        result = impl.get_row_counts(conn, _make_config(schema=""), ["analytics.events", "public.events"])

        # Same table name in two namespaces stays distinct; the view falls through to COUNT(*).
        assert result == {"analytics.events": 500, "public.events": 42}

    def test_returns_empty_on_exception(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.execute.side_effect = Exception("denied")
        conn.cursor.return_value = cur

        assert impl.get_row_counts(conn, _make_config(), ["users"]) == {}


class TestGetLeadingIndexColumns:
    def _make_conn(self, rows):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.return_value = rows
        conn.cursor.return_value = cur
        return conn

    def test_returns_empty_for_no_tables(self, impl):
        assert impl.get_leading_index_columns(MagicMock(), _make_config(), []) == {}

    def test_returns_leading_compound_sortkey(self, impl):
        # schemaname, tablename, column, sortkey
        conn = self._make_conn(
            [
                ("public", "messages", "created_at", 1),
                ("public", "messages", "user_id", 2),
            ]
        )
        result = impl.get_leading_index_columns(conn, _make_config(), ["messages"])
        assert result == {"messages": {"created_at"}}

    def test_treats_interleaved_sortkey_as_indexed(self, impl):
        conn = self._make_conn(
            [
                ("public", "messages", "a", -1),
                ("public", "messages", "b", 2),
                ("public", "messages", "c", -3),
            ]
        )
        result = impl.get_leading_index_columns(conn, _make_config(), ["messages"])
        assert result == {"messages": {"a", "b", "c"}}

    def test_blank_schema_classifies_sortkeys_per_namespace(self, impl):
        conn = self._make_conn(
            [
                ("analytics", "messages", "created_at", 1),
                ("public", "messages", "a", -1),
                ("public", "messages", "b", 2),
            ]
        )
        result = impl.get_leading_index_columns(
            conn, _make_config(schema=""), ["analytics.messages", "public.messages"]
        )
        assert result == {"analytics.messages": {"created_at"}, "public.messages": {"a", "b"}}

    def test_tables_with_no_sortkey_are_empty(self, impl):
        conn = self._make_conn([])
        result = impl.get_leading_index_columns(conn, _make_config(), ["messages", "logs"])
        assert result == {"messages": set(), "logs": set()}

    def test_returns_none_on_exception(self, impl):
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.execute.side_effect = Exception("denied")
        conn.cursor.return_value = cur
        assert impl.get_leading_index_columns(conn, _make_config(), ["t"]) is None


class TestGetSourceMetadata:
    def test_pinned_schema_stamps_config_namespace(self, impl):
        metadata = impl.get_source_metadata(MagicMock(), _make_config(), ["users", "orders"])
        assert metadata.schema_by_table == {"users": "public", "orders": "public"}
        assert metadata.table_name_by_table == {"users": "users", "orders": "orders"}
        assert metadata.catalog_by_table == {"users": None, "orders": None}

    def test_blank_schema_splits_qualified_display_names(self, impl):
        metadata = impl.get_source_metadata(MagicMock(), _make_config(schema=""), ["analytics.users", "public.users"])
        assert metadata.schema_by_table == {"analytics.users": "analytics", "public.users": "public"}
        assert metadata.table_name_by_table == {"analytics.users": "users", "public.users": "users"}
        assert metadata.catalog_by_table == {"analytics.users": None, "public.users": None}

    def test_blank_schema_does_not_guess_namespace_for_bare_name(self, impl):
        # A bare key in multi-schema mode is unexpected (discovery always qualifies); never invent
        # a schema we'd then fail to query — leave it unknown so the resolver self-heals.
        metadata = impl.get_source_metadata(MagicMock(), _make_config(schema=""), ["users"])
        assert metadata.schema_by_table == {"users": None}
        assert metadata.table_name_by_table == {"users": "users"}


# ---------------------------------------------------------------------------
# Source wiring — singleton + get_implementation + non-retryable errors
# ---------------------------------------------------------------------------


class TestRedshiftSourceWiring:
    def test_get_implementation_returns_singleton(self):
        source = RedshiftSource()
        assert source.get_implementation is _REDSHIFT_IMPLEMENTATION


class TestRedshiftSourceNonRetryableErrors:
    @pytest.mark.parametrize(
        "error_msg",
        [
            "Source column type changed",
            "SchemaColumnTypeChangedException: Source column type changed: 'id' has values that no longer fit",
        ],
    )
    def test_widened_integer_column_errors_are_non_retryable(self, error_msg):
        non_retryable = RedshiftSource().get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable

    def test_ssl_server_error_is_non_retryable(self):
        error_msg = (
            'connection failed: connection to server at "10.0.0.1", port 5439 failed: '
            "server does not support SSL, but SSL was required"
        )
        non_retryable = RedshiftSource().get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable


class TestRedshiftValidateCredentials:
    def test_server_without_ssl_returns_friendly_error_without_capturing(self, mocker):
        # We always connect with sslmode=require, so a server that doesn't support SSL is a
        # host/port misconfiguration on the customer's side — surface guidance, don't report it.
        config = _make_config()
        source = RedshiftSource()
        mocker.patch.object(source, "ssh_tunnel_is_valid", return_value=(True, None))
        mocker.patch.object(source, "is_database_host_valid", return_value=(True, None))
        mocker.patch.object(
            source,
            "get_schemas",
            side_effect=psycopg.OperationalError(
                'connection failed: connection to server at "10.0.0.1", port 5439 failed: '
                "server does not support SSL, but SSL was required"
            ),
        )
        capture = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.source.capture_exception"
        )

        ok, error = source.validate_credentials(config, team_id=1)

        assert ok is False
        assert error is not None and "does not support SSL" in error
        capture.assert_not_called()


class TestRedshiftSourceForPipeline:
    def test_forwards_chunk_size_override_from_external_data_schema(self, mocker):
        schema_row = MagicMock()
        schema_row.chunk_size_override = 9999
        mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.source.ExternalDataSchema.objects.get",
            return_value=schema_row,
        )
        build_pipeline = mocker.patch.object(RedshiftImplementation, "build_pipeline", return_value=MagicMock())

        source = RedshiftSource()
        config = _make_config()
        inputs = _make_inputs()
        source.source_for_pipeline(config, inputs)

        build_pipeline.assert_called_once_with(config, inputs, chunk_size_override=9999)


# ---------------------------------------------------------------------------
# End-to-end build_pipeline — wired through RedshiftImplementation
# ---------------------------------------------------------------------------


@pytest.fixture
def build_pipeline_mocks(mocker):
    """Patch psycopg.connect + per-cursor metadata methods on RedshiftImplementation
    so `build_pipeline` can run end-to-end without a real Redshift server.
    """
    fake_table = Table(
        name="messages",
        parents=("public",),
        columns=[RedshiftColumn(name="id", data_type="integer", nullable=False)],
        type="table",
    )

    mocker.patch.object(RedshiftImplementation, "get_table_metadata", return_value=fake_table)
    mocker.patch.object(RedshiftImplementation, "get_primary_keys_for_table", return_value=["id"])
    mocker.patch.object(RedshiftImplementation, "get_rows_to_sync", return_value=0)
    mocker.patch.object(RedshiftImplementation, "get_chunk_size", return_value=1000)
    mocker.patch.object(RedshiftImplementation, "get_partition_settings", return_value=None)
    mocker.patch.object(RedshiftImplementation, "has_duplicate_primary_keys", return_value=False)

    streaming_cursor = MagicMock()
    streaming_cursor.__enter__.return_value = streaming_cursor
    streaming_cursor.description = [MagicMock(name="id")]
    streaming_cursor.description[0].name = "id"
    streaming_cursor.fetchmany.return_value = []

    # The metadata pass uses the patched `RedshiftImplementation`
    # methods, so a single cursor mock can serve both connections —
    # only the streaming connection requires `conn.adapters` to be set.
    state = {"first_conn": True}
    created_conns: list = []

    def connect_side_effect(*args, **kwargs):
        conn = MagicMock()
        conn.__enter__.return_value = conn
        conn.cursor.return_value = streaming_cursor
        # psycopg requires autocommit be set before a transaction starts; default the mock to
        # False so a test can assert build_pipeline flips it on the metadata connection.
        conn.autocommit = False
        if not state["first_conn"]:
            conn.adapters = MagicMock()
        state["first_conn"] = False
        created_conns.append(conn)
        return conn

    mock_connect = mocker.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.psycopg.connect",
        side_effect=connect_side_effect,
    )
    mock_connect.created_conns = created_conns
    return mock_connect, streaming_cursor


class TestBuildPipeline:
    def test_returns_source_response(self, build_pipeline_mocks):
        mock_connect, _ = build_pipeline_mocks
        impl = RedshiftImplementation()
        response = impl.build_pipeline(_make_config(), _make_inputs())
        assert response.name == "messages"
        assert response.primary_keys == ["id"]
        # psycopg.connect was called at least once for the metadata pass
        assert mock_connect.called

    def test_metadata_connection_uses_autocommit(self, build_pipeline_mocks):
        # Regression: discovery probes share one connection. Without autocommit a single failing
        # best-effort probe leaves the transaction aborted (INERROR) and every probe after it —
        # `has_duplicate_primary_keys` was the reported one — raises `InFailedSqlTransaction`.
        mock_connect, _ = build_pipeline_mocks
        impl = RedshiftImplementation()
        impl.build_pipeline(_make_config(), _make_inputs())

        metadata_conn = mock_connect.created_conns[0]
        assert metadata_conn.autocommit is True

    def test_streaming_drains_without_error(self, build_pipeline_mocks):
        _, streaming_cursor = build_pipeline_mocks
        impl = RedshiftImplementation()
        response = impl.build_pipeline(_make_config(), _make_inputs())
        list(response.items())  # type: ignore[arg-type]
        # streaming cursor.execute should have been invoked for the streaming query
        assert streaming_cursor.execute.called

    def test_chunk_size_override_skips_probe(self, build_pipeline_mocks, mocker):
        mocked_chunk_size = mocker.patch.object(RedshiftImplementation, "get_chunk_size")
        impl = RedshiftImplementation()
        impl.build_pipeline(_make_config(), _make_inputs(), chunk_size_override=4242)
        mocked_chunk_size.assert_not_called()

    def test_routes_per_row_namespace_from_schema_metadata(self, build_pipeline_mocks, mocker):
        get_meta = mocker.patch.object(
            RedshiftImplementation,
            "get_table_metadata",
            return_value=Table(
                name="users",
                parents=("analytics",),
                columns=[RedshiftColumn(name="id", data_type="integer", nullable=False)],
                type="table",
            ),
        )
        impl = RedshiftImplementation()
        inputs = _make_inputs(
            schema_name="analytics.users",
            schema_metadata={"source_schema": "analytics", "source_table_name": "users"},
        )

        response = impl.build_pipeline(_make_config(schema=""), inputs)

        # Per-row schema + unqualified table threaded into the metadata query.
        assert get_meta.call_args.args[1] == "analytics"
        assert get_meta.call_args.args[2] == "users"
        # Delta subdir is the underscore-normalized qualified name.
        assert response.name == "analytics_users"

    def test_legacy_row_falls_back_to_config_schema(self, build_pipeline_mocks, mocker):
        get_meta = mocker.patch.object(
            RedshiftImplementation,
            "get_table_metadata",
            return_value=Table(
                name="messages",
                parents=("public",),
                columns=[RedshiftColumn(name="id", data_type="integer", nullable=False)],
                type="table",
            ),
        )
        impl = RedshiftImplementation()
        # No schema_metadata, bare table name, pinned config schema.
        response = impl.build_pipeline(_make_config(), _make_inputs(schema_name="messages"))

        assert get_meta.call_args.args[1] == "public"
        assert get_meta.call_args.args[2] == "messages"
        assert response.name == "messages"

    def test_s3_folder_name_preserves_legacy_delta_path(self, build_pipeline_mocks, mocker):
        mocker.patch.object(
            RedshiftImplementation,
            "get_table_metadata",
            return_value=Table(
                name="users",
                parents=("analytics",),
                columns=[RedshiftColumn(name="id", data_type="integer", nullable=False)],
                type="table",
            ),
        )
        impl = RedshiftImplementation()
        inputs = _make_inputs(
            schema_name="analytics.users",
            schema_metadata={"source_schema": "analytics", "source_table_name": "users"},
            s3_folder_name="users",
        )

        response = impl.build_pipeline(_make_config(schema=""), inputs)

        # Migrated row keeps its original subdir rather than moving to `analytics_users`.
        assert response.name == "users"


# ---------------------------------------------------------------------------
# Connection lifecycle
# ---------------------------------------------------------------------------


class TestConnect:
    def test_connect_forwards_tcp_keepalive_opts(self, mocker):
        # Regression: a discovery query (`get_columns`) hung in psycopg's `wait_c` on a dead
        # connection until the Temporal activity's `start_to_close_timeout` cancelled the worker
        # thread, surfacing a misleading `CancelledError`. `connect_timeout` only bounds
        # establishing the connection, so the connection must enable TCP keepalives to detect a
        # dead peer mid-query and fail fast with a retryable error instead.
        mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.open_ssh_tunnel",
        ).return_value.__enter__.return_value = ("localhost", 5439)
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mock_connect = mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.psycopg.connect",
            return_value=mock_conn,
        )

        impl = RedshiftImplementation()
        with impl.connect(_make_config()):
            pass

        kwargs = mock_connect.call_args.kwargs
        assert kwargs["keepalives"] == 1
        assert kwargs["keepalives_idle"] == 30
        assert kwargs["keepalives_interval"] == 10
        assert kwargs["keepalives_count"] == 3
        assert kwargs["tcp_user_timeout"] == 60000


class TestGetConnectionMetadata:
    # Source creation looks this method up by name (duck-typed) and silently persists {} when
    # it's absent — which left direct Redshift connections labeled as Postgres in the SQL editor.
    @pytest.mark.parametrize(
        "schema,expected_schema",
        [("public", "public"), ("", None), (None, None)],
    )
    def test_reports_redshift_engine_without_connecting(self, schema, expected_schema):
        metadata = RedshiftSource().get_connection_metadata(_make_config(schema=schema), team_id=1)

        assert metadata == {"engine": "redshift", "database": "dev", "schema": expected_schema}
