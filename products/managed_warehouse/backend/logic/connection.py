"""Expose a managed Duckgres warehouse in the SQL editor as a Postgres connection.

Each member team gets a Postgres ``ExternalDataSource`` whose short-lived Duckgres
credential is resolved when a connection is opened. Duckgres root sees every schema in
the warehouse, so the connection discovers and exposes the whole org catalog without
per-team namespace configuration. Setup happens in two steps:

1. ``ensure_managed_warehouse_direct_source`` creates the source row after explicit
   successful provision or onboarding, so the connection appears immediately.
2. ``reconcile_managed_warehouse_tables`` only updates an existing live source and records
   every non-internal schema/table the root credential can see.

This bypasses the user-facing create endpoint because the managed host is internal
infrastructure and is not reachable for live schema validation during provisioning.

Lifecycle is org-level only: ``soft_delete_managed_warehouse_sources`` handles
deprovisioning of the whole warehouse. There is no per-team offboarding flow yet —
a single team leaving keeps its connection until the org deprovisions (revisit if
per-team removal becomes a product flow).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from django.conf import settings
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen
from posthog.models.organization import Organization
from posthog.models.team.team import Team

from products.data_warehouse.backend.facade.api import reconcile_postgres_schemas
from products.managed_warehouse.backend.facade.contracts import ManagedWarehouseSourceAuth
from products.managed_warehouse.backend.logic.sql_editor_credentials import (
    MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
    resolve_managed_warehouse_postgres_connection,
)
from products.managed_warehouse.backend.models import DuckgresServer, ManagedWarehouseSourceLifecycle
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
# root bypasses Duckgres AllowedSchemas, so this denylist is the only filter on what the
# discover sweep registers. The later per-schema visibility control plugs in here.
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


def _source_auth(source: ExternalDataSource) -> ManagedWarehouseSourceAuth:
    metadata = source.connection_metadata if isinstance(source.connection_metadata, dict) else {}
    credential_kind = metadata.get("credential_kind")
    lifecycle_generation = metadata.get("lifecycle_generation")
    return ManagedWarehouseSourceAuth(
        prefix=source.prefix,
        system_managed=metadata.get("system_managed") is True,
        credential_kind=credential_kind if isinstance(credential_kind, str) else None,
        lifecycle_generation=(lifecycle_generation if isinstance(lifecycle_generation, int) else None),
    )


def _is_dynamic_managed_warehouse_source(source: ExternalDataSource) -> bool:
    return _source_auth(source).credential_kind == MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND


def _credential_kind(source: ExternalDataSource) -> str | None:
    return _source_auth(source).credential_kind


def _schema_discovery_principal(team_id: int) -> str:
    return f"posthog:sql-editor-schema-discovery:team:{team_id}"


@frozen
class _LifecycleSnapshot:
    organization_exists: bool
    desired_active: bool
    generation: int | None


def _lifecycle_snapshot(organization_id: str | UUID, *, lock: bool = False) -> _LifecycleSnapshot:
    organization_queryset = Organization.objects.only("id")
    if lock:
        organization_queryset = organization_queryset.select_for_update()
    if not organization_queryset.filter(id=organization_id).exists():
        return _LifecycleSnapshot(organization_exists=False, desired_active=False, generation=None)
    lifecycle_queryset = ManagedWarehouseSourceLifecycle.objects.filter(organization_id=organization_id)
    if lock:
        lifecycle_queryset = lifecycle_queryset.select_for_update()
    lifecycle = lifecycle_queryset.first()
    if lifecycle is None:
        return _LifecycleSnapshot(organization_exists=True, desired_active=True, generation=None)
    return _LifecycleSnapshot(
        organization_exists=True,
        desired_active=lifecycle.desired_active,
        generation=lifecycle.generation,
    )


def _source_config(server: DuckgresServer) -> dict[str, object]:
    """Snapshot the server's org root credential into the source's job_inputs."""
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


def _set_dynamic_source_auth(source: ExternalDataSource, *, lifecycle_generation: int) -> ExternalDataSource:
    source.access_method = ExternalDataSource.AccessMethod.DIRECT
    source.direct_query_enabled = True
    source.connection_metadata = {
        "engine": "duckdb",
        "system_managed": True,
        "credential_kind": MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
        "lifecycle_generation": lifecycle_generation,
    }
    source.job_inputs = {}
    source.deleted = False
    source.deleted_at = None
    source.save(
        update_fields=[
            "access_method",
            "direct_query_enabled",
            "connection_metadata",
            "job_inputs",
            "deleted",
            "deleted_at",
            "updated_at",
        ]
    )
    return source


def _tombstone_source(source: ExternalDataSource) -> None:
    now = timezone.now()
    DataWarehouseTable.raw_objects.filter(external_data_source_id=source.id, deleted=False).update(
        deleted=True,
        deleted_at=now,
        updated_at=now,
    )
    source.deleted = True
    source.deleted_at = now
    source.save(update_fields=["deleted", "deleted_at", "updated_at"])


def _ensure_managed_source_locked(
    *, team_id: int, convert_active_legacy: bool, lifecycle_generation: int
) -> ExternalDataSource:
    sources = list(_managed_source_queryset(team_id).select_for_update().order_by("-created_at"))
    if convert_active_legacy:
        for source in sources:
            if not source.deleted and _credential_kind(source) == MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND:
                _tombstone_source(source)

    live_dynamic = next(
        (source for source in sources if not source.deleted and _is_dynamic_managed_warehouse_source(source)), None
    )
    if live_dynamic is not None:
        return _set_dynamic_source_auth(live_dynamic, lifecycle_generation=lifecycle_generation)

    live_reader = next(
        (
            source
            for source in sources
            if not source.deleted
            and _credential_kind(source) == MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND
            and source.is_managed_warehouse_ready
        ),
        None,
    )
    live_legacy = next(
        (
            source
            for source in sources
            if not source.deleted and _credential_kind(source) in MANAGED_WAREHOUSE_LEGACY_CREDENTIAL_KINDS
        ),
        None,
    )
    if live_legacy is not None:
        return (
            _set_dynamic_source_auth(live_legacy, lifecycle_generation=lifecycle_generation)
            if convert_active_legacy
            else live_legacy
        )
    if live_reader is not None:
        return live_reader

    tombstoned_dynamic = next((source for source in sources if _is_dynamic_managed_warehouse_source(source)), None)
    if tombstoned_dynamic is not None:
        return _set_dynamic_source_auth(tombstoned_dynamic, lifecycle_generation=lifecycle_generation)
    if convert_active_legacy:
        tombstoned_legacy = next(
            (source for source in sources if _credential_kind(source) in MANAGED_WAREHOUSE_LEGACY_CREDENTIAL_KINDS),
            None,
        )
        if tombstoned_legacy is not None:
            return _set_dynamic_source_auth(tombstoned_legacy, lifecycle_generation=lifecycle_generation)

    return ExternalDataSource.objects.create(
        source_id=str(uuid4()),
        connection_id=str(uuid4()),
        destination_id=str(uuid4()),
        team_id=team_id,
        status=ExternalDataSource.Status.RUNNING,
        source_type=ExternalDataSourceType.POSTGRES,
        job_inputs={},
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        description=MANAGED_WAREHOUSE_SOURCE_DESCRIPTION,
        access_method=ExternalDataSource.AccessMethod.DIRECT,
        created_via=ExternalDataSource.CreatedVia.WEB,
        direct_query_enabled=True,
        connection_metadata={
            "engine": "duckdb",
            "system_managed": True,
            "credential_kind": MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
            "lifecycle_generation": lifecycle_generation,
        },
    )


def _ensure_stored_login_source_locked(*, team_id: int, server: DuckgresServer) -> ExternalDataSource:
    existing = next(
        (
            source
            for source in _managed_source_queryset(team_id).select_for_update().order_by("deleted", "-created_at")
            if _credential_kind(source) != MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND
        ),
        None,
    )
    config = _source_config(server)
    if existing is not None:
        update_fields: list[str] = []
        connection_metadata = dict(existing.connection_metadata or {})
        if connection_metadata.get("credential_kind") not in MANAGED_WAREHOUSE_LEGACY_CREDENTIAL_KINDS:
            now = timezone.now()
            DataWarehouseTable.raw_objects.filter(
                team_id=team_id,
                external_data_source_id=existing.id,
                deleted=False,
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
            migrated.pop("lifecycle_generation", None)
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


def _locked_source_lifecycle(organization_id: str | UUID) -> ManagedWarehouseSourceLifecycle:
    # The organization row serializes first-time lifecycle-row creation as well as all
    # later generation reads/writes. This avoids relying on DuckgresServer for lifecycle
    # coordination and gives every team in an organization one common fence.
    organization = Organization.objects.select_for_update().only("id").get(id=organization_id)
    lifecycle, _created = ManagedWarehouseSourceLifecycle.objects.get_or_create(organization=organization)
    return lifecycle


def get_active_managed_warehouse_source_generation(*, organization_id: str | UUID) -> int | None:
    """Capture the current active generation before onboarding an additional team."""
    with transaction.atomic():
        lifecycle = _locked_source_lifecycle(organization_id)
        return lifecycle.generation if lifecycle.desired_active else None


def get_managed_warehouse_source_generation(*, organization_id: str | UUID) -> int:
    """Capture the current generation before a provision request, active or inactive."""
    with transaction.atomic():
        return _locked_source_lifecycle(organization_id).generation


def activate_managed_warehouse_source_lifecycle(*, organization_id: str | UUID, expected_generation: int) -> int | None:
    """Conditionally advance after provision, unless a newer lifecycle operation won."""
    with transaction.atomic():
        lifecycle = _locked_source_lifecycle(organization_id)
        if lifecycle.generation != expected_generation:
            return None
        was_inactive = not lifecycle.desired_active
        lifecycle.generation += 1
        lifecycle.desired_active = True
        lifecycle.legacy_conversion_generation = lifecycle.generation if was_inactive else None
        lifecycle.save(update_fields=["generation", "desired_active", "legacy_conversion_generation"])
        return lifecycle.generation


def deactivate_managed_warehouse_source_lifecycle(
    *, organization_id: str | UUID, expected_generation: int
) -> int | None:
    """Mark the lifecycle inactive once and return the cleanup operation generation."""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().only("id").filter(id=organization_id).first()
        if organization is None:
            return None
        lifecycle, _created = ManagedWarehouseSourceLifecycle.objects.get_or_create(organization=organization)
        if lifecycle.generation != expected_generation:
            return None
        if lifecycle.desired_active:
            lifecycle.generation += 1
            lifecycle.desired_active = False
            lifecycle.legacy_conversion_generation = None
            lifecycle.save(update_fields=["generation", "desired_active", "legacy_conversion_generation"])
        return lifecycle.generation


def ensure_managed_warehouse_direct_source(
    *, team_id: int, organization_id: str | UUID, expected_generation: int
) -> ExternalDataSource | None:
    """Create or refresh a source only if no deprovision happened since the request began."""
    with transaction.atomic():
        lifecycle = _locked_source_lifecycle(organization_id)
        if not lifecycle.desired_active or lifecycle.generation != expected_generation:
            return None
        Team.objects.select_for_update().only("id").get(id=team_id, organization_id=organization_id)
        if not settings.MANAGED_WAREHOUSE_DYNAMIC_SQL_EDITOR_AUTH_ENABLED:
            sources = list(_managed_source_queryset(team_id).select_for_update().order_by("-created_at"))
            convert_active_legacy = lifecycle.legacy_conversion_generation == expected_generation
            if convert_active_legacy:
                for source in sources:
                    if (
                        not source.deleted
                        and _credential_kind(source) == MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND
                    ):
                        _tombstone_source(source)
            live_dynamic = next(
                (source for source in sources if not source.deleted and _is_dynamic_managed_warehouse_source(source)),
                None,
            )
            if live_dynamic is not None:
                if _source_auth(live_dynamic).lifecycle_generation != expected_generation:
                    return _set_dynamic_source_auth(
                        live_dynamic,
                        lifecycle_generation=expected_generation,
                    )
                return live_dynamic
            server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
            return _ensure_stored_login_source_locked(team_id=team_id, server=server)
        return _ensure_managed_source_locked(
            team_id=team_id,
            convert_active_legacy=lifecycle.legacy_conversion_generation == expected_generation,
            lifecycle_generation=expected_generation,
        )


def _reconcile_managed_warehouse_source(*, team_id: int, organization_id: str | UUID, source_id: UUID) -> None:
    lifecycle_snapshot = _lifecycle_snapshot(organization_id)
    if not lifecycle_snapshot.desired_active:
        return
    with transaction.atomic():
        team = Team.objects.select_for_update().only("id").filter(id=team_id, organization_id=organization_id).first()
        if team is None:
            return

        source = _managed_source_queryset(team_id).select_for_update().filter(id=source_id, deleted=False).first()
        if source is None:
            return
        source_id = source.id
        source_api_version = source.api_version
        credential_kind = _credential_kind(source)

    excluded_schemas = internal_schemas()

    source_impl = SourceRegistry.get_source(ExternalDataSourceType.POSTGRES)
    try:
        dynamic_connection = resolve_managed_warehouse_postgres_connection(
            source_auth=_source_auth(source),
            organization_id=organization_id,
            team_id=team_id,
            principal=_schema_discovery_principal(team_id),
        )
        source_config = (
            {
                "host": dynamic_connection.host,
                "port": dynamic_connection.port,
                "database": dynamic_connection.database,
                "user": dynamic_connection.username,
                "password": dynamic_connection.password,
            }
            if dynamic_connection is not None
            else dict(source.job_inputs or {})
        )
        config = source_impl.parse_config(source_config)
        discovered = source_impl.get_schemas(
            config,
            team_id,
            api_version=source_impl.resolve_api_version(source_api_version),
            require_ssl=dynamic_connection is not None and dynamic_connection.sslmode == "require",
        )
    except Exception:
        # A provisioning or briefly unreachable warehouse fails here on every periodic sweep;
        # skip and let the next run retry rather than surfacing a task error each time.
        logger.warning("Managed warehouse introspection failed; will retry", team_id=team_id, exc_info=True)
        return
    source_schemas = [schema for schema in discovered if (schema.source_schema or "") not in excluded_schemas]
    with transaction.atomic():
        if _lifecycle_snapshot(organization_id, lock=True) != lifecycle_snapshot:
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
                direct_query_enabled=True,
            )
            .first()
        )
        if source is None:
            return
        if _credential_kind(source) != credential_kind:
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
    """Reconcile every live managed catalog with that source's own credential mode."""
    if not settings.MANAGED_WAREHOUSE_DYNAMIC_SQL_EDITOR_AUTH_ENABLED:
        lifecycle_snapshot = _lifecycle_snapshot(organization_id)
        if not lifecycle_snapshot.desired_active:
            return
        try:
            if lifecycle_snapshot.generation is not None:
                ensure_managed_warehouse_direct_source(
                    team_id=team_id,
                    organization_id=organization_id,
                    expected_generation=lifecycle_snapshot.generation,
                )
            else:
                _ensure_unfenced_legacy_source_for_reconcile(
                    team_id=team_id,
                    organization_id=organization_id,
                )
        except (DuckgresServer.DoesNotExist, Team.DoesNotExist):
            return

    candidates = _managed_source_queryset(team_id).filter(deleted=False).order_by("created_at")
    source_ids = [
        source.id for source in candidates if source.managed_warehouse_sql_mode != ManagedWarehouseSQLMode.UNAVAILABLE
    ]
    for source_id in source_ids:
        _reconcile_managed_warehouse_source(
            team_id=team_id,
            organization_id=organization_id,
            source_id=source_id,
        )


