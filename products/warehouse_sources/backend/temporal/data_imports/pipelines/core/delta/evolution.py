import asyncio

import pyarrow as pa
import deltalake
from dlt.common.libs.deltalake import ensure_delta_compatible_arrow_schema

from products.warehouse_sources.backend.temporal.data_imports.pipelines.core.arrow_utils import (
    pyarrow_schema_from_arrow_exportable,
)


async def evolve_delta_schema(delta_table: deltalake.DeltaTable, schema: pa.Schema) -> deltalake.DeltaTable:
    """Add any columns `schema` carries that the table doesn't have yet.

    Kept out of `delta/ops.py` so the `dlt` import stays off the maintenance-only import path.

    Columns added here always predate their own addition: every file the table already
    holds was written without this column, so it must tolerate absent values on those
    rows. Forcing nullable regardless of the incoming batch's own nullability (which
    reflects only whether *this* batch happened to contain nulls) is what lets a later
    `optimize.compact()` read those old files at all — a non-nullable add otherwise fails
    compaction with "Non-nullable column '<name>' is missing from the physical schema".
    """
    delta_table_schema = pyarrow_schema_from_arrow_exportable(delta_table.schema())

    new_fields = [
        deltalake.Field.from_arrow(field.with_nullable(True))
        for field in ensure_delta_compatible_arrow_schema(schema)
        if field.name not in delta_table_schema.names
    ]
    if new_fields:
        await asyncio.to_thread(delta_table.alter.add_columns, new_fields)

    return delta_table
