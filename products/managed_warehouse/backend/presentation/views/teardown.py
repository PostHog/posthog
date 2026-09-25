"""Deprovisioning, organization and team deletion, and the pending-deletion guard."""

from uuid import UUID

import structlog
from rest_framework import status
from rest_framework.response import Response

from . import control_plane, query_sources, team_rows

logger = structlog.get_logger(__name__)


def _block_if_pending_deletion(organization_id: UUID | str) -> Response | None:
    """Refuse warehouse-creating calls for an organization whose deletion is underway.

    Organization deletion is asynchronous: ``perform_destroy`` marks the org
    ``is_pending_deletion`` and hands off to the Temporal workflow, whose first step
    deprovisions the org's managed warehouse. API-key routes bypass the UI's
    pending-deletion lockout, so without this guard a caller could provision a NEW
    warehouse (or add a team row) after that deprovision step and before the org cascade —
    recreating exactly the orphaned-warehouse hole the workflow closes (the fresh
    ``DuckgresServer`` row is cascade-deleted without ever being deprovisioned). Every
    entrypoint that can create duckgres state calls this first; read-only endpoints stay
    accessible.
    """
    from products.managed_warehouse.backend.facade.api import organization_is_pending_deletion  # noqa: PLC0415

    if organization_is_pending_deletion(organization_id):
        return Response(
            {"error": "This organization is pending deletion; its managed warehouse can no longer be modified."},
            status=status.HTTP_409_CONFLICT,
        )
    return None


def block_team_deletion(team_id: int, organization_id: UUID | str) -> str | None:
    """Remove the team from the org's duckgres warehouse ahead of a Django team deletion.

    Returns a user-facing error message when the deletion must be blocked, else None.
    Narrow coupling: orgs without a managed warehouse never trigger a control-plane call, so
    unrelated team deletions are unaffected by a duckgres outage.

    duckgres refuses to delete the org's last team (409) — the warehouse must be deprovisioned
    (or the organization deleted) first, so the Django deletion is blocked with that guidance.
    When the control plane can't confirm the deletion for a team that is warehouse-onboarded,
    the deletion is blocked with a retry error rather than silently orphaning the duckgres row.
    """
    from products.managed_warehouse.backend.facade.api import has_provisioned_warehouse  # noqa: PLC0415
    from products.managed_warehouse.backend.facade.team_state import backfill_row_exists  # noqa: PLC0415

    if not has_provisioned_warehouse(organization_id):
        return None

    resp = team_rows.delete_team(organization_id, team_id, require_enabled=False)
    if status.is_success(resp.status_code) or resp.status_code == status.HTTP_404_NOT_FOUND:
        return None
    if resp.status_code == status.HTTP_409_CONFLICT:
        return (
            "This is the last project in your organization's managed warehouse. "
            "Deprovision the managed warehouse in Data ops settings, or delete the organization, "
            "before deleting this project."
        )
    if backfill_row_exists(team_id, str(organization_id)):
        return "Could not remove this project from your organization's managed warehouse. Try again in a few minutes."
    # Org has a warehouse but this team has no membership row: almost certainly not
    # onboarded, so a control-plane hiccup must not block its deletion. If a duckgres-only
    # row does exist it is orphaned here, which the control plane tolerates.
    logger.warning(
        "Proceeding with team deletion despite duckgres delete-team failure",
        organization_id=str(organization_id),
        team_id=team_id,
        status_code=resp.status_code,
    )
    return None


