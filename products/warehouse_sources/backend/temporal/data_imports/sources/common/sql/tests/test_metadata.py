"""Tests for `common/sql/metadata.py` — the schema_metadata JSON shape."""

from __future__ import annotations

from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.metadata import (
    extract_available_column_names,
    sql_schema_metadata,
)


class TestSqlSchemaMetadata:
    def test_empty_columns_produce_empty_columns_list(self) -> None:
        metadata = sql_schema_metadata([])
        assert metadata == {
            "columns": [],
            "foreign_keys": [],
            "source_catalog": None,
            "source_schema": None,
            "source_table_name": None,
        }

    def test_columns_preserve_input_order(self) -> None:
        metadata = sql_schema_metadata([("c", "text", True), ("a", "int", False), ("b", "text", False)])
        names = [column["name"] for column in metadata["columns"]]
        assert names == ["c", "a", "b"]

    def test_column_dict_shape(self) -> None:
        metadata = sql_schema_metadata([("email", "text", True)])
        assert metadata["columns"] == [{"name": "email", "data_type": "text", "is_nullable": True}]

    def test_foreign_keys_optional(self) -> None:
        metadata = sql_schema_metadata([("id", "integer", False)])
        assert metadata["foreign_keys"] == []

    def test_foreign_keys_serialized(self) -> None:
        metadata = sql_schema_metadata(
            [("user_id", "integer", False)],
            foreign_keys=[("user_id", "users", "id")],
        )
        assert metadata["foreign_keys"] == [{"column": "user_id", "target_table": "users", "target_column": "id"}]

    def test_source_location_propagated(self) -> None:
        metadata = sql_schema_metadata(
            [],
            source_catalog="my_project",
            source_schema="analytics",
            source_table_name="events",
        )
        assert metadata["source_catalog"] == "my_project"
        assert metadata["source_schema"] == "analytics"
        assert metadata["source_table_name"] == "events"

    def test_preserves_driver_native_casing(self) -> None:
        # BigQuery returns uppercase types, Postgres lowercase. The metadata must round-trip
        # whatever the driver returned — no normalization.
        metadata = sql_schema_metadata([("col_a", "STRING", False), ("col_b", "integer", True)])
        types = [column["data_type"] for column in metadata["columns"]]
        assert types == ["STRING", "integer"]


class TestExtractAvailableColumnNames:
    def test_none_returns_empty_set(self) -> None:
        assert extract_available_column_names(None) == set()

    def test_empty_dict_returns_empty_set(self) -> None:
        assert extract_available_column_names({}) == set()

    def test_extracts_names_from_columns_list(self) -> None:
        metadata = sql_schema_metadata([("id", "int", False), ("email", "text", True)])
        assert extract_available_column_names(metadata) == {"id", "email"}

    def test_malformed_columns_silently_skipped(self) -> None:
        # Defensive against historic rows that may have shape drift.
        metadata = {"columns": [{"name": "id"}, "not a dict", {"data_type": "text"}, None]}
        assert extract_available_column_names(metadata) == {"id"}
