"""Expose a managed Duckgres warehouse in the SQL editor as a Postgres connection.

Each member team gets a Postgres ``ExternalDataSource`` fed by the duckgres control
plane: a per-team credential is minted at provision time
(``mint_service_credential`` — the canonical ``posthog_team_<id>_rw`` project_user
login) and snapshotted into the source's ``job_inputs`` together with the mint's
``connect`` block (host, port, database). Nothing on this path reads the
``DuckgresServer`` row or its org root credential. The stored credential is
long-lived state (``ExternalDataSource``'s model — the CP can be asked to rotate
it), so minting uses ``force_rotate=True``: the source holds no prior credential
when it is (re)written. Setup happens in two steps:

1. ``ensure_managed_warehouse_direct_source`` creates the source row when a team
   joins, so the connection appears immediately.
2. ``reconcile_managed_warehouse_tables`` runs once the warehouse is ready and records
   every non-internal schema/table the credential can see.

This bypasses the user-facing create endpoint because the managed host is internal
infrastructure and is not reachable for live schema validation during provisioning.

Lifecycle is org-level only: ``soft_delete_managed_warehouse_sources`` handles
deprovisioning of the whole warehouse. There is no per-team offboarding flow yet —
a single team leaving keeps its connection until the org deprovisions (revisit if
per-team removal becomes a product flow).
"""

from __future__ import annotations

from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog
from rest_framework import status

from posthog.models.team.team import Team

from products.data_warehouse.backend.facade.api import reconcile_postgres_schemas
from products.managed_warehouse.backend.common import _log_duckgres_server_access
from products.managed_warehouse.backend.facade.contracts import ServiceCredential
from products.managed_warehouse.backend.models import DuckgresServer
from products.managed_warehouse.backend.service_credentials import mint_service_credential
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

MANAGED_WAREHOUSE_SOURCE_DESCRIPTION = "Managed warehouse (auto-provisioned)"

# Principal stamped on the provision-time mint, so CP audit logs and credential listings
# attribute these stored grants to the SQL-editor direct-source setup flow.
MANAGED_WAREHOUSE_DIRECT_SOURCE_PRINCIPAL = "managed-warehouse:direct-source-setup"

# Database engine internals — never warehouse data. Sidebar hygiene, not permissioning:
# the minted project_user login's schema grants already bound the catalog, and this
# denylist is the only filter on what the discover sweep registers. The later per-schema
# visibility control plugs in here.
INTERNAL_SCHEMAS = frozenset({"pg_catalog", "information_schema", "pg_toast", "system"})


def internal_schemas() -> set[str]:
    """The schemas the discover sweep must never register as warehouse tables."""
    return set(INTERNAL_SCHEMAS)


def _managed_source_queryset(team_id: int) -> QuerySet[ExternalDataSource]:
    return ExternalDataSource._base_manager.filter(
        team_id=team_id,
        source_type=ExternalDataSourceType.POSTGRES,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        connection_metadata__system_managed=True,
    )


def _mint_direct_source_credential(*, organization_id: str | UUID, team_id: int) -> ServiceCredential:
    """Mint the team's stored provision-time credential for its SQL-editor source.

    The source snapshots the credential into ``job_inputs`` long-term
    (``ExternalDataSource``'s model), so ``force_rotate=True`` is right: the source
    holds no prior credential when (re)written, and the CP's rotation IS the expiry
    mechanism. Raises ``ServiceCredentialUnavailable`` on any CP failure — callers
    stay best-effort.
    """
    return mint_service_credential(
        str(organization_id),
        team_id,
        principal=MANAGED_WAREHOUSE_DIRECT_SOURCE_PRINCIPAL,
        force_rotate=True,
    )


def _source_config(credential: ServiceCredential) -> dict[str, object]:
    """Snapshot the minted credential and its CP-issued connect block into job_inputs."""
    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    return source_impl.parse_config(
        {
            "host": credential.connect.host,
            "port": credential.connect.port,
            "database": credential.connect.database,
            "user": credential.username,
            "password": credential.password,
        }
    ).to_dict()


