"""Where a sync with no cursor starts reading.

A source that bounds a first sync to a lookback resolves it against today, so a re-import — which
arrives with no cursor — narrows the range to the last window and the drain never walks back. The
schema records the answer once instead.

Still resolving it per run: `adobe_analytics`, `hatchet`, and `google_play_console`, whose own
`resolve_history_start` is this name for the opposite idea.
"""

import datetime as dt
from typing import TYPE_CHECKING

from django.utils import timezone

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def history_start_for_schema(schema: "ExternalDataSchema", now: dt.datetime | None = None) -> dt.datetime | None:
    """The oldest point this schema covers, or None for no bound.

    Written on a first sync, the one moment the lookback is the truthful answer. A schema already
    holding data covers a range nobody recorded, and inventing one declares away the rest.
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

    # Not `table_id`: `delete_table` nulls it on a schema that has synced for years. Jobs outlive
    # the wipe, so they tell a genuine first sync from a wiped one.
    if ExternalDataJob.objects.filter(schema_id=schema.pk).exists():
        return None

    # `update_fields` because the pipeline loaded this instance before the run linked its table.
    # `skip_activity_log` for the reasons `save` gives: it avoids a read that fails the import on a
    # dropped pooler connection, and forces an UPDATE rather than resurrecting a deleted row.
    schema.history_start = (now or timezone.now()) - lookback
    schema.save(update_fields=["history_start"], skip_activity_log=True)

    return schema.history_start
