"""
DuckLake query-client surface for managed_warehouse.

Compile and run queries against an org's duckgres server — the endpoints shadow path,
the data-modeling materialization activity, and the duckling backfill.

Delegates to ``client`` at call time rather than re-exporting its functions: a bound
re-export would freeze a copy that ``@patch`` on the source module never reaches. The
result types live in ``facade.contracts``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from products.managed_warehouse.backend import client

if TYPE_CHECKING:
    from posthog.schema import HogQLQuery

    from posthog.models.team.team import Team
    from posthog.models.user import User

    from products.managed_warehouse.backend.facade.contracts import DuckLakeQueryResult, DuckLakeTableResult

__all__ = [
    "compile_hogql_to_ducklake_sql",
    "execute_ducklake_create_table",
    "execute_ducklake_query",
    "make_duckgres_conninfo",
]


def make_duckgres_conninfo(team_id: int, *, organization_id: str | None = None) -> str:
    return client.make_duckgres_conninfo(team_id, organization_id=organization_id)


def compile_hogql_to_ducklake_sql(
    team_id: int,
    query: HogQLQuery,
    *,
    team: Team | None = None,
    user: User | None = None,
    bypass_warehouse_access_control: bool = False,
) -> tuple[str, dict[str, object], str]:
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
) -> DuckLakeTableResult:
    return client.execute_ducklake_create_table(
        team_id,
        sql,
        schema_name,
        table_name,
        values,
        organization_id=organization_id,
    )
