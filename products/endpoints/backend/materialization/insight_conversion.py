from typing import Any

from posthog.schema import HogQLQuery, HogQLQueryModifiers

from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.team import Team

from products.endpoints.backend.materialization.series_index import inject_series_index

# Query kinds that have a corresponding transformer and should receive a __series_index column.
_SERIES_INDEX_QUERY_TYPES = {"TrendsQuery", "LifecycleQuery", "RetentionQuery"}


def convert_insight_query_to_hogql(query: dict[str, Any], team: Team) -> dict[str, Any]:
    query_kind = query.get("kind")

    if query_kind == "HogQLQuery":
        return query

    query_runner = get_query_runner(
        query=query,
        team=team,
        timings=HogQLTimings(),
        modifiers=HogQLQueryModifiers(),
    )

    combined_query_ast = query_runner.to_query()

    if query_kind in _SERIES_INDEX_QUERY_TYPES:
        inject_series_index(combined_query_ast)

    hogql_string = to_printed_hogql(combined_query_ast, team=team, modifiers=query_runner.modifiers)

    result = HogQLQuery(query=hogql_string, modifiers=query_runner.modifiers).model_dump()
    if "variables" in query:
        result["variables"] = query["variables"]
    return result
