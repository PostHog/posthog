from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema


def bind_duckgres_data_imports_table_name(schema: ExternalDataSchema) -> str:
    from products.warehouse_sources.backend.duckgres_table_binding import bind_duckgres_data_imports_table_name

    return bind_duckgres_data_imports_table_name(schema)


def duckgres_data_imports_table_name_for_version(
    source_type: str,
    prefix: str | None,
    normalized_name: str,
    naming_version: str,
) -> str:
    from products.warehouse_sources.backend.duckgres_naming import duckgres_data_imports_table_name_for_version

    return duckgres_data_imports_table_name_for_version(source_type, prefix, normalized_name, naming_version)
