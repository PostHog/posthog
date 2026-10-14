from collections.abc import Mapping
from typing import Any, cast

from posthog.schema import HogQLQueryModifiers

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.api import get_restricted_properties_with_group_type_index_for_team
from products.product_analytics.backend.chart_events import ChartEvents, chart_events
from products.product_analytics.backend.facade.contracts import InsightDataCheck, InsightDataChecks
from products.product_analytics.backend.facade.enums import (
    InsightDataCheckAction,
    InsightDataCheckKey,
    InsightDataCheckLevel,
    InsightDataChecksStatus,
)

# Each check is a share of the events, so a sample this large gives the same answer as every event.
MAX_CHECKED_EVENTS = 1_000_000
# The first sample is sized from a count of the chart's event names and dates, which reads only the sort key. A
# count after the chart's filters reads those filters for every event in the range, so the checks run it only when
# the filters keep fewer than this many of the sampled events, and then size the sample from it.
MIN_CHECKED_EVENTS = 10_000
MAX_EXECUTION_SECONDS = 20

LOCAL_HOST_PATTERN = r"(?i)^(localhost|[a-z0-9.-]+\.localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:[0-9]+)?$"
# An event with no user agent has the type "Automation", and server-side SDKs send those, so it is not a crawler.
CRAWLER_TRAFFIC_TYPES = ("Bot", "AI Agent")

MIN_FINDING_EVENTS = 50
MIN_FINDING_SHARE = 0.01
MIN_DUPLICATE_EVENTS = 100
# Higher than the other share floors, because `uniq` estimates the distinct events of a common user agent and a small
# share of duplicates can be the error of that estimate.
MIN_DUPLICATE_SHARE = 0.05
PROBLEM_SHARE = 0.2

_TOTAL_QUERY = "SELECT count() FROM events"

# `uniq` is exact up to 65,536 values and an estimate above that, so one count for each user agent keeps the count of
# distinct events exact for all but the most common user agents.
_COUNTS_BY_USER_AGENT_QUERY = """
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
    GROUP BY user_agent
"""

_COUNTS_QUERY = """
    SELECT
        sum(event_count) AS events,
        sum(local_count) AS local_events,
        sum(bot_count) AS bot_events,
        sum(distinct_count) AS distinct_events
    FROM {counts_by_user_agent}
"""


@frozen
class DataCheckCounts:
    events: int
    local_events: int
    bot_events: int
    distinct_events: int
    sample_rate: float = 1.0


@frozen
class _EventReader:
    team: Team
    user: User
    modifiers: HogQLQueryModifiers
    # The database the chart's events were read with, so the checks do not build another.
    database: Database

    def first_row(self, query: ast.SelectQuery, *, query_type: str) -> list[Any]:
        response = execute_hogql_query(
            query=query,
            team=self.team,
            user=self.user,
            query_type=query_type,
            modifiers=self.modifiers,
            context=HogQLContext(team_id=self.team.pk, user=self.user, database=self.database),
            settings=_query_settings(),
        )
        return list(response.results[0]) if response.results else []


def run_insight_data_checks(query: Mapping[str, Any], team: Team, user: User) -> InsightDataChecks:
    with tags_context(product=Product.PRODUCT_ANALYTICS, feature=Feature.INSIGHT, name="insight_data_checks"):
        events = chart_events(query, team, user)
        if events is None:
            return _not_checked(InsightDataChecksStatus.UNSUPPORTED)
        # A property that is hidden from `user` reads as empty, so a check would count none of what it looks for.
        if get_restricted_properties_with_group_type_index_for_team(user=user, team_id=team.pk):
            return _not_checked(InsightDataChecksStatus.UNSUPPORTED)
        # With `debug` on, a failed query returns an error and no rows, which would read as no events.
        modifiers = events.modifiers.model_copy(update={"debug": False})
        reader = _EventReader(
            team=team,
            user=user,
            modifiers=modifiers,
            database=events.database,
        )
        total = _count_events(events, reader, where=events.sort_key_where, query_type="insight_data_checks_total")
        if total == 0:
            return _not_checked(InsightDataChecksStatus.NO_EVENTS)
        counts = _sampled_counts(events, reader, total_before_filters=total)
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


