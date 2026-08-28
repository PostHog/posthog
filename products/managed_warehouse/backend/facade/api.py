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
)

if TYPE_CHECKING:
    import psycopg

    from products.managed_warehouse.backend.models import DuckgresServer
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
    "get_catalog_connection_config",
    "get_control_plane_bucket",
    "get_duckgres_query_server_config",
    "get_org_id_for_team",
    "get_team_deletion_block_reason",
    "get_stored_bucket_config",
    "get_stored_warehouse_config",
    "get_team_backfill_state",
    "get_warehouse_provision_status",
    "has_provisioned_warehouse",
    "is_dev_mode",
    "organization_is_pending_deletion",
    "persist_duckgres_server_for_org",
    "reconcile_stored_bucket_config",
    "resolve_team_earliest_event_date",
    "setup_duckgres_session",
    "update_team_earliest_event_date",
    "validate_schema_name",
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


def is_dev_mode() -> bool:
    """Whether Duckgres runs in the env-var-configured local mode."""
    return common.is_dev_mode()


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
