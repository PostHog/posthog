"""Warehouse status, monitoring, and control-plane bucket reconciliation."""

from typing import Literal
from uuid import UUID

import structlog
from rest_framework.response import Response

from . import control_plane, naming

logger = structlog.get_logger(__name__)


ManagedWarehouseMonitoringMetric = Literal[
    "query_rate",
    "error_ratio",
    "duration_p50",
    "duration_p95",
    "sessions_active",
    "s3_bytes_rate",
    "acquire_p95",
    "acquire_by_source",
    "storage_bytes",
    "worker_crash_rate",
]

ManagedWarehouseMonitoringWindow = Literal["1h", "6h", "24h", "7d", "30d"]


def _strip_bucket_fields(body: dict) -> None:
    """Drop the internal bucket fields from a UI-facing response body, in place."""
    body.pop("bucket", None)
    body.pop("bucket_region", None)


def status_for(organization_id: UUID | str) -> Response:
    resp = control_plane._request("GET", organization_id, "/warehouse/status")
    if resp.status_code == 200 and isinstance(resp.data, dict):
        # Self-heal: the control plane is the authoritative source of the per-org
        # bucket name. If the stored DuckgresServer row disagrees — NULL (row
        # created before the CP returned it) or a stale locally-derived name — fix
        # it here so the value converges on every status read without a separate
        # backfill job. The UI reads status when viewing a warehouse, so a deploy
        # heals each org the first time its status is fetched.
        _reconcile_bucket_from_status(organization_id, resp.data)
        if isinstance(resp.data.get("connection"), dict):
            resp.data["connection"] = naming._present_connection(resp.data["connection"])
        # Internal infra detail — reconciled above, not part of the UI-facing
        # WarehouseStatusResponse schema. Backend callers use cp_bucket_for instead.
        _strip_bucket_fields(resp.data)
    return resp


def monitoring_snapshot_for(organization_id: UUID | str) -> Response:
    """Fetch tenant-safe live monitoring data for one organization."""
    return control_plane._request("GET", organization_id, "/monitoring/snapshot", timeout=10)


def monitoring_series_for(
    organization_id: UUID | str,
    metric: ManagedWarehouseMonitoringMetric,
    window: ManagedWarehouseMonitoringWindow,
) -> Response:
    """Fetch one allow-listed monitoring series for one organization."""
    return control_plane._request(
        "GET",
        organization_id,
        "/monitoring/series",
        params={"metric": metric, "window": window},
        timeout=10,
    )


def cp_bucket_for(organization_id: UUID | str) -> str | None:
    """Authoritative S3 bucket for the org's duckling, straight from the control plane.

    For backend/background callers (the Dagster duckling backfill), not the UI. Unlike
    `status_for` it:
      - bypasses the user-facing feature-flag gate (`require_enabled=False`), so a Dagster
        worker without the flag loaded locally doesn't get a spurious 403; and
      - returns the bucket only when the status body's own `org_id` matches the org asked
        about, so a CP bug or misrouted proxy can never hand back another tenant's bucket.

    Also reconciles the stored `DuckgresServer` row so it converges for next time. Returns
    None when the control plane is unreachable, unconfigured, or names no bucket.
    """
    resp = control_plane._request("GET", organization_id, "/warehouse/status", require_enabled=False)
    if resp.status_code != 200 or not isinstance(resp.data, dict):
        return None

    response_org = resp.data.get("org_id")
    if response_org is not None and str(response_org) != str(organization_id):
        logger.warning(
            "Refusing to use control-plane bucket: status org_id mismatch",
            requested_organization_id=str(organization_id),
            response_org_id=str(response_org),
        )
        return None

    _reconcile_bucket_from_status(organization_id, resp.data)
    return resp.data.get("bucket") or None


def _reconcile_bucket_from_status(organization_id: UUID | str, body: dict) -> None:
    """Converge DuckgresServer.bucket/bucket_region onto the control-plane-reported values.

    Best-effort and side-effect-only: a single UPDATE touching only rows where the
    bucket OR the region differs (no fetch, no create). A DB hiccup is swallowed — it
    must never fail the status read it piggybacks on.
    """
    # Defense-in-depth: the request is per-org (the URL carries the org id), but
    # only write back when the response's own org_id agrees with the one we asked
    # about. A mismatch (CP bug, misrouted proxy) must never let one tenant's
    # status overwrite another's bucket mapping — that would redirect backfill
    # reads/writes to the wrong S3 bucket.
    response_org = body.get("org_id")
    if response_org is not None and str(response_org) != str(organization_id):
        logger.warning(
            "Refusing to reconcile DuckgresServer bucket: status org_id mismatch",
            requested_organization_id=str(organization_id),
            response_org_id=str(response_org),
        )
        return

    bucket = body.get("bucket")
    if not bucket:
        # External data stores / not-yet-backfilled ducklings report no bucket —
        # nothing authoritative to copy.
        return
    from products.managed_warehouse.backend.facade.api import (  # noqa: PLC0415
        default_bucket_region,
        reconcile_stored_bucket_config,
    )

    bucket_region = body.get("bucket_region") or default_bucket_region()
    try:
        updated = reconcile_stored_bucket_config(
            organization_id,
            bucket=bucket,
            bucket_region=bucket_region,
        )
        if updated:
            logger.info(
                "duckgres_server_bucket_reconciled_from_status",
                organization_id=str(organization_id),
                bucket=bucket,
            )
    except Exception:
        logger.exception(
            "Failed to reconcile DuckgresServer bucket from status",
            organization_id=str(organization_id),
        )
