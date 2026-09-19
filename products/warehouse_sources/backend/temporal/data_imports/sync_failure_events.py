from collections.abc import Iterable
from typing import TYPE_CHECKING

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

logger = structlog.get_logger(__name__)

WAREHOUSE_SOURCE_SYNC_FAILED_EVENT = "$warehouse_source_sync_failed"

MAX_ERROR_LENGTH = 1000


def produce_sync_failed_events(
    source: "ExternalDataSource",
    schemas: Iterable["ExternalDataSchema"],
    error: str | None,
    *,
    job_id: str | None = None,
) -> None:
    """Produce one internal event per failed schema, so that destinations such as Slack can alert on it.

    Pass schemas whose in-memory state already reflects the failure, because `sync_paused` reads it.
    This function never raises. The callers write sync status, and a notification problem must not fail that write.
    """
    for schema in schemas:
        # The failure digest email skips deleted schemas and sources, and schemas the user switched off.
        if schema.deleted or source.deleted or (not schema.should_sync and schema.auto_disabled_at is None):
            continue
        try:
            produce_internal_event(
                team_id=source.team_id,
                event=InternalEventEvent(
                    event=WAREHOUSE_SOURCE_SYNC_FAILED_EVENT,
                    distinct_id=f"team_{source.team_id}",
                    properties={
                        "source_id": str(source.id),
                        "source_type": source.source_type,
                        "source_prefix": (source.prefix or "").rstrip("_") or None,
                        "schema_id": str(schema.id),
                        "schema_name": schema.label or schema.name,
                        "job_id": job_id,
                        "error": (error or "Unknown error")[:MAX_ERROR_LENGTH],
                        "sync_paused": schema.sync_halted,
                    },
                ),
            )
        except Exception:
            logger.exception(
                "Failed to produce warehouse source sync failed event",
                team_id=source.team_id,
                source_id=str(source.id),
                schema_id=str(schema.id),
            )
