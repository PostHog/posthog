from __future__ import annotations

import datetime as dt
from uuid import UUID

from django.db import transaction

from asgiref.sync import async_to_sync

from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false
from posthog.temporal.common.client import async_connect

from products.managed_warehouse.backend.common import (
    duckgres_data_imports_schema,
    get_duckgres_server_by_team_org,
    is_dev_mode,
)
from products.managed_warehouse.backend.facade.contracts import (
    ExternalTableSyncScheduleError,
    ExternalTableSyncSettings,
    ExternalTableSyncStatus,
)
from products.managed_warehouse.backend.facade.feature_flags import DATA_WAREHOUSE_SCENE_FLAG, EXTERNAL_TABLE_SYNC_FLAG
from products.managed_warehouse.backend.models import ManagedWarehouseExternalTable
from products.warehouse_sources.backend.facade.external_delta import get_external_delta_table


def enroll_external_table(team_id: int, table_id: UUID) -> ManagedWarehouseExternalTable:
    source = get_external_delta_table(team_id, table_id)
    registration, _ = ManagedWarehouseExternalTable.objects.for_team(team_id).get_or_create(
        table_id=table_id,
        defaults={
            "team_id": team_id,
            "source_fingerprint": source.fingerprint,
            "warehouse_schema": duckgres_data_imports_schema(team_id),
            "warehouse_table": f"external_{table_id.hex}",
        },
    )
    if registration.source_fingerprint != source.fingerprint:
        raise ValueError("The enrolled table location changed; enroll a new warehouse table")
    return registration


def _organization_flag_enabled(team_id: int, flag: str) -> bool:
    organization_id = str(Team.objects.only("organization_id").get(id=team_id).organization_id)
    return feature_enabled_or_false(
        flag,
        organization_id,
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def external_table_sync_feature_enabled(team_id: int) -> bool:
    return _organization_flag_enabled(team_id, EXTERNAL_TABLE_SYNC_FLAG)


def get_external_table_sync_settings(team_id: int, table_id: UUID) -> ExternalTableSyncSettings:
    registration = ManagedWarehouseExternalTable.objects.for_team(team_id).filter(table_id=table_id).first()
    unavailable_reason = None
    try:
        source = get_external_delta_table(team_id, table_id)
        if registration is not None and source.fingerprint != registration.source_fingerprint:
            unavailable_reason = "The source location changed. Add a new self-managed source to sync this location."
    except ValueError:
        unavailable_reason = "Warehouse sync supports Delta tables in Amazon S3."
    if unavailable_reason is None and (
        not _organization_flag_enabled(team_id, DATA_WAREHOUSE_SCENE_FLAG)
        or (not is_dev_mode() and get_duckgres_server_by_team_org(team_id) is None)
    ):
        unavailable_reason = "Set up a managed warehouse for this project before enabling sync."
    enabled = registration is not None and registration.enabled
    sync_status = ExternalTableSyncStatus.DISABLED
    error = None
    if enabled and registration is not None:
        if registration.latest_error:
            sync_status = ExternalTableSyncStatus.ERROR
            error = (
                "Couldn't start warehouse sync. Save settings to try again."
                if registration.latest_error == "ScheduleError"
                else "The last refresh failed. Check the source location and read permissions, then save settings to retry."
            )
        else:
            sync_status = (
                ExternalTableSyncStatus.READY
                if registration.published_version is not None
                else ExternalTableSyncStatus.PREPARING
            )
    return ExternalTableSyncSettings(
        available=unavailable_reason is None,
        unavailable_reason=unavailable_reason,
        enabled=enabled,
        interval_minutes=registration.interval_minutes if registration is not None else 60,
        status=sync_status,
        last_synced_at=registration.last_synced_at if registration is not None else None,
        error=error,
    )


@async_to_sync
async def _schedule_external_table(team_id: int, table_id: UUID, interval_minutes: int, *, trigger: bool) -> None:
    from products.managed_warehouse.backend.temporal.external_table_schedule import (
        configure_external_table_schedule,  # noqa: PLC0415 -- avoids the workflow import cycle
    )

    client = await async_connect()
    await configure_external_table_schedule(
        client, team_id, table_id, dt.timedelta(minutes=interval_minutes), trigger_immediately=trigger
    )


def disable_external_table_sync(team_id: int, table_id: UUID) -> None:
    ManagedWarehouseExternalTable.objects.for_team(team_id).filter(table_id=table_id).update(enabled=False)


def configure_external_table_sync(
    team_id: int, table_id: UUID, *, enabled: bool, interval_minutes: int
) -> ExternalTableSyncSettings:
    if not external_table_sync_feature_enabled(team_id):
        raise ValueError("Warehouse sync is not available for this project.")
    if not 5 <= interval_minutes <= 10080:
        raise ValueError("Choose a refresh interval between five minutes and seven days.")
    if not enabled:
        disable_external_table_sync(team_id, table_id)
        return get_external_table_sync_settings(team_id, table_id)
    current = get_external_table_sync_settings(team_id, table_id)
    if not current.available:
        raise ValueError(current.unavailable_reason)
    registration = enroll_external_table(team_id, table_id)
    with transaction.atomic():
        locked = ManagedWarehouseExternalTable.objects.for_team(team_id).select_for_update().get(id=registration.id)
        trigger = not current.enabled or bool(locked.latest_error)
        locked.enabled = True
        locked.interval_minutes = interval_minutes
        locked.save(update_fields=["enabled", "interval_minutes", "updated_at"])
    try:
        _schedule_external_table(team_id, table_id, interval_minutes, trigger=trigger)
    except Exception:
        ManagedWarehouseExternalTable.objects.for_team(team_id).filter(id=registration.id).update(
            latest_error="ScheduleError"
        )
        raise ExternalTableSyncScheduleError("Couldn't start warehouse sync. Save settings to try again.") from None
    return get_external_table_sync_settings(team_id, table_id)
