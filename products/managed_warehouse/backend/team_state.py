"""Readers for per-team managed-warehouse (duckling) state.

Per-team state lives in the duckgres control-plane org-teams API (read via
:mod:`products.managed_warehouse.backend.cp_teams`). This module is the single read seam for that
state: every consumer calls an accessor here instead of talking to the control
plane directly, so the failure posture of each read stays in one place.

Failure posture is per accessor (see each function): backfill-critical reads
raise :class:`CPUnavailableError`, sensor enumerations degrade to empty, status
reads degrade to not-onboarded, and the team-deletion guard fails closed.
"""

from __future__ import annotations

import structlog

from products.managed_warehouse.backend import cp_teams
from products.managed_warehouse.backend.common import _get_org_id_for_team, validate_duckgres_identifier
from products.managed_warehouse.backend.facade.contracts import (
    CPUnavailableError,
    DucklingTables,
    ManagedWarehouseBackfillState,
    ManagedWarehouseTableNames,
    ManagedWarehouseTeamMembership,
)

logger = structlog.get_logger(__name__)


def _get_cp_row(team_id: int) -> cp_teams.CPTeam | None:
    """The team's control-plane row, or None when absent.

    Raises :class:`CPUnavailableError` when the control plane can't answer and the
    cache is cold — callers pick their own degrade posture around it.
    """
    organization_id = _get_org_id_for_team(team_id)
    teams = cp_teams.list_org_teams(organization_id)
    if teams is None:
        raise CPUnavailableError(f"duckgres control plane unreachable reading team state for team {team_id}")
    return next((team for team in teams if team.team_id == team_id), None)


def _to_membership(row: cp_teams.CPTeam) -> ManagedWarehouseTeamMembership:
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


# --- events/persons table names (Dagster duckling backfill) -----------------------


def resolve_events_persons_tables(team_id: int) -> DucklingTables:
    """The per-team events/persons duckling table names the backfill writes to.

    Failure posture: raises :class:`CPUnavailableError` when the control plane can't
    answer and the cache is cold — the backfill run fails and retries rather than
    writing to guessed tables.
    """
    row = _get_cp_row(team_id)
    if row is None:
        # Legacy single-team ducklings without a team row share the base tables.
        return DucklingTables(events_table="events", persons_table="persons")
    events_table, persons_table = row.resolved_events_table, row.resolved_persons_table
    validate_duckgres_identifier(events_table)
    validate_duckgres_identifier(persons_table)
    return DucklingTables(events_table=events_table, persons_table=persons_table)


# --- data-imports schema (v3 sink hot path) ---------------------------------------


def data_imports_schema(team_id: int) -> str:
    """The duckgres schema the v3 data-import sink writes a team into.

    Hot path: reads are served from the cp_teams TTL cache. Failure posture: raises
    :class:`CPUnavailableError` when the control plane can't answer and the cache is
    cold — the batch fails and retries.
    """
    row = _get_cp_row(team_id)
    if row is None:
        # Teams without a control-plane row keep the historical per-team schema.
        return f"posthog_data_imports_team_{team_id}"
    schema = row.resolved_data_imports_schema
    validate_duckgres_identifier(schema)
    return schema


def data_imports_table_naming_version(team_id: int) -> str:
    """The organization-level naming policy shared by Duckgres data-import readers and writers."""
    row = _get_cp_row(team_id)
    if row is None:
        return "copy_v1"
    return row.data_imports_table_naming_version


# --- backfill state (warehouse-status UI) -----------------------------------------


def team_backfill_row(team_id: int) -> ManagedWarehouseTeamMembership | None:
    """The team's control-plane membership for status reads, or None when absent.

    Failure posture: a status read must never 500 — an unreachable control plane
    degrades to None (reported as not onboarded / not configured).
    """
    try:
        row = _get_cp_row(team_id)
    except CPUnavailableError:
        logger.warning("duckgres_team_state_cp_unavailable", call_site="team_backfill_row", team_id=team_id)
        return None
    return _to_membership(row) if row is not None else None


def team_backfill_state(team_id: int) -> ManagedWarehouseBackfillState:
    """The team's duckling backfill state for the warehouse-status UI.

    Failure posture: a status read must never 500 — an unreachable control plane
    degrades to the not-onboarded shape.
    """
    row = team_backfill_row(team_id)
    if row is None:
        return ManagedWarehouseBackfillState(has_backfill=False, table_suffix=None)
    return ManagedWarehouseBackfillState(has_backfill=True, table_suffix=cp_table_suffix_from_membership(row))


def cp_table_suffix_from_membership(row: ManagedWarehouseTeamMembership) -> str | None:
    if row.table_names.events_table == "events" or row.table_names.persons_table == "persons":
        return None
    return row.schema_name


# --- membership existence (team-deletion guard) -----------------------------------


def backfill_row_exists(team_id: int, organization_id: str) -> bool:
    """Whether the team has a managed-warehouse membership row.

    Failure posture: fail closed — an unreachable control plane reports the row as
    existing, so a possibly-onboarded team's deletion is blocked with a retry error
    instead of silently orphaning its duckgres state.
    """
    teams = cp_teams.list_org_teams(str(organization_id))
    if teams is None:
        logger.warning("duckgres_team_state_cp_unavailable", call_site="backfill_row_exists", team_id=team_id)
        return True
    return any(team.team_id == team_id for team in teams)


# --- enabled-backfill enumeration (Dagster sensors) -------------------------------


def list_enabled_backfill_rows(call_site: str) -> list[ManagedWarehouseTeamMembership]:
    """Every backfill-enabled team in a ready warehouse, for sensor enumeration.

    Failure posture: an unavailable team or warehouse listing yields an empty enumeration.
    The sensor tick becomes a no-op and the next tick retries; it must never raise.
    """
    cp_rows = cp_teams.list_enabled_backfills()
    if cp_rows is None:
        logger.warning("duckgres_team_state_cp_unavailable", call_site=call_site)
        return []
    return [_to_membership(row) for row in sorted(cp_rows, key=lambda row: row.team_id)]
