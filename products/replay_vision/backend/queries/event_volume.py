import datetime as dt
from collections.abc import Sequence

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

# The same window the visited pages and the matched actions use, so one briefing can put a page, an
# action and an event next to each other and have their counts mean the same thing.
_EVENT_WINDOW_DAYS = 7
# Events are counted in one query, so the whole measurement shares this budget.
_EVENT_QUERY_MAX_EXECUTION_SECONDS = 5


def recent_event_sessions(
    *,
    team: Team,
    event_names: Sequence[str],
    window_days: int = _EVENT_WINDOW_DAYS,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
) -> dict[str, int]:
    """How many sessions each event fired in over a recent window, keyed by event name.

    An event definition only records that a name was seen, so ordering a briefing by `last_seen_at`
    ranks an event that fired twice yesterday above one that fires in every session. A model picking
    a recording filter needs the second one, and only a measured session count tells them apart.

    A name absent from the result fired in no session in the window, which is exactly the event a
    filter must not use: events AND with the rest of the filter, so a dead one takes the whole scan
    to zero.

    Counts sessions that fired the event, the same way action volume does, rather than only the
    sessions a scanner could watch. The two are then comparable to each other; both overstate what
    is scannable by the short sessions the sweep skips.

    Matches names exactly, because `event` is the third column of the events sort key and wrapping
    it would read the whole window. Callers pass the team's own spelling.

    Raises on query failure, so the caller decides whether a missing measurement is fatal.
    """
    names = list(dict.fromkeys(name for name in event_names if name))
    if not names:
        return {}

    window_start = dt.datetime.now(dt.UTC) - dt.timedelta(days=window_days)
    query = parse_select(
        """
        SELECT event, count(DISTINCT `$session_id`) AS sessions
        FROM events
        WHERE timestamp >= {window_start}
          AND event IN {names}
          AND notEmpty(`$session_id`)
        GROUP BY event
        """,
        placeholders={
            "window_start": ast.Constant(value=window_start),
            "names": ast.Constant(value=names),
        },
    )

    tag_queries(team_id=team.id, product=Product.REPLAY_VISION, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ReplayVisionEventVolumeQuery",
        # "throw", not "break": a partial aggregate reads as a busy event that went quiet, which is
        # the distinction this query exists to make.
        settings=HogQLGlobalSettings(
            max_execution_time=_EVENT_QUERY_MAX_EXECUTION_SECONDS, timeout_overflow_mode="throw"
        ),
        ch_user=ch_user,
    )
    return {str(name): int(sessions) for name, sessions in (response.results or [])}
