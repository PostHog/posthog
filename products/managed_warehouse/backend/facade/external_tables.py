from __future__ import annotations

from uuid import UUID

from products.managed_warehouse.backend import external_tables
from products.managed_warehouse.backend.facade.contracts import ExternalTableSyncSettings


def external_table_sync_feature_enabled(team_id: int) -> bool:
    return external_tables.external_table_sync_feature_enabled(team_id)


def get_external_table_sync_settings(team_id: int, table_id: UUID) -> ExternalTableSyncSettings:
    return external_tables.get_external_table_sync_settings(team_id, table_id)


def configure_external_table_sync(
    team_id: int, table_id: UUID, *, enabled: bool, interval_minutes: int
) -> ExternalTableSyncSettings:
    return external_tables.configure_external_table_sync(
        team_id, table_id, enabled=enabled, interval_minutes=interval_minutes
    )


def disable_external_table_sync(team_id: int, table_id: UUID) -> None:
    external_tables.disable_external_table_sync(team_id, table_id)
