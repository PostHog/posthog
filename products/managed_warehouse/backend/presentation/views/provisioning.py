"""Provisioning of an organization's managed warehouse."""

from uuid import UUID

import structlog
from rest_framework import status
from rest_framework.response import Response

from . import control_plane, naming, query_sources, team_rows, teardown, warehouse_state

logger = structlog.get_logger(__name__)


def provision(
    organization_id: UUID | str,
    database_name: str | None,
    team_id: int,
    schema_name: str | None,
    require_enabled: bool = True,
    *,
    triggered_by: str,
) -> Response:
    pending_deletion = teardown._block_if_pending_deletion(organization_id)
    if pending_deletion is not None:
        return pending_deletion
    name_error = naming.validate_warehouse_name(database_name)
    if name_error:
        return Response({"error": name_error}, status=status.HTTP_400_BAD_REQUEST)
    # Validate the schema name up front: the duckling backfill setup runs best-effort after the
    # provision call, so a bad name there would be swallowed — catch it before provisioning.
    schema_name_error = team_rows._validate_schema_name(schema_name)
    if schema_name_error or schema_name is None:
        return Response({"error": schema_name_error or "schema_name is required"}, status=status.HTTP_400_BAD_REQUEST)
    source_generation = query_sources._managed_source_generation(organization_id)
    resp = control_plane._request(
        "POST",
        organization_id,
        "/provision",
        json_body={
            "database_name": database_name,
            # The provisioning team becomes the warehouse's first team: duckgres creates
            # its team row with this schema. In-product this is the calling (currently
            # active) team; in the Django admin it's the mandatory team field on the
            # provision form.
            "team_id": team_id,
            "schema_name": schema_name,
            "ducklake": {"enabled": True},
            "metadata_store": {"type": "cnpg-shard"},
            "data_store": {"type": "s3bucket"},
            # Onboarding also enrolls the org in the shared Trino cell, so Trino is
            # available as a compute engine over the same DuckLake catalog the duckgres
            # server reads. The control plane writes the opt-in row inside the provision
            # transaction and its provisioner claims the org into a cell on the next
            # reconcile. Idempotent, so re-provisioning is safe; omitting the key (the
            # behavior before this) means PG-only, which is not the same as sending
            # enabled=false — that is also a no-op, never a disable.
            "trino": {"enabled": True},
        },
        require_enabled=require_enabled,
    )
    if status.is_success(resp.status_code):
        logger.info(
            "managed_warehouse_action",
            action="provision",
            triggered_by=triggered_by,
            organization_id=str(organization_id),
            team_id=team_id,
            database_name=database_name,
            schema_name=schema_name,
        )
    if status.is_success(resp.status_code) and isinstance(resp.data, dict):
        activated_generation = query_sources._activate_managed_source_lifecycle(
            organization_id,
            expected_generation=source_generation,
        )
        if activated_generation is None:
            logger.warning(
                "Skipping stale managed warehouse provision completion",
                organization_id=str(organization_id),
                expected_generation=source_generation,
            )
            return resp
        team_rows._invalidate_team_state_cache(organization_id)
        _persist_duckgres_server(organization_id, database_name, resp.data)
        # Complete the row BEFORE registering the team: registration kicks off the
        # SQL-editor query-source setup and discovery against this row's warehouse.
        _complete_provisioning_team_row(organization_id, team_id, schema_name, require_enabled=require_enabled)
        _register_provisioning_team(organization_id, team_id, activated_generation)
        # The bucket is internal infra detail, persisted above and consumed by the
        # backfill via cp_bucket_for — not part of the UI-facing ProvisionWarehouseResponse
        # schema. Strip it so the response matches its OpenAPI contract.
        warehouse_state._strip_bucket_fields(resp.data)
    return resp


def _complete_provisioning_team_row(
    organization_id: UUID | str, team_id: int, schema_name: str, *, require_enabled: bool
) -> None:
    """Pin the first team's legacy table names onto the row duckgres just created.

    The provision body cannot carry them, so without this step the row describes the derived
    layout no data lands in yet (see onboard_team). Best-effort:
    the warehouse is already provisioned, so a transient failure must not fail the provision —
    re-running onboarding completes the row later.
    """
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
    if not status.is_success(resp.status_code):
        logger.warning(
            "Provisioned warehouse team row could not be completed with legacy table names",
            organization_id=str(organization_id),
            team_id=team_id,
            status_code=resp.status_code,
        )


def _register_provisioning_team(organization_id: UUID | str, team_id: int, source_generation: int) -> None:
    """Finish the provisioning (calling) team's onboarding after its row exists.

    duckgres creates the provisioning team's row from the provision request itself (and
    `_complete_provisioning_team_row` pins its legacy table names), so nothing is written
    here. The team gets its managed SQL-editor source and starts its earliest-event-date
    sync, matching the tail that `onboard_team` runs later.

    Best-effort, mirroring `_persist_duckgres_server`: a failure is logged, not raised, so
    the one-time provision password is never lost to it.
    """
    try:
        query_sources._ensure_direct_source(team_id, organization_id, source_generation)
        team_rows._schedule_earliest_event_date_sync(team_id)
    except Exception:
        logger.exception("Failed to register provisioning team after provision", team_id=team_id)


def _persist_duckgres_server(organization_id: UUID | str, database_name: str | None, body: dict) -> None:
    """Persist the org's DuckgresServer row from a successful provision response.

    The Dagster duckling backfill connects via this row, so provisioning must leave it in
    place. The connection mirrors `_present_connection` (the SNI host + "ducklake" database);
    the password is returned only in this provision response, so it's read from `body`.

    Best-effort: a persistence failure is logged but never raised, because the provision
    password is shown to the user exactly once (here) and must not be lost to a DB hiccup —
    the row can be reconciled later from the warehouse status.
    """
    # Keep ducklake.common (and its duckdb dependency) off the API import path.
    from products.managed_warehouse.backend.facade.api import (  # noqa: PLC0415
        default_bucket_region,
        persist_duckgres_server_for_org,
    )

    # The control plane is the single owner of the bucket name — it provisions
    # the bucket, pins the name on the Duckling CR's spec.dataStore.bucketName,
    # and returns it here. Persist it verbatim; never re-derive (the old local
    # derivation drifted from the Crossplane composition and named buckets that
    # don't exist). A response without a bucket (external data store, or a CP too
    # old to return it) leaves the column unset — upsert treats None as "leave
    # unset" — and status_for()'s self-heal fills it in on the next status read.
    bucket: str | None = body.get("bucket")
    # Region from the response too when present, so a CP outside this deployment's
    # home region isn't silently mis-recorded; the fallback is the deployment's own
    # managed-warehouse region. None when there's no bucket to region.
    bucket_region: str | None = (body.get("bucket_region") or default_bucket_region()) if bucket else None

    try:
        connection = naming._present_connection({"database": database_name, "username": body.get("username", "root")})
        persist_duckgres_server_for_org(
            organization_id,
            host=connection["host"],
            port=connection["port"],
            database=connection["database"],
            username=connection["username"],
            password=body.get("password", ""),
            bucket=bucket,
            bucket_region=bucket_region,
        )
    except Exception:
        logger.exception("Failed to persist DuckgresServer after provision", organization_id=str(organization_id))
