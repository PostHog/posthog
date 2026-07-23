import uuid
from collections.abc import Iterator
from typing import Any

import deltalake

from products.warehouse_sources.backend.models.external_data_schema import get_schema_if_exists
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_access import (
    build_delta_table_uri,
    delta_storage_options,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    pyarrow_schema_from_arrow_exportable,
)


class WarehouseParentTableNotFoundError(Exception):
    """The fan-out parent schema has no synced Delta table to read from.

    The run-time gate in `import_data_activity_sync` should prevent this; raising keeps the
    failure explicit if a table disappears between the gate and the read.
    """


def resolve_parent_table_uri(team_id: int, source_id: str, parent_name: str) -> str:
    """Locate the parent schema row and derive its Delta table URI.

    Does a Django ORM read — call it from sync context at source-build time (e.g. inside
    `source_for_pipeline`), NOT lazily from the pipeline's iterator executor threads, whose
    ad-hoc DB connections are exactly the pooler-drop failure mode `ExternalDataSchema.save`
    documents. The storage leaf honors a pinned `resolved_s3_folder_name` (legacy-migrated
    rows) before falling back to the normalized schema name, mirroring the writer.
    """
    parent_schema = get_schema_if_exists(parent_name, team_id, uuid.UUID(source_id))
    if parent_schema is None:
        raise WarehouseParentTableNotFoundError(f"Parent schema '{parent_name}' does not exist for source {source_id}")
    leaf = parent_schema.resolved_s3_folder_name or parent_name
    return build_delta_table_uri(parent_schema.folder_path(), leaf)


def iter_parent_pages_from_warehouse(
    *,
    table_uri: str,
    parent_name: str,
    columns: list[str],
    page_size: int,
) -> Iterator[list[dict[str, Any]]]:
    """Yield fan-out parent rows from the parent schema's already-synced Delta table.

    Pages are shaped exactly like the REST parent pages the dependent-resource machinery
    consumes (`list[dict]` keyed by the parent API's field names), so a child resource can
    be driven by this iterator instead of re-pulling the parent endpoint.

    `columns` are API field names (e.g. ``lastSeen``); the Delta writer stores snake_case
    identifiers, so each is normalized to locate the physical column and rows are re-keyed
    back to the API names.

    Strictly streaming: the scan holds one projected batch in memory at a time, with column
    projection pushed down to the parquet read. No sorting, no dedupe state — rows are
    assumed unique per parent, which holds for merge/full-refresh parents by construction;
    append-mode parents accumulate duplicates and are refused by the dependency gates
    before a sync ever reaches this reader. Do not add whole-table materialization here
    (`to_table`, global sorts, seen-sets) — parents can be arbitrarily large.
    """
    storage_options = delta_storage_options()

    if not deltalake.DeltaTable.is_deltatable(table_uri, storage_options=storage_options):
        raise WarehouseParentTableNotFoundError(
            f"Parent schema '{parent_name}' has no synced table yet — complete its initial sync first"
        )

    delta_table = deltalake.DeltaTable(table_uri, storage_options=storage_options)
    physical_schema_names = set(pyarrow_schema_from_arrow_exportable(delta_table.schema()).names)

    physical_by_api_name: dict[str, str] = {}
    missing_columns: list[str] = []
    for api_name in columns:
        physical = NamingConvention.normalize_identifier(api_name)
        if physical in physical_schema_names:
            physical_by_api_name[api_name] = physical
        else:
            missing_columns.append(api_name)

    if missing_columns:
        raise WarehouseParentTableNotFoundError(
            f"Parent table '{parent_name}' is missing requested column(s) {missing_columns} — "
            f"re-sync the parent schema so the fan-out fields are present"
        )

    projected = list(dict.fromkeys(physical_by_api_name.values()))
    dataset = delta_table.to_pyarrow_dataset()

    page: list[dict[str, Any]] = []
    for batch in dataset.to_batches(columns=projected, batch_size=page_size):
        for row in batch.to_pylist():
            page.append({api_name: row.get(physical) for api_name, physical in physical_by_api_name.items()})
            if len(page) >= page_size:
                yield page
                page = []
    if page:
        yield page
