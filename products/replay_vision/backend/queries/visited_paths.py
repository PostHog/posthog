import datetime as dt

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

# One week is enough to describe a product's surfaces and short enough to partition-prune.
_PATH_WINDOW_DAYS = 7
# The list goes into a model prompt, so it has to stay small enough to fit alongside everything else.
_MAX_PATHS = 300
# Below this a path is one person's visit, not a surface of the product.
_MIN_SESSIONS_PER_PATH = 5
_PATH_QUERY_MAX_EXECUTION_SECONDS = 5

# Identifiers in a path make one surface look like thousands. A UUID first, so its digit runs are not
# eaten by the numeric rule, then bare numeric segments.
_UUID_SEGMENT = r"/[0-9a-fA-F]{8}-[0-9a-fA-F-]{20,}"
_NUMERIC_SEGMENT = r"/[0-9]+"
_ID_PLACEHOLDER = "/:id"


@frozen
class VisitedPath:
    # Identifier segments are collapsed, so this reads "/invoice/:id" rather than "/invoice/8814".
    pathname: str
    sessions: int


def fetch_visited_paths(
    *,
    team: Team,
    window_days: int = _PATH_WINDOW_DAYS,
    limit: int = _MAX_PATHS,
    min_sessions: int = _MIN_SESSIONS_PER_PATH,
    ch_user: ClickHouseUser = ClickHouseUser.APP,
) -> tuple[VisitedPath, ...]:
    """The product's page paths, busiest first, for grounding a model that reads a person's goal.

    Someone asks about "money" and the product calls it "billing". Only a model bridges that, and only
    if it can see the real pages, so this returns a list short enough to put in a prompt.

    Collapsing identifiers is what makes that list short. Measured on a project with a million sessions
    a week: 991,985 distinct paths fall to 122,507 once identifier segments collapse, and to about
    1,800 at a five-session floor. Without the collapse, a thousand invoice pages crowd out the rest.

    Reads `all_urls` because that is the column a `visited_page` recording filter compiles against, so
    every path here matches a non-zero number of sessions. Counts only sessions long and active enough
    for a scanner to observe, using the sweep's own bounds: a landing page collects many short visits
    that no scanner will ever watch, and counting them overstates the page and mis-orders the list.

    Raises on failure; the caller decides whether missing grounding is fatal.
    """
    window_start = dt.datetime.now(dt.UTC) - dt.timedelta(days=window_days)
    query = parse_select(
        """
        SELECT pathname, count(DISTINCT session_id) AS sessions
        FROM (
            SELECT
                session_id,
                replaceRegexpAll(
                    replaceRegexpAll(
                        arrayJoin(arrayDistinct(arrayMap(url -> path(url), urls))),
                        {uuid_segment},
                        {id_placeholder}
                    ),
                    {numeric_segment},
                    {id_placeholder}
                ) AS pathname
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
        WHERE pathname != ''
        GROUP BY pathname
        HAVING sessions >= {min_sessions}
        ORDER BY sessions DESC, pathname ASC
        LIMIT {limit}
        """,
        placeholders={
            "window_start": ast.Constant(value=window_start),
            "uuid_segment": ast.Constant(value=_UUID_SEGMENT),
            "numeric_segment": ast.Constant(value=_NUMERIC_SEGMENT),
            "id_placeholder": ast.Constant(value=_ID_PLACEHOLDER),
            "min_duration": ast.Constant(value=MIN_SESSION_DURATION_FOR_VIDEO_SCANNER_S),
            "min_active": ast.Constant(value=MIN_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S),
            "max_active": ast.Constant(value=MAX_ACTIVE_SECONDS_FOR_VIDEO_SCANNER_S),
            "min_sessions": ast.Constant(value=min_sessions),
            "limit": ast.Constant(value=limit),
        },
    )

    tag_queries(team_id=team.id, product=Product.REPLAY_VISION, feature=Feature.QUERY)
    response = execute_hogql_query(
        query=query,
        team=team,
        query_type="ReplayVisionVisitedPathsQuery",
        # "throw", not "break": on "break" ClickHouse returns partial aggregates, so the counts would
        # be quietly wrong and the busiest-first order would be whatever it read first. Measured well
        # inside this budget on a project with a million sessions a week.
        settings=HogQLGlobalSettings(
            max_execution_time=_PATH_QUERY_MAX_EXECUTION_SECONDS, timeout_overflow_mode="throw"
        ),
        ch_user=ch_user,
    )
    return tuple(VisitedPath(pathname=str(row[0]), sessions=int(row[1])) for row in response.results or [])
