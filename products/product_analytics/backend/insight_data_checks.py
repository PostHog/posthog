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
from posthog.hogql.visitor import TraversingVisitor

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.product_analytics.backend.chart_events import ChartEvents, chart_events
from products.product_analytics.backend.facade.contracts import (
    InsightDataChecks,
    InsightDataChecksCoverage,
    InsightDataChecksSample,
)
from products.product_analytics.backend.facade.enums import (
    InsightDataCheckKey,
    InsightDataCheckSkipReason,
    InsightDataChecksStatus,
)
from products.product_analytics.backend.insight_data_check_days import CheckWindow, days_between, newest_days_within
from products.product_analytics.backend.insight_data_check_results import (
    CheckedEvents,
    LocalEvents,
    SampledEvents,
    Skipped,
    evaluate_data_checks,
    found_no_events,
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

# A check that takes longer than this is skipped, so it never holds up the insight it sits next to.
MAX_EXECUTION_SECONDS = 5
# Backstops for a size estimate that is far too low, such as for an event sent under a few distinct IDs.
# ClickHouse applies them to each shard separately.
MAX_BYTES_READ_PER_SHARD = 1_000_000_000
# The sample reads wide columns and sorts them for the repeat window, so it gets a tighter limit.
MAX_SAMPLE_BYTES_READ_PER_SHARD = 250_000_000

LOCAL_HOST_PATTERN = r"(?i)^(localhost|[a-z0-9.-]+\.localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:[0-9]+)?$"
# An event with no user agent has the type "Automation", and server-side SDKs send those, so it is not a crawler.
CRAWLER_TRAFFIC_TYPES = ("Bot", "AI Agent")
# A person cannot repeat an action this fast, but an app that sends an event twice does.
REPEAT_WINDOW_MILLISECONDS = 100
# A hidden property reads as empty, so the checks cannot run when one of these is hidden.
CHECKED_PROPERTIES = frozenset(
    {"$host", "$raw_user_agent", "$ip", "$current_url", "$screen_name", "$feature_flag", "$event_type"}
)
# The fields and functions that classify traffic, which apply a project's own bot rules.
TRAFFIC_TYPE_FIELDS = frozenset(
    {"$virt_is_bot", "$virt_traffic_type", "$virt_traffic_category", "$virt_bot_name", "$virt_bot_operator"}
)
TRAFFIC_TYPE_FUNCTIONS = frozenset(
    {"isLikelyBot", "getTrafficType", "getTrafficCategory", "getBotName", "getBotOperator"}
)

_EVENTS_PER_DAY_QUERY = """
    SELECT toDate(timestamp) AS day, count() AS events
    FROM events
    GROUP BY day
"""

_LOCAL_EVENTS_QUERY = """
    SELECT
        count() AS events,
        topK(3)(toString(properties.$host)) AS top_hosts,
        topK(3)(event) AS top_events
    FROM events
"""

_IS_LOCAL_HOST = "match(toString(properties.$host), {local_host_pattern})"

_SAMPLED_EVENTS_QUERY = """
    SELECT
        distinct_id,
        event,
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

# Each event, user agent and IP is classified once, which costs far less than classifying every event.
_SAMPLE_COUNTS_QUERY = """
    SELECT
        sum(source_events) AS events,
        uniqExactMerge(source_distinct_ids) AS distinct_ids,
        sumIf(source_events, is_bot) AS bot_events,
        sumMapIf([bot_name], [source_events], is_bot) AS bot_events_by_bot,
        sumMapIf([event], [source_events], is_bot) AS bot_events_by_event,
        sum(source_repeated_events) AS repeated_events,
        sumMap([event], [source_repeated_events]) AS repeated_events_by_event
    FROM (
        SELECT
            event,
            getTrafficType(user_agent, ip) IN {crawler_traffic_types} AS is_bot,
            getBotName(user_agent, ip) AS bot_name,
            source_events,
            source_repeated_events,
            source_distinct_ids
        FROM (
            SELECT
                event,
                user_agent,
                ip,
                count() AS source_events,
                countIf(milliseconds_since_identical_event < {repeat_window_milliseconds}) AS source_repeated_events,
                uniqExactState(distinct_id) AS source_distinct_ids
            FROM {sampled_events}
            GROUP BY event, user_agent, ip
        )
    )
"""


@frozen
class _EventReader:
    team: Team
    user: User
    modifiers: HogQLQueryModifiers
    # The database the chart's events were read with, so the checks do not build another.
    database: Database

    def rows_within_limits(
        self, query: ast.SelectQuery, *, query_type: str, max_bytes_read_per_shard: int
    ) -> list[list[Any]] | Skipped:
        try:
            response = execute_hogql_query(
                query=query,
                team=self.team,
                user=self.user,
                query_type=query_type,
                modifiers=self.modifiers,
                context=HogQLContext(team_id=self.team.pk, user=self.user, database=self.database),
                settings=_query_settings(max_bytes_read_per_shard),
            )
        except CHQueryErrorTooManyBytes:
            return Skipped(reason=InsightDataCheckSkipReason.READ_LIMIT)
        except (ClickHouseQueryTimeOut, ClickHouseEstimatedQueryExecutionTimeTooLong):
            return Skipped(reason=InsightDataCheckSkipReason.TIME_LIMIT)
        except ClickHouseQueryMemoryLimitExceeded:
            return Skipped(reason=InsightDataCheckSkipReason.MEMORY_LIMIT)
        return [list(row) for row in response.results or []]


def _query_settings(max_bytes_read_per_shard: int) -> HogQLGlobalSettings:
    # Without "throw", a query that reaches a limit can return the events it counted so far as the answer.
    return HogQLGlobalSettings(
        max_execution_time=MAX_EXECUTION_SECONDS,
        timeout_overflow_mode="throw",
        max_bytes_to_read=max_bytes_read_per_shard,
        read_overflow_mode="throw",
    )


class _TrafficTypeFinder(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.found = False

    def visit_field(self, node: ast.Field) -> None:
        self.found = self.found or any(part in TRAFFIC_TYPE_FIELDS for part in node.chain)

    def visit_call(self, node: ast.Call) -> None:
        self.found = self.found or node.name in TRAFFIC_TYPE_FUNCTIONS
        super().visit_call(node)


def _filters_on_traffic_type(where: ast.Expr) -> bool:
    finder = _TrafficTypeFinder()
    finder.visit(where)
    return finder.found


def _check_modifiers(chart_modifiers: HogQLQueryModifiers, *, keep_project_bot_rules: bool) -> HogQLQueryModifiers:
    # With `debug` on, a failed query returns an error and no rows, which would read as no events.
    update: dict[str, Any] = {"debug": False}
    if not keep_project_bot_rules:
        # The bot check uses PostHog's definition of a bot, so a project's own bot rules do not apply.
        update["customBotDefinitions"] = []
    return chart_modifiers.model_copy(update=update)


def _hidden_property_names(team: Team, user: User) -> set[str]:
    restricted = get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk)
    return {restricted_property.name for restricted_property in restricted}


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


def _top_three(values_by_key: tuple[list[str], list[int]] | None) -> list[str]:
    """The three keys with the highest values, highest first, from the key and value arrays that sumMap returns."""
    if not values_by_key:
        return []
    keys, values = values_by_key
    ranked = sorted(zip(keys, values), key=lambda key_and_value: key_and_value[1], reverse=True)
    return [key for key, value in ranked if key and value > 0][:3]


def _count_events_per_day(
    events: ChartEvents, reader: _EventReader, days: list[date], timezone: ZoneInfo
) -> dict[date, int] | Skipped:
    """Each day's events before the chart's filters, estimated from a sample of distinct IDs."""
    query = events.select(
        _EVENTS_PER_DAY_QUERY,
        where=ast.And(exprs=[events.sort_key_where, _between_days(events, days[0], days[-1], timezone)]),
        sample=_sample_of(1, SIZING_SAMPLE_ONE_IN),
    )
    rows = reader.rows_within_limits(
        query, query_type="insight_data_checks_sizing", max_bytes_read_per_shard=MAX_BYTES_READ_PER_SHARD
    )
    if isinstance(rows, Skipped):
        return rows

    sampled = {day: int(count) for day, count in rows}
    return {day: sampled.get(day, 0) * SIZING_SAMPLE_ONE_IN for day in days}


def _choose_window(events: ChartEvents, reader: _EventReader, timezone: ZoneInfo) -> CheckWindow | Skipped:
    days_in_range = days_between(
        events.date_from.astimezone(timezone).date(), events.date_to.astimezone(timezone).date()
    )
    events_per_day = _count_events_per_day(events, reader, days_in_range[-MAX_CHECKED_DAYS:], timezone)
    if isinstance(events_per_day, Skipped):
        return events_per_day

    return CheckWindow(
        days_in_range=days_in_range,
        days_to_check=newest_days_within(events_per_day, EVENT_BUDGET),
        events_per_day=events_per_day,
    )


def _count_local_events(
    events: ChartEvents, reader: _EventReader, where: ast.Expr, *, use_prewhere: bool
) -> LocalEvents | Skipped:
    is_local_host = parse_expr(
        _IS_LOCAL_HOST, placeholders={"local_host_pattern": ast.Constant(value=LOCAL_HOST_PATTERN)}
    )
    if use_prewhere:
        # In PREWHERE, ClickHouse reads only `$host` for every event, and the chart's filters only for the few that match.
        query = events.select(_LOCAL_EVENTS_QUERY, where=where, prewhere=is_local_host)
    else:
        # ClickHouse cannot run the function that hides a restricted property inside PREWHERE.
        query = events.select(_LOCAL_EVENTS_QUERY, where=ast.And(exprs=[where, is_local_host]))
    rows = reader.rows_within_limits(
        query, query_type="insight_data_checks_local", max_bytes_read_per_shard=MAX_BYTES_READ_PER_SHARD
    )
    if isinstance(rows, Skipped):
        return rows

    row: list[Any] = rows[0] if rows else [0, [], []]
    count, top_hosts, top_events = row
    return LocalEvents(count=int(count or 0), top_hosts=list(top_hosts), top_events=list(top_events))


def _sample_events(
    events: ChartEvents, reader: _EventReader, where: ast.Expr, *, events_before_filters: int
) -> SampledEvents | Skipped:
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
    rows = reader.rows_within_limits(
        cast(ast.SelectQuery, query),
        query_type="insight_data_checks_sample",
        max_bytes_read_per_shard=MAX_SAMPLE_BYTES_READ_PER_SHARD,
    )
    if isinstance(rows, Skipped):
        return rows

    row: list[Any] = rows[0] if rows else [0] * 7
    sampled, distinct_ids, bot_events, by_bot, bots_by_event, repeated_events, repeats_by_event = row
    return SampledEvents(
        rate=min(1.0, SAMPLE_SIZE / events_before_filters) if events_before_filters else 1.0,
        events=int(sampled or 0),
        distinct_ids=int(distinct_ids or 0),
        bot_events=int(bot_events or 0),
        top_bots=_top_three(by_bot),
        top_bot_events=_top_three(bots_by_event),
        repeated_events=int(repeated_events or 0),
        top_repeated_events=_top_three(repeats_by_event),
    )


def _read_checked_days(
    events: ChartEvents,
    reader: _EventReader,
    window: CheckWindow,
    timezone: ZoneInfo,
    *,
    hides_properties: bool,
    filters_traffic_type: bool,
) -> CheckedEvents:
    # The bounds apply to a whole range too, because a lifecycle chart also reads the interval before its range.
    first, last = window.days_to_check[0], window.days_to_check[-1]
    where = ast.And(exprs=[events.where, _between_days(events, first, last, timezone)])

    local: LocalEvents | Skipped = Skipped(reason=InsightDataCheckSkipReason.TOO_MANY_EVENTS)
    if window.events_on_days_to_check <= MAX_COUNTED_EVENTS:
        local = _count_local_events(events, reader, where, use_prewhere=not hides_properties)
    sample = _sample_events(events, reader, where, events_before_filters=window.events_on_days_to_check)
    return CheckedEvents(local=local, sample=sample, insight_filters_traffic_type=filters_traffic_type)


def _sample_summary(sample: SampledEvents | Skipped) -> InsightDataChecksSample | None:
    if isinstance(sample, Skipped):
        return None
    return InsightDataChecksSample(rate=sample.rate, events=sample.events, distinct_ids=sample.distinct_ids)


def _coverage(events: ChartEvents, window: CheckWindow, sample: SampledEvents | Skipped) -> InsightDataChecksCoverage:
    return InsightDataChecksCoverage(
        date_from=window.days_in_range[0],
        date_to=window.days_in_range[-1],
        days_in_range=len(window.days_in_range),
        checked_date_from=window.days_to_check[0],
        checked_date_to=window.days_to_check[-1],
        days_checked=len(window.days_to_check),
        filters_test_accounts=events.filters_test_accounts,
        events_checked=None if isinstance(sample, Skipped) else round(sample.events / sample.rate),
        sample=_sample_summary(sample),
    )


def _nothing_checked(
    status: InsightDataChecksStatus,
    coverage: InsightDataChecksCoverage | None = None,
    reason: InsightDataCheckSkipReason | None = None,
) -> InsightDataChecks:
    checks = [not_checked(key, reason) for key in InsightDataCheckKey]
    return InsightDataChecks(status=status, checks=checks, coverage=coverage)


def run_insight_data_checks(query: Mapping[str, Any], team: Team, user: User) -> InsightDataChecks:
    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.INSIGHT, name="insight_data_checks"):
        events = chart_events(query, team, user)
        if events is None:
            return _nothing_checked(InsightDataChecksStatus.UNSUPPORTED)
        hidden_properties = _hidden_property_names(team, user)
        if hidden_properties & CHECKED_PROPERTIES:
            return _nothing_checked(InsightDataChecksStatus.UNSUPPORTED)

        # A chart that filters on traffic type reads the project's bot rules, so the checks keep them to read its events.
        filters_traffic_type = _filters_on_traffic_type(events.where)
        reader = _EventReader(
            team=team,
            user=user,
            modifiers=_check_modifiers(events.modifiers, keep_project_bot_rules=filters_traffic_type),
            database=events.database,
        )
        timezone = ZoneInfo(team.timezone)
        window = _choose_window(events, reader, timezone)
        if isinstance(window, Skipped):
            return _nothing_checked(InsightDataChecksStatus.INCONCLUSIVE, reason=window.reason)
        checked = _read_checked_days(
            events,
            reader,
            window,
            timezone,
            hides_properties=bool(hidden_properties),
            filters_traffic_type=filters_traffic_type,
        )

    coverage = _coverage(events, window, checked.sample)
    if found_no_events(checked):
        return _nothing_checked(InsightDataChecksStatus.NO_EVENTS, coverage)
    checks = evaluate_data_checks(checked)
    return InsightDataChecks(status=status_of(checks), checks=checks, coverage=coverage)
