"""
Capability surface for managed_warehouse.

Provisioning, per-team backfill enablement and state, schema naming, and duckgres
session setup — everything external callers need to work with an org's managed
warehouse without reaching into the product's internals.

Delegates to ``common``/``storage``, which pull duckdb and psycopg, so this module must
stay off the ``django.setup()`` path. Consumers that only need the model classes should
import ``facade.models`` instead.
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

if TYPE_CHECKING:
    import psycopg

    from products.managed_warehouse.backend.models import DuckgresServer

__all__ = [
    "DUCKGRES_BUCKET_REGION",
    "EARLIEST_BACKFILL_DATE",
    "NO_HISTORY_SENTINEL",
    "default_bucket_region",
    "duckgres_data_imports_schema",
    "duckgres_data_modeling_schema",
    "get_duckgres_config_for_org",
    "get_duckgres_server_by_team_org",
    "get_duckgres_server_for_organization",
    "get_org_id_for_team",
    "get_team_backfill_state",
    "is_dev_mode",
    "resolve_team_earliest_event_date",
    "setup_duckgres_session",
    "upsert_duckgres_server_for_org",
    "validate_schema_name",
]


def is_dev_mode() -> bool:
    """Whether duckgres runs in the env-var-configured local mode rather than per-org servers."""
    return common.is_dev_mode()


def default_bucket_region() -> str:
    return common.default_bucket_region()


def get_org_id_for_team(team_id: int) -> str:
    return common._get_org_id_for_team(team_id)


def get_duckgres_server_for_organization(organization_id: str) -> DuckgresServer | None:
    return common.get_duckgres_server_for_organization(organization_id)


def get_duckgres_server_by_team_org(team_id: int) -> DuckgresServer | None:
    return common.get_duckgres_server_by_team_org(team_id)


def get_duckgres_config_for_org(organization_id: str) -> dict[str, str]:
    return common.get_duckgres_config_for_org(organization_id)


def upsert_duckgres_server_for_org(
    organization_id: str | UUID,
    *,
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    bucket: str | None = None,
    bucket_region: str | None = None,
) -> DuckgresServer:
    return common.upsert_duckgres_server_for_org(
        organization_id,
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        bucket=bucket,
        bucket_region=bucket_region,
    )


def duckgres_data_imports_schema(team_id: int) -> str:
    return common.duckgres_data_imports_schema(team_id)


def duckgres_data_modeling_schema(team_id: int) -> str:
    return common.duckgres_data_modeling_schema(team_id)


def validate_schema_name(name: str | None) -> str | None:
    return common.validate_schema_name(name)


def get_team_backfill_state(team_id: int) -> dict[str, object]:
    return common.get_team_backfill_state(team_id)


def resolve_team_earliest_event_date(team_id: int) -> date:
    return common.resolve_team_earliest_event_date(team_id)


def setup_duckgres_session(
    conn: psycopg.Connection,
    extensions: tuple[str, ...] = ("ducklake", "httpfs", "delta"),
) -> None:
    storage.setup_duckgres_session(conn, extensions)
