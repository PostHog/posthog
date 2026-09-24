from datetime import datetime
from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

if TYPE_CHECKING:
    from posthog.models import Team

# One page of spans can carry hundreds of distinct ids. The lookup is one query either way,
# but the IN list grows with it, so cap how many ids one request can ask about.
MAX_IDS_PER_LOOKUP = 200


def _run(query: ast.SelectQuery | ast.SelectSetQuery, team: "Team", query_type: str) -> dict[str, int]:
    response = execute_hogql_query(query=query, team=team, query_type=query_type)
    return {str(key): int(exceptions) for key, exceptions in response.results or []}


def _window_placeholders(date_from: datetime, date_to: datetime) -> dict[str, ast.Expr]:
    return {
        "date_from": ast.Constant(value=date_from),
        "date_to": ast.Constant(value=date_to),
        # Explicit, because HogQL caps a select without a LIMIT at 100 rows, which is below the
        # ids one request may ask about. A row cut there would read as a clean id.
        "limit": ast.Constant(value=MAX_IDS_PER_LOOKUP),
    }


def count_trace_exceptions(
    *, team: "Team", trace_ids: list[str], date_from: datetime, date_to: datetime
) -> dict[str, int]:
    """Exceptions Error Tracking linked to an issue, per trace, inside the window.

    Keys come back lowercased. A trace with no such exceptions is absent from the result rather
    than present with a zero.
    """
    if not trace_ids:
        return {}
    query = parse_select(
        """
        SELECT lower(properties.$trace_id) AS trace_id, count() AS exceptions
        FROM events
        WHERE event = '$exception'
          AND isNotNull(properties.$exception_issue_id)
          AND timestamp >= {date_from}
          AND timestamp <= {date_to}
          AND lower(properties.$trace_id) IN {trace_ids}
        GROUP BY trace_id
        LIMIT {limit}
        """,
        placeholders={
            # Spans read their ids back as uppercase hex, while the SDKs write them lowercase, so
            # both sides are lowercased here. Compare the two raw and every count comes back zero.
            "trace_ids": ast.Constant(value=[trace_id.lower() for trace_id in trace_ids]),
            **_window_placeholders(date_from, date_to),
        },
    )
    return _run(query, team, "TracingTraceErrorCountsQuery")


def count_span_exceptions(
    *, team: "Team", span_ids: list[str], trace_ids: list[str], date_from: datetime, date_to: datetime
) -> dict[str, int]:
    """Exceptions Error Tracking linked to an issue, per span, inside the window.

    A span id is only unique within its trace, so the traces the spans belong to bound the match
    as well. Keys come back lowercased.
    """
    if not span_ids or not trace_ids:
        return {}
    query = parse_select(
        """
        SELECT lower(properties.$span_id) AS span_id, count() AS exceptions
        FROM events
        WHERE event = '$exception'
          AND isNotNull(properties.$exception_issue_id)
          AND timestamp >= {date_from}
          AND timestamp <= {date_to}
          AND lower(properties.$trace_id) IN {trace_ids}
          AND lower(properties.$span_id) IN {span_ids}
        GROUP BY span_id
        LIMIT {limit}
        """,
        placeholders={
            "span_ids": ast.Constant(value=[span_id.lower() for span_id in span_ids]),
            "trace_ids": ast.Constant(value=[trace_id.lower() for trace_id in trace_ids]),
            **_window_placeholders(date_from, date_to),
        },
    )
    return _run(query, team, "TracingSpanErrorCountsQuery")


def count_session_exceptions(
    *, team: "Team", session_ids: list[str], date_from: datetime, date_to: datetime
) -> dict[str, int]:
    """Exceptions Error Tracking linked to an issue, per session, inside the window.

    A session with no such exceptions is absent from the result rather than present with a zero.
    """
    if not session_ids:
        return {}
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
        LIMIT {limit}
        """,
        placeholders={
            "session_ids": ast.Constant(value=session_ids),
            **_window_placeholders(date_from, date_to),
        },
    )
    return _run(query, team, "TracingSessionErrorCountsQuery")
