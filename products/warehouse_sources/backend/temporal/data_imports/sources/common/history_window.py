"""Where a sync with no cursor starts reading.

A source that bounds a first sync to a lookback has to answer "from scratch, but from when?".
Answering it per run against the current date is what makes a re-import destructive: the wipe
clears the cursor, the source resolves its lookback against today, and every row older than one
window is dropped with no later run walking back for it.

So a schema records the answer the first time it syncs, and reads it from there afterwards.

Sources still resolving it per run: `adobe_analytics` (90d), `hatchet` (30d), and
`google_play_console`, whose own `resolve_history_start` returns `today - history_days` whenever
the watermark is absent — the same name as this module's idea and the opposite of it.
"""

import datetime as dt
from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def history_start_for_schema(schema: "ExternalDataSchema", now: dt.datetime | None = None) -> dt.datetime | None:
    """Resolve a schema's history start, recording it on a first sync so later runs agree.

    Only a schema that has never synced gets a value written, because that is the only moment the
    lookback is the truthful answer. A schema already holding data covers a range nobody recorded,
    and inventing one would declare away whatever it holds beyond the invention. It stays unbounded
    instead, which the source is free to reach however it can cheaply.
    """
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob  # noqa: PLC0415
    from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import (  # noqa: PLC0415
        SourceRegistry,
    )
    from products.warehouse_sources.backend.types import ExternalDataSourceType  # noqa: PLC0415

    try:
        source = SourceRegistry.get_source(ExternalDataSourceType(schema.source.source_type))
    except ValueError:
        return None

    lookback = source.history_lookback
    if lookback is None:
        return None

    if schema.history_start is not None:
        return schema.history_start

    # Whether the schema has ever run, not whether it currently holds a table: `delete_table` nulls
    # the table link on a schema that has synced for years, and recording a lookback for that one
    # writes down a narrower range than it covered — the loss this exists to prevent. Jobs outlive
    # the wipe, so they separate a genuine first sync from a wiped one.
    if ExternalDataJob.objects.filter(schema_id=schema.pk).exists():
        return None

    # `update_fields` because the pipeline holds this instance from before the run linked its table,
    # and `skip_activity_log` because this is pipeline bookkeeping: it skips an extra SELECT that
    # fails the import when the pooler has dropped the connection mid-sync, and forces an UPDATE so
    # a concurrently deleted schema can't be resurrected as an INSERT (see `save`).
    schema.history_start = (now or timezone.now()) - lookback
    schema.save(update_fields=["history_start"], skip_activity_log=True)

    return schema.history_start
