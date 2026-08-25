"""Typed managed-warehouse control-plane membership capabilities."""

from __future__ import annotations

from datetime import date
from typing import Protocol

from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)


class _ControlPlaneTeam(Protocol):
    team_id: int
    organization_id: str
    schema_name: str
    enabled: bool
    backfill_enabled: bool
    earliest_event_date: date | None

    @property
    def resolved_events_table(self) -> str: ...

    @property
    def resolved_persons_table(self) -> str: ...

    @property
    def resolved_data_imports_schema(self) -> str: ...


__all__ = [
    "clear_team_membership_cache",
    "get_org_team_membership",
    "invalidate_team_membership_cache",
    "list_enabled_backfill_team_memberships",
    "list_org_team_memberships",
    "list_team_memberships",
]


def _to_membership(row: _ControlPlaneTeam) -> ManagedWarehouseTeamMembership:
    return ManagedWarehouseTeamMembership(
        team_id=row.team_id,
        organization_id=row.organization_id,
        schema_name=row.schema_name,
        enabled=row.enabled,
        backfill_enabled=row.backfill_enabled,
        table_names=ManagedWarehouseTableNames(
            events_table=row.resolved_events_table,
            persons_table=row.resolved_persons_table,
            data_imports_schema=row.resolved_data_imports_schema,
        ),
        earliest_event_date=row.earliest_event_date,
    )


def clear_team_membership_cache() -> None:
    from products.managed_warehouse.backend import cp_teams

    cp_teams.clear_cache()


def invalidate_team_membership_cache(organization_id: str) -> None:
    from products.managed_warehouse.backend import cp_teams

    cp_teams.invalidate_org_cache(organization_id)


def list_org_team_memberships(
    organization_id: str,
    *,
    use_cache: bool = True,
) -> list[ManagedWarehouseTeamMembership] | None:
    from products.managed_warehouse.backend import cp_teams

    rows = cp_teams.list_org_teams(organization_id, use_cache=use_cache)
    return [_to_membership(row) for row in rows] if rows is not None else None


def get_org_team_membership(organization_id: str, team_id: int) -> ManagedWarehouseTeamMembership | None:
    from products.managed_warehouse.backend import cp_teams

    row = cp_teams.get_team(organization_id, team_id)
    return _to_membership(row) if row is not None else None


def list_team_memberships(*, use_cache: bool = True) -> list[ManagedWarehouseTeamMembership] | None:
    from products.managed_warehouse.backend import cp_teams

    rows = cp_teams.list_member_teams(use_cache=use_cache)
    return [_to_membership(row) for row in rows] if rows is not None else None


def list_enabled_backfill_team_memberships() -> list[ManagedWarehouseTeamMembership] | None:
    from products.managed_warehouse.backend import cp_teams

    rows = cp_teams.list_enabled_backfills()
    return [_to_membership(row) for row in rows] if rows is not None else None