def _ensure_unfenced_legacy_source_for_reconcile(
    *, team_id: int, organization_id: str | UUID
) -> ExternalDataSource | None:
    """Keep pre-lifecycle workers recoverable without weakening a lifecycle fence."""
    with transaction.atomic():
        organization = Organization.objects.select_for_update().only("id").filter(id=organization_id).first()
        if organization is None or ManagedWarehouseSourceLifecycle.objects.filter(organization=organization).exists():
            return None
        Team.objects.select_for_update().only("id").get(id=team_id, organization_id=organization_id)
        sources = list(_managed_source_queryset(team_id).select_for_update().order_by("-created_at"))
        live_dynamic = next(
            (source for source in sources if not source.deleted and _is_dynamic_managed_warehouse_source(source)),
            None,
        )
        if live_dynamic is not None:
            return live_dynamic
        has_tombstone = any(source.deleted for source in sources)
        has_live_legacy = any(
            not source.deleted and _credential_kind(source) in MANAGED_WAREHOUSE_LEGACY_CREDENTIAL_KINDS
            for source in sources
        )
        if has_tombstone and not has_live_legacy:
            return None
        server = DuckgresServer.objects.select_for_update().filter(organization_id=organization_id).first()
        if server is None:
            return None
        return _ensure_stored_login_source_locked(team_id=team_id, server=server)


