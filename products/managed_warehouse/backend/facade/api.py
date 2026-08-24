"""
Capability surface for managed_warehouse.

Provisioning state, per-team backfill state, schema naming, Duckgres session setup,
and direct-connection lifecycle commands cross this boundary as contracts or narrow
commands. Django models remain implementation details of the product.
"""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from django.db.models import Q
from django.utils import timezone

from products.managed_warehouse.backend import common, storage
from products.managed_warehouse.backend.common import (
    DUCKGRES_BUCKET_REGION,
    EARLIEST_BACKFILL_DATE,
    NO_HISTORY_SENTINEL,
)
from products.managed_warehouse.backend.facade.contracts import (
    DuckgresQueryServerConfig,
    DuckgresStoredBucketConfig,
    DuckgresStoredServerConfig,
    DuckLakeCatalogConnectionConfig,
    ManagedWarehouseBackfillState,
    ManagedWarehouseProvisionStatus,
    ManagedWarehousePublishedTableRecord,
    ManagedWarehousePublishedTableStatus,
)

if TYPE_CHECKING:
    import psycopg

    from products.managed_warehouse.backend.models import DuckgresServer, ManagedWarehousePublishedTable
    from products.warehouse_sources.backend.facade.models import ExternalDataSchema

__all__ = [
    "DUCKGRES_BUCKET_REGION",
    "EARLIEST_BACKFILL_DATE",
    "NO_HISTORY_SENTINEL",
    "default_bucket_region",
    "deprovision_for_org_deletion",
    "duckgres_data_imports_schema",
    "duckgres_data_imports_table_name",
    "duckgres_data_modeling_schema",
    "ducklake_data_modeling_schema",
    "ducklake_data_modeling_schema_team_id",
    "get_catalog_connection_config",
    "get_control_plane_bucket",
    "get_duckgres_query_server_config",
    "get_org_id_for_team",
    "get_team_deletion_block_reason",
    "get_stored_bucket_config",
    "get_stored_warehouse_config",
    "get_team_backfill_state",
    "get_warehouse_provision_status",
    "get_managed_warehouse_published_table",
    "has_provisioned_warehouse",
    "is_dev_mode",
    "is_publishable_table",
    "organization_is_pending_deletion",
    "persist_duckgres_server_for_org",
    "create_managed_warehouse_published_table",
    "list_managed_warehouse_published_tables",
    "managed_warehouse_published_table_name_exists",
    "mark_managed_warehouse_published_table_deleted",
    "reconcile_stored_bucket_config",
    "resolve_team_earliest_event_date",
    "sanitize_ducklake_identifier",
    "setup_duckgres_session",
    "update_team_earliest_event_date",
    "validate_schema_name",
    "validate_duckgres_identifier",
]


def _to_stored_server_config(server: DuckgresServer) -> DuckgresStoredServerConfig:
    catalog = None
    if server.catalog_host:
        catalog = DuckLakeCatalogConnectionConfig(
            host=server.catalog_host,
            port=server.catalog_port,
            database=server.catalog_database,
            username=server.catalog_username,
            password=server.catalog_password,
        )
    bucket = None
    if server.bucket:
        bucket = DuckgresStoredBucketConfig(bucket=server.bucket, region=server.bucket_region)
    return DuckgresStoredServerConfig(
        organization_id=server.organization_id,
        query_server=DuckgresQueryServerConfig(
            host=server.host,
            port=server.port,
            flight_port=server.flight_port,
            database=server.database,
            username=server.username,
            password=server.password,
        ),
        catalog=catalog,
        bucket=bucket,
    )


