"""Where a file destination writes a run's objects: its prefix, the table folder, then the run id.

The prefix takes the same template variables as the S3 batch export key prefix, so `{year}/{month}/{day}/`
splits files into date folders.
"""

from __future__ import annotations

import datetime as dt

from products.batch_exports.backend.facade.contracts import InvalidKeyError
from products.batch_exports.backend.facade.destinations.s3 import render_key_prefix
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import DestinationRunContext
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.errors import (
    DestinationConfigurationError,
)


def run_object_prefix(ctx: DestinationRunContext) -> str:
    """The folder every object of the run goes under, ending in a slash."""
    raw_prefix: str = (ctx.config or {}).get("prefix") or ""
    try:
        rendered_prefix = (
            render_key_prefix(raw_prefix, at=ctx.run_started_at.astimezone(dt.UTC), table=ctx.table_name)
            if ctx.run_started_at is not None
            else raw_prefix
        )
    except InvalidKeyError as err:
        raise DestinationConfigurationError(ctx.destination_name, str(err)) from err
    # A prefix that places `{table}` itself already gives each table its own folder.
    filled_table = rendered_prefix != raw_prefix and "{table}" in raw_prefix
    table_folder = "" if filled_table else ctx.table_name
    parts = [p for p in (rendered_prefix.strip("/"), table_folder, ctx.run_uuid) if p]
    return f"{'/'.join(parts)}/"