def _ensure_managed_source_locked(*, team_id: int, credential: ServiceCredential) -> ExternalDataSource:
    # Deliberately includes soft-deleted rows: a re-enabled membership revives its
    # tombstoned source.
    existing = _managed_source_queryset(team_id).select_for_update().order_by("-created_at").first()

    config = _source_config(credential)
    if existing is not None:
        update_fields: list[str] = []
        connection_metadata = dict(existing.connection_metadata or {})
        if connection_metadata.get("credential_kind") not in ("org_root", "project_reader"):
            # Old managed sources predate the project-reader credential boundary, so
            # discard any catalog entries discovered before Duckgres enforced it.
            now = timezone.now()
            DataWarehouseTable.raw_objects.filter(
                team_id=team_id, external_data_source_id=existing.id, deleted=False
            ).update(deleted=True, deleted_at=now, updated_at=now)
            ExternalDataSchema.objects.filter(team_id=team_id, source_id=existing.id).delete()
        if existing.job_inputs != config:
            existing.job_inputs = config
            update_fields.append("job_inputs")
        if existing.access_method != ExternalDataSource.AccessMethod.DIRECT:
            existing.access_method = ExternalDataSource.AccessMethod.DIRECT
            update_fields.append("access_method")
        if not existing.direct_query_enabled:
            existing.direct_query_enabled = True
            update_fields.append("direct_query_enabled")
        if (
            connection_metadata.get("engine") != "duckdb"
            or connection_metadata.get("system_managed") is not True
            or connection_metadata.get("credential_kind") != "org_root"
        ):
            migrated = {
                **connection_metadata,
                "engine": "duckdb",
                "system_managed": True,
                "credential_kind": "org_root",
            }
            migrated.pop("reader_configured", None)
            existing.connection_metadata = migrated
            update_fields.append("connection_metadata")
        if existing.deleted:
            existing.deleted = False
            existing.deleted_at = None
            update_fields.extend(["deleted", "deleted_at"])
        if update_fields:
            existing.save(update_fields=[*update_fields, "updated_at"])
        return existing

    return ExternalDataSource.objects.create(
        source_id=str(uuid4()),
        connection_id=str(uuid4()),
        destination_id=str(uuid4()),
        team_id=team_id,
        status=ExternalDataSource.Status.RUNNING,
        source_type=ExternalDataSourceType.POSTGRES,
        job_inputs=config,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        description=MANAGED_WAREHOUSE_SOURCE_DESCRIPTION,
        access_method=ExternalDataSource.AccessMethod.DIRECT,
        created_via=ExternalDataSource.CreatedVia.WEB,
        direct_query_enabled=True,
        connection_metadata={
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": "org_root",
        },
    )


def ensure_managed_warehouse_direct_source(*, team_id: int, organization_id: str | UUID) -> ExternalDataSource:
    """Create or refresh the team's managed-warehouse query source from a CP-minted credential.

    Raises ``Team.DoesNotExist`` when the team is not (or no longer) in this organization
    and ``ServiceCredentialUnavailable`` when the control plane cannot issue the
    credential — both stay best-effort for the caller, which logs and moves on. There is
    deliberately no fallback to Django state: the CP is the only authority for the
    credential and its dial target.
    """
    # Mint FIRST — before any write: a CP failure must abort the setup before a row is
    # created or refreshed (no half-written source), and no credential string ever sits
    # inside an open Postgres transaction (the mint fans out over HTTP).
    credential = _mint_direct_source_credential(organization_id=organization_id, team_id=team_id)
    with transaction.atomic():
        Team.objects.select_for_update().only("id").get(id=team_id, organization_id=organization_id)
        return _ensure_managed_source_locked(team_id=team_id, credential=credential)


def _cp_warehouse_exists(organization_id: str | UUID) -> bool:
    """Whether the control plane still holds a live warehouse for this organization.

    Replaces the ``DuckgresServer`` row-existence oracle on the reconcile path with a
    probe of the same ``GET /warehouse/status`` accessor the deprovision and status
    views use. Fail-CLOSED on ambiguity:

    - 404, 409, or a 2xx body whose ``state`` is not a known live one (absent/"deleted"/
      unparseable) ⇒ the warehouse is gone (or going) ⇒ ``False``.
    - Any other non-2xx, an unreachable CP, or an unconfigured provisioning API ⇒ the CP
      cannot confirm either way ⇒ ``False`` here too (don't revive); the miss is logged
      and the next status read reconciles.
    """
    from products.managed_warehouse.backend.presentation.views import _request  # noqa: PLC0415

    org_id = str(organization_id)
    try:
        resp = _request("GET", organization_id, "/warehouse/status", require_enabled=False)
    except Exception:
        # Fail-closed: an unreachable CP must never revive a tombstoned source; a later
        # sweep re-probes when the control plane is back.
        logger.exception(
            "Managed warehouse status probe failed; treating as deprovisioned for this sweep",
            organization_id=org_id,
        )
        return False
    if status.is_success(resp.status_code):
        state = resp.data.get("state") if isinstance(resp.data, dict) else None
        exists = state in ("provisioning", "ready")
        if not exists:
            logger.info(
                "Managed warehouse reports no live state; treating as deprovisioned",
                organization_id=org_id,
                state=state,
            )
        return exists
    if resp.status_code in (status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT):
        # Unknown to the CP, or teardown already underway/finished — the same two codes
        # the deprovision path treats as converged.
        logger.info(
            "Managed warehouse unknown to the control plane; treating as deprovisioned",
            organization_id=org_id,
            status_code=resp.status_code,
        )
        return False
    # 5xx / unconfigured / anything else: the CP cannot confirm liveness — fail closed.
    logger.warning(
        "Managed warehouse status probe inconclusive; treating as deprovisioned for this sweep",
        organization_id=org_id,
        status_code=resp.status_code,
    )
    return False