def _to_published_table_record(
    publication: ManagedWarehousePublishedTable,
) -> ManagedWarehousePublishedTableRecord:
    saved_query = None
    if publication.saved_query_id is not None:
        from products.data_modeling.backend.facade import api as data_modeling  # noqa: PLC0415

        saved_query = data_modeling.get_managed_warehouse_saved_query(publication.team_id, publication.saved_query_id)
        # An older Temporal worker can finish after the web process creates the saved query but before
        # that worker knows how to update it. Reconcile the legacy terminal state when the publication
        # is next resolved so the saved query does not remain unusable after a rolling deployment.
        if (
            saved_query is not None
            and publication.status == publication.Status.COMPLETED
            and publication.table_id is not None
            and saved_query.table_id is None
        ):
            saved_query = data_modeling.complete_managed_warehouse_saved_query_publish(
                team_id=publication.team_id,
                saved_query_id=publication.saved_query_id,
                table_id=publication.table_id,
                job_id=None,
            )
        elif (
            saved_query is not None
            and publication.status == publication.Status.FAILED
            and saved_query.status != "Failed"
        ):
            data_modeling.fail_managed_warehouse_saved_query_publish(
                team_id=publication.team_id,
                saved_query_id=publication.saved_query_id,
                error=publication.last_error or "Publish failed. Publish the table again.",
                job_id=None,
            )
            saved_query = data_modeling.get_managed_warehouse_saved_query(
                publication.team_id, publication.saved_query_id
            )

    status_by_saved_query_status = {
        "Modified": ManagedWarehousePublishedTableStatus.PENDING,
        "Running": ManagedWarehousePublishedTableStatus.PUBLISHING,
        "Completed": ManagedWarehousePublishedTableStatus.COMPLETED,
        "Failed": ManagedWarehousePublishedTableStatus.FAILED,
        "Cancelled": ManagedWarehousePublishedTableStatus.FAILED,
    }
    if saved_query is None:
        publication_status = ManagedWarehousePublishedTableStatus(publication.status)
    elif saved_query.status == "Modified" and publication.status == publication.Status.PUBLISHING:
        publication_status = ManagedWarehousePublishedTableStatus.PUBLISHING
    else:
        publication_status = status_by_saved_query_status.get(
            saved_query.status, ManagedWarehousePublishedTableStatus.PENDING
        )
    return ManagedWarehousePublishedTableRecord(
        id=publication.id,
        saved_query_id=saved_query.id if saved_query is not None else publication.saved_query_id,
        team_id=publication.team_id,
        source_schema_name=publication.source_schema_name,
        source_table_name=publication.source_table_name,
        name=saved_query.name if saved_query is not None else publication.name,
        status=publication_status,
        last_published_at=saved_query.last_run_at if saved_query is not None else publication.last_published_at,
        last_error=saved_query.latest_error if saved_query is not None else publication.last_error,
        row_count=saved_query.row_count if saved_query is not None else publication.row_count,
        folder_version=publication.folder_version,
        table_id=saved_query.table_id if saved_query is not None else publication.table_id,
        deleted=publication.deleted or (saved_query.deleted if saved_query is not None else False),
    )


def is_dev_mode() -> bool:
    """Whether Duckgres runs in the env-var-configured local mode."""
    return common.is_dev_mode()


def sanitize_ducklake_identifier(raw: str, *, default_prefix: str) -> str:
    return common.sanitize_ducklake_identifier(raw, default_prefix=default_prefix)


def validate_duckgres_identifier(identifier: str) -> None:
    common.validate_duckgres_identifier(identifier)


def is_publishable_table(schema_name: str, table_name: str, *, reserved_table_names: frozenset[str]) -> bool:
    from products.managed_warehouse.backend.publish import is_publishable_table as is_publishable  # noqa: PLC0415

    return is_publishable(schema_name, table_name, reserved_table_names=reserved_table_names)


def default_bucket_region() -> str:
    return common.default_bucket_region()


def get_org_id_for_team(team_id: int) -> str:
    return common._get_org_id_for_team(team_id)


def organization_is_pending_deletion(organization_id: str | UUID) -> bool:
    from posthog.models.organization import Organization  # noqa: PLC0415

    return Organization.objects.filter(id=organization_id, is_pending_deletion=True).exists()


def get_stored_warehouse_config(organization_id: str) -> DuckgresStoredServerConfig | None:
    server = common.get_duckgres_server_for_organization(organization_id)
    return _to_stored_server_config(server) if server is not None else None


def get_warehouse_provision_status(organization_id: str) -> ManagedWarehouseProvisionStatus:
    return ManagedWarehouseProvisionStatus(provisioned=has_provisioned_warehouse(organization_id))


def has_provisioned_warehouse(organization_id: str | UUID) -> bool:
    from products.managed_warehouse.backend.models import DuckgresServer  # noqa: PLC0415

    return DuckgresServer.objects.filter(organization_id=organization_id).exists()


def create_managed_warehouse_published_table(
    *,
    team_id: int,
    source_schema_name: str,
    source_table_name: str,
    name: str,
    saved_query_id: UUID | None = None,
    created_by_id: int | None = None,
) -> ManagedWarehousePublishedTableRecord:
    from products.managed_warehouse.backend.models import ManagedWarehousePublishedTable  # noqa: PLC0415

    publication = ManagedWarehousePublishedTable.objects.for_team(team_id).create(
        team_id=team_id,
        source_schema_name=source_schema_name,
        source_table_name=source_table_name,
        name=name,
        saved_query_id=saved_query_id,
        created_by_id=created_by_id,
    )
    return _to_published_table_record(publication)


def get_managed_warehouse_published_table(
    team_id: int, publication_id: UUID | str
) -> ManagedWarehousePublishedTableRecord | None:
    from products.managed_warehouse.backend.models import ManagedWarehousePublishedTable  # noqa: PLC0415

    publication = (
        ManagedWarehousePublishedTable.objects.for_team(team_id)
        .filter(Q(id=publication_id) | Q(saved_query_id=publication_id))
        .first()
    )
    return _to_published_table_record(publication) if publication is not None else None


def list_managed_warehouse_published_tables(team_id: int) -> list[ManagedWarehousePublishedTableRecord]:
    from products.managed_warehouse.backend.models import ManagedWarehousePublishedTable  # noqa: PLC0415

    publications = ManagedWarehousePublishedTable.objects.for_team(team_id).filter(deleted=False).order_by("name")
    return [_to_published_table_record(publication) for publication in publications]


