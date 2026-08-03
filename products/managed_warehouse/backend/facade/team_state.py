"""Typed managed-warehouse team-state capabilities."""

from __future__ import annotations

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseBackfillState,
    ManagedWarehouseTeamMembership,
)

__all__ = [
    "backfill_row_exists",
    "data_imports_schema",
    "list_enabled_backfill_team_memberships",
    "resolve_events_persons_tables",
    "team_backfill_membership",
    "team_backfill_state",
]


def resolve_events_persons_tables(team_id: int) -> tuple[str, str]:
    from products.managed_warehouse.backend import team_state

    return team_state.resolve_events_persons_tables(team_id)


def data_imports_schema(team_id: int) -> str:
    from products.managed_warehouse.backend import team_state

    return team_state.data_imports_schema(team_id)


def team_backfill_membership(team_id: int) -> ManagedWarehouseTeamMembership | None:
    from products.managed_warehouse.backend import team_state

    return team_state.team_backfill_row(team_id)


def team_backfill_state(team_id: int) -> ManagedWarehouseBackfillState:
    from products.managed_warehouse.backend import team_state

    return team_state.team_backfill_state(team_id)


def backfill_row_exists(team_id: int, organization_id: str) -> bool:
    from products.managed_warehouse.backend import team_state

    return team_state.backfill_row_exists(team_id, organization_id)


def list_enabled_backfill_team_memberships(call_site: str) -> list[ManagedWarehouseTeamMembership]:
    from products.managed_warehouse.backend import team_state

    return team_state.list_enabled_backfill_rows(call_site)
