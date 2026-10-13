from collections.abc import Mapping
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from posthog.schema import (
    DateRange,
    EventsNode,
    FunnelsQuery,
    HogQLFilters,
    LifecycleQuery,
    StickinessQuery,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.hogql_queries.apply_dashboard_filters import WRAPPER_NODE_KINDS
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team import Team
from posthog.models.user import User

from products.product_analytics.backend.facade.contracts import InsightDataCheck, InsightDataChecks
from products.product_analytics.backend.facade.enums import (
    InsightDataCheckAction,
    InsightDataCheckKey,
    InsightDataCheckLevel,
    InsightDataChecksStatus,
)
from products.product_analytics.backend.hogql_queries.trends.utils import is_groups_math

# Each check is a share of the events, so a sample this large gives the same answer as every event.
MAX_CHECKED_EVENTS = 1_000_000
# The sample is drawn before the chart's filters, because a count after them reads every event. When the filters
# keep fewer of the sampled events than the minimum, one larger sample is drawn that keeps about the second number.
MIN_SAMPLED_EVENTS = 10_000
RESAMPLED_EVENTS = 100_000
MAX_EXECUTION_SECONDS = 20
DEFAULT_DATE_FROM = "-7d"

LOCAL_HOST_PATTERN = r"(?i)^(localhost|[a-z0-9.-]+\.localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:[0-9]+)?$"
# An event with no user agent has the type "Automation", and server-side SDKs send those, so it is not a crawler.
CRAWLER_TRAFFIC_TYPES = ("Bot", "AI Agent")

MIN_FINDING_EVENTS = 50
MIN_FINDING_SHARE = 0.01
MIN_DUPLICATE_EVENTS = 100
MIN_DUPLICATE_SHARE = 0.05
PROBLEM_SHARE = 0.2

_WRAPPER_KINDS = {kind.value for kind in WRAPPER_NODE_KINDS}
_SERIES_QUERIES: dict[str, type[TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery]] = {
    "TrendsQuery": TrendsQuery,
    "FunnelsQuery": FunnelsQuery,
    "StickinessQuery": StickinessQuery,
    "LifecycleQuery": LifecycleQuery,
}

# Event names and dates are in the sort key of the events table, so this count reads no property of any event.
_TOTAL_QUERY = "SELECT count() FROM events WHERE {filters} AND {event_condition}"

# `uniq` is exact up to 65,536 values and an estimate above that, so one count for each user agent keeps the count of
# distinct events exact for all but the most common user agents.
_COUNTS_QUERY = """
    SELECT
        sum(event_count) AS events,
        sum(local_count) AS local_events,
        sum(bot_count) AS bot_events,
        sum(distinct_count) AS distinct_events
    FROM (
        SELECT
            toString(properties.$raw_user_agent) AS user_agent,
            count() AS event_count,
            countIf(match(toString(properties.$host), {local_host_pattern})) AS local_count,
            countIf(`$virt_traffic_type` IN {crawler_traffic_types}) AS bot_count,
            uniq((
                distinct_id,
                event,
                toStartOfSecond(timestamp),
                toString(properties.$current_url),
                toString(properties.$screen_name),
                toString(properties.$feature_flag),
                elements_chain
            )) AS distinct_count
        FROM events
        SAMPLE {sample}
        WHERE {filters}
            AND {insight_filters}
            AND {event_condition}
        GROUP BY user_agent
    )
"""


@frozen
class DataCheckCounts:
    events: int
    local_events: int
    bot_events: int
    distinct_events: int
    sample_rate: float = 1.0


@frozen
class _CheckedSeries:
    # None for a series that reads every event.
    event: str | None
    properties: Any
    # The group type the series counts. The chart leaves out an event that has no group of that type.
    group_type_index: int | None = None


@frozen
class _CheckedQuery:
    series: tuple[_CheckedSeries, ...]
    date_range: DateRange
    properties: Any
    filters_internal_users: bool
    # A lifecycle chart leaves out an event with no person profile, and it has no weekday filter.
    is_lifecycle: bool = False

    @property
    def event_names(self) -> tuple[str, ...] | None:
        names = tuple(dict.fromkeys(series.event for series in self.series if series.event is not None))
        return names if all(series.event is not None for series in self.series) else None


def run_insight_data_checks(query: Mapping[str, Any], team: Team, user: User) -> InsightDataChecks:
    """Check the events an insight reads for the common ways they mislead.

    Runs two ClickHouse queries: a cheap count that sets the sample, then the checks on that sample. A chart whose
    filters keep few of its events runs the checks a second time on a larger sample.
    """
    checked = _checked_query(query)
    if checked is None:
        return _not_checked(InsightDataChecksStatus.UNSUPPORTED)
    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.INSIGHT, name="insight_data_checks"):
        total = _count_events_in_range(checked, team, user)
        if total == 0:
            return _not_checked(InsightDataChecksStatus.NO_EVENTS)
        counts = _count_events(checked, team, user, total=total)
    if counts.events == 0:
        return _not_checked(InsightDataChecksStatus.NO_EVENTS)
    checks = evaluate_data_checks(counts)
    return InsightDataChecks(
        status=_status_of(checks), checks=checks, events_checked=counts.events, sample_rate=counts.sample_rate
    )


