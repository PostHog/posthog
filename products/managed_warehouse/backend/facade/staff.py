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
    "onboard_team_for_staff",
    "organization_id_for_duckgres_server",
]


def onboard_team_for_staff(
    organization_id: UUID, team_id: int, schema_name: str, *, actor_email: str, actor_distinct_id: str
) -> StaffActionOutcome:
    return StaffActions(actor_email=actor_email, actor_distinct_id=actor_distinct_id).onboard_team(
        organization_id, team_id, schema_name
    )


def deprovision_for_staff(organization_id: UUID, *, actor_email: str, actor_distinct_id: str) -> StaffActionOutcome:
    return StaffActions(actor_email=actor_email, actor_distinct_id=actor_distinct_id).deprovision(organization_id)
