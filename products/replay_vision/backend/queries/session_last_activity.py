import datetime as dt

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models import Team

# Bounds the partition scan; a request waits for its sessions to end for far less than this.
_LOOKBACK = dt.timedelta(days=2)

# Kept well under HogQL's returned-row ceiling, so every chunk's explicit LIMIT can return each session.
_CHUNK_SIZE = 1000


def fetch_session_last_activity(*, team: Team, session_ids: list[str], now: dt.datetime) -> dict[str, dt.datetime]:
    """The last recorded moment of each session, keyed by session id. A session not recorded yet is absent."""
    tag_queries(team_id=team.id, product=Product.REPLAY_VISION, feature=Feature.QUERY)
    last_activity: dict[str, dt.datetime] = {}
    for start in range(0, len(session_ids), _CHUNK_SIZE):
        chunk = session_ids[start : start + _CHUNK_SIZE]
        # The LIMIT is explicit because HogQL caps a select without one at 100 rows, and a session cut off
        # there would read as still recording.
        query = parse_select(
            "SELECT session_id, max(max_last_timestamp) FROM raw_session_replay_events "
            "WHERE session_id IN {session_ids} AND min_first_timestamp >= {since} GROUP BY session_id LIMIT {limit}",
            placeholders={
                "session_ids": ast.Constant(value=chunk),
                "since": ast.Constant(value=now - _LOOKBACK),
                "limit": ast.Constant(value=len(chunk)),
            },
        )
        response = execute_hogql_query(query=query, team=team, query_type="ReplayVisionSessionLastActivityQuery")
        last_activity.update({str(row[0]): row[1] for row in response.results or []})
    return last_activity