def evaluate_data_checks(counts: DataCheckCounts) -> list[InsightDataCheck]:
    """Every check, in a fixed order, so the list shows what was checked whatever the result."""
    return [
        _local_development_check(counts),
        _bot_traffic_check(counts),
        _duplicate_events_check(counts),
    ]


def _checked_query(query: Mapping[str, Any]) -> _CheckedQuery | None:
    node: Any = query
    while isinstance(node, Mapping) and node.get("kind") in _WRAPPER_KINDS:
        node = node.get("source")
    if not isinstance(node, Mapping):
        return None
    model = _SERIES_QUERIES.get(str(node.get("kind")))
    if model is None:
        return None
    try:
        source = model.model_validate(node)
    except ValidationError:
        return None
    if not source.series:
        return None

    checked_series: list[_CheckedSeries] = []
    for series in source.series:
        # An action or a data warehouse series has no event name to check.
        if not isinstance(series, EventsNode):
            return None
        checked_series.append(
            _CheckedSeries(
                event=series.event or None,
                properties=series.properties,
                group_type_index=_counted_group_type(source, series),
            )
        )
    date_range = source.dateRange or DateRange()
    if not date_range.date_from:
        date_range = date_range.model_copy(update={"date_from": DEFAULT_DATE_FROM})
    return _CheckedQuery(
        series=tuple(checked_series),
        date_range=date_range,
        properties=source.properties,
        filters_internal_users=bool(source.filterTestAccounts),
        is_lifecycle=isinstance(source, LifecycleQuery),
    )


def _counted_group_type(
    source: TrendsQuery | FunnelsQuery | StickinessQuery | LifecycleQuery, series: EventsNode
) -> int | None:
    if isinstance(source, FunnelsQuery):
        return source.aggregation_group_type_index
    if isinstance(source, TrendsQuery):
        counts_groups = is_groups_math(series)
    else:
        counts_groups = isinstance(source, StickinessQuery) and series.math == "unique_group"
    if counts_groups and series.math_group_type_index is not None:
        return int(series.math_group_type_index)
    return None


def _event_condition(checked: _CheckedQuery) -> ast.Expr:
    if checked.event_names is None:
        return ast.Constant(value=True)
    return ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["event"]),
        right=ast.Tuple(exprs=[ast.Constant(value=name) for name in checked.event_names]),
    )


def _all_of(conditions: list[ast.Expr]) -> ast.Expr:
    if not conditions:
        return ast.Constant(value=True)
    return conditions[0] if len(conditions) == 1 else ast.And(exprs=conditions)


def _series_filter(series: _CheckedSeries, team: Team) -> ast.Expr:
    conditions: list[ast.Expr] = []
    if series.event is not None:
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq, left=ast.Field(chain=["event"]), right=ast.Constant(value=series.event)
            )
        )
    if series.properties:
        conditions.append(property_to_expr(series.properties, team))
    if series.group_type_index is not None:
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=ast.Field(chain=[f"$group_{int(series.group_type_index)}"]),
                right=ast.Constant(value=""),
            )
        )
    return _all_of(conditions)