def _managed_sources_for_org(organization_id: str | UUID) -> QuerySet[ExternalDataSource]:
    return ExternalDataSource._base_manager.filter(
        team__organization_id=organization_id,
        source_type=ExternalDataSourceType.POSTGRES,
        prefix=MANAGED_WAREHOUSE_SOURCE_PREFIX,
        connection_metadata__system_managed=True,
    ).exclude(deleted=True)


def update_managed_warehouse_root_password(*, organization_id: str | UUID, password: str) -> None:
    """Rotate the stored root password and active legacy sources for the organization.

    Dynamic sources mint credentials at connection time and are intentionally skipped.
    """
    with transaction.atomic():
        server = DuckgresServer.objects.select_for_update().get(organization_id=organization_id)
        server.password = password
        server.save(update_fields=["password", "updated_at"])

        config = _source_config(server)
        for source in _managed_sources_for_org(organization_id).select_for_update().order_by("team_id"):
            if _credential_kind(source) in {
                MANAGED_WAREHOUSE_SERVICE_CREDENTIAL_KIND,
                MANAGED_WAREHOUSE_PROJECT_READER_CREDENTIAL_KIND,
            }:
                continue
            if source.job_inputs != config:
                source.job_inputs = config
                source.save(update_fields=["job_inputs", "updated_at"])


