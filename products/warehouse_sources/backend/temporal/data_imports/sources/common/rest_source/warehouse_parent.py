import uuid
from collections.abc import Iterable, Iterator
from typing import Any, Literal, Optional

from django.conf import settings

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.models.external_data_schema import get_schema_if_exists
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_storage import (
    get_delta_storage_options,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    pyarrow_schema_from_arrow_exportable,
)


class WarehouseParentTableNotFoundError(Exception):
    """The fan-out parent schema has no synced Delta table to read from.

    The run-time gate in `import_data_activity_sync` should prevent this; raising keeps the
    failure explicit if a table disappears between the gate and the read.
    """


def _parent_table_uri(team_id: int, source_id: str, parent_name: str) -> str:
    parent_schema = get_schema_if_exists(parent_name, team_id, uuid.UUID(source_id))
    if parent_schema is None:
        raise WarehouseParentTableNotFoundError(f"Parent schema '{parent_name}' does not exist for source {source_id}")
    # Mirrors DeltaTableHelper._get_delta_table_uri: the writer keys the table path on the
    # parent schema's folder_path + normalized resource name.
    normalized_name = NamingConvention.normalize_identifier(parent_name)
    return f"{settings.BUCKET_URL}/{parent_schema.folder_path()}/{normalized_name}"


def iter_parent_pages_from_warehouse(
    *,
    team_id: int,
    source_id: str,
    parent_name: str,
    columns: list[str],
    page_size: int,
    order_by: Optional[tuple[str, Literal["ascending", "descending"]]] = None,
    dedupe_by: Optional[str] = None,
) -> Iterator[list[dict[str, Any]]]:
    """Yield fan-out parent rows from the parent schema's already-synced Delta table.

    Pages are shaped exactly like the REST parent pages the dependent-resource machinery
    consumes (`list[dict]` keyed by the parent API's field names), so a child resource can
    be driven by this iterator instead of re-pulling the parent endpoint.

    `columns` are API field names (e.g. ``lastSeen``); the Delta writer stores snake_case
    identifiers, so each is normalized to locate the physical column and rows are re-keyed
    back to the API names. `order_by` sorts the projected rows (an API field name from
    `columns`) for callers whose iteration semantics depend on parent order — it
    materializes only the projected columns, so keep `columns` narrow.

    `dedupe_by` keeps only the first row per value of that field. Fan-out callers should
    always pass their resolve field: an append-mode parent accumulates one row per sync
    per parent, and without dedupe the child would re-fetch once per duplicate — the exact
    API cost this reader exists to remove. First occurrence wins, which under a descending
    `order_by` is also the freshest row.
    """
    uri = _parent_table_uri(team_id, source_id, parent_name)
    storage_options = get_delta_storage_options()

    if not deltalake.DeltaTable.is_deltatable(uri, storage_options=storage_options):
        raise WarehouseParentTableNotFoundError(
            f"Parent schema '{parent_name}' has no synced table yet — complete its initial sync first"
        )

    delta_table = deltalake.DeltaTable(uri, storage_options=storage_options)
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

    batches: Iterable[pa.RecordBatch]
    if order_by is not None:
        order_field, order_direction = order_by
        if order_field not in physical_by_api_name:
            raise ValueError(f"order_by field '{order_field}' must be one of the requested columns {columns}")
        table = dataset.to_table(columns=projected)
        table = table.sort_by([(physical_by_api_name[order_field], order_direction)])
        batches = table.to_batches(max_chunksize=page_size)
    else:
        batches = dataset.to_batches(columns=projected, batch_size=page_size)

    seen_keys: set[Any] = set()
    page: list[dict[str, Any]] = []
    for batch in batches:
        rows = batch.to_pylist()
        for row in rows:
            emitted = {api_name: row.get(physical) for api_name, physical in physical_by_api_name.items()}
            if dedupe_by is not None:
                key = emitted.get(dedupe_by)
                if key in seen_keys:
                    continue
                seen_keys.add(key)
            page.append(emitted)
            if len(page) >= page_size:
                yield page
                page = []
    if page:
        yield page
