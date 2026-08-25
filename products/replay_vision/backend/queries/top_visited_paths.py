import datetime as dt

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models import Team

# One week is enough to rank a product's surfaces and short enough to partition-prune.
_PATH_WINDOW_DAYS = 7
# The caller only ever shows a handful of these; the rest are the pool a scope phrase matches against.
_MAX_RANKED_PATHS = 200
_PATH_QUERY_MAX_EXECUTION_SECONDS = 5


@frozen
class RankedPath:
    pathname: str
    sessions: int


def fetch_top_visited_paths(
    *,
    team: Team,
    window_days: int = _PATH_WINDOW_DAYS,
    limit: int = _MAX_RANKED_PATHS,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
) -> tuple[RankedPath, ...]:
    """The product's page paths, ranked by how many recorded sessions touched each one.

    Reads `all_urls` because that is the column a `visited_page` recording filter compiles against, so
    every path returned here is guaranteed to match a non-zero number of sessions. Ranking pageview
    events instead would surface pages that are busy but barely recorded, which is how a filter built
    from them ends up matching nothing.

    Raises on failure; the caller decides whether a missing ranking is fatal.
    """
    window_start = dt.datetime.now(dt.UTC) - dt.timedelta(days=window_days)
    query = parse_select(
        """
        SELECT pathname, count(DISTINCT session_id) AS sessions
        FROM (
            SELECT session_id, arrayJoin(arrayDistinct(arrayMap(url -> path(url), all_urls))) AS pathname
            FROM raw_session_replay_events
            WHERE min_first_timestamp >= {window_start}
        )
        WHERE pathname != ''
        GROUP BY pathname
        ORDER BY sessions DESC, pathname ASC
        LIMIT {limit}
        """,
        placeholders={
            "window_start": ast.Constant(value=window_start),
            "limit": ast.Constant(value=limit),
        },
    )

    tag_queries(team_id=team.id, product=Product.REPLAY_VISION, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ReplayVisionTopVisitedPathsQuery",
        # "break" rather than the estimator's "throw": a partial ranking is still usable grounding,
        # where a partial count would be read as an exact one.
        settings=HogQLGlobalSettings(
            max_execution_time=_PATH_QUERY_MAX_EXECUTION_SECONDS, timeout_overflow_mode="break"
        ),
        ch_user=ch_user,
    )
    return tuple(RankedPath(pathname=str(row[0]), sessions=int(row[1])) for row in response.results or [])
