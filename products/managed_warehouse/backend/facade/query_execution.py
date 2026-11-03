from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.schema import DatabaseSchemaQuery, DatabaseSchemaQueryResponse, HogQLQuery, HogQLQueryResponse

    from posthog.hogql.constants import HogQLGlobalSettings, LimitContext
    from posthog.hogql.timings import HogQLTimings

    from posthog.models import Team, User

    from products.access_control.backend.facade.user_access_control import UserAccessControl


def validate_managed_trino_raw_access(team: Team, user: User | None) -> None:
    from products.managed_warehouse.backend.query_execution import (
        validate_managed_trino_raw_access as validate,  # noqa: PLC0415 -- query execution is optional during Django startup
    )

    validate(team, user)


def validate_managed_trino_query(query: HogQLQuery, team: Team, user: User | None) -> None:
    from products.managed_warehouse.backend.query_execution import (
        validate_managed_trino_query as validate,  # noqa: PLC0415 -- query compilation is optional during Django startup
    )

    validate(query, team, user)


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
    from products.managed_warehouse.backend.query_execution import (
        execute_managed_trino_query as execute,  # noqa: PLC0415 -- query compilation is optional during Django startup
    )

    return execute(
        query,
        team=team,
        user=user,
        user_access_control=user_access_control,
        settings=settings,
        timings=timings,
        limit_context=limit_context,
    )


def get_managed_trino_schema(
    query: DatabaseSchemaQuery, *, team: Team, user: User | None
) -> DatabaseSchemaQueryResponse:
    from products.managed_warehouse.backend.query_schema import (
        get_managed_trino_schema as get_schema,  # noqa: PLC0415 -- keeps optional Trino drivers off Django startup
    )

    return get_schema(query, team=team, user=user)
