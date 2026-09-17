from datetime import datetime
from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

if TYPE_CHECKING:
    from posthog.models import Team

# One page of spans can carry hundreds of distinct sessions. The lookup is one query either way,
# but the IN list grows with it, so cap how many sessions one request can ask about.
MAX_SESSIONS_PER_LOOKUP = 200


def count_session_exceptions(
    *, team: "Team", session_ids: list[str], date_from: datetime, date_to: datetime
) -> dict[str, int]:
    """Exceptions Error Tracking linked to an issue, per session, inside the window.

    A session with no such exceptions is absent from the result rather than present with a zero.
    """
    query = parse_select(
        """
        SELECT properties.$session_id AS session_id, count() AS exceptions
        FROM events
        WHERE event = '$exception'
          AND isNotNull(properties.$exception_issue_id)
          AND timestamp >= {date_from}
          AND timestamp <= {date_to}
          AND properties.$session_id IN {session_ids}
        GROUP BY session_id
        """,
        placeholders={
            "date_from": ast.Constant(value=date_from),
            "date_to": ast.Constant(value=date_to),
            "session_ids": ast.Tuple(exprs=[ast.Constant(value=session_id) for session_id in session_ids]),
        },
    )
    response = execute_hogql_query(query=query, team=team, query_type="TracingSessionErrorCountsQuery")
    return {str(session_id): int(exceptions) for session_id, exceptions in response.results or []}
