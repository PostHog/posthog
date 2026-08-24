from datetime import date

import pytest
from unittest.mock import MagicMock, call, patch

import psycopg
import pyarrow as pa
from psycopg import sql
from psycopg.pq import TransactionStatus
from sshtunnel import BaseSSHTunnelForwarderError

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    TemporaryFileSizeExceedsLimitException,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import Table, TableStats
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.redshift import (
    RedshiftSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift import (
    REDSHIFT_SINGLE_NODE_FETCH_LIMIT,
    RedshiftColumn,
    RedshiftImplementation,
    SafeDateLoader,
    _build_query,
    _explain_query,
    _fetch_arrow_batches,
    _is_transient_connection_drop_error,
    _libpq_rows_per_chunk,
    _stream_arrow_batches,
    _stream_rows_as_arrow_batches,
    filter_redshift_incremental_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.redshift.source import (
    _REDSHIFT_IMPLEMENTATION,
    RedshiftSource,
)
from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException
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


class TestSafeDateLoader:
    @pytest.fixture
    def loader(self):
        return SafeDateLoader(oid=1082)

    @pytest.mark.parametrize(
        "input_data,expected",
        [
            (b"2024-01-15", date(2024, 1, 15)),
            (b"0001-01-01", date(1, 1, 1)),
            (b"9999-12-31", date(9999, 12, 31)),
            # Reproduces the reported incident: psycopg's default `DateLoader` raises
            # `DataError: can't parse date '0000-01-01': year 0 is out of range`, aborting the sync.
            (b"0000-01-01", date.min),
            (b"10000-01-01", date.max),
            (b"infinity", date.max),
            (b"-infinity", date.min),
            (b"-0001-01-01", date.min),
            (b"0044-03-15 BC", date.min),
            (None, None),
        ],
    )
    def test_load_dates(self, loader, input_data, expected):
        assert loader.load(input_data) == expected

    @pytest.mark.parametrize("input_data", [b"04/01/2022", b"not-a-date", b"20220401"])
    def test_unparseable_dates_raise_instead_of_clamping(self, loader, input_data):
        # A silent clamp to date.max corrupts the whole column with a real-looking date;
        # an unparseable value must surface as a loud sync failure instead.
        with pytest.raises(ValueError):
            loader.load(input_data)


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

    @pytest.mark.parametrize(
        "table_type,expected_phrase",
        [
            ("view", "A view cannot have a primary key"),
            ("materialized_view", "A materialized view cannot have a primary key"),
        ],
    )
    def test_warns_that_a_relation_without_a_key_cannot_have_one(
        self, impl, cursor, logger, table_type, expected_phrase
    ):
        # Neither relation can declare a PRIMARY KEY in Redshift, so the empty result is final —
        # the message has to name the remedies rather than send the operator looking for a key.
        cursor.fetchall.return_value = []

        impl.get_primary_keys_for_table(cursor, "public", "t", logger, table_type)

        warning = logger.warning.call_args.args[0]
        assert expected_phrase in warning
        assert "full table replication" in warning

    def test_warns_that_a_table_declares_no_key_when_the_role_can_read_constraints(self, impl, cursor, logger):
        # A key found elsewhere in the schema proves the role can read `table_constraints`, so this
        # table's empty result is a real absence and the message can say so outright.
        cursor.fetchall.return_value = []
        cursor.execute.return_value = cursor
        cursor.fetchone.return_value = (1,)

        impl.get_primary_keys_for_table(cursor, "public", "t", logger, "table")

        assert "No primary key is set on t" in logger.warning.call_args.args[0]

    @pytest.mark.parametrize("probe_outcome", ["sees_nothing", "probe_fails"])
    def test_does_not_claim_a_table_is_keyless_when_detection_is_undetermined(
        self, impl, cursor, logger, probe_outcome
    ):
        # The reported bug: an unreadable key and an absent key both produce zero rows, and the
        # message asserted the second. Asserting absence here sends the operator to set keys by
        # hand for a condition they may not have.
        cursor.fetchall.return_value = []
        cursor.execute.return_value = cursor
        cursor.fetchone.return_value = None
        if probe_outcome == "probe_fails":
            # Only the privilege probe is a LIMIT 1, so this fails it without counting calls.
            def fail_the_probe(query, *args):
                if "LIMIT 1" in query.as_string():
                    raise Exception("permission denied")
                return cursor

            cursor.execute.side_effect = fail_the_probe

        impl.get_primary_keys_for_table(cursor, "public", "t", logger, "table")

        warning = logger.warning.call_args.args[0]
        assert "Could not determine a primary key" in warning
        assert "No primary key is set" not in warning

    def test_orders_composite_key_columns_by_declared_position(self, impl, cursor):
        # Without ORDER BY, Redshift returns the constraint's columns in arbitrary order and a
        # composite key is assembled wrong, which silently corrupts incremental merge matching.
        cursor.fetchall.return_value = [("a",), ("b",)]

        impl.get_primary_keys_for_table(cursor, "public", "t")

        assert "ORDER BY" in cursor.execute.call_args.args[0].as_string()
        assert "kcu.ordinal_position" in cursor.execute.call_args.args[0].as_string()


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
        # svv_mv_info probe first, then pg_views.
        cursor.fetchone.side_effect = [(False,), (True,)]
        cursor.__iter__.return_value = iter([("id", "integer", "NO", None, None)])
        table = impl.get_table_metadata(cursor, "public", "myview")
        assert table.type == "view"

    def test_marks_materialized_view_when_svv_mv_info_matches(self, impl, cursor):
        # Redshift has no `pg_matviews`, so the `pg_views` lookup alone reported every
        # materialized view as a plain table.
        cursor.execute.return_value = cursor
        cursor.fetchone.side_effect = [(True,)]
        cursor.__iter__.return_value = iter([("id", "integer", "NO", None, None)])

        table = impl.get_table_metadata(cursor, "public", "daily_totals")

        assert table.type == "materialized_view"

    def test_falls_back_to_the_view_check_when_the_mv_probe_fails(self, impl, cursor):
        # A role without access to `svv_mv_info` must still get a classified relation.
        cursor.execute.side_effect = [Exception("permission denied for relation svv_mv_info"), cursor, cursor]
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

    def test_permission_denied_on_materialized_view_is_not_reported(self, impl, cursor, logger):
        # A materialized view's base relation can be denied even when the view itself is
        # selectable. That's an expected customer permission-config issue, not an actionable bug —
        # row-count estimation is best-effort (the caller defaults to 0), so skip gracefully
        # without reporting the non-actionable error to error tracking (the source of the reported
        # noise).
        cursor.execute.side_effect = psycopg.errors.InsufficientPrivilege(
            'permission denied for materialized view base relation "Payment_Actions"'
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ) as mock_capture:
            assert impl.get_rows_to_sync(cursor, self._inner(), None, logger) == 0
        mock_capture.assert_not_called()

    def test_remote_request_timeout_is_not_reported(self, impl, cursor, logger):
        # A `Remote request timeout` (code 29150) is Redshift's leader node losing internal RPC
        # contact with a compute node mid-query — a transient cluster-side hiccup, the same
        # non-actionable class as a WLM/QMR abort. Row-count estimation is best-effort (the caller
        # defaults to 0), so skip gracefully without reporting the expected error to error tracking.
        cursor.execute.side_effect = psycopg.errors.InternalError_(
            "Remote request timeout\nDETAIL:  \n  -----------------------------------------------\n"
            "  error:  Remote request timeout\n  code:      29150\n  context:   \n  query:     0\n"
            "  location:  redcat_rpc_client.cpp:3197\n  process:   padbmaster [pid=1074384894]\n"
            "  -----------------------------------------------"
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ) as mock_capture:
            assert impl.get_rows_to_sync(cursor, self._inner(), None, logger) == 0
        mock_capture.assert_not_called()


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

    @pytest.mark.parametrize(
        "table_info_row,expected",
        [
            ((2, 100), 2 * 1024 * 1024 // 100),
            # Rows far smaller than a byte still have to report at least 1: a 0 would make the
            # caller discard the measurement and fall back to the full default chunk.
            ((1, 10_000_000), 1),
            (None, None),
            ((0, 100), None),
            ((10, 0), None),
        ],
    )
    def test_derives_row_size_from_table_stats(self, impl, cursor, logger, table_info_row, expected):
        cursor.fetchone.return_value = table_info_row
        assert impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger) == expected

    def test_returns_none_on_exception(self, impl, cursor, logger):
        cursor.execute.side_effect = RuntimeError("boom")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ):
            assert impl.fetch_average_row_size(cursor, "public", "t", self._inner(), None, logger) is None


# ---------------------------------------------------------------------------
# Streaming reads
# ---------------------------------------------------------------------------


_STREAM_SCHEMA = pa.schema([pa.field("id", pa.int64())])
_STREAM_QUERY = sql.SQL("SELECT id FROM public.t").format()


def _stream_cursor(batches: list[list[tuple]]) -> MagicMock:
    column = MagicMock()
    column.name = "id"

    cursor = MagicMock()
    cursor.description = [column]
    cursor.fetchmany.side_effect = [*batches, []]
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    return cursor


def _rows_cursor(rows: list[tuple] | Exception) -> MagicMock:
    """An unnamed cursor whose `stream()` yields `rows`, or raises when given an exception."""
    column = MagicMock()
    column.name = "id"

    cursor = MagicMock()
    cursor.description = [column]
    if isinstance(rows, Exception):
        cursor.stream.side_effect = rows
    else:
        cursor.stream.return_value = iter(rows)
    cursor.__enter__.return_value = cursor
    cursor.__exit__.return_value = False
    return cursor


def _stream_connection(
    server_cursor: MagicMock,
    stream_cursor: MagicMock,
    transaction_status: TransactionStatus = TransactionStatus.INTRANS,
) -> MagicMock:
    connection = MagicMock()
    connection.cursor.side_effect = lambda name=None: server_cursor if name is not None else stream_cursor
    connection.info.transaction_status = transaction_status
    return connection


def _ids(tables) -> list[list[int]]:
    return [table.column("id").to_pylist() for table in tables]


class TestFetchArrowBatches:
    def test_accumulates_small_fetches_into_chunk_sized_batches(self):
        # Paging the FETCH must not shrink the Arrow batch too: one table per 1000-row fetch would
        # hand the Delta writer 20x more, 20x smaller batches than the chunk size budgets for.
        cursor = _stream_cursor([[(1,), (2,)], [(3,), (4,)], [(5,), (6,)], [(7,)]])

        tables = list(_fetch_arrow_batches(cursor, 5, _STREAM_SCHEMA, fetch_size=2))

        assert _ids(tables) == [[1, 2, 3, 4, 5, 6], [7]]
        assert [c.args[0] for c in cursor.fetchmany.call_args_list] == [2, 2, 2, 2, 2]

    def test_fetches_a_whole_chunk_at_a_time_by_default(self):
        cursor = _stream_cursor([[(1,), (2,)]])

        assert _ids(list(_fetch_arrow_batches(cursor, 2, _STREAM_SCHEMA))) == [[1, 2]]
        assert [c.args[0] for c in cursor.fetchmany.call_args_list] == [2, 2]


class TestStreamRowsAsArrowBatches:
    def test_accumulates_streamed_rows_into_chunk_sized_batches(self):
        # Streaming yields row by row; the Delta writer still has to see chunk_size-sized batches.
        cursor = _rows_cursor([(1,), (2,), (3,), (4,), (5,)])

        tables = list(_stream_rows_as_arrow_batches(cursor, _STREAM_QUERY, 2, _STREAM_SCHEMA))

        assert _ids(tables) == [[1, 2], [3, 4], [5]]

    def test_asks_libpq_for_chunked_delivery(self):
        cursor = _rows_cursor([(1,)])

        list(_stream_rows_as_arrow_batches(cursor, _STREAM_QUERY, 1, _STREAM_SCHEMA))

        assert cursor.stream.call_args.kwargs["size"] == _libpq_rows_per_chunk()

    def test_yields_nothing_for_an_empty_result(self):
        cursor = _rows_cursor([])

        assert list(_stream_rows_as_arrow_batches(cursor, _STREAM_QUERY, 2, _STREAM_SCHEMA)) == []


class TestStreamArrowBatches:
    def test_streams_without_declaring_a_cursor(self, logger):
        # Streaming declares nothing on the cluster, so the per-node cap on cursor data - which no
        # fetch size can get under - never applies to the table at all.
        stream_cursor = _rows_cursor([(1,), (2,), (3,)])
        server_cursor = _stream_cursor([])
        connection = _stream_connection(server_cursor, stream_cursor)

        tables = list(_stream_arrow_batches(connection, _STREAM_QUERY, 2, _STREAM_SCHEMA, "cur", logger))

        assert _ids(tables) == [[1, 2], [3]]
        assert connection.cursor.call_args_list == [call()]
        server_cursor.execute.assert_not_called()

    def test_falls_back_to_a_server_cursor_when_streaming_fails(self, logger):
        stream_cursor = _rows_cursor(psycopg.errors.FeatureNotSupported("single row mode not supported"))
        server_cursor = _stream_cursor([[(1,), (2,)]])
        connection = _stream_connection(server_cursor, stream_cursor, TransactionStatus.INERROR)

        tables = list(_stream_arrow_batches(connection, _STREAM_QUERY, 2, _STREAM_SCHEMA, "cur", logger))

        assert _ids(tables) == [[1, 2]]
        # Without the rollback the fallback dies on `InFailedSqlTransaction` instead of syncing.
        connection.rollback.assert_called_once()

    def test_retries_the_cursor_at_the_single_node_limit(self, logger):
        # A single-node cluster rejects the first FETCH of every sync, and that one a smaller fetch
        # does fix - so it must retry rather than give up on the cursor.
        stream_cursor = _rows_cursor(psycopg.errors.FeatureNotSupported("single row mode not supported"))
        server_cursor = _stream_cursor([[(1,), (2,)]])
        server_cursor.fetchmany.side_effect = [
            psycopg.errors.InternalError_("Fetch size 20000 exceeds the limit of 1000 for a single node configuration"),
            [(1,), (2,)],
            [],
        ]
        connection = _stream_connection(server_cursor, stream_cursor, TransactionStatus.INERROR)

        tables = list(_stream_arrow_batches(connection, _STREAM_QUERY, 20_000, _STREAM_SCHEMA, "cur", logger))

        assert _ids(tables) == [[1, 2]]
        # The retry has to actually shrink the fetch, or Redshift rejects it identically.
        assert [c.args[0] for c in server_cursor.fetchmany.call_args_list] == [
            20_000,
            REDSHIFT_SINGLE_NODE_FETCH_LIMIT,
            REDSHIFT_SINGLE_NODE_FETCH_LIMIT,
        ]

    def test_fails_the_sync_when_the_result_set_exceeds_the_cursor_limit(self, logger):
        # The production failure: streaming is unavailable and the table is over the cluster's cursor
        # cap. Reading it client-side instead OOM-killed the pod, taking co-tenant extractions with it.
        stream_cursor = _rows_cursor(psycopg.errors.FeatureNotSupported("single row mode not supported"))
        server_cursor = _stream_cursor([])
        server_cursor.fetchmany.side_effect = psycopg.errors.InternalError_(
            "exceeded the maximum size allowed for the total set of cursor data: 8000MB."
        )
        connection = _stream_connection(server_cursor, stream_cursor, TransactionStatus.INERROR)

        with pytest.raises(NonRetryableException) as failure:
            list(
                _stream_arrow_batches(
                    connection, _STREAM_QUERY, REDSHIFT_SINGLE_NODE_FETCH_LIMIT, _STREAM_SCHEMA, "cur", logger
                )
            )

        assert "too large to read" in str(failure.value)
        # Only the stream cursor and the one server cursor: no third, unnamed read of the whole table.
        assert connection.cursor.call_args_list == [call(), call(name="cur")]

    def test_propagates_an_unclassified_cursor_failure(self, logger):
        # Unclassified means possibly transient, so it must stay retryable rather than fail the
        # schema outright the way the cursor-cap case does.
        stream_cursor = _rows_cursor(psycopg.errors.FeatureNotSupported("single row mode not supported"))
        server_cursor = _stream_cursor([])
        server_cursor.fetchmany.side_effect = psycopg.OperationalError("connection lost")
        connection = _stream_connection(server_cursor, stream_cursor, TransactionStatus.INERROR)

        with pytest.raises(psycopg.OperationalError):
            list(_stream_arrow_batches(connection, _STREAM_QUERY, 2, _STREAM_SCHEMA, "cur", logger))

    def test_does_not_fall_back_once_a_batch_has_been_yielded(self, logger):
        def rows():
            yield (1,)
            raise psycopg.OperationalError("connection lost")

        stream_cursor = _rows_cursor([])
        stream_cursor.stream.return_value = rows()
        server_cursor = _stream_cursor([[(9,)]])
        connection = _stream_connection(server_cursor, stream_cursor)

        stream = _stream_arrow_batches(connection, _STREAM_QUERY, 1, _STREAM_SCHEMA, "cur", logger)

        assert next(stream).column("id").to_pylist() == [1]
        with pytest.raises(psycopg.OperationalError):
            next(stream)
        # Re-running the query here would re-emit rows the pipeline already merged.
        server_cursor.execute.assert_not_called()


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

    def test_operational_error_is_propagated(self, impl, cursor, logger):
        # A connection-level failure (e.g. the SSL connection dropping mid-query) means the probe
        # never ran — swallowing it as "no duplicate keys" would be a false negative, so it must
        # propagate instead of being reported to error tracking and defaulted to False.
        cursor.execute.side_effect = psycopg.OperationalError(
            "consuming input failed: SSL connection has been closed unexpectedly"
        )
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.capture_exception"
        ) as mock_capture:
            with pytest.raises(psycopg.OperationalError):
                impl.has_duplicate_primary_keys(cursor, "public", "t", ["id"], logger)
        mock_capture.assert_not_called()

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
        # 1: SET statement_timeout, 2: svv_table_info, 3: pg_views, 4: svv_mv_info, 5: UNION ALL counts.
        cur.fetchall.side_effect = [
            [("analytics", "events", 500)],  # svv_table_info (materialized tables)
            [("public", "events")],  # pg_views (views aren't in svv_table_info)
            [],  # svv_mv_info
            [("public", "events", 42)],  # COUNT(*) per view
        ]
        conn.cursor.return_value = cur

        result = impl.get_row_counts(conn, _make_config(schema=""), ["analytics.events", "public.events"])

        # Same table name in two namespaces stays distinct; the view falls through to COUNT(*).
        assert result == {"analytics.events": 500, "public.events": 42}

    def test_materialized_view_falls_through_to_count_query(self, impl):
        # A materialized view is in neither `svv_table_info` (registered under an internal name)
        # nor `pg_views`, so without the `svv_mv_info` probe it got no row count at all.
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.fetchall.side_effect = [
            [],  # svv_table_info
            [],  # pg_views
            [("public", "daily_totals")],  # svv_mv_info
            [("public", "daily_totals", 7)],  # COUNT(*)
        ]
        conn.cursor.return_value = cur

        assert impl.get_row_counts(conn, _make_config(), ["daily_totals"]) == {"daily_totals": 7}

    def test_failed_materialized_view_probe_keeps_the_other_counts(self, impl):
        # The probe is isolated so a role without access to `svv_mv_info` loses only the
        # materialized-view counts, not every count in the batch.
        conn = MagicMock()
        cur = MagicMock()
        cur.__enter__.return_value = cur
        cur.execute.side_effect = [None, None, None, Exception("permission denied for relation svv_mv_info")]
        cur.fetchall.side_effect = [
            [("public", "users", 500)],  # svv_table_info
            [],  # pg_views
        ]
        conn.cursor.return_value = cur

        assert impl.get_row_counts(conn, _make_config(), ["users"]) == {"users": 500}

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

    def test_permission_denied_raw_message_is_non_retryable(self):
        # The activity-level check matches the raw `str(exception)`, which for a psycopg
        # `InsufficientPrivilege` never contains the class name — only the `InsufficientPrivilege`
        # key (which only matches once Temporal's `ApplicationError` wraps the failure with the
        # class name) would miss this, letting the activity burn its full retry budget on a
        # permission denial that can't resolve itself.
        error_msg = 'permission denied for materialized view base relation "Payment_Actions"'
        non_retryable = RedshiftSource().get_non_retryable_errors()
        is_non_retryable = any(pattern in error_msg for pattern in non_retryable.keys())
        assert is_non_retryable

    def test_query_timeout_raw_message_is_non_retryable(self):
        # Mirrors the `InsufficientPrivilege` case above: the activity-level check matches raw
        # `str(exception)`, which for `QueryTimeoutException` is just the message with no class
        # name — only the `QueryTimeoutException` key (workflow layer only) would miss this,
        # letting the activity retry a query that times out identically every attempt because the
        # table's incremental field isn't a SORTKEY.
        error_msg = "10 min timeout statement reached. Please ensure your incremental field (updated_at) is set as a SORTKEY on the table"
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

    def test_ssh_gateway_session_error_maps_to_actionable_message(self, mocker):
        # sshtunnel's raw "Could not establish session to SSH gateway" is meaningless to the user;
        # it must be replaced with concrete guidance rather than surfaced verbatim.
        config = _make_config()
        source = RedshiftSource()
        mocker.patch.object(source, "ssh_tunnel_is_valid", return_value=(True, None))
        mocker.patch.object(source, "is_database_host_valid", return_value=(True, None))
        mocker.patch.object(
            source,
            "get_schemas",
            side_effect=BaseSSHTunnelForwarderError("Could not establish session to SSH gateway"),
        )

        ok, error = source.validate_credentials(config, team_id=1)

        assert ok is False
        assert error is not None
        assert "Could not establish session to SSH gateway" not in error
        assert "SSH tunnel" in error and "firewall" in error


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


