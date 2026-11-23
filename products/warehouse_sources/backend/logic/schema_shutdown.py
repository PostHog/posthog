"""Stopping the warehouse syncs of teams that staff shut down for abuse."""

from collections.abc import Collection

from products.data_warehouse.backend.facade.api import pause_external_data_schedule
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema


def syncing_schema_ids(team_ids: Collection[int]) -> list[str]:
    rows = (
        ExternalDataSchema.objects.filter(source__team_id__in=team_ids, should_sync=True)
        .order_by("created_at")
        .values_list("id", flat=True)
    )
    return [str(schema_id) for schema_id in rows]


def stop_schema_syncing(schema_id: str, *, team_ids: Collection[int]) -> bool:
    schemas = ExternalDataSchema.objects.filter(id=schema_id, source__team_id__in=team_ids, should_sync=True)
    if not schemas.exists():
        return False
    # Pausing first means a failed pause leaves the schema syncing, so a second run picks it up again.
    pause_external_data_schedule(schema_id)
    # The queryset update also tears down a sync that is running now.
    schemas.update(should_sync=False)
    return True
