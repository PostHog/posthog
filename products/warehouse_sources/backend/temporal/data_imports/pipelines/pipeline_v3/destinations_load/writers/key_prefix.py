"""Where a file destination writes a run's objects: its prefix, the table folder, then the run id.

The prefix takes the same template variables as the S3 batch export key prefix, so `{year}/{month}/{day}/`
splits files into date folders.
"""

from __future__ import annotations

import datetime as dt

from products.batch_exports.backend.facade.key_prefix import datetime_template_variables, render_key_prefix_template
from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import DestinationRunContext


def render_key_prefix(prefix: str, *, run_started_at: dt.datetime | None, table: str) -> str:
    """Fill the prefix the way a batch export fills its key prefix, with times from the run's start in UTC."""
    variables = {"table": table}
    if run_started_at is not None:
        variables |= datetime_template_variables(run_started_at.astimezone(dt.UTC))
    return render_key_prefix_template(prefix, variables)


def run_object_prefix(ctx: DestinationRunContext) -> str:
    """The folder every object of the run goes under, ending in a slash."""
    raw_prefix: str = (ctx.config or {}).get("prefix") or ""
    prefix = render_key_prefix(raw_prefix, run_started_at=ctx.run_started_at, table=ctx.table_name).strip("/")
    # A prefix that places `{table}` itself already gives each table its own folder.
    table_folder = "" if "{table}" in raw_prefix else ctx.table_name
    parts = [p for p in (prefix, table_folder, ctx.run_uuid) if p]
    return f"{'/'.join(parts)}/"
