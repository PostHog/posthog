from typing import cast

from unittest.mock import patch

from django.test import SimpleTestCase

import duckdb
import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.models.util import motherduck_column_to_dwh_column
from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.motherduck import (
    _build_sync_query,
    build_connection_string,
    check_duplicate_primary_keys,
    display_table_name,
    filter_motherduck_incremental_fields,
    get_schemas,
    motherduck_source,
    translate_motherduck_error,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


def _local_connection(*_args, **_kwargs) -> duckdb.DuckDBPyConnection:
    """In-memory stand-in for a MotherDuck connection — the driver API is identical, so
    everything above `connect()` can be exercised without network."""
    connection = duckdb.connect(":memory:")
    connection.execute("CREATE SCHEMA nyc")
    connection.execute("CREATE TABLE nyc.taxi (id BIGINT, fare DOUBLE, pickup TIMESTAMP, notes VARCHAR)")
    connection.execute(
        "INSERT INTO nyc.taxi VALUES"
        " (1, 10.5, '2026-01-01 10:00:00', 'a'),"
        " (2, 20.0, '2026-01-02 10:00:00', 'b'),"
        " (3, 30.0, '2026-01-03 10:00:00', 'c')"
    )
    return connection


_CONNECT = "products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.motherduck.connect"


class TestMotherDuckTransport(SimpleTestCase):
    def test_connection_string_pins_saas_mode_and_escapes(self):
        conn_str = build_connection_string("tok&en", "my db")
        self.assertEqual(conn_str, "md:my%20db?motherduck_token=tok%26en&saas_mode=true")

    @parameterized.expand(
        [
            ("pinned_database", "my_db", "nyc", "taxi", "nyc.taxi"),
            ("all_databases", None, "nyc", "taxi", "memory.nyc.taxi"),
        ]
    )
    def test_display_table_name(self, _name, configured, schema, table, expected):
        self.assertEqual(display_table_name("memory", schema, table, configured_database=configured), expected)

    def test_get_schemas_discovers_columns_and_location(self):
        schemas = get_schemas(_local_connection(), "memory")
        self.assertEqual(list(schemas), ["nyc.taxi"])
        entry = schemas["nyc.taxi"]
        self.assertEqual((entry["database"], entry["schema"], entry["table"]), ("memory", "nyc", "taxi"))
        column_names = [name for name, _type, _nullable in entry["columns"]]
        self.assertEqual(column_names, ["id", "fare", "pickup", "notes"])

    def test_get_schemas_excludes_system_schemas(self):
        schemas = get_schemas(_local_connection(), None)
        # information_schema/pg_catalog tables never surface as syncable schemas.
        self.assertEqual(list(schemas), ["memory.nyc.taxi"])

    def test_get_schemas_scopes_discovery_to_the_configured_database(self):
        # MotherDuck attaches every workspace database to one connection; a pinned database
        # must not surface (or merge with) same-named tables from the others.
        connection = _local_connection()
        connection.execute("ATTACH ':memory:' AS other")
        connection.execute("CREATE SCHEMA other.nyc")
        connection.execute("CREATE TABLE other.nyc.taxi (id BIGINT, other_only VARCHAR)")

        pinned = get_schemas(connection, "memory")
        self.assertEqual(list(pinned), ["nyc.taxi"])
        self.assertEqual(pinned["nyc.taxi"]["database"], "memory")
        column_names = [name for name, _type, _nullable in pinned["nyc.taxi"]["columns"]]
        self.assertEqual(column_names, ["id", "fare", "pickup", "notes"])

        unpinned = get_schemas(connection, None)
        self.assertEqual(sorted(unpinned), ["memory.nyc.taxi", "other.nyc.taxi"])

    def test_incremental_field_detection(self):
        columns = [("id", "BIGINT", False), ("pickup", "TIMESTAMP", True), ("notes", "VARCHAR", True)]
        self.assertEqual(
            filter_motherduck_incremental_fields(columns),
            [("id", IncrementalFieldType.Integer), ("pickup", IncrementalFieldType.DateTime)],
        )

    def test_full_refresh_query_has_no_where(self):
        query, params = _build_sync_query(
            ("db", "nyc", "taxi"),
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
        )
        self.assertEqual(query, 'SELECT * FROM "db"."nyc"."taxi"')
        self.assertEqual(params, {})

    @parameterized.expand(
        [
            # DateTime/Integer cursors carry enough resolution for `>`; `>=` would re-ship the
            # boundary row forever in append mode, which has no merge dedup.
            ("datetime_uses_gt", IncrementalFieldType.DateTime, ">"),
            ("integer_uses_gt", IncrementalFieldType.Integer, ">"),
            # Day-granularity cursors must re-fetch the boundary day or rows are lost.
            ("date_uses_gte", IncrementalFieldType.Date, ">="),
            # Legacy rows without a stored type fall back to the merge-safe `>=`.
            ("unknown_type_uses_gte", None, ">="),
        ]
    )
    def test_incremental_query_operator_follows_field_type(self, _name, field_type, operator):
        query, params = _build_sync_query(
            ("db", "nyc", "taxi"),
            should_use_incremental_field=True,
            incremental_field="pickup",
            incremental_field_type=field_type,
            db_incremental_field_last_value="2026-01-02 10:00:00",
        )
        self.assertEqual(
            query,
            f'SELECT * FROM "db"."nyc"."taxi" WHERE "pickup" {operator} $incremental_last_value ORDER BY "pickup" ASC',
        )
        self.assertEqual(params, {"incremental_last_value": "2026-01-02 10:00:00"})

    def test_projected_columns_replace_select_star(self):
        query, _params = _build_sync_query(
            ("db", "nyc", "taxi"),
            should_use_incremental_field=False,
            incremental_field=None,
            incremental_field_type=None,
            db_incremental_field_last_value=None,
            projected_columns=["id", "fare"],
        )
        self.assertEqual(query, 'SELECT "id", "fare" FROM "db"."nyc"."taxi"')

    def test_source_yields_arrow_batches(self):
        with patch(_CONNECT, side_effect=_local_connection):
            response = motherduck_source(
                token="token",
                database="memory",
                display_name="nyc.taxi",
                location=("memory", "nyc", "taxi"),
                primary_keys=["id"],
            )
            tables = list(cast("list[pa.Table]", response.items()))
        self.assertEqual(response.name, "nyc.taxi")
        self.assertEqual(response.primary_keys, ["id"])
        combined = pa.concat_tables(tables)
        self.assertEqual(combined.num_rows, 3)
        self.assertEqual(combined.column_names, ["id", "fare", "pickup", "notes"])

    def test_incremental_source_skips_older_rows(self):
        with patch(_CONNECT, side_effect=_local_connection):
            response = motherduck_source(
                token="token",
                database="memory",
                display_name="nyc.taxi",
                location=("memory", "nyc", "taxi"),
                primary_keys=["id"],
                should_use_incremental_field=True,
                incremental_field="pickup",
                incremental_field_type=IncrementalFieldType.DateTime,
                db_incremental_field_last_value="2026-01-02 10:00:00",
            )
            combined = pa.concat_tables(cast("list[pa.Table]", response.items()))
        # A DateTime cursor uses `>`, so the boundary row itself is not re-shipped.
        self.assertEqual(sorted(combined.column("id").to_pylist()), [3])

    def test_projected_columns_limit_synced_columns(self):
        with patch(_CONNECT, side_effect=_local_connection):
            response = motherduck_source(
                token="token",
                database="memory",
                display_name="nyc.taxi",
                location=("memory", "nyc", "taxi"),
                primary_keys=["id"],
                projected_columns=["id", "fare"],
            )
            combined = pa.concat_tables(cast("list[pa.Table]", response.items()))
        # The projection is load-bearing: with supports_column_selection the pipeline no
        # longer drops deselected columns after the fetch.
        self.assertEqual(combined.column_names, ["id", "fare"])

    @parameterized.expand(
        [
            ("unique_key", ["id"], False),
            ("duplicated_key", ["fare"], True),
        ]
    )
    def test_check_duplicate_primary_keys(self, _name, keys, expected):
        connection = _local_connection()
        connection.execute("INSERT INTO nyc.taxi VALUES (4, 10.5, '2026-01-04 10:00:00', 'd')")
        self.assertIs(check_duplicate_primary_keys(connection, ("memory", "nyc", "taxi"), keys), expected)

    @parameterized.expand(
        [
            ("auth", "UNAUTHENTICATED: jwt expired", "Invalid MotherDuck token"),
            (
                "compute_limit",
                "Error: You've reached the daily compute limit for this plan. Upgrade to get more capacity.",
                "reached its compute limit",
            ),
            # Unmapped errors surface their first line only (DuckDB appends candidate/hint blocks).
            ("fallback_first_line", "Binder Error: column nope not found\nCandidate bindings: ...", "Binder Error"),
        ]
    )
    def test_translates_errors(self, _name, raw, expected_fragment):
        self.assertIn(expected_fragment, translate_motherduck_error(Exception(raw)))


class TestMotherDuckColumnMapping(SimpleTestCase):
    @parameterized.expand(
        [
            ("BIGINT", False, "Int64", "integer"),
            ("HUGEINT", False, "Int128", "integer"),
            ("UTINYINT", False, "UInt8", "integer"),
            ("VARCHAR", True, "Nullable(String)", "string"),
            ("UUID", False, "UUID", "string"),
            ("DATE", False, "Date32", "date"),
            ("DECIMAL(18,3)", False, "Decimal", "numeric"),
            ("TIMESTAMP WITH TIME ZONE", True, "Nullable(DateTime64(6, 'UTC'))", "datetime"),
            ("STRUCT(a INTEGER, b VARCHAR)", False, "String", "string"),
            # Arrays keep their [] suffix through normalization and must not fall into the
            # scalar decimal/timestamp fallbacks.
            ("DECIMAL(18,3)[]", False, "String", "string"),
            ("TIMESTAMP[]", False, "String", "string"),
            ("INTEGER[]", False, "String", "string"),
        ]
    )
    def test_maps_to_clickhouse_types(self, duckdb_type, nullable, expected, expected_hogql):
        column = motherduck_column_to_dwh_column("c", duckdb_type, nullable)
        self.assertEqual(column["clickhouse"], expected)
        self.assertEqual(column["hogql"], expected_hogql)
        self.assertTrue(column["valid"])
