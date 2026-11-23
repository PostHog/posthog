"""Stopping the warehouse syncs of teams that staff shut down for abuse."""

from collections.abc import Collection

from django.db.models import Exists, OuterRef, Q

from products.data_warehouse.backend.facade.api import pause_cdc_extraction_schedule, pause_external_data_schedule
from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource


def syncing_schema_ids(team_ids: Collection[int]) -> list[str]:
    rows = (
        ExternalDataSchema.objects.filter(source__team_id__in=team_ids, should_sync=True)
        .order_by("created_at")
        .values_list("id", flat=True)
    )
    return [str(schema_id) for schema_id in rows]


def stop_schema_syncing(schema_id: str, *, team_id: int) -> bool:
    schemas = ExternalDataSchema.objects.filter(team_id=team_id, id=schema_id, should_sync=True)
    if not schemas.exists():
        return False
    # Pausing first means a failed pause leaves the schema syncing, so a second run picks it up again.
    pause_external_data_schedule(schema_id)
    # The queryset update also tears down a sync that is running now.
    schemas.update(should_sync=False)
    return True


def _syncing_cdc_schemas() -> Exists:
    return Exists(
        ExternalDataSchema.objects.filter(
            source_id=OuterRef("id"), sync_type=ExternalDataSchema.SyncType.CDC, should_sync=True
        )
    )


def running_source_ids(team_ids: Collection[int]) -> list[str]:
    rows = (
        ExternalDataSource.objects.filter(team_id__in=team_ids, deleted=False)
        .filter(Q(auto_sync_new_schemas=True) | _syncing_cdc_schemas())
        .order_by("created_at")
        .values_list("id", flat=True)
    )
    return [str(source_id) for source_id in rows]


def stop_source(source_id: str, *, team_id: int) -> bool:
    source = (
        ExternalDataSource.objects.filter(team_id=team_id, id=source_id, deleted=False)
        .annotate(syncs_cdc=_syncing_cdc_schemas())
        .values("auto_sync_new_schemas", "syncs_cdc")
        .first()
    )
    if source is None or not (source["auto_sync_new_schemas"] or source["syncs_cdc"]):
        return False
    # The CDC extraction runs on its own schedule per source, not on the schedules of its tables.
    if source["syncs_cdc"]:
        pause_cdc_extraction_schedule(source_id)
    # Discovery keeps running on its own schedule, and with this on it would start syncing new tables again.
    ExternalDataSource.objects.filter(team_id=team_id, id=source_id).update(auto_sync_new_schemas=False)
    return True
