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
        with patch(_CONNECT, side_effect=_local_connection):
            schemas = get_schemas("token", "memory")
        self.assertEqual(list(schemas), ["nyc.taxi"])
        entry = schemas["nyc.taxi"]
        self.assertEqual((entry["database"], entry["schema"], entry["table"]), ("memory", "nyc", "taxi"))
        column_names = [name for name, _type, _nullable in entry["columns"]]
        self.assertEqual(column_names, ["id", "fare", "pickup", "notes"])

    def test_get_schemas_excludes_system_schemas(self):
        with patch(_CONNECT, side_effect=_local_connection):
            schemas = get_schemas("token", None)
        # information_schema/pg_catalog tables never surface as syncable schemas.
        self.assertEqual(list(schemas), ["memory.nyc.taxi"])

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
            db_incremental_field_last_value=None,
        )
        self.assertEqual(query, 'SELECT * FROM "db"."nyc"."taxi"')
        self.assertEqual(params, {})

    def test_incremental_query_filters_and_orders(self):
        query, params = _build_sync_query(
            ("db", "nyc", "taxi"),
            should_use_incremental_field=True,
            incremental_field="pickup",
            db_incremental_field_last_value="2026-01-02 10:00:00",
        )
        self.assertEqual(
            query,
            'SELECT * FROM "db"."nyc"."taxi" WHERE "pickup" >= $incremental_last_value ORDER BY "pickup" ASC',
        )
        self.assertEqual(params, {"incremental_last_value": "2026-01-02 10:00:00"})

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
                db_incremental_field_last_value="2026-01-02 10:00:00",
            )
            combined = pa.concat_tables(cast("list[pa.Table]", response.items()))
        # `>=` re-reads the boundary row (merge dedupes on primary key) but drops older ones.
        self.assertEqual(sorted(combined.column("id").to_pylist()), [2, 3])

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
            ("BIGINT", False, "Int64"),
            ("VARCHAR", True, "Nullable(String)"),
            ("DECIMAL(18,3)", False, "Decimal"),
            ("TIMESTAMP WITH TIME ZONE", True, "Nullable(DateTime64(6, 'UTC'))"),
            ("STRUCT(a INTEGER, b VARCHAR)", False, "String"),
        ]
    )
    def test_maps_to_clickhouse_types(self, duckdb_type, nullable, expected):
        column = motherduck_column_to_dwh_column("c", duckdb_type, nullable)
        self.assertEqual(column["clickhouse"], expected)
        self.assertTrue(column["valid"])
