"""How often each of the project's events fired in the last week, sampled for large teams, and the values its person
properties take."""

import json
import math
from collections.abc import Iterable

from posthog.schema import HogQLQueryResponse, ProductKey

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, tag_queries
from posthog.models import Team
from posthog.models.event.new_events_schema import use_new_events_schema

# Above this many events a week the counts are sampled. The estimate itself reads 1 in 100 events.
FULL_SCAN_MAX_WEEKLY_EVENTS = 20_000_000
_ESTIMATE_SAMPLE_DENOMINATOR = 100
_COUNT_TIMEOUT_SECONDS = 30
# Sampling is by distinct ID, so the volume estimate misses a busy event that a few sampled-out IDs send, like a
# server-side event, and an exact count can then hit it. Past this many bytes a count stops and keeps the partial
# result, which still ranks the events and clears the minimum weekly count.
_COUNT_MAX_BYTES = 2_000_000_000
MAX_EVENTS = 5000
_MAX_BRANCH_VALUES = 6
# Longer values are free text. The cap also bounds the size of the planner prompt.
_MAX_BRANCH_VALUE_LENGTH = 60
# A share needs far fewer events than a ranking, so its scan reads about this many whatever the project's size.
_SHARE_SAMPLE_EVENTS = 1_000_000
# PostHog's own events that mark a real moment, unlike the generic `$` events the planner must skip.
ALLOWED_POSTHOG_EVENTS = frozenset({"$conversation_ticket_created"})
MOBILE_LIBS = frozenset({"posthog-ios", "posthog-android", "posthog-react-native", "posthog-flutter"})


def weekly_counts(team: Team) -> dict[str, int]:
    """How often each of the project's own events fired in the last week. PostHog's generic `$` events are left out,
    except the few that mark a real moment."""
    # Small teams get exact counts, since a quiet event could vanish from a sample. Large teams only need the
    # ranking, so a sample keeps the scan at about the size of a small team's.
    sample_denominator = max(1, math.ceil(estimated_weekly_events(team) / FULL_SCAN_MAX_WEEKLY_EVENTS))
    counts = _count_events(team, sample_denominator, skip=frozenset())
    if sample_denominator > 1:
        # A sample can miss a quiet event, like a weekly sign-up, entirely. The events table is sorted by event name
        # within a day, so an exact count that skips the events the sample found reads few rows.
        counts.update(_count_events(team, 1, skip=frozenset(counts)))
    return counts


def estimated_weekly_events(team: Team) -> int:
    query = parse_select("SELECT count() FROM events WHERE timestamp >= now() - INTERVAL 7 DAY")
    if isinstance(query, ast.SelectQuery) and query.select_from is not None:
        query.select_from.sample = _sample(_ESTIMATE_SAMPLE_DENOMINATOR)
    response = _run_count(team, query, "workflows_data_suggestions_volume")
    rows = response.results or []
    return int(rows[0][0]) * _ESTIMATE_SAMPLE_DENOMINATOR if rows else 0


def mobile_share(team: Team) -> float:
    """The share of the project's app events that its mobile SDKs send, out of mobile and web together. Server-side
    events are left out, because a mobile app's backend often sends them too."""
    query = parse_select(
        """
        SELECT countIf(properties.$lib IN {mobile}), countIf(properties.$lib IN {app})
        FROM events
        WHERE timestamp >= now() - INTERVAL 1 DAY
        """,
        placeholders={"mobile": _strings(MOBILE_LIBS), "app": _strings(MOBILE_LIBS | {"web"})},
    )
    # The events table is sorted by event name, so a scan that stops at the read cap would count only the events
    # early in that order. A sample keeps the scan under the cap and spreads it over every event.
    sample_denominator = max(1, math.ceil(estimated_weekly_events(team) / 7 / _SHARE_SAMPLE_EVENTS))
    if sample_denominator > 1 and isinstance(query, ast.SelectQuery) and query.select_from is not None:
        query.select_from.sample = _sample(sample_denominator)
    rows = _run_count(team, query, "workflows_data_suggestions_mobile_share").results or []
    if not rows or not rows[0][1]:
        return 0.0
    return int(rows[0][0]) / int(rows[0][1])


