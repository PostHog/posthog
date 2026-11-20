"""The audiences a suggestion can describe: the cohort that holds them, and how many of them have an email address."""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from posthog.schema import HogQLQueryModifiers, HogQLQueryResponse, PersonsOnEventsMode, ProductKey

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models import Team, User

from products.workflows.backend.facade.contracts import AudienceKind, AudienceSuggestion

# A lapsed person did the event within this many days, but not within the suggestion's window.
LAPSED_LOOKBACK_DAYS = 90
_COUNT_TIMEOUT_SECONDS = 30
_COUNT_MAX_BYTES = 4_000_000_000
# A scan this size answers in about 3 seconds.
_COUNT_TARGET_ROWS = 10_000_000
# PostHog events that stand for being active in the product.
ACTIVITY_EVENTS = frozenset({"$pageview", "$screen"})
# pinned: broadcast email steps send to {{ person.properties.email }}
EMAIL_PROPERTY = "email"


def cohort_filters(
    *, kind: AudienceKind, event: str, missing_event: str | None, window_days: int, min_count: int | None
) -> dict[str, Any]:
    """The cohort definition for the audience. People without an email address are left out, because a
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
    # "is_set" also matches an empty string, which no send can reach.
    email = {"key": EMAIL_PROPERTY, "type": "person", "operator": "icontains", "value": "@"}
    return {"properties": {"type": "AND", "values": [{"type": "AND", "values": [*behavior, email]}]}}


def sample_denominator(audiences: Sequence[AudienceSuggestion], weekly_counts: Mapping[str, int]) -> int:
    """Which share of people to count, so the scan stays small however busy the audiences' events are."""
    weekly_rows = sum(weekly_counts.get(name, 0) for name in _event_names(audiences))
    return max(1, math.ceil(weekly_rows * _lookback_days(audiences) / 7 / _COUNT_TARGET_ROWS))


def reachable_counts(
    team: Team, audiences: Sequence[AudienceSuggestion], *, denominator: int = 1, user: User | None = None
) -> list[int]:
    """Roughly how many people in each audience have an email address, from one scan of the audiences' events. The
    scan misses an address set after the person's last scanned event, and the sample keeps one distinct ID in
    `denominator`, so a person with several IDs can look lapsed. Each window starts where the cohort's window starts."""
    if not audiences:
        return []
    matched = parse_select(
        """
        SELECT person_id, countIf({email} ILIKE '%@%') > 0 AS has_email
        FROM events
        WHERE timestamp >= toStartOfDay(now() - toIntervalDay({lookback})) AND event IN {events}
        GROUP BY person_id
        """,
        placeholders={
            # The send reads the address from the person, which events copy when they are captured.
            "email": ast.Field(chain=["person", "properties", EMAIL_PROPERTY]),
            "lookback": ast.Constant(value=_lookback_days(audiences)),
            "events": ast.Tuple(exprs=[ast.Constant(value=name) for name in sorted(_event_names(audiences))]),
        },
    )
    assert isinstance(matched, ast.SelectQuery) and matched.select_from is not None
    if denominator > 1:
        matched.select_from.sample = ast.SampleExpr(
            sample_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=denominator))
        )
    aliases = [f"audience_{index}" for index in range(len(audiences))]
    matched.select.extend(
        ast.Alias(alias=alias, expr=_matches(audience)) for alias, audience in zip(aliases, audiences)
    )
    query = ast.SelectQuery(
        select=[
            parse_expr("countIf({matched} AND has_email)", placeholders={"matched": ast.Field(chain=[alias])})
            for alias in aliases
        ],
        select_from=ast.JoinExpr(table=matched),
    )
    response = _run(team, query, "workflows_audience_suggestions_size", user)
    row = (response.results or [[0] * len(audiences)])[0]
    return [int(count) * denominator for count in row]


def _event_names(audiences: Sequence[AudienceSuggestion]) -> set[str]:
    return {name for audience in audiences for name in (audience.event, audience.missing_event) if name}


def _lookback_days(audiences: Sequence[AudienceSuggestion]) -> int:
    return max(LAPSED_LOOKBACK_DAYS if audience.kind == "lapsed" else audience.window_days for audience in audiences)


def _matches(audience: AudienceSuggestion) -> ast.Expr:
    placeholders: dict[str, ast.Expr] = {
        "event": ast.Constant(value=audience.event),
        "since": parse_expr(
            "toStartOfDay(now() - toIntervalDay({window}))",
            placeholders={"window": ast.Constant(value=audience.window_days)},
        ),
        "window": ast.Constant(value=audience.window_days),
        "missing": ast.Constant(value=audience.missing_event or ""),
        "min_count": ast.Constant(value=audience.min_count or 1),
        "lookback": ast.Constant(value=LAPSED_LOOKBACK_DAYS),
    }
    match audience.kind:
        case "not_yet":
            template = """
                countIf(event = {event} AND timestamp >= {since}) > 0
                AND countIf(event = {missing} AND timestamp >= {since}) = 0
            """
        case "regulars":
            # The cohort counts repeat events over a rolling window that ends 5 seconds from now, not by the day.
            template = """
                countIf(
                    event = {event}
                    AND timestamp >= now() - toIntervalDay({window})
                    AND timestamp < now() + toIntervalSecond(5)
                ) >= {min_count}
            """
        case "lapsed":
            template = """
                countIf(event = {event} AND timestamp >= toStartOfDay(now() - toIntervalDay({lookback}))) > 0
                AND countIf(event = {event} AND timestamp >= {since}) = 0
            """
    return parse_expr(template, placeholders=placeholders)


def activity_counts(team: Team, user: User | None = None) -> dict[str, int]:
    """Weekly counts of the PostHog events that stand for being active, which the project's own event counts skip."""
    query = parse_select(
        """
        SELECT event, count() FROM events
        WHERE timestamp >= now() - INTERVAL 7 DAY AND event IN {events}
        GROUP BY event
        """,
        placeholders={"events": ast.Tuple(exprs=[ast.Constant(value=name) for name in sorted(ACTIVITY_EVENTS)])},
    )
    response = _run(team, query, "workflows_audience_suggestions_activity", user)
    return {str(row[0]): int(row[1]) for row in response.results or [] if int(row[1]) > 0}


def _run(
    team: Team, query: ast.SelectQuery | ast.SelectSetQuery, query_type: str, user: User | None
) -> HogQLQueryResponse:
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY)
    settings = HogQLGlobalSettings(
        max_execution_time=_COUNT_TIMEOUT_SECONDS,
        timeout_overflow_mode="throw",
        max_bytes_to_read=_COUNT_MAX_BYTES,
        # A partial count would cache a size that is too small for a week, so a big scan fails instead.
        read_overflow_mode="throw",
    )
    # The user's property access rules apply, so a masked email address counts nobody.
    return execute_hogql_query(
        query=query,
        team=team,
        query_type=query_type,
        settings=settings,
        # A person waits on the page for these cards.
        workload=Workload.ONLINE,
        # Merged persons count once, and the email comes from the events, so counting never reads the persons table.
        modifiers=HogQLQueryModifiers(personsOnEventsMode=PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS),
        user=user,
    )


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
