import time
from typing import Any

from structlog import get_logger

from posthog.schema import EndpointRunRequest, HogQLQuery

from posthog.ducklake.client import execute_ducklake_query
from posthog.ducklake.common import get_duckgres_server_for_organization, is_dev_mode
from posthog.models import Team
from posthog.ph_client import ph_scoped_capture

from products.endpoints.backend.logic.strategies import strategy_for
from products.endpoints.backend.models import Endpoint, EndpointVersion

logger = get_logger(__name__)

SHADOW_EVENT = "ducklake_endpoint_exec_shadow"


def shadow_target_exists(team: Team) -> bool:
    # Local dev points at the dev duckgres config and has no provisioned DuckgresServer row.
    if is_dev_mode():
        return True
    return get_duckgres_server_for_organization(str(team.organization_id)) is not None


def build_ducklake_hogql_query(
    endpoint: Endpoint,
    version: EndpointVersion,
    team: Team,
    data: EndpointRunRequest,
    *,
    limit: int | None = None,
    offset: int | None = None,
) -> HogQLQuery:
    """Build the HogQL an endpoint would run against DuckLake, matching the inline path's
    variable overrides and pagination so the shadow mirrors what ClickHouse executed."""
    strategy = strategy_for(endpoint, version, team)
    query = strategy.prepare_inline_query(version.query.copy())
    if limit is not None:
        query, _ = strategy.apply_pagination(query, limit, offset or 0)
    plan = strategy.build_inline_plan(query, data)

    hogql_query = HogQLQuery(query=query["query"], variables=query.get("variables"))
    if plan.variables_override and hogql_query.variables:
        for override in plan.variables_override:
            if hogql_query.variables.get(override.variableId):
                hogql_query.variables[override.variableId] = override
    return hogql_query


def run_ducklake_shadow_comparison(
    *,
    team_id: int,
    endpoint_id: str,
    version_id: str,
    variables: dict[str, Any] | None,
    execution_type: str,
    clickhouse_cached: bool,
    clickhouse_ms: float,
    clickhouse_row_count: int | None,
    limit: int | None,
    offset: int | None,
) -> None:
    """Re-run an endpoint's HogQL against DuckLake and emit a comparison event. Runs in a
    Celery worker off the request path; must never raise into the caller."""
    try:
        team = Team.objects.get(pk=team_id)
        endpoint = Endpoint.objects.get(pk=endpoint_id, team_id=team_id)
        version = EndpointVersion.objects.get(pk=version_id, endpoint=endpoint)
    except (Team.DoesNotExist, Endpoint.DoesNotExist, EndpointVersion.DoesNotExist):
        logger.info(
            "ducklake_shadow_skip_missing_entity",
            team_id=team_id,
            endpoint_id=endpoint_id,
            version_id=version_id,
        )
        return

    if not shadow_target_exists(team):
        logger.info("ducklake_shadow_skip_no_server", team_id=team_id)
        return

    data = EndpointRunRequest(variables=variables)

    ducklake_ms: float | None = None
    ducklake_connect_ms: float | None = None
    ducklake_query_ms: float | None = None
    ducklake_row_count: int | None = None
    ducklake_error: str | None = None
    try:
        hogql_query = build_ducklake_hogql_query(endpoint, version, team, data, limit=limit, offset=offset)
        _start = time.monotonic()
        result = execute_ducklake_query(
            team_id,
            query=hogql_query,
            organization_id=str(team.organization_id),
            team=team,
            # Shadow comparisons run off-request after the endpoint query already executed.
            bypass_warehouse_access_control=True,
        )
        ducklake_ms = (time.monotonic() - _start) * 1000
        ducklake_connect_ms = result.connect_ms
        ducklake_query_ms = result.query_ms
        ducklake_row_count = len(result.results)
    except Exception as e:
        ducklake_error = f"{type(e).__name__}: {e}"
        logger.warning(
            "ducklake_shadow_query_failed",
            endpoint_name=endpoint.name,
            team_id=team_id,
            error=ducklake_error,
        )

    row_count_match: bool | None = None
    if ducklake_row_count is not None and clickhouse_row_count is not None:
        row_count_match = ducklake_row_count == clickhouse_row_count

    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(team.uuid),
            event=SHADOW_EVENT,
            properties={
                "team_id": team_id,
                "organization_id": str(team.organization_id),
                "endpoint_name": endpoint.name,
                "endpoint_version": version.version,
                "query_kind": "hogql",
                "execution_type": execution_type,
                "clickhouse_cached": clickhouse_cached,
                "clickhouse_ms": clickhouse_ms,
                "ducklake_ms": ducklake_ms,
                "ducklake_connect_ms": ducklake_connect_ms,
                "ducklake_query_ms": ducklake_query_ms,
                "clickhouse_row_count": clickhouse_row_count,
                "ducklake_row_count": ducklake_row_count,
                "row_count_match": row_count_match,
                "ducklake_error": ducklake_error,
                "has_variables": bool(variables),
            },
            groups={"organization": str(team.organization_id), "project": str(team_id)},
        )
