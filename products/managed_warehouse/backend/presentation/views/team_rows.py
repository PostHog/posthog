"""Reads and writes of the per-team rows the control plane holds for an organization."""

from datetime import date
from uuid import UUID

import structlog
from rest_framework import status
from rest_framework.response import Response

from . import control_plane

logger = structlog.get_logger(__name__)


def _get_project_team_row(*, organization_id: UUID | str, team_id: int) -> dict | None:
    """Fetch the org-team row Duckgres currently holds for this project, if any."""
    resp = control_plane._request("GET", organization_id, "/teams", require_enabled=False)
    if not status.is_success(resp.status_code) or not isinstance(resp.data, dict):
        raise RuntimeError("Failed to read the organization's managed warehouse team rows")
    for row in resp.data.get("teams") or []:
        if isinstance(row, dict) and _row_team_id(row) == team_id:
            return row
    return None


def _row_team_id(row: dict) -> int | None:
    """A control-plane row's team id as int, tolerating a string serialization."""
    try:
        return int(row["team_id"])
    except (KeyError, TypeError, ValueError):
        return None


def _validate_schema_name(name: str | None) -> str | None:
    """Return an error message if `name` isn't a valid duckgres schema name, else None."""
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from products.managed_warehouse.backend.facade.api import validate_schema_name  # noqa: PLC0415

    return validate_schema_name(name)


def team_backfill_state(team_id: int) -> dict[str, object]:
    """Return the calling team's duckling backfill state for the warehouse-status response."""
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from products.managed_warehouse.backend.facade.api import get_team_backfill_state  # noqa: PLC0415

    state = get_team_backfill_state(team_id)
    return {"has_backfill": state.has_backfill, "table_suffix": state.table_suffix}


def list_teams(organization_id: UUID | str, require_enabled: bool = True) -> Response:
    """List the org's duckgres team rows (schema names, legacy table names)."""
    return control_plane._request("GET", organization_id, "/teams", require_enabled=require_enabled)


def list_all_teams() -> Response:
    """List every duckgres team row across orgs (global internal endpoint).

    Backend-only: feeds the cp-mode sensor enumeration in products.managed_warehouse.backend.cp_teams,
    which is why the feature-flag gate is bypassed.
    """
    return control_plane._request("GET", "", "teams", require_enabled=False)


def create_team(
    organization_id: UUID | str,
    team_id: int,
    schema_name: str | None,
    *,
    enabled: bool | None = None,
    backfill_enabled: bool | None = None,
    events_table_name: str | None = None,
    persons_table_name: str | None = None,
    schema_data_imports_name: str | None = None,
    require_enabled: bool = True,
) -> Response:
    """Upsert a team row in the org's duckgres warehouse.

    duckgres answers 409 when the schema name is already used by another team in the org.
    Legacy table-name fields are only sent when set — leaving them NULL makes duckgres derive
    the layout (`<schema_name>.events`, `<schema_name>.persons`, `<schema_name>_data_imports.*`);
    grandfathered teams pass their explicit legacy names instead.
    """
    schema_error = _validate_schema_name(schema_name)
    if schema_error:
        return Response({"error": schema_error}, status=status.HTTP_400_BAD_REQUEST)
    body: dict = {"team_id": team_id, "schema_name": schema_name}
    optional_fields = {
        "enabled": enabled,
        "backfill_enabled": backfill_enabled,
        "events_table_name": events_table_name,
        "persons_table_name": persons_table_name,
        "schema_data_imports_name": schema_data_imports_name,
    }
    body.update({key: value for key, value in optional_fields.items() if value is not None})
    resp = control_plane._request("POST", organization_id, "/teams", json_body=body, require_enabled=require_enabled)
    if status.is_success(resp.status_code):
        _invalidate_team_state_cache(organization_id)
    return resp


def update_team(
    organization_id: UUID | str,
    team_id: int,
    *,
    require_enabled: bool = True,
    **fields: object,
) -> Response:
    """Update fields on an existing duckgres team row via the admin PUT endpoint.

    Presence-aware on the duckgres side: only the fields present in the body change, so
    callers pass exactly what they want written (e.g. just ``earliest_event_date``).
    """
    resp = control_plane._request(
        "PUT", organization_id, f"/teams/{team_id}", json_body=dict(fields), require_enabled=require_enabled
    )
    if status.is_success(resp.status_code) or resp.status_code == status.HTTP_404_NOT_FOUND:
        _invalidate_team_state_cache(organization_id)
    return resp