def deprovision(organization_id: UUID | str, require_enabled: bool = True, *, triggered_by: str) -> Response:
    expected_generation = query_sources._active_managed_source_generation(organization_id)
    inactive_cleanup_generation = (
        query_sources._managed_source_generation(organization_id) if expected_generation is None else None
    )
    resp = control_plane._request("POST", organization_id, "/deprovision", require_enabled=require_enabled)
    control_plane_converged = status.is_success(resp.status_code) or resp.status_code == status.HTTP_404_NOT_FOUND
    if not control_plane_converged and (
        resp.status_code == status.HTTP_409_CONFLICT or resp.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR
    ):
        status_response = control_plane._request(
            "GET",
            organization_id,
            "/warehouse/status",
            require_enabled=False,
        )
        control_plane_converged = status_response.status_code == status.HTTP_404_NOT_FOUND or (
            status_response.status_code == status.HTTP_200_OK
            and isinstance(status_response.data, dict)
            and status_response.data.get("state") in {"deleting", "deleted"}
        )
    if not control_plane_converged:
        return resp
    converged_response = (
        resp
        if status.is_success(resp.status_code)
        else Response({"status": "deprovisioning started"}, status=status.HTTP_202_ACCEPTED)
    )
    logger.info(
        "managed_warehouse_action",
        action="deprovision",
        triggered_by=triggered_by,
        organization_id=str(organization_id),
        status_code=resp.status_code,
    )
    team_rows._invalidate_team_state_cache(organization_id)
    cleanup_generation = inactive_cleanup_generation
    if expected_generation is not None:
        try:
            cleanup_generation = query_sources._deactivate_managed_source_lifecycle(
                organization_id,
                expected_generation=expected_generation,
            )
        except Exception:
            logger.exception("Failed to record managed warehouse deprovision", organization_id=str(organization_id))
            return Response(
                {
                    "error": "The warehouse accepted deprovisioning, but its local SQL connection state was not updated. Retry deprovisioning."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    if cleanup_generation is None:
        return converged_response
    try:
        query_sources._remove_direct_connection_sources(organization_id, cleanup_generation)
    except Exception:
        logger.exception("Failed to remove managed warehouse query sources", organization_id=str(organization_id))
        try:
            query_sources._schedule_remove_direct_connection_sources(organization_id, cleanup_generation)
        except Exception:
            logger.exception(
                "Failed to schedule managed warehouse query source removal",
                organization_id=str(organization_id),
            )
            return Response(
                {
                    "error": "The warehouse was deprovisioned but its SQL connections could not be removed or scheduled for removal. They must be cleaned up manually."
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
    return converged_response


def deprovision_for_org_deletion(organization_id: UUID | str) -> None:
    """Deprovision the org's managed warehouse ahead of an organization deletion.

    Called from the organization-deletion Temporal workflow while the ``DuckgresServer``
    row still exists (the Django cascade destroys it with the org). Without this call the
    duckgres warehouse outlives the organization fully alive: external writers keep
    ingesting into it, storage keeps being metered, and its credentials stay valid — while
    the Django pointer to it is gone.

    No-op for orgs without a managed warehouse (mirrors ``block_team_deletion``'s gating,
    so unrelated org deletions never touch the control plane). Idempotent against
    duckgres: 404 means the warehouse is absent. A repeated deprovision that returns 409
    is normalized to 202 only after status reports ``deleting`` or ``deleted``. Any
    other failure raises so the Temporal activity retries: the org-record deletion (whose
    cascade drops the ``DuckgresServer`` pointer) is conditional on this call being
    accepted, so a persistent duckgres outage stalls the deletion workflow — visibly, and
    resumable once the control plane is reachable — instead of orphaning a live warehouse
    with no pointer left for any later cleanup.
    """
    from products.managed_warehouse.backend.facade.api import has_provisioned_warehouse  # noqa: PLC0415

    org_id = str(organization_id)
    if not has_provisioned_warehouse(organization_id):
        return

    # Backend caller: bypass the user-facing feature flag so the deletion never depends on
    # flag evaluation on the Temporal worker.
    resp = deprovision(organization_id, require_enabled=False, triggered_by="system:organization-deletion")
    if status.is_success(resp.status_code):
        return
    if resp.status_code == status.HTTP_404_NOT_FOUND:
        logger.info(
            "Managed warehouse already deprovisioned or unknown to duckgres; continuing organization deletion",
            organization_id=org_id,
            status_code=resp.status_code,
        )
        return
    if resp.status_code == status.HTTP_501_NOT_IMPLEMENTED:
        # DUCKGRES_API_URL is not configured (e.g. a dev/env-var-backed DuckgresServer
        # row): there is no control plane to deprovision against.
        logger.warning(
            "Managed warehouse deprovisioning skipped: provisioning API not configured",
            organization_id=org_id,
        )
        return
    raise RuntimeError(
        f"duckgres deprovision failed with status {resp.status_code} for organization {org_id}; "
        "the org's managed warehouse must be deprovisioned before the Django cascade drops its pointer"
    )


def delete_org(organization_id: UUID | str, require_enabled: bool = True, *, triggered_by: str) -> Response:
    """Delete the org's provisioning record once teardown has finished, freeing its warehouse name.

    `deprovision` tears the warehouse down (status goes deleting → deleted); this removes the
    now-empty org row from the control plane so its `database_name` can be reused. Deprovision
    teardown has no terminal failed state (the provisioner retries indefinitely), so callers
    should only issue this once the warehouse status reports `deleted`.
    """
    resp = control_plane._request("DELETE", organization_id, "", require_enabled=require_enabled)
    if status.is_success(resp.status_code):
        logger.info(
            "managed_warehouse_action",
            action="delete_org",
            triggered_by=triggered_by,
            organization_id=str(organization_id),
        )
    return resp
