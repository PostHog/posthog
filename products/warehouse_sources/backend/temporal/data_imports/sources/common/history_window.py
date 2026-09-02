"""Where a sync with no cursor starts reading.

A source that bounds a first sync to a lookback resolves it against today, so a re-import — which
arrives with no cursor — narrows the range to the last window and the drain never walks back. The
schema records the answer once instead.

Still resolving it per run: `adobe_analytics`, `hatchet`, and `google_play_console`, whose own
`resolve_history_start` is this name for the opposite idea.
"""

import uuid
import datetime as dt
from typing import TYPE_CHECKING

from django.utils import timezone

import structlog

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def history_start_for_schema(
    schema: "ExternalDataSchema", current_job_id: str | uuid.UUID, now: dt.datetime | None = None
) -> dt.datetime | None:
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
        # An unknown type means the source's module failed to import, not that it reads everything.
        # Both answer None here, so say which one this was rather than leave a widened range
        # looking like a declared one.
        logger.warning("history_window.unknown_source_type", source_type=schema.source.source_type)
        return None

    lookback = source.history_lookback
    if lookback is None:
        return None

    if schema.history_start is not None:
        return schema.history_start

    # Whether a run before this one imported anything, not whether a table exists: `delete_table`
    # nulls the table link on a schema that has synced for years, and jobs outlive the wipe.
    #
    # Rows landed rather than the job row itself, because a job is created several activities before
    # the import runs and outlives every way a run can end early — a billing limit, a cancellation, a
    # deploy. Counting those would leave the schema unrecorded forever, reading unbounded on every
    # re-import. This run's own job is excluded too: it is created before this call, and a retry of
    # this activity may already have landed rows under it.
    if ExternalDataJob.objects.filter(schema_id=schema.pk, rows_synced__gt=0).exclude(pk=current_job_id).exists():
        return None

    # `update_fields` because the pipeline loaded this instance before the run linked its table.
    # `skip_activity_log` for the reasons `save` gives: it avoids a read that fails the import on a
    # dropped pooler connection, and forces an UPDATE rather than resurrecting a deleted row.
    schema.history_start = (now or timezone.now()) - lookback
    schema.save(update_fields=["history_start"], skip_activity_log=True)

    return schema.history_start
