"""Empirical reach for a set of event names.

Mirrors `flag_reach.py` but queries the raw `events` table for the
supplied event names directly. Each requested name comes back with
users / sessions / call_count over the lookback window; names that
didn't fire in the window are returned with zeroed counts and
`has_data=False` so the UI can say "unknown" rather than "zero."
"""

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from .regime import is_server_side_signal

if TYPE_CHECKING:
    from posthog.models import Team

    from ..facade.contracts import EventReach


def _string_array(names: list[str]) -> ast.Array:
    return ast.Array(exprs=[ast.Constant(value=n) for n in names])


def compute_per_event_reach(team: "Team", names: list[str], lookback_days: int) -> list["EventReach"]:
    """Aggregate users / sessions / call_count per event name."""
    from ..facade.contracts import EventReach

    if not names:
        return []

    response = execute_hogql_query(
        query="""
            SELECT
                event AS name,
                uniq(person_id) AS users,
                uniq($session_id) AS sessions,
                count() AS calls
            FROM events
            WHERE event IN {event_names}
              AND timestamp > now() - toIntervalDay({lookback_days})
            GROUP BY name
        """,
        team=team,
        placeholders={
            "lookback_days": ast.Constant(value=lookback_days),
            "event_names": _string_array(names),
        },
    )

    by_name: dict[str, tuple[int, int, int]] = {}
    for row in response.results or []:
        name, users, sessions, calls = row
        by_name[name] = (int(users or 0), int(sessions or 0), int(calls or 0))

    out: list[EventReach] = []
    for name in names:
        users, sessions, calls = by_name.get(name, (0, 0, 0))
        out.append(
            EventReach(
                name=name,
                users_affected=users,
                sessions_affected=sessions,
                call_count=calls,
                has_data=name in by_name,
                is_server_side=is_server_side_signal(users, calls),
            )
        )
    return out
