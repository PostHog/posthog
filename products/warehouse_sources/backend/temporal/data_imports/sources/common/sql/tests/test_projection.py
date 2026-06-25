"""Tests for the column-projection helpers in `common/sql/projection.py`."""

from __future__ import annotations

import pytest
from unittest.mock import patch

import pyarrow as pa
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.identifiers import (
    AnsiIdentifierQuoter,
    BacktickIdentifierQuoter,
    BracketIdentifierQuoter,
    InvalidIdentifierError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection import (
    compute_projected_columns,
    filter_columns_by_enabled_columns,
    filter_dwh_columns_by_enabled_columns,
    format_projected_select_clause,
    project_arrow_columns,
    prune_enabled_columns,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.types import Column, Table


class _FakeColumn(Column):
    def __init__(self, name: str) -> None:
        self.name = name

    def to_arrow_field(self) -> pa.Field[pa.DataType]:
        return pa.field(self.name, pa.string())


def _table_with(*column_names: str) -> Table[_FakeColumn]:
    return Table(name="t", parents=("s",), columns=[_FakeColumn(c) for c in column_names])


class TestComputeProjectedColumns:
    @parameterized.expand(
        [
            ("none_keeps_all", None, ["id"], "updated_at", None),
            ("empty_keeps_pks_and_incremental", [], ["id"], "updated_at", ["id", "updated_at"]),
            ("subset_keeps_listed_plus_pk", ["email"], ["id"], None, ["email", "id"]),
            (
                "subset_keeps_listed_plus_pk_plus_incremental",
                ["email"],
                ["id"],
                "updated_at",
                ["email", "id", "updated_at"],
            ),
            (
                "user_already_listed_pk_no_dup",
                ["id", "email"],
                ["id"],
                "updated_at",
                ["id", "email", "updated_at"],
            ),
            (
                "user_already_listed_incremental_no_dup",
                ["email", "updated_at"],
                ["id"],
                "updated_at",
                ["email", "updated_at", "id"],
            ),
            ("multi_pk_appended_in_order", ["email"], ["a", "b"], None, ["email", "a", "b"]),
            ("empty_with_no_pk_no_incremental_falls_back", [], None, None, None),
            ("empty_with_only_incremental_keeps_it", [], None, "updated_at", ["updated_at"]),
        ]
    )
    def test_compute_projected_columns(
        self,
        _name: str,
        enabled_columns: list[str] | None,
        primary_keys: list[str] | None,
        incremental_field: str | None,
        expected: list[str] | None,
    ) -> None:
        assert compute_projected_columns(enabled_columns, primary_keys, incremental_field) == expected


class TestFormatProjectedSelectClause:
    def test_none_renders_as_star(self) -> None:
        assert format_projected_select_clause(None, BacktickIdentifierQuoter()) == "*"

    @parameterized.expand(
        [
            ("backtick", BacktickIdentifierQuoter(), "`id`, `email`"),
            ("ansi", AnsiIdentifierQuoter(), '"id", "email"'),
            ("bracket", BracketIdentifierQuoter(), "[id], [email]"),
        ]
    )
    def test_quoter_applied_per_dialect(self, _name: str, quoter: AnsiIdentifierQuoter, expected: str) -> None:
        assert format_projected_select_clause(["id", "email"], quoter) == expected

    def test_invalid_identifier_raises(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            format_projected_select_clause(["id", "email; DROP TABLE users"], BacktickIdentifierQuoter())


class TestFilterColumnsByEnabledColumns:
    columns: list[tuple[str, str, bool]] = [
        ("id", "integer", False),
        ("email", "text", True),
        ("name", "text", True),
        ("secret", "text", True),
    ]

    def test_none_returns_all(self) -> None:
        assert filter_columns_by_enabled_columns(self.columns, None, ["id"]) == self.columns

    def test_empty_keeps_only_pks(self) -> None:
        assert filter_columns_by_enabled_columns(self.columns, [], ["id"]) == [("id", "integer", False)]

    def test_subset_keeps_listed_plus_pk(self) -> None:
        result = filter_columns_by_enabled_columns(self.columns, ["email"], ["id"])
        names = {column_name for column_name, _, _ in result}
        assert names == {"id", "email"}

    def test_keeps_incremental_field_even_if_excluded(self) -> None:
        result = filter_columns_by_enabled_columns(self.columns, ["email"], ["id"], incremental_field="name")
        names = {column_name for column_name, _, _ in result}
        assert names == {"id", "email", "name"}

    def test_unknown_enabled_columns_silently_dropped(self) -> None:
        result = filter_columns_by_enabled_columns(self.columns, ["email", "ghost"], ["id"])
        names = {column_name for column_name, _, _ in result}
        assert names == {"id", "email"}


class TestFilterDwhColumnsByEnabledColumns:
    dwh_columns: dict[str, dict[str, str]] = {
        "id": {"hogql": "Integer"},
        "email": {"hogql": "String"},
        "name": {"hogql": "String"},
        "updated_at": {"hogql": "DateTime"},
    }

    def test_none_returns_all(self) -> None:
        assert filter_dwh_columns_by_enabled_columns(self.dwh_columns, None, ["id"]) == self.dwh_columns

    def test_subset_keeps_listed_plus_pk(self) -> None:
        result = filter_dwh_columns_by_enabled_columns(self.dwh_columns, ["email"], ["id"])
        assert set(result.keys()) == {"id", "email"}

    def test_incremental_field_retained_even_if_excluded(self) -> None:
        result = filter_dwh_columns_by_enabled_columns(
            self.dwh_columns, ["email"], ["id"], incremental_field="updated_at"
        )
        assert set(result.keys()) == {"id", "email", "updated_at"}

    def test_uppercase_source_names_match_normalized_keys(self) -> None:
        # Snowflake hands back uppercase identifiers in enabled_columns / PKs, but the Delta
        # column keys are dlt-normalized to lowercase. They must still line up.
        result = filter_dwh_columns_by_enabled_columns(self.dwh_columns, ["EMAIL"], ["ID"])
        assert set(result.keys()) == {"id", "email"}

    def test_mixed_case_incremental_field_matches_normalized_key(self) -> None:
        result = filter_dwh_columns_by_enabled_columns(
            self.dwh_columns, ["EMAIL"], ["ID"], incremental_field="UpdatedAt"
        )
        assert set(result.keys()) == {"id", "email", "updated_at"}

    def test_empty_projection_falls_back_to_all_columns(self) -> None:
        # A selection that matches nothing (e.g. namespace mismatch or schema drift) must not
        # wipe the table to zero columns — that leaves `SELECT *` returning no rows.
        result = filter_dwh_columns_by_enabled_columns(self.dwh_columns, ["does_not_exist"], None)
        assert result == self.dwh_columns

    def test_empty_input_stays_empty(self) -> None:
        assert filter_dwh_columns_by_enabled_columns({}, ["email"], ["id"]) == {}

    def test_source_namespace_keys_on_both_sides_still_filter(self) -> None:
        # Direct-postgres callers pass raw source-namespace keys on both sides with normalize=False;
        # an actual subset must filter cleanly without tripping the all-columns fallback.
        source_keyed = {"ID": {"hogql": "Integer"}, "EMAIL": {"hogql": "String"}, "NAME": {"hogql": "String"}}
        result = filter_dwh_columns_by_enabled_columns(source_keyed, ["EMAIL"], ["ID"], normalize=False)
        assert set(result.keys()) == {"ID", "EMAIL"}

    def test_normalize_false_preserves_case_sensitive_selection(self) -> None:
        # Postgres allows `"Foo"` and `"foo"` in one table. With normalize=False (direct-postgres),
        # selecting only `"Foo"` must not drag in `"foo"` by folding them to the same key.
        case_collision = {"Foo": {"hogql": "String"}, "foo": {"hogql": "String"}}
        result = filter_dwh_columns_by_enabled_columns(case_collision, ["Foo"], None, normalize=False)
        assert set(result.keys()) == {"Foo"}

    def test_normalize_true_collapses_case_collision(self) -> None:
        # Warehouse path: source names fold into the stored normalized namespace, so a case-only
        # difference is intentionally matched as the same column.
        case_collision = {"Foo": {"hogql": "String"}, "foo": {"hogql": "String"}}
        result = filter_dwh_columns_by_enabled_columns(case_collision, ["Foo"], None)
        assert set(result.keys()) == {"Foo", "foo"}

    def test_empty_projection_fallback_logs_warning(self) -> None:
        # The all-columns fallback must be observable: an operator should be able to tell their
        # selection was bypassed rather than silently applied.
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection.logger"
        ) as mock_logger:
            result = filter_dwh_columns_by_enabled_columns(self.dwh_columns, ["does_not_exist"], None)
        assert result == self.dwh_columns
        mock_logger.warning.assert_called_once()


class TestPruneEnabledColumns:
    def test_none_passes_through(self) -> None:
        assert prune_enabled_columns(None, {"id", "email"}) == (None, [])

    def test_drops_missing_columns(self) -> None:
        kept, removed = prune_enabled_columns(["id", "email", "ghost"], {"id", "email"})
        assert kept == ["id", "email"]
        assert removed == ["ghost"]

    def test_empty_list_passes_through(self) -> None:
        assert prune_enabled_columns([], {"id", "email"}) == ([], [])

    def test_all_kept_when_all_present(self) -> None:
        kept, removed = prune_enabled_columns(["id", "email"], {"id", "email", "name"})
        assert kept == ["id", "email"]
        assert removed == []

    def test_preserves_caller_order(self) -> None:
        kept, _ = prune_enabled_columns(["email", "id", "name"], {"id", "email", "name"})
        assert kept == ["email", "id", "name"]


class TestProjectArrowColumns:
    def test_none_retained_passes_through(self) -> None:
        table = _table_with("id", "email", "name")
        result = project_arrow_columns(table, None)
        assert result is table

    def test_subset_returns_new_table_with_only_listed_columns(self) -> None:
        table = _table_with("id", "email", "name", "secret")
        result = project_arrow_columns(table, ["id", "email"])
        assert [c.name for c in result.columns] == ["id", "email"]
        assert result.name == table.name
        assert result.parents == table.parents

    def test_preserves_source_order_not_retained_order(self) -> None:
        table = _table_with("id", "email", "name")
        result = project_arrow_columns(table, ["name", "id"])
        assert [c.name for c in result.columns] == ["id", "name"]

    def test_all_missing_columns_falls_back_to_full_table(self) -> None:
        table = _table_with("id", "email")
        result = project_arrow_columns(table, ["ghost", "phantom"])
        assert result is table

    def test_partial_overlap_keeps_only_matching_columns(self) -> None:
        table = _table_with("id", "email", "name")
        result = project_arrow_columns(table, ["email", "ghost"])
        assert [c.name for c in result.columns] == ["email"]
