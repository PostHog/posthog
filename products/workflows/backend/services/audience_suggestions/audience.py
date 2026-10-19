"""The audiences a suggestion can describe: the cohort that holds them, and how many of them have an email address."""

from typing import Any

from posthog.schema import HogQLQueryResponse, ProductKey

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models import Team

from products.workflows.backend.facade.contracts import AudienceKind

# A lapsed person did the event within this many days, but not within the suggestion's window.
LAPSED_LOOKBACK_DAYS = 90
_COUNT_TIMEOUT_SECONDS = 30
_COUNT_MAX_BYTES = 4_000_000_000
# PostHog events that stand for being active in the product.
ACTIVITY_EVENTS = frozenset({"$pageview", "$screen"})
# pinned: broadcast email steps send to {{ person.properties.email }}
EMAIL_PROPERTY = "email"


def cohort_filters(
    *, kind: AudienceKind, event: str, missing_event: str | None, window_days: int, min_count: int | None
) -> dict[str, Any]:
    """A dynamic cohort definition for the audience. People without an email address are left out, because a
    broadcast cannot reach them and the wizard would count them."""
    match kind:
        case "not_yet":
            behavior = [_performed(event, window_days), _performed(missing_event or "", window_days, negation=True)]
        case "regulars":
            behavior = [
                {
                    "key": event,
                    "type": "behavioral",
                    "value": "performed_event_multiple",
                    "event_type": "events",
                    "operator": "gte",
                    "operator_value": min_count or 1,
                    "time_value": window_days,
                    "time_interval": "day",
                }
            ]
        case "lapsed":
            behavior = [_performed(event, LAPSED_LOOKBACK_DAYS), _performed(event, window_days, negation=True)]
    email = {"key": EMAIL_PROPERTY, "type": "person", "operator": "is_set", "value": "is_set"}
    return {"properties": {"type": "AND", "values": [{"type": "AND", "values": [*behavior, email]}]}}


def reachable_count(
    team: Team, *, kind: AudienceKind, event: str, missing_event: str | None, window_days: int, min_count: int | None
) -> int:
    """How many people match the cohort definition and have an email address. Windows start at
    the start of the day, like the cohort's relative dates, so the card and the calculated cohort agree."""
    placeholders: dict[str, ast.Expr] = {
        "event": ast.Constant(value=event),
        "window": ast.Constant(value=window_days),
        "email": ast.Field(chain=["properties", EMAIL_PROPERTY]),
    }
    match kind:
        case "not_yet":
            placeholders["missing"] = ast.Constant(value=missing_event or "")
            inner = """
                SELECT person_id
                FROM events
                WHERE timestamp >= toStartOfDay(now() - toIntervalDay({window})) AND event IN ({event}, {missing})
                GROUP BY person_id
                HAVING countIf(event = {event}) > 0 AND countIf(event = {missing}) = 0
            """
        case "regulars":
            placeholders["min_count"] = ast.Constant(value=min_count or 1)
            inner = """
                SELECT person_id
                FROM events
                WHERE timestamp >= toStartOfDay(now() - toIntervalDay({window})) AND event = {event}
                GROUP BY person_id
                HAVING count() >= {min_count}
            """
        case "lapsed":
            placeholders["lookback"] = ast.Constant(value=LAPSED_LOOKBACK_DAYS)
            inner = """
                SELECT person_id
                FROM events
                WHERE timestamp >= toStartOfDay(now() - toIntervalDay({lookback})) AND event = {event}
                GROUP BY person_id
                HAVING max(timestamp) < toStartOfDay(now() - toIntervalDay({window}))
            """
    # The email comes from the person, not the events, because the send reads it from the person.
    query = parse_select(
        "SELECT count() FROM {matched} WHERE person_id IN (SELECT id FROM persons WHERE notEmpty(toString({email})))",
        placeholders={"matched": parse_select(inner, placeholders=placeholders), "email": placeholders["email"]},
    )
    response = _run(team, query, "workflows_audience_suggestions_size")
    rows = response.results or []
    return int(rows[0][0]) if rows else 0


def activity_counts(team: Team) -> dict[str, int]:
    """Weekly counts of the PostHog events that stand for being active, which the project's own event counts skip."""
    query = parse_select(
        """
        SELECT event, count() FROM events
        WHERE timestamp >= now() - INTERVAL 7 DAY AND event IN {events}
        GROUP BY event
        """,
        placeholders={"events": ast.Tuple(exprs=[ast.Constant(value=name) for name in sorted(ACTIVITY_EVENTS)])},
    )
    response = _run(team, query, "workflows_audience_suggestions_activity")
    return {str(row[0]): int(row[1]) for row in response.results or [] if int(row[1]) > 0}


def _run(team: Team, query: ast.SelectQuery | ast.SelectSetQuery, query_type: str) -> HogQLQueryResponse:
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY)
    settings = HogQLGlobalSettings(
        max_execution_time=_COUNT_TIMEOUT_SECONDS,
        timeout_overflow_mode="throw",
        max_bytes_to_read=_COUNT_MAX_BYTES,
        # A partial count would cache a size that is too small for a week, so a big scan fails instead.
        read_overflow_mode="throw",
    )
    return execute_hogql_query(query=query, team=team, query_type=query_type, settings=settings)


def _performed(event: str, days: int, *, negation: bool = False) -> dict[str, Any]:
    return {
        "key": event,
        "type": "behavioral",
        "value": "performed_event",
        "event_type": "events",
        "time_value": days,
        "time_interval": "day",
        "negation": negation,
    }