def managed_warehouse_published_table_name_exists(team_id: int, name: str) -> bool:
    from products.managed_warehouse.backend.models import ManagedWarehousePublishedTable  # noqa: PLC0415

    return ManagedWarehousePublishedTable.objects.for_team(team_id).filter(name=name, deleted=False).exists()


def mark_managed_warehouse_published_table_deleted(team_id: int, publication_id: UUID | str) -> bool:
    from products.managed_warehouse.backend.models import ManagedWarehousePublishedTable  # noqa: PLC0415

    return bool(
        ManagedWarehousePublishedTable.objects.for_team(team_id)
        .filter(Q(id=publication_id) | Q(saved_query_id=publication_id), deleted=False)
        .update(deleted=True, updated_at=timezone.now())
    )


def get_duckgres_query_server_config(organization_id: str) -> DuckgresQueryServerConfig:
    config = common.get_duckgres_config_for_org(organization_id)
    return DuckgresQueryServerConfig(
        host=config["DUCKGRES_HOST"],
        port=int(config["DUCKGRES_PORT"]),
        flight_port=int(config["DUCKGRES_FLIGHT_PORT"]),
        database=config["DUCKGRES_DATABASE"],
        username=config["DUCKGRES_USERNAME"],
        password=config["DUCKGRES_PASSWORD"],
    )


def get_catalog_connection_config(organization_id: str) -> DuckLakeCatalogConnectionConfig | None:
    stored = get_stored_warehouse_config(organization_id)
    return stored.catalog if stored is not None else None


def get_stored_bucket_config(organization_id: str) -> DuckgresStoredBucketConfig | None:
    stored = get_stored_warehouse_config(organization_id)
    return stored.bucket if stored is not None else None


def persist_duckgres_server_for_org(
    organization_id: str | UUID,
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    bucket: str | None = None,
    bucket_region: str | None = None,
) -> DuckgresStoredServerConfig:
    return _to_stored_server_config(
        common.upsert_duckgres_server_for_org(
            organization_id,
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            bucket=bucket,
            bucket_region=bucket_region,
        )
    )


def reconcile_stored_bucket_config(organization_id: str | UUID, *, bucket: str, bucket_region: str) -> bool:
    from products.managed_warehouse.backend.models import DuckgresServer  # noqa: PLC0415

    return bool(
        DuckgresServer.objects.filter(organization_id=organization_id)
        .exclude(bucket=bucket, bucket_region=bucket_region)
        .update(bucket=bucket, bucket_region=bucket_region)
    )


def get_control_plane_bucket(organization_id: str | UUID) -> str | None:
    from products.managed_warehouse.backend.presentation.views import cp_bucket_for  # noqa: PLC0415

    return cp_bucket_for(organization_id)


def update_team_earliest_event_date(
    organization_id: str | UUID, team_id: int, earliest_event_date: date | None
) -> bool:
    from products.managed_warehouse.backend.presentation.views import push_team_earliest_event_date  # noqa: PLC0415

    return push_team_earliest_event_date(organization_id, team_id, earliest_event_date)


def get_team_deletion_block_reason(team_id: int, organization_id: str | UUID) -> str | None:
    from products.managed_warehouse.backend.presentation.views import block_team_deletion  # noqa: PLC0415

    return block_team_deletion(team_id, organization_id)


def deprovision_for_org_deletion(organization_id: str | UUID) -> None:
    from products.managed_warehouse.backend.presentation.views import (  # noqa: PLC0415
        deprovision_for_org_deletion as deprovision,
    )

    deprovision(organization_id)


def duckgres_data_imports_schema(team_id: int) -> str:
    return common.duckgres_data_imports_schema(team_id)


def duckgres_data_imports_table_name(schema: ExternalDataSchema) -> str:
    return common.duckgres_data_imports_table_name(schema)


def duckgres_data_modeling_schema(team_id: int) -> str:
    return common.duckgres_data_modeling_schema(team_id)


def ducklake_data_modeling_schema(team_id: int) -> str:
    return common.ducklake_data_modeling_schema(team_id)


def ducklake_data_modeling_schema_team_id(schema_name: str) -> int | None:
    return common.ducklake_data_modeling_schema_team_id(schema_name)


def validate_schema_name(name: str | None) -> str | None:
    return common.validate_schema_name(name)


def get_team_backfill_state(team_id: int) -> ManagedWarehouseBackfillState:
    return common.get_team_backfill_state(team_id)


def resolve_team_earliest_event_date(team_id: int) -> date:
    return common.resolve_team_earliest_event_date(team_id)


def setup_duckgres_session(
    conn: psycopg.Connection,
    extensions: tuple[str, ...] = ("ducklake", "httpfs", "delta"),
) -> None:
    storage.setup_duckgres_session(conn, extensions)
