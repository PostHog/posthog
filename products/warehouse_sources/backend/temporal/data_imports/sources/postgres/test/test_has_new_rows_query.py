"""The probe query must ask exactly what the sync query asks.

A probe predicate narrower than the sync's reports "nothing new" for rows the sync would
have read, and the run completes having silently skipped them. Nothing else in the fast
return catches that, so these lock the two predicates together.
"""

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.predicates import (
    ColumnTypeCategory,
    ValidatedRowFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
    _build_query,
    build_has_new_rows_query,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

_FILTERS = [ValidatedRowFilter(column="region", operator="=", value="eu", category=ColumnTypeCategory.STRING)]


def _sync_predicate(field_type, last_value, row_filters) -> str:
    query = _build_query(
        schema="public",
        table_name="orders",
        should_use_incremental_field=True,
        table_type="table",
        incremental_field="updated_at",
        incremental_field_type=field_type,
        db_incremental_field_last_value=last_value,
        row_filters=row_filters,
    ).as_string()
    return query.split(" WHERE ", 1)[1].split(" ORDER BY ")[0]


def _probe_predicate(field_type, last_value, row_filters) -> str:
    query = build_has_new_rows_query(
        schema="public",
        table_name="orders",
        incremental_field="updated_at",
        incremental_field_type=field_type,
        db_incremental_field_last_value=last_value,
        row_filters=row_filters,
    ).as_string()
    return query.split(" WHERE ", 1)[1].removesuffix(" LIMIT 1")


class TestBuildHasNewRowsQuery:
    @parameterized.expand(
        [
            ("datetime", IncrementalFieldType.DateTime, "2026-08-01", None),
            ("integer", IncrementalFieldType.Integer, 42, None),
            ("date_uses_inclusive_operator", IncrementalFieldType.Date, "2026-08-01", None),
            ("empty_watermark_falls_back", IncrementalFieldType.Integer, "", None),
            ("with_row_filters", IncrementalFieldType.DateTime, "2026-08-01", _FILTERS),
            ("integer_with_row_filters", IncrementalFieldType.Integer, 42, _FILTERS),
        ]
    )
    def test_predicate_matches_the_sync_query(self, _name: str, field_type, last_value, row_filters):
        assert _probe_predicate(field_type, last_value, row_filters) == _sync_predicate(
            field_type, last_value, row_filters
        )

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
        assert "ORDER BY" not in query