def push_team_earliest_event_date(organization_id: UUID | str, team_id: int, earliest: date | None) -> bool:
    """Persist a team's resolved earliest event date (incl. the no-history sentinel) onto
    its duckgres team row — the read source for the backfill sensors.

    A failure is logged and swallowed; returns True when the control plane accepted the
    value, so callers (the provisioning-time task, the full-backfill sensor) can leave
    the date unresolved and retry on a later tick.
    """
    if earliest is None:
        return False
    try:
        resp = update_team(organization_id, team_id, require_enabled=False, earliest_event_date=earliest.isoformat())
    except Exception:
        logger.exception(
            "Failed to push earliest event date to duckgres",
            organization_id=str(organization_id),
            team_id=team_id,
        )
        return False
    if not status.is_success(resp.status_code):
        logger.warning(
            "Duckgres rejected earliest event date push",
            organization_id=str(organization_id),
            team_id=team_id,
            status_code=resp.status_code,
        )
        return False
    return True


def _schedule_earliest_event_date_sync(team_id: int) -> None:
    """Dispatch the earliest-event-date resolution task for a freshly onboarded team.

    Best-effort: a dispatch failure is logged, not raised — the full-backfill sensor
    resolves the date lazily regardless.
    """
    # Keep the Celery task module (and its import graph) off the API import path; the
    # facade is the allowed boundary for presentation -> tasks.
    from products.data_warehouse.backend.facade.tasks import sync_team_earliest_event_date  # noqa: PLC0415

    try:
        sync_team_earliest_event_date.delay(team_id)
    except Exception:
        logger.exception("Failed to schedule earliest event date sync", team_id=team_id)


def delete_team(organization_id: UUID | str, team_id: int, require_enabled: bool = True) -> Response:
    """Delete a team row from the org's duckgres warehouse.

    duckgres answers 409 for the org's last team (the org must be deprovisioned or deleted
    instead).
    """
    resp = control_plane._request("DELETE", organization_id, f"/teams/{team_id}", require_enabled=require_enabled)
    if status.is_success(resp.status_code) or resp.status_code == status.HTTP_404_NOT_FOUND:
        _invalidate_team_state_cache(organization_id)
    return resp


def _invalidate_team_state_cache(organization_id: UUID | str) -> None:
    from products.managed_warehouse.backend.facade.cp_teams import invalidate_team_membership_cache  # noqa: PLC0415

    invalidate_team_membership_cache(str(organization_id))


def _legacy_table_fields(schema_name: str) -> dict:
    """The legacy suffix-derived table names to pin on a new duckgres team row.

    The duckling DAG and the v3 sink still write the suffix-derived layout
    (`posthog.events_<schema>`, `posthog_data_imports_<schema>`), so a new row pins those
    names explicitly instead of leaving duckgres to derive the future
    `<schema_name>.events` layout no data lands in yet.
    """
    return {
        "events_table_name": f"events_{schema_name}",
        "persons_table_name": f"persons_{schema_name}",
        "schema_data_imports_name": f"posthog_data_imports_{schema_name}",
    }


def _teams_from_response(resp: Response) -> list[dict] | None:
    """Extract the team rows from a list-teams response, or None when unusable."""
    if not status.is_success(resp.status_code):
        return None
    data = resp.data
    if isinstance(data, dict):
        naming_version = data.get("data_imports_table_naming_version")
        data = data.get("teams")
        if isinstance(data, list) and isinstance(naming_version, str) and naming_version:
            data = [
                {**row, "data_imports_table_naming_version": naming_version} if isinstance(row, dict) else row
                for row in data
            ]
    if not isinstance(data, list):
        return None
    return [row for row in data if isinstance(row, dict)]


def team_onboarding_state(organization_id: UUID | str, team_id: int) -> dict:
    """Resolve the calling team's duckgres onboarding state for the warehouse-status response.

    Best-effort: a status read must never 500, so a failed list-teams call degrades to the
    not-onboarded shape.
    """
    duckgres_team: dict | None = None
    try:
        teams = _teams_from_response(list_teams(organization_id, require_enabled=False))
        if teams is not None:
            duckgres_team = next((row for row in teams if _row_team_id(row) == team_id), None)
    except Exception:
        logger.exception(
            "Failed to resolve duckgres team onboarding state",
            organization_id=str(organization_id),
            team_id=team_id,
        )

    schema_name = duckgres_team.get("schema_name") if duckgres_team is not None else None
    return {"team_onboarded": duckgres_team is not None, "schema_name": schema_name}


def check_schema_name(organization_id: UUID | str, name: str | None) -> Response:
    """Check whether a schema name is free within the org's warehouse."""
    schema_error = _validate_schema_name(name)
    if schema_error:
        return Response({"error": schema_error}, status=status.HTTP_400_BAD_REQUEST)

    resp = list_teams(organization_id)
    teams = _teams_from_response(resp)
    if teams is None:
        return resp

    taken = any(row.get("schema_name") == name for row in teams)
    return Response({"name": name, "available": not taken}, status=status.HTTP_200_OK)
