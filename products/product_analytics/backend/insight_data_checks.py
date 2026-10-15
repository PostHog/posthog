"""Checks the events an insight reads for local development, bots and events sent twice."""

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.product_analytics.backend.chart_events import ChartEvents, chart_events
from products.product_analytics.backend.facade.contracts import (
    InsightDataChecks,
    InsightDataChecksCoverage,
    InsightDataChecksSample,
)
from products.product_analytics.backend.facade.enums import InsightDataCheckKey, InsightDataChecksStatus
from products.product_analytics.backend.insight_data_check_days import CheckWindow, days_between, newest_days_within
from products.product_analytics.backend.insight_data_check_results import (
    REPEAT_WINDOW_MILLISECONDS,
    CheckedEvents,
    SampledEvents,
    evaluate_data_checks,
    not_checked,
    status_of,
)

# The checks read only the newest days of a range, so they stay cheap enough to run on every load.
MAX_CHECKED_DAYS = 7
# The most events the local development check counts, so a busy event checks fewer days.
EVENT_BUDGET = 20_000_000
# A day cannot be split, so the newest day alone is counted up to this size.
MAX_COUNTED_EVENTS = 2 * EVENT_BUDGET
SAMPLE_SIZE = 100_000
SIZING_SAMPLE_ONE_IN = 1_000

MAX_EXECUTION_SECONDS = 20
# A backstop for a size estimate that is far too low. ClickHouse applies it to each shard separately.
MAX_BYTES_READ_PER_SHARD = 1_000_000_000

LOCAL_HOST_PATTERN = r"(?i)^(localhost|[a-z0-9.-]+\.localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:[0-9]+)?$"
# An event with no user agent has the type "Automation", and server-side SDKs send those, so it is not a crawler.
CRAWLER_TRAFFIC_TYPES = ("Bot", "AI Agent")

_EVENTS_PER_DAY_QUERY = """
    SELECT toDate(timestamp) AS day, count() AS events
    FROM events
    GROUP BY day
"""

_COUNT_QUERY = "SELECT count() FROM events"

_IS_LOCAL_HOST = "match(toString(properties.$host), {local_host_pattern})"

_SAMPLED_EVENTS_QUERY = """
    SELECT
        distinct_id,
        toString(properties.$raw_user_agent) AS user_agent,
        toString(properties.$ip) AS ip,
        dateDiff(
            'millisecond',
            lagInFrame(timestamp) OVER (
                PARTITION BY
                    distinct_id,
                    event,
                    toString(properties.$raw_user_agent),
                    toString(properties.$current_url),
                    toString(properties.$screen_name),
                    toString(properties.$feature_flag),
                    toString(properties.$event_type),
                    elements_chain_texts,
                    elements_chain_href,
                    elements_chain_ids,
                    elements_chain_elements
                ORDER BY timestamp
                ROWS BETWEEN 1 PRECEDING AND CURRENT ROW
            ),
            timestamp
        ) AS milliseconds_since_identical_event
    FROM events
"""

# Each user agent and IP pair is classified once, which costs far less than classifying every event.
_SAMPLE_COUNTS_QUERY = """
    SELECT
        sum(pair_events) AS events,
        sumIf(pair_events, getTrafficType(user_agent, ip) IN {crawler_traffic_types}) AS bot_events,
        sum(pair_repeated_events) AS repeated_events,
        uniqExactMerge(pair_distinct_ids) AS distinct_ids
    FROM (
        SELECT
            user_agent,
            ip,
            count() AS pair_events,
            countIf(milliseconds_since_identical_event < {repeat_window_milliseconds}) AS pair_repeated_events,
            uniqExactState(distinct_id) AS pair_distinct_ids
        FROM {sampled_events}
        GROUP BY user_agent, ip
    )
"""


