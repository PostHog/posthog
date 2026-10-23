"""Pick the watched insights that the next anomaly scoring tick scores.

There is no stored state. One query per team reads the newest scored bucket of each series back
from the `$anomaly_score` events. `selection.pick_order` then orders the due insights, and the tick
picks from that order the insights whose queries fit the hourly budgets.
"""

import datetime
import itertools
from collections.abc import Callable, Collection
from typing import Any, cast

from django.core.cache import cache

from posthog.schema import ChartDisplayType, IntervalType

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.interval_specs import interval_spec
from posthog.models import Team
from posthog.tasks.alerts.utils import NON_TIME_SERIES_DISPLAY_TYPES

from products.alerts_platform.backend.facade.scheduling import CalendarInterval, alert_check_offset
from products.product_analytics.backend.facade.api import (
    insights_including_soft_deleted_for_team,
    watched_trends_insights,
)
from products.signals.backend.anomaly_scores.config import AnomalyScoringConfig
from products.signals.backend.anomaly_scores.scoring import bucket_end, query_cost
from products.signals.backend.anomaly_scores.selection import (
    Candidate,
    InsightUsage,
    SelectionConfig,
    insight_usage,
    pick_order,
)

from ee.billing.quota_limiting import QuotaLimitingCaches, QuotaResource, list_limited_team_attributes

SCORE_EVENT = "$anomaly_score"
SOURCE_INSIGHT = "insight"
# An insight counts as watched when it is on a dashboard or someone viewed it in this window.
VIEW_WINDOW = datetime.timedelta(days=30)
# One row is one series. Far more than the series of every watched insight of one team.
_MAX_SCORED_SERIES = 50_000
# An insight is not picked again in this time after an attempt. Events take a moment to reach
# ClickHouse, and an insight that writes nothing would otherwise stay at the head of the queue.
ATTEMPT_COOLDOWN = datetime.timedelta(hours=1)
# For a failure that the next hour does not fix: an unsupported shape, a query that is too expensive, or no access.
SKIP_COOLDOWN = datetime.timedelta(days=1)
# A query counter lives a little longer than its clock hour, so a tick at the end of the hour still reads it.
# A lost counter lets the scorer spend at most one more hour of budget.
_BUDGET_TTL = datetime.timedelta(minutes=70)

_CALENDAR_INTERVALS = {
    IntervalType.HOUR: CalendarInterval.HOURLY,
    IntervalType.DAY: CalendarInterval.DAILY,
    IntervalType.WEEK: CalendarInterval.WEEKLY,
    IntervalType.MONTH: CalendarInterval.MONTHLY,
}
# The scorer rejects these, so selection leaves them out instead of picking them on every tick.
_UNSCORED_DISPLAYS = sorted(
    display.value for display in {*NON_TIME_SERIES_DISPLAY_TYPES, ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE}
)

_SCORED_BUCKETS_QUERY = """
SELECT
    toInt(properties.$anomaly_insight_id) AS insight_id,
    toString(properties.$anomaly_series_key) AS series_key,
    max(timestamp) AS newest_bucket
FROM events
WHERE event = {event}
    AND timestamp >= {since}
    AND timestamp <= {now}
    AND properties.$anomaly_source = {source}
    AND toInt(properties.$anomaly_insight_id) IN {insight_ids}
GROUP BY insight_id, series_key
LIMIT {limit}
"""


@frozen
class WatchedInsight:
    team_id: int
    insight_id: int
    interval: IntervalType


@frozen
class InsightPick:
    team_id: int
    insight_id: int
    # The newest scored bucket start of each series, in UTC. Empty when the insight was never scored.
    scored_through: dict[str, datetime.datetime]
    interval: IntervalType | None = None
    # The ClickHouse queries this pick sends. Selection charges them to the hourly budgets, so two ticks
    # that overlap cannot spend the same budget.
    query_cost: int = 1


@frozen
class Selection:
    picks: list[InsightPick]
    # Due insights, picked or not. More than the picks means the tick cap or a budget cut the queue.
    candidates: int
    # Due insights that the walk reached but skipped, because their queries did not fit a budget.
    skipped_for_budget: int = 0