def soft_delete_managed_warehouse_sources(*, organization_id: str | UUID, expected_generation: int) -> None:
    """Fence stale setup requests and atomically tombstone all current query sources."""
    now = timezone.now()
    cleanup_error: Exception | None = None
    with transaction.atomic():
        organization = Organization.objects.select_for_update().only("id").filter(id=organization_id).first()
        if organization is None:
            return
        lifecycle = ManagedWarehouseSourceLifecycle.objects.filter(organization=organization).first()
        if lifecycle is None or lifecycle.desired_active or lifecycle.generation != expected_generation:
            return

        # The inactive generation was committed immediately after remote deprovision.
        # Keep source tombstoning atomic, while allowing a retry with this same token.
        try:
            with transaction.atomic():
                _soft_delete_sources_for_inactive_generation_locked(
                    organization_id=organization_id,
                    expected_generation=expected_generation,
                    now=now,
                )
        except Exception as error:
            cleanup_error = error

    if cleanup_error is not None:
        raise cleanup_error


def soft_delete_legacy_managed_warehouse_sources(*, organization_id: str | UUID) -> None:
    if settings.MANAGED_WAREHOUSE_DYNAMIC_SQL_EDITOR_AUTH_ENABLED:
        return
    now = timezone.now()
    with transaction.atomic():
        organization = Organization.objects.select_for_update().only("id").filter(id=organization_id).first()
        if organization is None:
            return
        lifecycle = ManagedWarehouseSourceLifecycle.objects.filter(organization=organization).first()
        if lifecycle is not None:
            _soft_delete_sources_for_inactive_generation_locked(
                organization_id=organization_id,
                expected_generation=lifecycle.generation,
                now=now,
            )
            return
        sources = list(_managed_sources_for_org(organization_id).select_for_update().order_by("team_id"))
        _soft_delete_sources_locked(sources=sources, now=now)


def _soft_delete_sources_for_inactive_generation_locked(
    *, organization_id: str | UUID, expected_generation: int, now: datetime
) -> None:
    lifecycle = ManagedWarehouseSourceLifecycle.objects.filter(organization_id=organization_id).first()
    if lifecycle is None or lifecycle.desired_active or lifecycle.generation != expected_generation:
        return
    sources = list(_managed_sources_for_org(organization_id).select_for_update().order_by("team_id"))
    _soft_delete_sources_locked(sources=sources, now=now)


def _soft_delete_sources_locked(*, sources: list[ExternalDataSource], now: datetime) -> None:
    DataWarehouseTable.raw_objects.filter(
        external_data_source_id__in=[source.id for source in sources],
        deleted=False,
    ).update(deleted=True, deleted_at=now, updated_at=now)
    for source in sources:
        source.deleted = True
        source.deleted_at = now
        source.save(update_fields=["deleted", "deleted_at", "updated_at"])
