from posthog.schema import HogQLQuery

from posthog.hogql.direct_sql.adapter import DirectQueryResult
from posthog.hogql.direct_sql.trino_adapter import (
    TrinoQueryRequest,
    ensure_read_only_raw_trino_statement,
    execute_trino_query,
)
from posthog.hogql.timings import HogQLTimings

from posthog.models import Team, User

from products.managed_warehouse.backend.facade.access import is_internal_warehouse
from products.managed_warehouse.backend.facade.contracts import TrinoExpansionMode
from products.managed_warehouse.backend.trino_compiler import compile_hogql_to_trino_sql
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino


def query_internal_warehouse(team: Team, user: User, sql: str, language: str) -> DirectQueryResult:
    if not user.is_active or not user.is_staff or not is_internal_warehouse(team.organization_id):
        raise PermissionError("Internal warehouse preview requires staff access.")
    values = None
    if language == "hogql":
        compiled = compile_hogql_to_trino_sql(
            team.id,
            HogQLQuery(query=sql),
            team=team,
            user=user,
            expansion_mode=TrinoExpansionMode.DJANGO,
            limit_top_select=True,
        )
        sql, values = compiled.sql, compiled.values
    return execute_trino_query(
        TrinoQueryRequest(
            sql=ensure_read_only_raw_trino_statement(sql),
            values=values,
            timeout_seconds=60,
            timings=HogQLTimings(),
            team_id=team.id,
        ),
        connect_managed_warehouse_trino(
            str(team.organization_id), principal=f"posthog:internal-preview:user:{user.id}"
        ),
    )
