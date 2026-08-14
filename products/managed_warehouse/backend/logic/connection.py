"""Expose a managed Duckgres warehouse in the SQL editor as a Postgres connection.

Each enrolled team gets a Postgres ``ExternalDataSource`` pointed at its managed
Duckgres warehouse. Sources that already hold a confirmed ``project_reader`` login keep
that credential and discover only the catalog Duckgres exposes to it. This module does
not create, replace, or rotate project readers. Older sources backed by a broader stored
login remain ineligible for managed-warehouse discovery and queries.

This bypasses the user-facing create endpoint because the managed host is internal
infrastructure and is not reachable for live schema validation during provisioning.

``soft_delete_managed_warehouse_sources`` handles deprovisioning of the whole warehouse.
Deleting a team removes its project-scoped source through the existing model cascade.
"""

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog

from posthog.models.team.team import Team

from products.data_warehouse.backend.facade.api import reconcile_postgres_schemas
from products.managed_warehouse.backend.models import DuckgresServer
from products.warehouse_sources.backend.facade.models import (
    MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND,
    MANAGED_WAREHOUSE_SOURCE_PREFIX,
    DataWarehouseTable,
    ExternalDataSchema,
    ExternalDataSource,
)
from products.warehouse_sources.backend.facade.source_management import SourceRegistry
from products.warehouse_sources.backend.facade.types import ExternalDataSourceType

logger = structlog.get_logger(__name__)

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


def ensure_managed_warehouse_direct_source(*, team_id: int, organization_id: str | UUID) -> ExternalDataSource:
    """Return the team's ready project reader without creating or changing credentials."""
    with transaction.atomic():
        Team.objects.select_for_update().only("id").get(id=team_id, organization_id=organization_id)
        project_readers = (
            _managed_source_queryset(team_id)
            .select_for_update()
            .filter(deleted=False)
            .filter(connection_metadata__credential_kind=MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND)
            .order_by("-created_at")
        )
        for project_reader in project_readers:
            if project_reader.is_managed_warehouse_ready:
                return project_reader

        raise ExternalDataSource.DoesNotExist("Managed warehouse project reader is not configured.")


def reconcile_managed_warehouse_tables(*, team_id: int, organization_id: str | UUID) -> None:
    """Discover and register the managed-warehouse catalog visible to this team's source."""
    with transaction.atomic():
        # A deprovision tombstone must win over delayed reconciliation, even while the
        # organization-scoped server row remains available to other internal workflows.
        if _managed_source_queryset(team_id).filter(deleted=True).exists():
            return

    try:
        ensured_source = ensure_managed_warehouse_direct_source(team_id=team_id, organization_id=organization_id)
    except (ExternalDataSource.DoesNotExist, Team.DoesNotExist):
        return

    with transaction.atomic():
        team = Team.objects.select_for_update().only("id").filter(id=team_id, organization_id=organization_id).first()
        if team is None:
            return

        source = (
            _managed_source_queryset(team_id)
            .select_for_update()
            .filter(
                id=ensured_source.id,
                deleted=False,
                connection_metadata__credential_kind=MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND,
            )
            .first()
        )
        if source is None or not source.is_managed_warehouse_ready:
            return
        source_id = source.id
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
        logger.warning("Managed warehouse introspection failed; will retry", team_id=team_id, exc_info=True)
        return
    source_schemas = [schema for schema in discovered if (schema.source_schema or "") not in excluded_schemas]
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
                connection_metadata__credential_kind=MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND,
            )
            .first()
        )
        if source is None or not source.is_managed_warehouse_ready:
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
