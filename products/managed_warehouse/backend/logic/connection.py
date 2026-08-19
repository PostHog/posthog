"""Expose a managed Duckgres warehouse in the SQL editor as a Postgres connection.

Each enrolled team keeps its auto-provisioned external source backed by the stored server
login. If a confirmed ``project_reader`` source also exists, it has an independent catalog.
This module does not create, replace, or rotate project readers.

This bypasses the user-facing create endpoint because the managed host is internal
infrastructure and is not reachable for live schema validation during provisioning.

``soft_delete_managed_warehouse_sources`` handles deprovisioning of the whole warehouse.
Deleting a team removes its project-scoped source through the existing model cascade.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog

from posthog.models.team.team import Team

from products.data_warehouse.backend.facade.api import reconcile_postgres_schemas
from products.managed_warehouse.backend.models import DuckgresServer
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_LEGACY_CREDENTIAL_KINDS,
    MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND,
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType, ManagedWarehouseSQLMode

logger = structlog.get_logger(__name__)

MANAGED_WAREHOUSE_SOURCE_DESCRIPTION = "Managed warehouse (auto-provisioned)"

# Database engine internals — never warehouse data. Sidebar hygiene, not permissioning:
# The discovery login may expose engine internals, so this denylist keeps them out of the sidebar.
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


def _source_config(server: DuckgresServer) -> dict[str, object]:
    """Snapshot the stored server login into the source's job_inputs."""
    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    return source_impl.parse_config(
        {
            "host": server.host,
            "port": server.port,
            "database": server.database,
            "user": server.username,
            "password": server.password,
        }
    ).to_dict()


def _is_project_reader_source(source: ExternalDataSource) -> bool:
    metadata = source.connection_metadata
    return (
        isinstance(metadata, dict)
        and metadata.get("credential_kind") == MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND
    )


def _ensure_stored_login_source_locked(*, team_id: int, server: DuckgresServer) -> ExternalDataSource:
    existing = next(
        (
            source
            for source in _managed_source_queryset(team_id).select_for_update().order_by("deleted", "-created_at")
            if not _is_project_reader_source(source)
        ),
        None,
    )

    config = _source_config(server)
    if existing is not None:
        update_fields: list[str] = []
        connection_metadata = dict(existing.connection_metadata or {})
        if connection_metadata.get("credential_kind") not in MANAGED_WAREHOUSE_LEGACY_CREDENTIAL_KINDS:
            # Catalog rows discovered with an unknown credential scope cannot be reused safely.
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
    """Create or refresh the external source backed by the stored server login."""
    with transaction.atomic():
        server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
        Team.objects.select_for_update().only("id").get(id=team_id, organization_id=organization_id)
        return _ensure_stored_login_source_locked(team_id=team_id, server=server)


def _reconcile_managed_warehouse_source(
    *,
    team_id: int,
    organization_id: str | UUID,
    source_id: UUID,
    expected_mode: ManagedWarehouseSQLMode,
) -> None:
    with transaction.atomic():
        if expected_mode == ManagedWarehouseSQLMode.EXTERNAL:
            server_exists = DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).exists()
            if not server_exists:
                return
        team = Team.objects.select_for_update().only("id").filter(id=team_id, organization_id=organization_id).first()
        if team is None:
            return

        source = (
            _managed_source_queryset(team_id)
            .select_for_update()
            .filter(
                id=source_id,
                deleted=False,
            )
            .first()
        )
        if source is None or source.managed_warehouse_sql_mode != expected_mode:
            return
        source_config = dict(source.job_inputs or {})
        source_api_version = source.api_version

    excluded_schemas = internal_schemas()

    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    try:
        config = source_impl.parse_config(source_config)
        discovered = source_impl.get_schemas(
            config, team_id, api_version=source_impl.resolve_api_version(source_api_version)
        )
    except Exception:
        # A provisioning or briefly unreachable warehouse fails here on every periodic sweep;
        # skip and let the next run retry rather than surfacing a task error each time.
        logger.warning(
            "Managed warehouse introspection failed; will retry",
            team_id=team_id,
            source_id=source_id,
            source_mode=expected_mode,
            exc_info=True,
        )
        return
    source_schemas = [schema for schema in discovered if (schema.source_schema or "") not in excluded_schemas]
    with transaction.atomic():
        # Revalidate after live introspection so deprovision wins the race.
        if expected_mode == ManagedWarehouseSQLMode.EXTERNAL:
            server_exists = DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).exists()
            if not server_exists:
                return
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
            )
            .first()
        )
        if source is None or source.managed_warehouse_sql_mode != expected_mode:
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


