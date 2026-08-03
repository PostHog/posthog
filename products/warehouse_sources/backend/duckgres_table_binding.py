from __future__ import annotations

from django.db.models import Q

from products.managed_warehouse.backend.facade import team_state
from products.warehouse_sources.backend.duckgres_naming import duckgres_data_imports_table_name_for_version
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def bind_duckgres_data_imports_table_name(schema: ExternalDataSchema) -> str:
    pinned_name = schema.duckgres_table_name
    if pinned_name:
        return pinned_name

    naming_version = team_state.data_imports_table_naming_version(schema.team_id)
    candidate = duckgres_data_imports_table_name_for_version(
        schema.source.source_type,
        schema.source.prefix,
        schema.normalized_name,
        naming_version,
    )
    updated = ExternalDataSchema.objects.filter(
        Q(duckgres_table_name__isnull=True) | Q(duckgres_table_name=""), pk=schema.pk
    ).update(duckgres_table_name=candidate)
    if updated:
        schema.duckgres_table_name = candidate
        return candidate

    schema.refresh_from_db(fields=["duckgres_table_name"])
    if not schema.duckgres_table_name:
        raise RuntimeError(f"External data schema {schema.pk} has no Duckgres table name after binding")
    return schema.duckgres_table_name
