"""Warehouse lifecycle actions for staff in PostHog Admin."""

from uuid import UUID

from products.managed_warehouse.backend.facade.contracts import (
    StaffActionOutcome,
    StaffProvisionPreview,
    ViewTranslationSummary,
)
from products.managed_warehouse.backend.logic.staff_actions import (
    StaffActions,
    get_duckgres_server_summary,
    organization_id_for_duckgres_server,
)
from products.managed_warehouse.backend.logic.view_translation_staff import ViewTranslationStaff

__all__ = [
    "deprovision_for_staff",
    "get_duckgres_server_summary",
    "get_view_translation_summary",
    "is_control_plane_configured",
    "onboard_team_for_staff",
    "organization_id_for_duckgres_server",
    "preview_provision_for_staff",
    "provision_for_staff",
    "retry_view_translation_for_staff",
    "start_view_translation_for_staff",
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


def preview_provision_for_staff(organization_id: UUID, team_id: int, database_name: str) -> StaffProvisionPreview:
    return StaffActions.preview_provision(organization_id, team_id, database_name)


def provision_for_staff(
    organization_id: UUID,
    team_id: int,
    database_name: str,
    schema_name: str,
    *,
    internal_only: bool,
    actor_email: str,
    actor_distinct_id: str,
) -> StaffActionOutcome:
    return StaffActions(actor_email=actor_email, actor_distinct_id=actor_distinct_id).provision(
        organization_id, team_id, database_name, schema_name, internal_only=internal_only
    )


def get_view_translation_summary(organization_id: UUID) -> ViewTranslationSummary | None:
    return ViewTranslationStaff.summary(organization_id)


def start_view_translation_for_staff(
    organization_id: UUID, saved_query_ids: list[UUID], *, actor_user_id: int
) -> StaffActionOutcome:
    return ViewTranslationStaff.start(organization_id, saved_query_ids, actor_user_id)


def retry_view_translation_for_staff(
    organization_id: UUID, job_id: UUID, saved_query_ids: list[UUID], *, actor_user_id: int
) -> StaffActionOutcome:
    return ViewTranslationStaff.retry(organization_id, job_id, saved_query_ids, actor_user_id)


def is_control_plane_configured() -> bool:
    from products.managed_warehouse.backend import trino_compile_check_run  # noqa: PLC0415 — heavy Trino compiler

    return trino_compile_check_run.is_control_plane_configured()


def start_trino_compile_check(team_id: int, *, explain: bool, limit: int | None = None) -> str:
    """Enqueue a background Trino compile check for the team and return its run id."""
    from products.managed_warehouse.backend import trino_compile_check_run  # noqa: PLC0415 — heavy Trino compiler

    return trino_compile_check_run.start_trino_compile_check(team_id, explain=explain, limit=limit)
