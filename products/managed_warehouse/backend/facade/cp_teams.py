"""Typed managed-warehouse control-plane membership capabilities."""

from __future__ import annotations

from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseTeamMembership

__all__ = [
    "clear_team_membership_cache",
    "get_org_team_membership",
    "invalidate_team_membership_cache",
    "list_enabled_backfill_team_memberships",
    "list_org_team_memberships",
    "list_team_memberships",
]


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
    return [row.to_membership() for row in rows] if rows is not None else None


def get_org_team_membership(organization_id: str, team_id: int) -> ManagedWarehouseTeamMembership | None:
    from products.managed_warehouse.backend import cp_teams

    row = cp_teams.get_team(organization_id, team_id)
    return row.to_membership() if row is not None else None


def list_team_memberships(*, use_cache: bool = True) -> list[ManagedWarehouseTeamMembership] | None:
    from products.managed_warehouse.backend import cp_teams

    rows = cp_teams.list_member_teams(use_cache=use_cache)
    return [row.to_membership() for row in rows] if rows is not None else None


def list_enabled_backfill_team_memberships() -> list[ManagedWarehouseTeamMembership] | None:
    from products.managed_warehouse.backend import cp_teams

    rows = cp_teams.list_enabled_backfills()
    return [row.to_membership() for row in rows] if rows is not None else None