@frozen
class QueryBudget:
    """Scoring queries left in this clock hour, for the fleet and for each project."""

    fleet: int
    projects: dict[int, int]


def eligible_teams(config: AnomalyScoringConfig) -> list[Team]:
    if not config.enabled or not config.organization_ids:
        return []
    teams = Team.objects.filter(organization_id__in=config.organization_ids).exclude(id__in=config.skip_team_ids)
    if config.allow_team_ids:
        teams = teams.filter(id__in=config.allow_team_ids)
    # Capture drops every event of a project over its event quota, so scoring it wastes the query.
    limited = set(list_limited_team_attributes(QuotaResource.EVENTS, QuotaLimitingCaches.QUOTA_LIMITER_CACHE_KEY))
    return [team for team in teams if team.api_token not in limited]


def watched_insights(
    team_ids: list[int], intervals: tuple[IntervalType, ...], now: datetime.datetime
) -> list[WatchedInsight]:
    """Saved trends insights with a scored interval that are on a dashboard or were viewed lately."""
    return [
        WatchedInsight(team_id=watched.team_id, insight_id=watched.insight_id, interval=IntervalType(watched.interval))
        for watched in watched_trends_insights(
            team_ids=team_ids,
            intervals=[interval.value for interval in intervals],
            excluded_displays=_UNSCORED_DISPLAYS,
            viewed_since=now - VIEW_WINDOW,
        )
    ]


def scored_state_since(config: AnomalyScoringConfig, now: datetime.datetime) -> datetime.datetime:
    """How far back the scored state reaches: one bucket more than the backfill cap of the longest interval."""
    return min(
        now - interval_spec(interval).period * (config.limits.max_backfill_buckets + 1) for interval in config.intervals
    )


def _utc(value: datetime.datetime) -> datetime.datetime:
    return value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)


def scored_buckets(
    team: Team, insight_ids: Collection[int], since: datetime.datetime, now: datetime.datetime
) -> dict[int, dict[str, datetime.datetime]]:
    """Insight id to the newest scored bucket start of each of its series, for this team's own insights.

    Any member can capture an event with any properties into the project. Rows for another team's
    insight, or with a future bucket, are ignored, so they cannot stop the scoring of an insight.
    """
    if not insight_ids:
        return {}
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    response = execute_hogql_query(
        _SCORED_BUCKETS_QUERY,
        team,
        query_type="AnomalyScoresScoredBuckets",
        placeholders={
            "event": ast.Constant(value=SCORE_EVENT),
            "source": ast.Constant(value=SOURCE_INSIGHT),
            "since": ast.Constant(value=since),
            "now": ast.Constant(value=now),
            "insight_ids": ast.Tuple(exprs=[ast.Constant(value=insight_id) for insight_id in sorted(insight_ids)]),
            "limit": ast.Constant(value=_MAX_SCORED_SERIES),
        },
        workload=Workload.OFFLINE,
        ch_user=ClickHouseUser.DEFAULT,
    )
    state: dict[int, dict[str, datetime.datetime]] = {}
    for insight_id, series_key, newest_bucket in cast(list[tuple[Any, ...]], response.results or []):
        if insight_id is None or not series_key:
            continue
        state.setdefault(int(insight_id), {})[str(series_key)] = _utc(newest_bucket)
    return state


def is_due(
    insight: WatchedInsight, newest_bucket: datetime.datetime | None, timezone: datetime.tzinfo, now: datetime.datetime
) -> bool:
    """The bucket after the newest scored one is complete, and this insight's slot after its end has passed."""
    if newest_bucket is None:
        return True
    next_start = bucket_end(newest_bucket.astimezone(timezone), insight.interval)
    next_end = bucket_end(next_start, insight.interval)
    # The same offset as alert checks, so insights spread over the window after each boundary.
    offset = alert_check_offset(_CALENDAR_INTERVALS[insight.interval], f"anomaly:{insight.insight_id}")
    return now >= next_end + offset