def _count_events(team: Team, sample_denominator: int, *, skip: frozenset[str]) -> dict[str, int]:
    query = parse_select(
        """
        SELECT event, count() AS weekly_count
        FROM events
        WHERE timestamp >= now() - INTERVAL 7 DAY
            AND (NOT startsWith(event, '$') OR event IN {allowed})
            AND event NOT IN {skip}
        GROUP BY event
        ORDER BY weekly_count DESC
        LIMIT {limit}
        """,
        placeholders={
            "allowed": _strings(ALLOWED_POSTHOG_EVENTS),
            # An empty tuple is not valid HogQL, so an empty skip list holds a name no event has.
            "skip": _strings(skip or {""}),
            # Without an explicit limit HogQL returns 100 rows. Events with dynamic names can reach many thousands.
            "limit": ast.Constant(value=MAX_EVENTS),
        },
    )
    if sample_denominator > 1 and isinstance(query, ast.SelectQuery) and query.select_from is not None:
        query.select_from.sample = _sample(sample_denominator)
    response = _run_count(team, query, "workflows_data_suggestions_counts")
    return {str(row[0]): int(row[1]) * sample_denominator for row in response.results or [] if int(row[1]) > 0}


def person_property_values(team: Team, names: Iterable[str]) -> dict[str, tuple[str, ...]]:
    """The values seen on recent events for each person property in `names`. Only properties with a few short values,
    like a plan or a status, are kept: a branch splits on one of them, and a property with many or long values is an id
    or free text."""
    keys = list(names)
    if not keys:
        return {}
    values, found_any = _person_property_values(team, keys, sampled=True)
    if found_any:
        return values
    # Sampling is by distinct ID, so a small project whose active people all fall outside the sample shows no values.
    return _person_property_values(team, keys, sampled=False)[0]


def _person_property_values(team: Team, keys: list[str], *, sampled: bool) -> tuple[dict[str, tuple[str, ...]], bool]:
    """The kept values for each property, and whether the scan saw any value at all."""
    query = parse_select("SELECT 1 FROM events WHERE timestamp >= now() - INTERVAL 1 DAY")
    if not isinstance(query, ast.SelectQuery) or query.select_from is None:
        return {}, False
    query.select = []
    for key in keys:
        # Aggregates skip NULL, so blank values never take one of the capped slots.
        value = ast.Call(
            name="nullIf",
            args=[
                ast.Call(
                    name="nullIf",
                    args=[
                        ast.Call(name="toString", args=[ast.Field(chain=["person", "properties", key])]),
                        ast.Constant(value=""),
                    ],
                ),
                ast.Constant(value="null"),
            ],
        )
        query.select.append(
            ast.Call(name="groupUniqArray", params=[ast.Constant(value=_MAX_BRANCH_VALUES + 1)], args=[value])
        )
        query.select.append(ast.Call(name="max", args=[ast.Call(name="length", args=[value])]))
    if sampled:
        query.select_from.sample = _sample(_ESTIMATE_SAMPLE_DENOMINATOR)
    response = _run_count(team, query, "workflows_data_suggestions_person_properties")
    row = (response.results or [[]])[0]
    native_json = use_new_events_schema(team.pk, response.modifiers)
    values: dict[str, tuple[str, ...]] = {}
    found_any = False
    for index, key in enumerate(keys):
        seen, longest = row[2 * index : 2 * index + 2] or ([], None)
        found_any = found_any or bool(seen)
        decoded = list(seen or []) if native_json else _decoded(seen or [])
        if 0 < len(decoded) <= _MAX_BRANCH_VALUES and (longest or 0) <= _MAX_BRANCH_VALUE_LENGTH:
            values[key] = tuple(sorted(decoded))
    return values, found_any


def _decoded(raw_values: Iterable[str]) -> list[str]:
    # On the legacy events schema, person property reads strip the JSON quotes but keep escapes like `\"`, and a branch
    # filter compares against the decoded value. A value that does not decode is left out, since its filter could
    # never match. The native JSON schema returns decoded strings already.
    decoded = []
    for raw in raw_values:
        try:
            decoded.append(json.loads(f'"{raw}"'))
        except ValueError:
            continue
    return decoded


def _strings(values: Iterable[str]) -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=value) for value in sorted(values)])


def _sample(denominator: int) -> ast.SampleExpr:
    return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=1), right=ast.Constant(value=denominator)))


def _run_count(team: Team, query: ast.SelectQuery | ast.SelectSetQuery, query_type: str) -> HogQLQueryResponse:
    tag_queries(product=ProductKey.WORKFLOWS, feature=Feature.QUERY)
    settings = HogQLGlobalSettings(
        max_execution_time=_COUNT_TIMEOUT_SECONDS,
        # A timeout must fail the run. A profile set to break would return a partial count that is cached for a week.
        timeout_overflow_mode="throw",
        max_bytes_to_read=_COUNT_MAX_BYTES,
        read_overflow_mode="break",
    )
    return execute_hogql_query(query=query, team=team, query_type=query_type, settings=settings)
