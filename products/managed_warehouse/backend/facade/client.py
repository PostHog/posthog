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
from uuid import UUID

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
    from products.managed_warehouse.backend.trino_compiler import PreparedTrinoCompiler

__all__ = [
    "request_model_alias_reconciliation",
    "ServiceCredential",
    "ServiceCredentialUnavailable",
    "ManagedWarehouseTrinoConnectionUnavailable",
    "compile_hogql_to_ducklake_sql",
    "compile_hogql_to_trino_sql",
    "connect_managed_warehouse_trino",
    "execute_ducklake_create_table",
    "execute_ducklake_query",
    "execute_trino_shadow_materialization",
    "execute_trino_model",
    "make_duckgres_conninfo",
    "mint_service_credential",
    "prepare_hogql_to_trino_compiler",
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


def execute_trino_shadow_materialization(
    *,
    organization_id: str,
    team_id: int,
    saved_query_id: str | UUID,
    source_query: object,
) -> DuckLakeTableResult:
    from products.managed_warehouse.backend.trino_materialization import (  # noqa: PLC0415 -- keeps the optional Trino driver off startup paths
        execute_trino_shadow_materialization as execute_shadow,
    )

    return execute_shadow(
        organization_id=organization_id,
        team_id=team_id,
        saved_query_id=saved_query_id,
        source_query=source_query,
    )


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


def prepare_hogql_to_trino_compiler(
    team_id: int,
    *,
    team: Team | None = None,
    catalog_manifest: TrinoCatalogManifest | None = None,
) -> PreparedTrinoCompiler:
    from products.managed_warehouse.backend.trino_compiler import (  # noqa: PLC0415 -- keep the optional compiler off startup paths
        prepare_hogql_to_trino_compiler as _prepare_hogql_to_trino_compiler,
    )

    return _prepare_hogql_to_trino_compiler(
        team_id,
        team=team,
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


async def request_model_alias_reconciliation(team_id: int, saved_query_id: str | None = None) -> None:
    from products.managed_warehouse.backend.model_alias_dispatch import request_model_alias_reconciliation as request

    await request(team_id, saved_query_id)


async def execute_trino_model(
    *, organization_id: str, team_id: int, saved_query_id: str | UUID, source_query: object
) -> DuckLakeTableResult:
    from products.managed_warehouse.backend.trino_execution import (  # noqa: PLC0415 -- keeps executor creation off startup paths
        run_trino_model,
    )
    from products.managed_warehouse.backend.trino_materialization import (  # noqa: PLC0415 -- keeps the optional Trino driver off startup paths
        execute_trino_shadow_materialization,
    )

    return await run_trino_model(
        lambda control: execute_trino_shadow_materialization(
            organization_id=organization_id,
            team_id=team_id,
            saved_query_id=saved_query_id,
            source_query=source_query,
            control=control,
        ),
    )