def reconcile_managed_warehouse_tables(*, team_id: int, organization_id: str | UUID) -> None:
    """Discover each live managed-warehouse catalog using that source's own credentials."""
    legacy_source_id: UUID | None = None
    reader_source_id: UUID | None = None
    try:
        with transaction.atomic():
            server = DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
            Team.objects.select_for_update().only("id").get(id=team_id, organization_id=organization_id)
            sources = list(_managed_source_queryset(team_id).select_for_update().order_by("-created_at"))
            has_tombstone = any(source.deleted for source in sources)
            has_live_legacy_source = any(
                not source.deleted and not _is_project_reader_source(source) for source in sources
            )
            # Explicit reprovisioning revives one mode; tombstones left for the other mode remain authoritative.
            if server is not None and (not has_tombstone or has_live_legacy_source):
                legacy_source_id = _ensure_stored_login_source_locked(team_id=team_id, server=server).id

            reader_source = next(
                (source for source in sources if not source.deleted and source.is_managed_warehouse_ready),
                None,
            )
            if reader_source is not None:
                reader_source_id = reader_source.id
    except Team.DoesNotExist:
        return

    if legacy_source_id is not None:
        _reconcile_managed_warehouse_source(
            team_id=team_id,
            organization_id=organization_id,
            source_id=legacy_source_id,
            expected_mode=ManagedWarehouseSQLMode.EXTERNAL,
        )
    if reader_source_id is not None:
        _reconcile_managed_warehouse_source(
            team_id=team_id,
            organization_id=organization_id,
            source_id=reader_source_id,
            expected_mode=ManagedWarehouseSQLMode.BUILT_IN,
        )


def _managed_sources_for_org(organization_id: str | UUID) -> QuerySet[ExternalDataSource]:
    return ExternalDataSource._base_manager.filter(
        team__organization_id=organization_id,
        source_type=ExternalDataSourceType.POSTGRES,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        connection_metadata__system_managed=True,
    ).exclude(deleted=True)


def update_managed_warehouse_root_password(*, organization_id: str | UUID, password: str) -> None:
    """Rotate the stored root password without modifying project-reader sources.

    Stored-login sources snapshot the root credential into ``job_inputs``. Project-reader
    passwords have a separate lifecycle and must remain unchanged.
    """
    with transaction.atomic():
        server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
        server.password = password
        server.save(update_fields=["password", "updated_at"])

        config = _source_config(server)
        for source in _managed_sources_for_org(organization_id).select_for_update().order_by("team_id"):
            if _is_project_reader_source(source):
                continue
            if source.job_inputs != config:
                source.job_inputs = config
                source.save(update_fields=["job_inputs", "updated_at"])


def soft_delete_managed_warehouse_sources(*, organization_id: str | UUID) -> None:
    """Atomically tombstone the organization's managed query sources on deprovision."""
    now = timezone.now()
    with transaction.atomic():
        DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
        sources = list(_managed_sources_for_org(organization_id).select_for_update().order_by("team_id"))
        DataWarehouseTable.raw_objects.filter(
            external_data_source_id__in=[source.id for source in sources], deleted=False
        ).update(deleted=True, deleted_at=now, updated_at=now)
        for source in sources:
            source.deleted = True
            source.deleted_at = now
            source.save(update_fields=["deleted", "deleted_at", "updated_at"])
