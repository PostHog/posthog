"""Direct-query connection lifecycle capabilities for managed warehouses."""

from __future__ import annotations

from uuid import UUID

from products.managed_warehouse.backend.logic import connection as connection_logic

__all__ = [
    "activate_managed_warehouse_source_lifecycle",
    "deactivate_managed_warehouse_source_lifecycle",
    "ensure_managed_warehouse_direct_source",
    "get_active_managed_warehouse_source_generation",
    "get_managed_warehouse_source_generation",
    "reconcile_managed_warehouse_tables",
    "soft_delete_legacy_managed_warehouse_sources",
    "soft_delete_managed_warehouse_sources",
    "update_managed_warehouse_root_password",
]


def get_active_managed_warehouse_source_generation(*, organization_id: str | UUID) -> int | None:
    return connection_logic.get_active_managed_warehouse_source_generation(organization_id=organization_id)


def get_managed_warehouse_source_generation(*, organization_id: str | UUID) -> int:
    return connection_logic.get_managed_warehouse_source_generation(organization_id=organization_id)


def activate_managed_warehouse_source_lifecycle(*, organization_id: str | UUID, expected_generation: int) -> int | None:
    return connection_logic.activate_managed_warehouse_source_lifecycle(
        organization_id=organization_id,
        expected_generation=expected_generation,
    )


def deactivate_managed_warehouse_source_lifecycle(
    *, organization_id: str | UUID, expected_generation: int
) -> int | None:
    return connection_logic.deactivate_managed_warehouse_source_lifecycle(
        organization_id=organization_id,
        expected_generation=expected_generation,
    )


def ensure_managed_warehouse_direct_source(
    *, team_id: int, organization_id: str | UUID, expected_generation: int
) -> None:
    connection_logic.ensure_managed_warehouse_direct_source(
        team_id=team_id,
        organization_id=organization_id,
        expected_generation=expected_generation,
    )


def reconcile_managed_warehouse_tables(*, team_id: int, organization_id: str | UUID) -> None:
    connection_logic.reconcile_managed_warehouse_tables(team_id=team_id, organization_id=organization_id)


def soft_delete_managed_warehouse_sources(*, organization_id: str | UUID, expected_generation: int) -> None:
    connection_logic.soft_delete_managed_warehouse_sources(
        organization_id=organization_id,
        expected_generation=expected_generation,
    )


def soft_delete_legacy_managed_warehouse_sources(*, organization_id: str | UUID) -> None:
    connection_logic.soft_delete_legacy_managed_warehouse_sources(organization_id=organization_id)


def update_managed_warehouse_root_password(*, organization_id: str | UUID, password: str) -> None:
    connection_logic.update_managed_warehouse_root_password(organization_id=organization_id, password=password)