def _insight_filters(checked: _CheckedQuery, team: Team) -> ast.Expr:
    """What the chart asks of an event, other than its name and its date."""
    conditions: list[ast.Expr] = []
    if checked.properties:
        conditions.append(property_to_expr(checked.properties, team))
    if any(series.properties or series.group_type_index is not None for series in checked.series):
        series_filters = [_series_filter(series, team) for series in checked.series]
        conditions.append(series_filters[0] if len(series_filters) == 1 else ast.Or(exprs=series_filters))
    if checked.is_lifecycle:
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=ast.Field(chain=["properties", "$process_person_profile"]),
                right=ast.Constant(value="false"),
            )
        )
    else:
        weekdays = QueryDateRange(
            date_range=checked.date_range, team=team, interval=None, now=datetime.now()
        ).day_of_week_filter_expr(ast.Field(chain=["timestamp"]))
        if weekdays is not None:
            conditions.append(weekdays)
    return _all_of(conditions)


def _query_settings() -> HogQLGlobalSettings:
    # Without "throw", a query that reaches the time limit can return the events it counted so far as the answer.
    return HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_SECONDS, timeout_overflow_mode="throw")


def _count_events_in_range(checked: _CheckedQuery, team: Team, user: User) -> int:
    """Every event with the insight's event names in its date range, before any property filter."""
    response = execute_hogql_query(
        query=_TOTAL_QUERY,
        team=team,
        user=user,
        query_type="insight_data_checks_total",
        filters=HogQLFilters(dateRange=checked.date_range),
        placeholders={"event_condition": _event_condition(checked)},
        settings=_query_settings(),
    )
    return int(response.results[0][0] or 0) if response.results else 0


