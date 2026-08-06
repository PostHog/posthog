"""Builders for the per-schema `schema_metadata` JSON.

Persisted on `ExternalDataSchema.sync_type_config.schema_metadata` so the column
picker and per-row routing avoid re-querying the source. `data_type` strings stay
driver-native — no consumer should branch on case.

Shape: `{columns: [{name, data_type, is_nullable}], foreign_keys: [...], source_catalog, source_schema, source_table_name}`
"""

from __future__ import annotations

from typing import Any


def sql_schema_metadata(
    columns: list[tuple[str, str, bool]],
    foreign_keys: list[tuple[str, str, str]] | None = None,
    source_catalog: str | None = None,
    source_schema: str | None = None,
    source_table_name: str | None = None,
) -> dict[str, Any]:
    """Build the `schema_metadata` JSON for one schema row."""
    return {
        "columns": [
            {
                "name": column_name,
                "data_type": column_type,
                "is_nullable": nullable,
            }
            for column_name, column_type, nullable in columns
        ],
        "foreign_keys": [
            {"column": column_name, "target_table": target_table, "target_column": target_column}
            for column_name, target_table, target_column in (foreign_keys or [])
        ],
        "source_catalog": source_catalog,
        "source_schema": source_schema,
        "source_table_name": source_table_name,
    }


def extract_available_column_names(schema_metadata: dict[str, Any] | None) -> set[str]:
    """Column names persisted on a `schema_metadata` row. Defensive against shape drift."""
    if not isinstance(schema_metadata, dict):
        return set()
    columns = schema_metadata.get("columns")
    if not isinstance(columns, list):
        return set()
    return {column["name"] for column in columns if isinstance(column, dict) and isinstance(column.get("name"), str)}
