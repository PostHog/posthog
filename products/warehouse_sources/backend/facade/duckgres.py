from __future__ import annotations

from products.warehouse_sources.backend.duckgres_naming import (
    duckgres_data_imports_table_name_for_version as _duckgres_data_imports_table_name_for_version,
)


def duckgres_data_imports_table_name_for_version(
    source_type: str,
    prefix: str | None,
    normalized_name: str,
    naming_version: str,
) -> str:
    return _duckgres_data_imports_table_name_for_version(source_type, prefix, normalized_name, naming_version)
