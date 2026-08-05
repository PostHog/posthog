"""Direct-query connection lifecycle capabilities for managed warehouses."""

from __future__ import annotations

from uuid import UUID

from products.managed_warehouse.backend.logic import connection as connection_logic

__all__ = [
    "ensure_managed_warehouse_direct_source",
    "reconcile_managed_warehouse_tables",
    "soft_delete_managed_warehouse_sources",
    "update_managed_warehouse_root_password",
]


def ensure_managed_warehouse_direct_source(*, team_id: int, organization_id: str | UUID) -> None:
    connection_logic.ensure_managed_warehouse_direct_source(team_id=team_id, organization_id=organization_id)


def reconcile_managed_warehouse_tables(*, team_id: int, organization_id: str | UUID) -> None:
    connection_logic.reconcile_managed_warehouse_tables(team_id=team_id, organization_id=organization_id)


def soft_delete_managed_warehouse_sources(*, organization_id: str | UUID) -> None:
    connection_logic.soft_delete_managed_warehouse_sources(organization_id=organization_id)


def update_managed_warehouse_root_password(*, organization_id: str | UUID, password: str) -> None:
    connection_logic.update_managed_warehouse_root_password(organization_id=organization_id, password=password)
