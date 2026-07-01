from __future__ import annotations

from collections.abc import Awaitable
from typing import TYPE_CHECKING, Protocol, cast

import pyarrow as pa
import deltalake

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    pyarrow_schema_from_arrow_exportable,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.revenuecat.constants import (
    EVENT_RESOURCE_NAME,
    REVENUECAT_WEBHOOK_DOUBLE_FIELDS,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.delta_table_helper import (
        DeltaTableHelper,
    )


MAX_REVENUECAT_EVENT_SCHEMA_REWRITE_BYTES = 256 * 1024 * 1024


class _AsyncWarningLogger(Protocol):
    def awarning(self, event: str, **kwargs: object) -> Awaitable[object]:
        pass


class _SyncWarningLogger(Protocol):
    def warning(self, event: str, **kwargs: object) -> object:
        pass


async def _log_warning(logger: object, event: str, **kwargs: object) -> None:
    if hasattr(logger, "awarning"):
        await cast(_AsyncWarningLogger, logger).awarning(event, **kwargs)
        return
    cast(_SyncWarningLogger, logger).warning(event, **kwargs)


def _delta_table_size_bytes(delta_table: deltalake.DeltaTable) -> int | None:
    try:
        add_actions = delta_table.get_add_actions(flatten=True)
    except Exception:
        return None

    if "size_bytes" not in add_actions.column_names:
        return None

    sizes = add_actions.column("size_bytes").to_pylist()
    if not all(isinstance(size, int) for size in sizes):
        return None
    return sum(sizes)


async def repair_revenuecat_event_double_columns(
    *,
    schema_name: str,
    incoming_table: pa.Table,
    delta_table: deltalake.DeltaTable | None,
    delta_table_helper: DeltaTableHelper,
    logger: object,
) -> deltalake.DeltaTable | None:
    if schema_name != EVENT_RESOURCE_NAME or delta_table is None:
        return delta_table

    delta_schema = pyarrow_schema_from_arrow_exportable(delta_table.schema())
    columns_to_widen: dict[str, pa.DataType] = {}
    for field_name in REVENUECAT_WEBHOOK_DOUBLE_FIELDS:
        if field_name not in delta_schema.names or field_name not in incoming_table.column_names:
            continue

        delta_field = delta_schema.field(field_name)
        incoming_field = incoming_table.field(field_name)
        if pa.types.is_integer(delta_field.type) and pa.types.is_floating(incoming_field.type):
            columns_to_widen[field_name] = pa.float64()

    if not columns_to_widen:
        return delta_table

    table_size_bytes = _delta_table_size_bytes(delta_table)
    if table_size_bytes is None or table_size_bytes > MAX_REVENUECAT_EVENT_SCHEMA_REWRITE_BYTES:
        await _log_warning(
            logger,
            "resetting_revenuecat_event_table_for_double_column_repair",
            columns=list(columns_to_widen.keys()),
            table_size_bytes=table_size_bytes,
            max_rewrite_bytes=MAX_REVENUECAT_EVENT_SCHEMA_REWRITE_BYTES,
        )
        await delta_table_helper.reset_table()
        return None

    await _log_warning(
        logger,
        "repairing_revenuecat_event_double_columns",
        columns=list(columns_to_widen.keys()),
        table_size_bytes=table_size_bytes,
    )
    return await delta_table_helper.rewrite_columns(columns_to_widen)