def _cooldown_key(insight_id: int) -> str:
    return f"signals:anomaly_scores:attempted:{insight_id}"


def mark_attempted(insight_id: int, cooldown: datetime.timedelta) -> None:
    cache.set(_cooldown_key(insight_id), True, timeout=int(cooldown.total_seconds()))


def _cooling_down(insight_ids: list[int]) -> set[int]:
    if not insight_ids:
        return set()
    found = cache.get_many([_cooldown_key(insight_id) for insight_id in insight_ids])
    return {insight_id for insight_id in insight_ids if _cooldown_key(insight_id) in found}


def _hour(now: datetime.datetime) -> str:
    return _utc(now).strftime("%Y%m%d%H")


def _fleet_budget_key(now: datetime.datetime) -> str:
    return f"signals:anomaly_scores:queries:{_hour(now)}"


def _project_budget_key(team_id: int, now: datetime.datetime) -> str:
    return f"signals:anomaly_scores:queries:{_hour(now)}:team:{team_id}"


def remaining_budget(config: AnomalyScoringConfig, team_ids: Collection[int], now: datetime.datetime) -> QueryBudget:
    project_keys = {team_id: _project_budget_key(team_id, now) for team_id in team_ids}
    spent = cache.get_many([_fleet_budget_key(now), *project_keys.values()])
    return QueryBudget(
        fleet=config.max_queries_per_hour - spent.get(_fleet_budget_key(now), 0),
        projects={
            team_id: config.max_queries_per_project_per_hour - spent.get(key, 0)
            for team_id, key in project_keys.items()
        },
    )


def _reserve(key: str, queries: int, cap: int) -> bool:
    # `incr` is atomic, so two planners that run at the same time cannot both take the last queries.
    # `incr` fails on a missing key, and `add` does nothing when the key exists.
    cache.add(key, 0, timeout=int(_BUDGET_TTL.total_seconds()))
    if cache.incr(key, queries) <= cap:
        return True
    cache.decr(key, queries)
    return False


def reserve_queries(config: AnomalyScoringConfig, team_id: int, queries: int, now: datetime.datetime) -> bool:
    """Charge ``queries`` to both hourly budgets, or to neither when one of them has too few left."""
    fleet_key = _fleet_budget_key(now)
    if not _reserve(fleet_key, queries, config.max_queries_per_hour):
        return False
    if _reserve(_project_budget_key(team_id, now), queries, config.max_queries_per_project_per_hour):
        return True
    cache.decr(fleet_key, queries)
    return False


def within_budget(
    order: list[int],
    team_ids: dict[int, int],
    budget: QueryBudget,
    limit: int,
    costs_for: Callable[[list[int]], dict[int, int]],
    reserve: Callable[[int, int], bool],
) -> tuple[dict[int, int], int]:
    """The insights of ``order`` whose cost fits both budgets, up to ``limit``, with their costs, and the skip count.

    A pick that does not fit is skipped and the walk continues, so a large insight does not block smaller ones.
    ``budget`` is a snapshot that skips most misses without a cache call. ``reserve`` charges a pick for real.
    ``costs_for`` loads costs in batches of ``limit``, and only for insights that the snapshot can still fit.
    """
    fleet = budget.fleet
    projects = dict(budget.projects)
    picked: dict[int, int] = {}
    skipped = 0
    batch_size = max(1, limit)
    for start in range(0, len(order), batch_size):
        if len(picked) >= limit:
            break
        batch = order[start : start + batch_size]
        affordable = [insight_id for insight_id in batch if fleet > 0 and projects.get(team_ids[insight_id], 0) > 0]
        costs = costs_for(affordable) if affordable else {}
        for insight_id in batch:
            if len(picked) >= limit:
                break
            team_id = team_ids[insight_id]
            cost = costs.get(insight_id)
            if cost is None or cost > fleet or cost > projects.get(team_id, 0) or not reserve(team_id, cost):
                skipped += 1
                continue
            picked[insight_id] = cost
            fleet -= cost
            projects[team_id] -= cost
    return picked, skipped


