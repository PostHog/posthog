"""Fetch a team's known feature-flag keys and event names.

These are inputs to the "blast radius" scan: we look for any of these
strings as literals in the diff to catch references our call-shape regex
misses (wrapped SDKs, const-indirected keys, config-driven names, etc.).
"""

from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.models import FeatureFlag

if TYPE_CHECKING:
    from posthog.models import Team


def fetch_team_flag_keys(team: "Team", limit: int = 1000) -> list[str]:
    """Return non-deleted flag keys for the team, newest first.

    Caps to ``limit`` to keep the substring scan bounded — at >1000 active
    flags the long tail is rarely PR-relevant.
    """
    return [
        k
        for k in FeatureFlag.objects.filter(team=team, deleted=False)
        .order_by("-id")
        .values_list("key", flat=True)[:limit]
        if k
    ]


def fetch_team_event_names(team: "Team", lookback_days: int = 90, limit: int = 500) -> list[str]:
    """Return the top-N most-active event names on the team in the window.

    Internal events ($-prefixed: $pageview, $autocapture, etc.) are excluded —
    a PR rarely "adds" those, and matching them would generate noise.
    """
    response = execute_hogql_query(
        query="""
            SELECT event, count() AS c
            FROM events
            WHERE timestamp > now() - toIntervalDay({lookback_days})
              AND NOT startsWith(event, '$')
            GROUP BY event
            ORDER BY c DESC
            LIMIT {limit}
        """,
        team=team,
        placeholders={
            "lookback_days": ast.Constant(value=lookback_days),
            "limit": ast.Constant(value=limit),
        },
    )
    return [row[0] for row in (response.results or []) if row and row[0]]
