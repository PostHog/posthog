"""The warehouse table record of a schema's `_cdc` history table.

Kept apart from the pipeline so the API can retire the record without importing the loader.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from django.db.models import Exists, OuterRef

from products.warehouse_sources.backend.temporal.data_imports.cdc.batcher import companion_resource_name
from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    build_table_name,
    resolve_table_and_folder_names,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.table import DataWarehouseTable


def companion_tables(schema: ExternalDataSchema) -> list[DataWarehouseTable]:
    """The live records of the schema's history table."""
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.table import DataWarehouseTable

    source = schema.source
    companion_name = build_table_name(source, companion_resource_name(schema.name))
    own_names = resolve_table_and_folder_names(schema.name, schema.resolved_s3_folder_name)
    # A pinned folder can give the schema's own table the companion's name.
    if companion_name == build_table_name(source, own_names.table_storage_name):
        return []

    # A source table named `<table>_cdc` resolves to the same table name, and that record is not ours.
    owned_by_another_schema = (
        ExternalDataSchema.objects.filter(team_id=schema.team_id, table_id=OuterRef("pk"))
        .exclude(deleted=True)
        .exclude(id=schema.id)
    )
    return list(
        DataWarehouseTable.objects.filter(
            team_id=schema.team_id,
            name=companion_name,
            external_data_source_id=source.id,
            deleted=False,
        ).filter(~Exists(owned_by_another_schema))
    )


def deregister_companion_table(schema: ExternalDataSchema) -> bool:
    """Soft-delete the record of the schema's history table. Returns whether a record went.

    Nothing writes the history table once its schema stops keeping history, so its open rows
    would claim to be current forever. The Delta files stay, and a later return to history
    resets them before the new seed.
    """
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

    companions = companion_tables(schema)
    if not companions:
        return False

    companion_ids = [companion.id for companion in companions]
    for companion in companions:
        companion.soft_delete()
    # cdc_only links the schema to its companion.
    ExternalDataSchema.objects.filter(id=schema.id, team_id=schema.team_id, table_id__in=companion_ids).update(
        table=None
    )
    if schema.table_id in companion_ids:
        schema.table = None
    return True