def reconcile_managed_warehouse_tables(*, team_id: int, organization_id: str | UUID) -> None:
    """Discover and register the org-wide managed-warehouse catalog for this team's source."""
    with transaction.atomic():
        # Check before ensure: a tombstoned source means the warehouse was deprovisioned,
        # and nothing may revive it — otherwise this sweep would resurrect sources right
        # after deprovision.
        if _managed_source_queryset(team_id).filter(deleted=True).exists():
            return

        # The control plane, not the DuckgresServer row, is the existence oracle: only a
        # CP-confirmed live warehouse gets its source (re)created or introspected.
        if not _cp_warehouse_exists(organization_id):
            return

        team = Team.objects.select_for_update().only("id").filter(id=team_id, organization_id=organization_id).first()
        if team is None:
            return

    ensure_managed_warehouse_direct_source(team_id=team_id, organization_id=organization_id)

    with transaction.atomic():
        team = Team.objects.select_for_update().only("id").filter(id=team_id, organization_id=organization_id).first()
        if team is None:
            return

        source = _managed_source_queryset(team_id).select_for_update().filter(deleted=False).first()
        if source is None:
            return
        source_id = source.id
        source_config = dict(source.job_inputs or {})
        source_api_version = source.api_version

    excluded_schemas = internal_schemas()

    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    config = source_impl.parse_config(source_config)
    try:
        discovered = source_impl.get_schemas(
            config, team_id, api_version=source_impl.resolve_api_version(source_api_version)
        )
    except Exception:
        # A provisioning or briefly unreachable warehouse fails here on every periodic sweep;
        # skip and let the next run retry rather than surfacing a task error each time.
        logger.warning("Managed warehouse introspection failed; will retry", team_id=team_id, exc_info=True)
        return
    source_schemas = [schema for schema in discovered if (schema.source_schema or "") not in excluded_schemas]
    if not source_schemas:
        return

    with transaction.atomic():
        # Revalidate after live introspection so deprovision wins the race.
        team = Team.objects.select_for_update().only("id").filter(id=team_id, organization_id=organization_id).first()
        if team is None:
            return
        source = (
            _managed_source_queryset(team_id)
            .select_for_update()
            .filter(
                id=source_id,
                deleted=False,
                access_method=ExternalDataSource.AccessMethod.DIRECT,
                direct_query_enabled=True,
            )
            .first()
        )
        if source is None:
            return

        for schema in source_schemas:
            schema_model, _created = ExternalDataSchema.objects.get_or_create(
                team_id=team_id,
                source=source,
                name=schema.name,
                defaults={"should_sync": True, "sync_type": None, "sync_type_config": {}},
            )
            if schema_model.deleted:
                schema_model.deleted = False
                schema_model.deleted_at = None
                schema_model.should_sync = True
                schema_model.save(update_fields=["deleted", "deleted_at", "should_sync", "updated_at"])

        reconcile_postgres_schemas(source=source, source_schemas=source_schemas, team_id=team_id)


def _managed_sources_for_org(organization_id: str | UUID) -> QuerySet[ExternalDataSource]:
    return ExternalDataSource._base_manager.filter(
        team__organization_id=organization_id,
        source_type=ExternalDataSourceType.POSTGRES,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        connection_metadata__system_managed=True,
    ).exclude(deleted=True)


def update_managed_warehouse_root_password(*, organization_id: str | UUID, password: str) -> None:
    """Rotate the root password on the server row and every managed source of the org.

    Each source snapshots the root credential into its ``job_inputs``, so a rotation must
    fan out to all of them in the same transaction — otherwise every source holds a stale
    password and fails silently.
    """
    with transaction.atomic():
        _log_duckgres_server_access("connection.update_managed_warehouse_root_password:write", str(organization_id))
        server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
        server.password = password
        server.save(update_fields=["password", "updated_at"])

        config = (
            SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
            .parse_config(
                {
                    "host": server.host,
                    "port": server.port,
                    "database": server.database,
                    "user": server.username,
                    "password": server.password,
                }
            )
            .to_dict()
        )
        for source in _managed_sources_for_org(organization_id).select_for_update().order_by("team_id"):
            if source.job_inputs != config:
                source.job_inputs = config
                source.save(update_fields=["job_inputs", "updated_at"])


def soft_delete_managed_warehouse_sources(*, organization_id: str | UUID) -> None:
    """Atomically tombstone the organization's managed query sources on deprovision.

    Per-team state needs no disabling here: deprovisioning removes the org's team rows
    from the duckgres control plane, which is the read source for membership.
    """
    now = timezone.now()
    with transaction.atomic():
        _log_duckgres_server_access("connection.soft_delete_managed_warehouse_sources", str(organization_id))
        DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
        sources = list(_managed_sources_for_org(organization_id).select_for_update().order_by("team_id"))
        DataWarehouseTable.raw_objects.filter(
            external_data_source_id__in=[source.id for source in sources], deleted=False
        ).update(deleted=True, deleted_at=now, updated_at=now)
        for source in sources:
            source.deleted = True
            source.deleted_at = now
            source.save(update_fields=["deleted", "deleted_at", "updated_at"])