def _query_settings() -> HogQLGlobalSettings:
    # Without "throw", a query that reaches the time limit can return the events it counted so far as the answer.
    return HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_SECONDS, timeout_overflow_mode="throw")


def _count_events(events: ChartEvents, reader: _EventReader, *, where: ast.Expr, query_type: str) -> int:
    row = reader.first_row(events.select(_TOTAL_QUERY, where=where), query_type=query_type)
    return int(row[0] or 0) if row else 0


def _sampled_counts(events: ChartEvents, reader: _EventReader, *, total_before_filters: int) -> DataCheckCounts:
    counts = _query_counts(events, reader, total=total_before_filters)
    if counts.sample_rate == 1 or counts.events >= MIN_CHECKED_EVENTS:
        return counts
    # Sampling picks whole distinct IDs, so a filter that keeps the events of a few people can leave none in the
    # first sample although the chart has events.
    total = _count_events(events, reader, where=events.where, query_type="insight_data_checks_filtered_total")
    if total == 0:
        return counts
    return _query_counts(events, reader, total=total)


def _query_counts(events: ChartEvents, reader: _EventReader, *, total: int) -> DataCheckCounts:
    sampled = min(total, MAX_CHECKED_EVENTS)
    counts_by_user_agent = events.select(
        _COUNTS_BY_USER_AGENT_QUERY,
        where=events.where,
        # The events table samples by distinct ID, so a sampled ID keeps all its events and no duplicate pair is split.
        sample=ast.SampleExpr(sample_value=_sample(sampled, total)),
        crawler_traffic_types=ast.Tuple(exprs=[ast.Constant(value=name) for name in CRAWLER_TRAFFIC_TYPES]),
        local_host_pattern=ast.Constant(value=LOCAL_HOST_PATTERN),
    )
    row = reader.first_row(
        cast(ast.SelectQuery, parse_select(_COUNTS_QUERY, placeholders={"counts_by_user_agent": counts_by_user_agent})),
        query_type="insight_data_checks",
    )
    event_count, local_events, bot_events, distinct_events = (int(value or 0) for value in row or [0] * 4)
    return DataCheckCounts(
        events=event_count,
        local_events=local_events,
        bot_events=bot_events,
        distinct_events=distinct_events,
        sample_rate=sampled / total,
    )


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


def _is_finding(count: float, share: float) -> bool:
    return count >= MIN_FINDING_EVENTS and share >= MIN_FINDING_SHARE


def _percent(share: float) -> str:
    return f"{round(share * 100)}%"


def _estimate(count: int, counts: DataCheckCounts) -> float:
    return count / counts.sample_rate


def _event_count(count: int, counts: DataCheckCounts) -> str:
    if counts.sample_rate >= 1:
        return f"{count:,}"
    estimate = round(_estimate(count, counts))
    magnitude = 10 ** max(len(str(estimate)) - 2, 0)
    return f"about {round(estimate / magnitude) * magnitude:,}"


def _passed(key: InsightDataCheckKey, things: str, count: int, counts: DataCheckCounts) -> InsightDataCheck:
    result = f"Almost no {things} found ({_event_count(count, counts)} events)" if count else f"No {things} found"
    return _check(key, InsightDataCheckLevel.PASSED, result, events=count, share=count / counts.events)


def _local_development_check(counts: DataCheckCounts) -> InsightDataCheck:
    key = InsightDataCheckKey.LOCAL_DEVELOPMENT
    share = counts.local_events / counts.events
    # No minimum share: a local session also creates test persons and flag exposures, whatever its share.
    if _estimate(counts.local_events, counts) < MIN_FINDING_EVENTS:
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
    if not _is_finding(_estimate(counts.bot_events, counts), share):
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
    if _estimate(duplicates, counts) < MIN_DUPLICATE_EVENTS or share < MIN_DUPLICATE_SHARE:
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
