"""
DuckLake query-client surface for managed_warehouse.

Connect to managed Trino, compile queries for managed DuckLake data, and run queries against
an org's duckgres server. This surface serves the endpoints shadow path, data-modeling
materialization, and the duckling backfill.

Delegates to ``client`` at call time rather than re-exporting its functions: a bound
re-export would freeze a copy that ``@patch`` on the source module never reaches. The
result types live in ``facade.contracts``.
"""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING

from products.managed_warehouse.backend import client
from products.managed_warehouse.backend.facade.contracts import (
    ManagedWarehouseTrinoConnectionUnavailable,
    TrinoExpansionMode,
)
from products.managed_warehouse.backend.service_credentials import (
    ServiceCredential,
    ServiceCredentialUnavailable,
    mint_service_credential,
    refresh_service_credential,
)

if TYPE_CHECKING:
    from trino.dbapi import Connection

    from posthog.schema import HogQLQuery

    from posthog.hogql.transforms.trino.manifest import TrinoCatalogManifest

    from posthog.models.team.team import Team
    from posthog.models.user import User

    from products.managed_warehouse.backend.facade.contracts import (
        DuckLakeCompiledQuery,
        DuckLakeQueryResult,
        DuckLakeS3Secret,
        DuckLakeTableResult,
        ManagedWarehouseTrinoConnection,
        TrinoCompiledQuery,
    )
    from products.managed_warehouse.backend.service_credentials import ServiceCredential

__all__ = [
    "ServiceCredential",
    "ServiceCredentialUnavailable",
    "ManagedWarehouseTrinoConnectionUnavailable",
    "compile_hogql_to_ducklake_sql",
    "compile_hogql_to_trino_sql",
    "connect_managed_warehouse_trino",
    "execute_ducklake_create_table",
    "execute_ducklake_query",
    "make_duckgres_conninfo",
    "mint_service_credential",
    "refresh_service_credential",
    "resolve_managed_warehouse_trino_connection",
]


def resolve_managed_warehouse_trino_connection(organization_id: str) -> ManagedWarehouseTrinoConnection:
    from products.managed_warehouse.backend.trino_connection import (  # noqa: PLC0415 -- keep the optional connection path off startup paths
        resolve_managed_warehouse_trino_connection as _resolve_managed_warehouse_trino_connection,
    )

    return _resolve_managed_warehouse_trino_connection(organization_id)


def connect_managed_warehouse_trino(organization_id: str) -> AbstractContextManager[Connection]:
    from products.managed_warehouse.backend.trino_connection import (  # noqa: PLC0415 -- keep the optional connection path off startup paths
        connect_managed_warehouse_trino as _connect_managed_warehouse_trino,
    )

    return _connect_managed_warehouse_trino(organization_id)


def compile_hogql_to_trino_sql(
    team_id: int,
    query: HogQLQuery,
    *,
    team: Team | None = None,
    user: User | None = None,
    bypass_warehouse_access_control: bool = False,
    include_hogql: bool = False,
    expansion_mode: TrinoExpansionMode = TrinoExpansionMode.PURE,
    catalog_manifest: TrinoCatalogManifest | None = None,
) -> TrinoCompiledQuery:
    from products.managed_warehouse.backend.trino_compiler import (  # noqa: PLC0415 -- keep the optional compiler off startup paths
        compile_hogql_to_trino_sql as _compile_hogql_to_trino_sql,
    )

    return _compile_hogql_to_trino_sql(
        team_id,
        query,
        team=team,
        user=user,
        bypass_warehouse_access_control=bypass_warehouse_access_control,
        include_hogql=include_hogql,
        expansion_mode=expansion_mode,
        catalog_manifest=catalog_manifest,
    )


def make_duckgres_conninfo(
    team_id: int,
    *,
    organization_id: str | None = None,
    service_credential: ServiceCredential | None = None,
    application_name: str = "posthog",
) -> str:
    return client.make_duckgres_conninfo(
        team_id,
        organization_id=organization_id,
        service_credential=service_credential,
        application_name=application_name,
    )


def compile_hogql_to_ducklake_sql(
    team_id: int,
    query: HogQLQuery,
    *,
    team: Team | None = None,
    user: User | None = None,
    bypass_warehouse_access_control: bool = False,
) -> DuckLakeCompiledQuery:
    return client.compile_hogql_to_ducklake_sql(
        team_id,
        query,
        team=team,
        user=user,
        bypass_warehouse_access_control=bypass_warehouse_access_control,
    )


def execute_ducklake_query(
    team_id: int,
    *,
    sql: str | None = None,
    query: HogQLQuery | None = None,
    organization_id: str | None = None,
    team: Team | None = None,
    user: User | None = None,
    bypass_warehouse_access_control: bool = False,
) -> DuckLakeQueryResult:
    return client.execute_ducklake_query(
        team_id,
        sql=sql,
        query=query,
        organization_id=organization_id,
        team=team,
        user=user,
        bypass_warehouse_access_control=bypass_warehouse_access_control,
    )


def execute_ducklake_create_table(
    team_id: int,
    sql: str,
    schema_name: str,
    table_name: str,
    values: dict[str, object] | None = None,
    *,
    organization_id: str | None = None,
    s3_secrets: Sequence[DuckLakeS3Secret] = (),
) -> DuckLakeTableResult:
    return client.execute_ducklake_create_table(
        team_id,
        sql,
        schema_name,
        table_name,
        values,
        organization_id=organization_id,
        s3_secrets=s3_secrets,
    )