@frozen
class _EventReader:
    team: Team
    user: User
    modifiers: HogQLQueryModifiers
    # The database the chart's events were read with, so the checks do not build another.
    database: Database

    def rows(self, query: ast.SelectQuery, *, query_type: str) -> list[list[Any]]:
        response = execute_hogql_query(
            query=query,
            team=self.team,
            user=self.user,
            query_type=query_type,
            modifiers=self.modifiers,
            context=HogQLContext(team_id=self.team.pk, user=self.user, database=self.database),
            settings=_query_settings(),
        )
        return [list(row) for row in response.results or []]

    def first_row(self, query: ast.SelectQuery, *, query_type: str) -> list[Any]:
        rows = self.rows(query, query_type=query_type)
        return rows[0] if rows else []


def _query_settings() -> HogQLGlobalSettings:
    # Without "throw", a query that reaches a limit can return the events it counted so far as the answer.
    return HogQLGlobalSettings(
        max_execution_time=MAX_EXECUTION_SECONDS,
        timeout_overflow_mode="throw",
        max_bytes_to_read=MAX_BYTES_READ_PER_SHARD,
        read_overflow_mode="throw",
    )


def _start_of(day: date, timezone: ZoneInfo) -> ast.Constant:
    return ast.Constant(value=datetime.combine(day, time.min, tzinfo=timezone))


def _between_days(events: ChartEvents, first: date, last: date, timezone: ZoneInfo) -> ast.Expr:
    """The events from the start of `first` to the end of `last`, as a timestamp range ClickHouse can skip by."""
    return ast.And(
        exprs=[
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq, left=events.timestamp(), right=_start_of(first, timezone)
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.Lt,
                left=events.timestamp(),
                right=_start_of(last + timedelta(days=1), timezone),
            ),
        ]
    )


def _sample_of(count: int, total: int) -> ast.SampleExpr:
    if total <= count:
        return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=1)))
    return ast.SampleExpr(sample_value=ast.RatioExpr(left=ast.Constant(value=count), right=ast.Constant(value=total)))


def _count_events_per_day(
    events: ChartEvents, reader: _EventReader, days: list[date], timezone: ZoneInfo
) -> dict[date, int]:
    """Each day's events before the chart's filters, estimated from a sample of distinct IDs."""
    query = events.select(
        _EVENTS_PER_DAY_QUERY,
        where=ast.And(exprs=[events.sort_key_where, _between_days(events, days[0], days[-1], timezone)]),
        sample=_sample_of(1, SIZING_SAMPLE_ONE_IN),
    )
    sampled = {day: int(count) for day, count in reader.rows(query, query_type="insight_data_checks_sizing")}
    return {day: sampled.get(day, 0) * SIZING_SAMPLE_ONE_IN for day in days}


def _choose_window(events: ChartEvents, reader: _EventReader, timezone: ZoneInfo) -> CheckWindow:
    days_in_range = days_between(
        events.date_from.astimezone(timezone).date(), events.date_to.astimezone(timezone).date()
    )
    events_per_day = _count_events_per_day(events, reader, days_in_range[-MAX_CHECKED_DAYS:], timezone)
    return CheckWindow(
        days_in_range=days_in_range,
        days_to_check=newest_days_within(events_per_day, EVENT_BUDGET),
        events_per_day=events_per_day,
    )


def _count_local_events(events: ChartEvents, reader: _EventReader, where: ast.Expr) -> int | None:
    is_local_host = parse_expr(
        _IS_LOCAL_HOST, placeholders={"local_host_pattern": ast.Constant(value=LOCAL_HOST_PATTERN)}
    )
    # In PREWHERE, ClickHouse reads only `$host` for every event, and the chart's filters only for the few that match.
    query = events.select(_COUNT_QUERY, where=where, prewhere=is_local_host)
    try:
        row = reader.first_row(query, query_type="insight_data_checks_local")
    except CHQueryErrorTooManyBytes:
        return None
    return int(row[0] or 0) if row else 0


