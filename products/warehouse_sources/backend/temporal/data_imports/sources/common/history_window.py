"""Where a sync with no cursor starts reading.

A source that bounds a first sync to a lookback has to answer "from scratch, but from when?".
Answering it per run against the current date is what makes a re-import destructive: the wipe
clears the cursor, the source resolves its lookback against today, and every row older than one
window is dropped with no later run walking back for it.

So a schema records the answer the first time it syncs, and reads it from there afterwards.
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

    if schema.history_start is None and schema.table_id is None:
        # `update_fields` rather than a plain save: the pipeline holds this instance from before the
        # run linked its table, so writing the whole row would put back the values it was loaded with.
        schema.history_start = (now or timezone.now()) - lookback
        schema.save(update_fields=["history_start"])

    return schema.history_start
