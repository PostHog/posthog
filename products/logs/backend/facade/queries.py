"""Query-runner surface of the logs facade.

Core's query-runner registry (server-side CSV export) and HogQL tooling
construct the logs runner through this module instead of reaching into
internals. The runner class itself is re-exported because registry-style
consumers need class identity (``isinstance`` dispatch), which a data
contract cannot provide.
"""

from typing import TYPE_CHECKING, Any

from products.logs.backend.logs_query_runner import LogsQueryRunner

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers, LogsQuery

    from posthog.hogql.timings import HogQLTimings

    from posthog.hogql_queries.query_runner import LimitContext
    from posthog.models.team import Team
    from posthog.models.user import User

__all__ = ["LogsQueryRunner", "build_logs_query_runner"]


def build_logs_query_runner(
    query: "LogsQuery | dict[str, Any]",
    team: "Team",
    *,
    timings: "HogQLTimings | None" = None,
    modifiers: "HogQLQueryModifiers | None" = None,
    limit_context: "LimitContext | None" = None,
    user: "User | None" = None,
) -> LogsQueryRunner:
    return LogsQueryRunner(
        query=query,
        team=team,
        timings=timings,
        modifiers=modifiers,
        limit_context=limit_context,
        user=user,
    )
