from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
    _build_count_query,
    build_has_new_rows_query,
)
from products.warehouse_sources.backend.types import IncrementalFieldType


class TestBuildHasNewRowsQuery:
    @parameterized.expand(
        [
            ("datetime", IncrementalFieldType.DateTime, ">"),
            ("integer", IncrementalFieldType.Integer, ">"),
            ("date", IncrementalFieldType.Date, ">="),
        ]
    )
    def test_operator_matches_the_query_the_sync_would_run(self, _name: str, field_type, expected_operator: str):
        # A `>` where the sync uses `>=` silently drops every row sharing the watermark's value.
        probe = build_has_new_rows_query(
            schema="public",
            table_name="orders",
            incremental_field="updated_at",
            incremental_field_type=field_type,
            db_incremental_field_last_value="2026-08-01",
        ).as_string()
        sync = _build_count_query(
            schema="public",
            table_name="orders",
            should_use_incremental_field=True,
            incremental_field="updated_at",
            incremental_field_type=field_type,
            db_incremental_field_last_value="2026-08-01",
        ).as_string()

        assert f'"updated_at" {expected_operator}' in probe
        assert probe.split("WHERE")[1].removesuffix(" LIMIT 1") == sync.split("WHERE")[1]

    def test_stops_at_the_first_matching_row(self):
        query = build_has_new_rows_query(
            schema="public",
            table_name="orders",
            incremental_field="updated_at",
            incremental_field_type=IncrementalFieldType.DateTime,
            db_incremental_field_last_value="2026-08-01",
        ).as_string()

        assert query.startswith("SELECT 1 ")
        assert query.endswith("LIMIT 1")
