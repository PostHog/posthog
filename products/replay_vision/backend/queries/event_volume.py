import datetime as dt
from collections.abc import Sequence

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

# The same window the visited pages and actions lists use, so a briefing can compare an event
# against a page or an action on one scale.
_EVENT_WINDOW_DAYS = 7
# Every candidate event is counted in one grouped query, so the whole measurement shares this budget.
_EVENT_QUERY_MAX_EXECUTION_SECONDS = 5


def recent_event_sessions(
    *,
    team: Team,
    event_names: Sequence[str],
    window_days: int = _EVENT_WINDOW_DAYS,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
) -> dict[str, int]:
    """How many sessions each named event fired in over a recent window, keyed by event name.

    The candidate list surfaces an event by name match, which finds a rare-but-relevant event the
    volume ranking would bury, but tells the model nothing about how many sessions a filter on it
    would match. A name match cannot separate a busy event from one that fired twice last year. This
    count gives the model the same volume signal the pages and actions lists already carry, so it
    prefers an event a filter can actually catch sessions with.

    A count of 0, or an event absent from the result, means the event fired in no session in the
    window. Fails open: the caller shows the event without a count rather than losing the candidate.
    """
    names = list(dict.fromkeys(name for name in event_names if name))
    if not names:
        return {}

    window_start = dt.datetime.now(dt.UTC) - dt.timedelta(days=window_days)
    query = ast.SelectQuery(
        select=[
            ast.Field(chain=["event"]),
            ast.Call(name="uniq", args=[ast.Field(chain=["$session_id"])]),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=window_start),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["event"]),
                    right=ast.Constant(value=names),
                ),
            ]
        ),
        group_by=[ast.Field(chain=["event"])],
    )

    tag_queries(team_id=team.id, product=Product.REPLAY_VISION, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ReplayVisionEventVolumeQuery",
        settings=HogQLGlobalSettings(
            max_execution_time=_EVENT_QUERY_MAX_EXECUTION_SECONDS, timeout_overflow_mode="throw"
        ),
        ch_user=ch_user,
    )
    return {str(name): int(count) for name, count in (response.results or [])}
