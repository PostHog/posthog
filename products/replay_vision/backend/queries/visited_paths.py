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
# On a large project the floor below leaves a few thousand paths; this keeps the busiest of them.
_MAX_PATHS = 300
# Below this a path is one person's visit, not a surface of the product.
_MIN_SESSIONS_PER_PATH = 5
# Visitors control their own URLs, so a fabricated path must not be able to blow up the prompt.
_MAX_PATHNAME_CHARS = 256
_PATH_QUERY_MAX_EXECUTION_SECONDS = 5

# Identifiers in a path make one surface look like thousands. Each rule matches a WHOLE segment
# between slashes — a partial match would eat the digits off a real page name and emit garbage
# ("/2fa" must never become "/:idfa"). Every rule except the numeric one also demands a digit, so a
# long real word is never mistaken for a token.
_SEGMENT_NUMERIC = r"^[0-9]+$"
_SEGMENT_DASHED_UUID = r"^[0-9a-fA-F-]{20,}$"
_SEGMENT_HEX = r"^[0-9a-fA-F]{12,}$"
_SEGMENT_TOKEN = r"^[a-zA-Z0-9]{16,}$"
_ANY_DIGIT = r"[0-9]"
# A path that is one all-digit segment is a page, not an ID: /404, /500.
_TOPLEVEL_NUMERIC_PATH = r"^/[0-9]+$"
_ID_PLACEHOLDER = ":id"


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

    Collapsing identifier segments is what makes the list short. A segment collapses to ":id" only
    when the whole segment is an identifier: all digits, a dashed UUID, a hex run, or a long token
    holding a digit. Measured on a project with a million sessions a week: 991,985 distinct paths fall
    to 117,569 collapsed, and the five-session floor leaves about 8,400; the limit then keeps the
    busiest of those. Known limit: short mixed identifiers ("/insights/AbC123xY") stay uncollapsed.

    The pathnames are visitor-controlled content — anyone can put any string in their own URL. Each is
    capped at a fixed length here, and the consumer must still fence the list as untrusted data, the
    way `scanner_draft.py` fences its briefing.

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
                substring(
                    if(
                        match(raw_path, {toplevel_numeric}),
                        raw_path,
                        arrayStringConcat(
                            arrayMap(
                                s -> multiIf(
                                    match(s, {segment_numeric}), {id_placeholder},
                                    match(s, {segment_dashed_uuid}) and match(s, {any_digit}), {id_placeholder},
                                    match(s, {segment_hex}) and match(s, {any_digit}), {id_placeholder},
                                    match(s, {segment_token}) and match(s, {any_digit}), {id_placeholder},
                                    s
                                ),
                                splitByChar('/', raw_path)
                            ),
                            '/'
                        )
                    ),
                    1, {max_pathname_chars}
                ) AS pathname
            FROM (
                SELECT
                    session_id,
                    arrayJoin(arrayDistinct(arrayMap(url -> path(url), groupUniqArrayArray(all_urls)))) AS raw_path
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
            "toplevel_numeric": ast.Constant(value=_TOPLEVEL_NUMERIC_PATH),
            "segment_numeric": ast.Constant(value=_SEGMENT_NUMERIC),
            "segment_dashed_uuid": ast.Constant(value=_SEGMENT_DASHED_UUID),
            "segment_hex": ast.Constant(value=_SEGMENT_HEX),
            "segment_token": ast.Constant(value=_SEGMENT_TOKEN),
            "any_digit": ast.Constant(value=_ANY_DIGIT),
            "id_placeholder": ast.Constant(value=_ID_PLACEHOLDER),
            "max_pathname_chars": ast.Constant(value=_MAX_PATHNAME_CHARS),
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
