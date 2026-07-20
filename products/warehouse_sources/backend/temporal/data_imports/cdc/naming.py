"""Shared CDC naming helpers, dependency-free so both steady-state extraction and
recovery paths can use them without importing each other."""

from __future__ import annotations

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def cdc_qualified_table_name(schema: ExternalDataSchema, default_schema: str | None) -> str:
    """Resolve a CDC schema row to its source-qualified `schema.table` name.

    Prefers stored schema_metadata, then a dotted display name, then the source's
    default schema — so a row stored bare (`orders`) still resolves to its real
    source location (`public.orders`).
    """
    metadata = schema.sync_type_config.get("schema_metadata") or {}
    src_schema = metadata.get("source_schema")
    src_table = metadata.get("source_table_name")
    if isinstance(src_schema, str) and isinstance(src_table, str):
        return f"{src_schema}.{src_table}"
    if "." in schema.name:
        return schema.name
    return f"{default_schema or 'public'}.{schema.name}"
