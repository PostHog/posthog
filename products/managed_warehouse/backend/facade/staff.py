"""Warehouse lifecycle actions for staff in PostHog Admin."""

from uuid import UUID

from products.managed_warehouse.backend.facade.contracts import StaffActionOutcome
from products.managed_warehouse.backend.logic.staff_actions import (
    StaffActions,
    get_duckgres_server_summary,
    organization_id_for_duckgres_server,
)

__all__ = [
    "deprovision_for_staff",
    "get_duckgres_server_summary",
    "is_control_plane_configured",
    "onboard_team_for_staff",
    "organization_id_for_duckgres_server",
    "start_trino_compile_check",
]


def onboard_team_for_staff(
    organization_id: UUID, team_id: int, schema_name: str, *, actor_email: str, actor_distinct_id: str
) -> StaffActionOutcome:
    return StaffActions(actor_email=actor_email, actor_distinct_id=actor_distinct_id).onboard_team(
        organization_id, team_id, schema_name
    )


def deprovision_for_staff(organization_id: UUID, *, actor_email: str, actor_distinct_id: str) -> StaffActionOutcome:
    return StaffActions(actor_email=actor_email, actor_distinct_id=actor_distinct_id).deprovision(organization_id)


def is_control_plane_configured() -> bool:
    from products.managed_warehouse.backend import trino_compile_check_run  # noqa: PLC0415 — heavy Trino compiler

    return trino_compile_check_run.is_control_plane_configured()


def start_trino_compile_check(team_id: int, *, explain: bool, limit: int | None = None) -> str:
    """Enqueue a background Trino compile check for the team and return its run id."""
    from products.managed_warehouse.backend import trino_compile_check_run  # noqa: PLC0415 — heavy Trino compiler

    return trino_compile_check_run.start_trino_compile_check(team_id, explain=explain, limit=limit)
