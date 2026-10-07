from __future__ import annotations

from typing import TYPE_CHECKING

import posthoganalytics

from posthog.schema import HogQLQuery, HogQLQueryResponse

from posthog.hogql.direct_sql.trino_adapter import (
    DIRECT_TRINO_DEFAULT_STATEMENT_TIMEOUT_SECONDS,
    TrinoQueryRequest,
    ensure_read_only_raw_trino_statement,
    execute_trino_query,
)
from posthog.hogql.errors import ExposedHogQLError

from posthog.clickhouse.query_tagging import get_query_tags
from posthog.direct_query_cancellation import build_direct_query_cancellation_token

from products.managed_warehouse.backend.facade.contracts import TrinoExpansionMode
from products.managed_warehouse.backend.trino_compiler import TrinoTargetUnavailable, compile_hogql_to_trino_sql
from products.managed_warehouse.backend.trino_connection import connect_managed_warehouse_trino

if TYPE_CHECKING:
    from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
    from posthog.hogql.timings import HogQLTimings

    from posthog.models import Team, User

    from products.access_control.backend.facade.user_access_control import UserAccessControl

MANAGED_TRINO_QUERY_FLAG = "managed-warehouse-trino-query"


def validate_managed_trino_query(query: HogQLQuery, team: Team, user: User | None) -> None:
    if user is None or not user.is_authenticated:
        raise ExposedHogQLError("Sign in to run a query against hosted Trino.")
    org_id = str(team.organization_id)
    try:
        enabled = posthoganalytics.feature_enabled(
            MANAGED_TRINO_QUERY_FLAG,
            org_id,
            groups={"organization": org_id},
            group_properties={"organization": {"id": org_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        enabled = False
    if not enabled:
        raise ExposedHogQLError(
            "Hosted Trino queries are not enabled for this organization. Select PostHog to run this query."
        )
    if query.connectionId or query.sendRawQuery:
        raise ExposedHogQLError("Hosted Trino runs HogQL queries. Clear the external connection and raw SQL mode.")


def execute_managed_trino_query(
    query: HogQLQuery,
    *,
    team: Team,
    user: User | None,
    user_access_control: UserAccessControl | None,
    settings: HogQLGlobalSettings,
    timings: HogQLTimings,
    limit_context: LimitContext | None,
) -> HogQLQueryResponse:
    validate_managed_trino_query(query, team, user)
    assert user is not None
    try:
        with timings.measure("trino_compile"):
            compiled = compile_hogql_to_trino_sql(
                team.pk,
                query,
                team=team,
                user=user,
                user_access_control=user_access_control,
                expansion_mode=TrinoExpansionMode.DJANGO,
                include_hogql=True,
                limit_top_select=True,
                limit_context=limit_context,
            )
    except TrinoTargetUnavailable as error:
        raise ExposedHogQLError("Hosted Trino is not ready for this project. Try again later.") from error
    tags = get_query_tags()
    cancellation_token = (
        build_direct_query_cancellation_token(tags.client_query_id, str(tags.celery_task_id))
        if tags.client_query_id is not None and tags.celery_task_id is not None
        else None
    )
    result = execute_trino_query(
        TrinoQueryRequest(
            sql=ensure_read_only_raw_trino_statement(compiled.sql),
            values=compiled.values,
            timeout_seconds=settings.max_execution_time or DIRECT_TRINO_DEFAULT_STATEMENT_TIMEOUT_SECONDS,
            timings=timings,
            team_id=team.pk,
            cancellation_token=cancellation_token,
        ),
        connect_managed_warehouse_trino(
            str(team.organization_id), principal=f"posthog:sql-editor:team:{team.pk}:user:{user.pk}"
        ),
    )
    return HogQLQueryResponse(
        query=query.query,
        hogql=compiled.hogql,
        clickhouse=compiled.sql,
        results=result.results,
        columns=result.print_columns,
        types=result.types,
        error=result.error,
        timings=timings.to_list(),
        modifiers=query.modifiers,
    )
