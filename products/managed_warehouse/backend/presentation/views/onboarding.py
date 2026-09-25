"""Onboarding of a team onto its organization's existing managed warehouse."""

from uuid import UUID

import structlog
from rest_framework import status
from rest_framework.response import Response

from . import control_plane, query_sources, team_rows, teardown

logger = structlog.get_logger(__name__)


def onboard_team(
    organization_id: UUID | str,
    team_id: int,
    schema_name: str | None,
    require_enabled: bool = True,
    *,
    triggered_by: str,
) -> Response:
    """Onboard a team onto the org's existing managed warehouse with its own schema.

    The duckgres control plane owns per-team state: it enforces schema uniqueness across
    the org's teams (409 on a conflict, mapped to a user-facing message here) and stores
    the row the backfill sensors and the v3 sink read.

    The schema name is write-once: it names the team's warehouse tables, so changing it
    after data is written would split the team's data across two layouts. The control-plane
    POST is an upsert, so an already-onboarded team is guarded here — re-onboarding with
    the current name is an idempotent no-op, any other name is rejected.

    Backend/ops callers (the Django admin) pass `require_enabled=False` to bypass the
    org feature-flag gate.
    """
    pending_deletion = teardown._block_if_pending_deletion(organization_id)
    if pending_deletion is not None:
        return pending_deletion
    if require_enabled and not control_plane.is_enabled(organization_id):
        return Response({"error": "This feature is not enabled"}, status=status.HTTP_403_FORBIDDEN)
    schema_error = team_rows._validate_schema_name(schema_name)
    if schema_error or schema_name is None:
        return Response({"error": schema_error or "schema_name is required"}, status=status.HTTP_400_BAD_REQUEST)
    if not _org_has_warehouse(organization_id):
        return Response(
            {"error": "No managed warehouse is provisioned for this organization. Provision one first."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    source_generation = query_sources._active_managed_source_generation(organization_id)
    if source_generation is None:
        return Response(
            {"error": "No managed warehouse is provisioned for this organization. Provision one first."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        existing = team_rows._get_project_team_row(organization_id=organization_id, team_id=team_id)
    except RuntimeError:
        return Response(
            {"error": "Could not read the organization's managed warehouse state. Try again in a few minutes."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    if existing is not None:
        if existing.get("schema_name") != schema_name:
            events_table = existing.get("events_table_name") or f"events_{existing.get('schema_name')}"
            current = "the shared tables" if events_table == "events" else events_table
            return Response(
                {
                    "error": f"This project already writes to {current}, and its warehouse table can't be changed — "
                    "that would split its existing data across two tables."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
    else:
        # Pin the legacy table names the duckling DAG writes today (posthog.events_<suffix>,
        # posthog_data_imports_<suffix>): the suffix for a newly onboarded team IS its schema
        # name. A row without them describes the derived layout no data lands in yet (the EU
        # placeholder-row bug). Drop this once the duckling DAG writes the derived
        # <schema_name>.events layout for real.
        legacy = team_rows._legacy_table_fields(schema_name)
        resp = team_rows.create_team(
            organization_id,
            team_id,
            schema_name,
            events_table_name=legacy["events_table_name"],
            persons_table_name=legacy["persons_table_name"],
            schema_data_imports_name=legacy["schema_data_imports_name"],
            require_enabled=require_enabled,
        )
        if resp.status_code == status.HTTP_409_CONFLICT:
            return Response(
                {"error": f"The schema name '{schema_name}' is already used by another project in this organization."},
                status=status.HTTP_409_CONFLICT,
            )
        if not status.is_success(resp.status_code):
            return resp

    logger.info(
        "managed_warehouse_action",
        action="onboard_team",
        triggered_by=triggered_by,
        organization_id=str(organization_id),
        team_id=team_id,
        schema_name=schema_name,
        created=existing is None,
    )
    query_sources._ensure_direct_source(team_id, organization_id, source_generation)
    team_rows._schedule_earliest_event_date_sync(team_id)
    return Response({"onboarded": True, "schema_name": schema_name}, status=status.HTTP_200_OK)


def _org_has_warehouse(organization_id: UUID | str) -> bool:
    """Whether the org has a provisioned managed warehouse (its connection row exists)."""
    from products.managed_warehouse.backend.facade.api import has_provisioned_warehouse  # noqa: PLC0415

    return has_provisioned_warehouse(organization_id)