def _query_costs(team: Team, insight_ids: list[int]) -> dict[int, int]:
    insights = insights_including_soft_deleted_for_team(team_id=team.id, insight_ids=insight_ids)
    costs = {insight.id: query_cost(insight, team) for insight in insights}
    # An insight that no longer exists sends no query, but one query is the safe charge.
    return {insight_id: costs.get(insight_id, 1) for insight_id in insight_ids}


def select_insights(
    config: AnomalyScoringConfig, selection_config: SelectionConfig, now: datetime.datetime, limit: int
) -> Selection:
    teams = {team.id: team for team in eligible_teams(config)}
    insights = watched_insights(list(teams), config.intervals, now)
    since = scored_state_since(config, now)
    state: dict[int, dict[str, datetime.datetime]] = {}
    for team_id in sorted({insight.team_id for insight in insights}):
        team_insight_ids = {insight.insight_id for insight in insights if insight.team_id == team_id}
        state.update(scored_buckets(teams[team_id], team_insight_ids, since, now))

    newest_buckets = {
        insight.insight_id: max(state[insight.insight_id].values()) if insight.insight_id in state else None
        for insight in insights
    }
    due = [
        insight
        for insight in insights
        if is_due(insight, newest_buckets[insight.insight_id], teams[insight.team_id].timezone_info, now)
    ]
    cooling = _cooling_down([insight.insight_id for insight in due])
    due_by_id = {insight.insight_id: insight for insight in due if insight.insight_id not in cooling}

    usage: dict[int, InsightUsage] = {}
    for team_id in sorted({insight.team_id for insight in due_by_id.values()}):
        due_ids = [insight.insight_id for insight in due_by_id.values() if insight.team_id == team_id]
        usage.update(insight_usage(team_id=team_id, insight_ids=due_ids, now=now))
    candidates_by_team: dict[int, list[Candidate]] = {}
    for insight in due_by_id.values():
        newest = newest_buckets[insight.insight_id]
        candidates_by_team.setdefault(insight.team_id, []).append(
            Candidate(
                insight_id=insight.insight_id,
                interval=insight.interval,
                # Staleness steps whole buckets, so it needs the bucket start in the project timezone.
                newest_scored_bucket=None
                if newest is None
                else newest.astimezone(teams[insight.team_id].timezone_info),
                usage=usage[insight.insight_id],
            )
        )
    team_orders = [
        pick_order(
            candidates_by_team[team_id],
            config=selection_config,
            tick_start=now,
            max_staleness=config.limits.max_backfill_buckets,
        )
        for team_id in sorted(candidates_by_team)
    ]
    # Projects take turns, so one large project cannot take every slot of the tick budget.
    order = [
        insight_id for turn in itertools.zip_longest(*team_orders) for insight_id in turn if insight_id is not None
    ]
    team_ids = {insight_id: due_by_id[insight_id].team_id for insight_id in order}

    def costs_for(insight_ids: list[int]) -> dict[int, int]:
        costs: dict[int, int] = {}
        for team_id in sorted({team_ids[insight_id] for insight_id in insight_ids}):
            team_batch = [insight_id for insight_id in insight_ids if team_ids[insight_id] == team_id]
            costs.update(_query_costs(teams[team_id], team_batch))
        return costs

    # Read the budget before any cost, so a spent hour loads no insight.
    picked, skipped = within_budget(
        order,
        team_ids,
        remaining_budget(config, set(team_ids.values()), now),
        limit,
        costs_for,
        reserve=lambda team_id, cost: reserve_queries(config, team_id, cost, now),
    )
    picks = [
        InsightPick(
            team_id=team_ids[insight_id],
            insight_id=insight_id,
            scored_through=state.get(insight_id, {}),
            interval=due_by_id[insight_id].interval,
            query_cost=cost,
        )
        for insight_id, cost in picked.items()
    ]
    return Selection(picks=picks, candidates=len(order), skipped_for_budget=skipped)