def _sample_events(
    events: ChartEvents, reader: _EventReader, where: ast.Expr, *, events_before_filters: int
) -> SampledEvents | None:
    sampled_events = events.select(
        _SAMPLED_EVENTS_QUERY,
        where=where,
        # The events table samples by distinct ID, so a sampled ID keeps all its events and no repeat is split.
        sample=_sample_of(SAMPLE_SIZE, events_before_filters),
    )
    query = parse_select(
        _SAMPLE_COUNTS_QUERY,
        placeholders={
            "sampled_events": sampled_events,
            "crawler_traffic_types": ast.Tuple(exprs=[ast.Constant(value=name) for name in CRAWLER_TRAFFIC_TYPES]),
            "repeat_window_milliseconds": ast.Constant(value=REPEAT_WINDOW_MILLISECONDS),
        },
    )
    try:
        row = reader.first_row(cast(ast.SelectQuery, query), query_type="insight_data_checks_sample")
    except CHQueryErrorTooManyBytes:
        return None

    sampled, bot_events, repeated_events, distinct_ids = (int(value or 0) for value in row or [0] * 4)
    return SampledEvents(
        rate=min(1.0, SAMPLE_SIZE / events_before_filters) if events_before_filters else 1.0,
        events=sampled,
        bot_events=bot_events,
        repeated_events=repeated_events,
        distinct_ids=distinct_ids,
    )


def _check_window(events: ChartEvents, reader: _EventReader, window: CheckWindow, timezone: ZoneInfo) -> CheckedEvents:
    where = events.where
    if not window.checks_whole_range:
        first, last = window.days_to_check[0], window.days_to_check[-1]
        where = ast.And(exprs=[events.where, _between_days(events, first, last, timezone)])

    too_many_to_count = window.events_on_days_to_check > MAX_COUNTED_EVENTS
    return CheckedEvents(
        local_events=None if too_many_to_count else _count_local_events(events, reader, where),
        sample=_sample_events(events, reader, where, events_before_filters=window.events_on_days_to_check),
        days_checked=len(window.days_to_check),
        checked_whole_range=window.checks_whole_range,
    )


def _sample_summary(sample: SampledEvents | None) -> InsightDataChecksSample | None:
    if sample is None:
        return None
    return InsightDataChecksSample(rate=sample.rate, events=sample.events, distinct_ids=sample.distinct_ids)


def _coverage(events: ChartEvents, window: CheckWindow, sample: SampledEvents | None) -> InsightDataChecksCoverage:
    return InsightDataChecksCoverage(
        date_from=window.days_in_range[0],
        date_to=window.days_in_range[-1],
        days_in_range=len(window.days_in_range),
        checked_date_from=window.days_to_check[0],
        checked_date_to=window.days_to_check[-1],
        days_checked=len(window.days_to_check),
        filters_test_accounts=events.filters_test_accounts,
        events_checked=None if sample is None else round(sample.events / sample.rate),
        sample=_sample_summary(sample),
    )


def _found_no_events(window: CheckWindow, checked: CheckedEvents) -> bool:
    return (
        window.checks_whole_range
        and checked.sample is not None
        and checked.sample.read_every_event
        and checked.sample.events == 0
        and not checked.local_events
    )


def _nothing_checked(
    status: InsightDataChecksStatus, coverage: InsightDataChecksCoverage | None = None
) -> InsightDataChecks:
    return InsightDataChecks(status=status, checks=[not_checked(key) for key in InsightDataCheckKey], coverage=coverage)


def run_insight_data_checks(query: Mapping[str, Any], team: Team, user: User) -> InsightDataChecks:
    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.INSIGHT, name="insight_data_checks"):
        events = chart_events(query, team, user)
        if events is None:
            return _nothing_checked(InsightDataChecksStatus.UNSUPPORTED)
        # A property that is hidden from `user` reads as empty, so a check would count none of what it looks for.
        if get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk):
            return _nothing_checked(InsightDataChecksStatus.UNSUPPORTED)

        reader = _EventReader(
            team=team,
            user=user,
            # With `debug` on, a failed query returns an error and no rows, which would read as no events.
            modifiers=events.modifiers.model_copy(update={"debug": False}),
            database=events.database,
        )
        timezone = ZoneInfo(team.timezone)
        window = _choose_window(events, reader, timezone)
        checked = _check_window(events, reader, window, timezone)

    coverage = _coverage(events, window, checked.sample)
    if _found_no_events(window, checked):
        return _nothing_checked(InsightDataChecksStatus.NO_EVENTS, coverage)
    checks = evaluate_data_checks(checked)
    return InsightDataChecks(status=status_of(checks), checks=checks, coverage=coverage)