def _count_events(checked: _CheckedQuery, team: Team, user: User, *, total: int) -> DataCheckCounts:
    insight_filters = _insight_filters(checked, team)
    sampled = min(total, MAX_CHECKED_EVENTS)
    row = _query_counts(checked, team, user, insight_filters=insight_filters, sample=_sample(sampled, total))
    if sampled < total and row[0] < MIN_SAMPLED_EVENTS:
        sampled = min(total, sampled * RESAMPLED_EVENTS // max(row[0], 1))
        row = _query_counts(checked, team, user, insight_filters=insight_filters, sample=_sample(sampled, total))
    events, local_events, bot_events, distinct_events = row
    return DataCheckCounts(
        events=events,
        local_events=local_events,
        bot_events=bot_events,
        distinct_events=distinct_events,
        sample_rate=sampled / total,
    )


def _query_counts(
    checked: _CheckedQuery, team: Team, user: User, *, insight_filters: ast.Expr, sample: ast.RatioExpr
) -> tuple[int, int, int, int]:
    response = execute_hogql_query(
        query=_COUNTS_QUERY,
        team=team,
        user=user,
        query_type="insight_data_checks",
        filters=HogQLFilters(dateRange=checked.date_range, filterTestAccounts=checked.filters_internal_users),
        placeholders={
            "crawler_traffic_types": ast.Tuple(exprs=[ast.Constant(value=name) for name in CRAWLER_TRAFFIC_TYPES]),
            "local_host_pattern": ast.Constant(value=LOCAL_HOST_PATTERN),
            # The events table samples by distinct ID, so a sampled ID keeps all its events and no duplicate pair
            # is split.
            "sample": sample,
            "insight_filters": insight_filters,
            "event_condition": _event_condition(checked),
        },
        settings=_query_settings(),
    )
    row = response.results[0] if response.results else []
    events, local_events, bot_events, distinct_events = (int(value or 0) for value in row or [0] * 4)
    return events, local_events, bot_events, distinct_events


def _sample(limit: int, total: int) -> ast.RatioExpr:
    if total > limit:
        return ast.RatioExpr(left=ast.Constant(value=limit), right=ast.Constant(value=total))
    return ast.RatioExpr(left=ast.Constant(value=1))


def _check(
    key: InsightDataCheckKey,
    level: InsightDataCheckLevel,
    result: str,
    *,
    fix: str | None = None,
    action: InsightDataCheckAction | None = None,
    events: int | None = None,
    share: float | None = None,
) -> InsightDataCheck:
    return InsightDataCheck(
        key=key, level=level, name=key.label, result=result, fix=fix, action=action, events=events, share=share
    )


def _not_checked(status: InsightDataChecksStatus) -> InsightDataChecks:
    checks = [_check(key, InsightDataCheckLevel.SKIPPED, key.label) for key in InsightDataCheckKey]
    return InsightDataChecks(status=status, checks=checks, events_checked=0, sample_rate=1.0)


def _status_of(checks: list[InsightDataCheck]) -> InsightDataChecksStatus:
    levels = {check.level for check in checks}
    if InsightDataCheckLevel.PROBLEM in levels:
        return InsightDataChecksStatus.PROBLEM
    return (
        InsightDataChecksStatus.WARNING if InsightDataCheckLevel.WARNING in levels else InsightDataChecksStatus.PASSED
    )


def _finding_level(share: float) -> InsightDataCheckLevel:
    return InsightDataCheckLevel.PROBLEM if share >= PROBLEM_SHARE else InsightDataCheckLevel.WARNING


def _is_finding(count: int, share: float) -> bool:
    return count >= MIN_FINDING_EVENTS and share >= MIN_FINDING_SHARE


def _percent(share: float) -> str:
    return f"{round(share * 100)}%"


def _event_count(count: int, counts: DataCheckCounts) -> str:
    """A count of the insight's events. From a sample it is an estimate, so it is scaled up and rounded."""
    if counts.sample_rate >= 1:
        return f"{count:,}"
    estimate = round(count / counts.sample_rate)
    magnitude = 10 ** max(len(str(estimate)) - 2, 0)
    return f"about {round(estimate / magnitude) * magnitude:,}"


def _passed(key: InsightDataCheckKey, things: str, count: int, counts: DataCheckCounts) -> InsightDataCheck:
    """`things` is what the check looks for, as it reads after "No": "bots or crawlers"."""
    result = f"Almost no {things} found ({_event_count(count, counts)} events)" if count else f"No {things} found"
    return _check(key, InsightDataCheckLevel.PASSED, result, events=count, share=count / counts.events)


def _local_development_check(counts: DataCheckCounts) -> InsightDataCheck:
    key = InsightDataCheckKey.LOCAL_DEVELOPMENT
    share = counts.local_events / counts.events
    # No minimum share: a local session also creates test persons and flag exposures, whatever its share.
    if counts.local_events < MIN_FINDING_EVENTS:
        return _passed(key, "local development events", counts.local_events, counts)
    amount = _percent(share) if share >= MIN_FINDING_SHARE else _event_count(counts.local_events, counts)
    return _check(
        key,
        _finding_level(share),
        f"{amount[0].upper()}{amount[1:]} of these events came from local development",
        fix=(
            "Send local traffic to a separate project, or exclude localhost in the internal and test users filter "
            "and turn that filter on for this insight."
        ),
        action=InsightDataCheckAction.OPEN_FILTER_SETTINGS,
        events=counts.local_events,
        share=share,
    )


def _bot_traffic_check(counts: DataCheckCounts) -> InsightDataCheck:
    key = InsightDataCheckKey.BOT_TRAFFIC
    share = counts.bot_events / counts.events
    if not _is_finding(counts.bot_events, share):
        return _passed(key, "bots or crawlers", counts.bot_events, counts)
    return _check(
        key,
        _finding_level(share),
        f"{_percent(share)} of these events came from bots and crawlers",
        fix=(
            'In the internal and test users filter, add "Traffic type is not Bot or AI Agent", '
            "and turn that filter on for this insight."
        ),
        action=InsightDataCheckAction.OPEN_FILTER_SETTINGS,
        events=counts.bot_events,
        share=share,
    )


def _duplicate_events_check(counts: DataCheckCounts) -> InsightDataCheck:
    key = InsightDataCheckKey.DUPLICATE_EVENTS
    duplicates = max(counts.events - counts.distinct_events, 0)
    share = duplicates / counts.events
    if duplicates < MIN_DUPLICATE_EVENTS or share < MIN_DUPLICATE_SHARE:
        # The count is an estimate, so a small one can be an error of the estimate and not a real event.
        result = (
            "No events sent twice" if share < MIN_FINDING_SHARE else f"Few events sent twice (about {_percent(share)})"
        )
        return _check(key, InsightDataCheckLevel.PASSED, result, events=duplicates, share=share)
    return _check(
        key,
        _finding_level(share),
        f"About {_percent(share)} of these events were sent twice within one second",
        fix="Start PostHog once in your app, and send each event from one place only.",
        events=duplicates,
        share=share,
    )
