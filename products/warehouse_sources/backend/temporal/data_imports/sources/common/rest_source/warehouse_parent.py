import uuid
from collections.abc import Iterable, Iterator
from typing import Any, Literal, Optional

from django.conf import settings

import pyarrow as pa
import deltalake
import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team

from products.warehouse_sources.backend.models.external_data_schema import get_schema_if_exists
from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_storage import (
    get_delta_storage_options,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    pyarrow_schema_from_arrow_exportable,
)

FANOUT_WAREHOUSE_REUSE_FLAG = "warehouse-fanout-parent-reuse"


def is_fanout_warehouse_reuse_enabled(team_id: int) -> bool:
    """Gate for reading fan-out parents from the warehouse instead of the parent API.

    Fails closed: any error means "off", which keeps the legacy parent-API path.
    """
    try:
        team = Team.objects.get(id=team_id)
        return bool(
            posthoganalytics.feature_enabled(
                FANOUT_WAREHOUSE_REUSE_FLAG,
                str(team.uuid),
                groups={"organization": str(team.organization_id), "project": str(team.id)},
                group_properties={
                    "organization": {"id": str(team.organization_id)},
                    "project": {"id": str(team.id)},
                },
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as e:
        capture_exception(e)
        return False


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
    for api_name in columns:
        physical = NamingConvention.normalize_identifier(api_name)
        if physical in physical_schema_names:
            physical_by_api_name[api_name] = physical

    if not physical_by_api_name:
        raise WarehouseParentTableNotFoundError(
            f"Parent table '{parent_name}' has none of the requested columns {columns}"
        )

    projected = list(dict.fromkeys(physical_by_api_name.values()))
    dataset = delta_table.to_pyarrow_dataset()

    batches: Iterable[pa.RecordBatch]
    if order_by is not None:
        order_field, order_direction = order_by
        order_physical = physical_by_api_name.get(order_field)
        if order_physical is None:
            raise WarehouseParentTableNotFoundError(
                f"Parent table '{parent_name}' has no column for order_by field '{order_field}'"
            )
        table = dataset.to_table(columns=projected)
        table = table.sort_by([(order_physical, order_direction)])
        batches = table.to_batches(max_chunksize=page_size)
    else:
        batches = dataset.to_batches(columns=projected, batch_size=page_size)

    page: list[dict[str, Any]] = []
    for batch in batches:
        rows = batch.to_pylist()
        for row in rows:
            page.append({api_name: row.get(physical) for api_name, physical in physical_by_api_name.items()})
            if len(page) >= page_size:
                yield page
                page = []
    if page:
        yield page