class TestIsTransientConnectionDropError:
    def test_matches_connection_is_lost(self):
        assert _is_transient_connection_drop_error(psycopg.OperationalError("the connection is lost")) is True

    def test_does_not_match_unrelated_operational_error(self):
        # A permanent, non-actionable failure that also raises OperationalError must not be
        # swept up by the narrow "the connection is lost" match and retried in-process.
        assert (
            _is_transient_connection_drop_error(
                psycopg.OperationalError("password authentication failed for user testuser")
            )
            is False
        )

    def test_does_not_match_non_operational_error(self):
        assert _is_transient_connection_drop_error(ValueError("the connection is lost")) is False


class TestBuildPipeline:
    def test_retries_once_on_transient_connection_drop_during_setup(self, build_pipeline_mocks, mocker):
        # Regression: `get_table_metadata` hit a freshly opened connection that dropped
        # (`psycopg.OperationalError: the connection is lost`) before setup finished. Without an
        # in-process retry this failed the whole sync out to Temporal's activity-level retry, which
        # restarts the entire setup phase from scratch instead of reconnecting once.
        mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.time.sleep")
        attempts = {"n": 0}
        fake_table = Table(
            name="messages",
            parents=("public",),
            columns=[RedshiftColumn(name="id", data_type="integer", nullable=False)],
            type="table",
        )

        def flaky_get_table_metadata(*args, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise psycopg.OperationalError("the connection is lost")
            return fake_table

        mocker.patch.object(RedshiftImplementation, "get_table_metadata", side_effect=flaky_get_table_metadata)

        impl = RedshiftImplementation()
        response = impl.build_pipeline(_make_config(), _make_inputs())

        assert attempts["n"] == 2
        assert response.primary_keys == ["id"]

    def test_gives_up_after_max_attempts_on_persistent_connection_drop(self, build_pipeline_mocks, mocker):
        mocker.patch("products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.time.sleep")
        mocker.patch.object(
            RedshiftImplementation,
            "get_table_metadata",
            side_effect=psycopg.OperationalError("the connection is lost"),
        )

        impl = RedshiftImplementation()
        with pytest.raises(psycopg.OperationalError):
            impl.build_pipeline(_make_config(), _make_inputs())

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

    def test_connect_registers_safe_date_loader(self, mocker):
        # Wiring guard: SafeDateLoader only protects a sync if it's actually registered on the
        # connection every `connect()` call produces.
        mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.open_ssh_tunnel",
        ).return_value.__enter__.return_value = ("localhost", 5439)
        mock_conn = MagicMock()
        mock_conn.__enter__.return_value = mock_conn
        mocker.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.redshift.redshift.psycopg.connect",
            return_value=mock_conn,
        )

        impl = RedshiftImplementation()
        with impl.connect(_make_config()):
            pass

        mock_conn.adapters.register_loader.assert_any_call("date", SafeDateLoader)


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
