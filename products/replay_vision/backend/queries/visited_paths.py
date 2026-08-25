import datetime as dt
from collections.abc import Sequence

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team

from products.replay_vision.backend.session_limits import (
    MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S,
    MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S,
)

# One week is enough to rank a product's surfaces and short enough to partition-prune.
_PATH_WINDOW_DAYS = 7
# Caps how many *matching* paths come back. The caller shows a handful and filters on fewer still.
_MAX_MATCHING_PATHS = 200
_PATH_QUERY_MAX_EXECUTION_SECONDS = 5


@frozen
class RankedPath:
    pathname: str
    sessions: int


def fetch_matching_paths(
    *,
    team: Team,
    terms: Sequence[str],
    window_days: int = _PATH_WINDOW_DAYS,
    limit: int = _MAX_MATCHING_PATHS,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
) -> tuple[RankedPath, ...]:
    """Page paths containing any of `terms`, ranked by how many scanner-eligible sessions touched each.

    `terms` selects; volume only orders. A team must be able to scan a page that launched yesterday,
    so a page is never dropped for being quiet. Ordering by volume decides which of several matching
    pages the caller most likely meant, and which ones earn a place in the filter.

    Match the terms loosely here and score them precisely in the caller. This runs a substring match,
    so it returns a superset; the caller then applies the real token rules. Pass stems rather than
    whole words for that reason.

    Reads `all_urls` because that is the column a `visited_page` recording filter compiles against, so
    every path returned here is guaranteed to match a non-zero number of sessions. Ranking pageview
    events instead would surface pages that are busy but barely recorded, which is how a filter built
    from them ends up matching nothing.

    Counts only sessions long and active enough for a scanner to observe, using the same bounds as the
    sweep's own gate. A landing page collects many short bounces that no scanner will ever watch, so
    counting every recording both overstates the volume and mis-orders the ranking against it.

    Raises on failure; the caller decides whether a missing ranking is fatal.
    """
    if not terms:
        return ()
    window_start = dt.datetime.now(dt.UTC) - dt.timedelta(days=window_days)
    query = parse_select(
        """
        SELECT pathname, count(DISTINCT session_id) AS sessions
        FROM (
            SELECT session_id, arrayJoin(arrayDistinct(arrayMap(url -> path(url), urls))) AS pathname
            FROM (
                SELECT session_id, groupUniqArrayArray(all_urls) AS urls
                FROM raw_session_replay_events
                WHERE min_first_timestamp >= {window_start}
                GROUP BY session_id
                HAVING dateDiff('second', min(min_first_timestamp), max(max_last_timestamp)) >= {min_duration}
                   AND sum(active_milliseconds) / 1000 >= {min_active}
                   AND sum(active_milliseconds) / 1000 <= {max_active}
            )
        )
        WHERE pathname != '' AND multiSearchAnyCaseInsensitive(pathname, {terms})
        GROUP BY pathname
        ORDER BY sessions DESC, pathname ASC
        LIMIT {limit}
        """,
        placeholders={
            "window_start": ast.Constant(value=window_start),
            "terms": ast.Array(exprs=[ast.Constant(value=term) for term in terms]),
            "min_duration": ast.Constant(value=MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S),
            "min_active": ast.Constant(value=MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S),
            "max_active": ast.Constant(value=MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S),
            "limit": ast.Constant(value=limit),
        },
    )

    tag_queries(team_id=team.id, product=Product.REPLAY_VISION, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ReplayVisionMatchingPathsQuery",
        # "throw", not "break": on "break" ClickHouse returns partial aggregates, so `sessions` would
        # be silently undercounted and the ranking would be whatever it read first. The caller reports
        # the failure as a degraded source instead, which is honest. Measured well inside this budget
        # on a project with a million sessions a week.
        settings=HogQLGlobalSettings(
            max_execution_time=_PATH_QUERY_MAX_EXECUTION_SECONDS, timeout_overflow_mode="throw"
        ),
        ch_user=ch_user,
    )
    return tuple(RankedPath(pathname=str(row[0]), sessions=int(row[1])) for row in response.results or [])
