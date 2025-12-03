from typing import Any

from posthog.schema import HogQLQuery, HogQLQueryModifiers

from posthog.hogql.printer import to_printed_hogql
from posthog.hogql.timings import HogQLTimings

from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models.team import Team


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

    hogql_string = to_printed_hogql(combined_query_ast, team=team, modifiers=query_runner.modifiers)

    return HogQLQuery(query=hogql_string, modifiers=query_runner.modifiers).model_dump()
