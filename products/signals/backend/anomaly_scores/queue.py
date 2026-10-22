"""Pick the watched insights that the next anomaly scoring tick scores.

There is no stored state. One query per team reads the newest scored bucket of each series back
from the `$anomaly_score` events. Insights that were never scored come first, then the insight whose
newest scored bucket is oldest, so coverage rotates over every eligible insight.
"""

import hashlib
import datetime
from collections.abc import Collection
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
from products.product_analytics.backend.facade.api import watched_trends_insights
from products.signals.backend.anomaly_scores.config import AnomalyScoringConfig
from products.signals.backend.anomaly_scores.scoring import bucket_end

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
UNSUPPORTED_COOLDOWN = datetime.timedelta(days=1)

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


@frozen
class Selection:
    picks: list[InsightPick]
    # Due insights, picked or not. More than the picks means the tick cap cut the queue.
    candidates: int


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
        ch_user=ClickHouseUser.SIGNALS,
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


def _stable_hash(insight_id: int) -> int:
    # Python's `hash` of an int is the int, which would order first coverage by creation.
    return int.from_bytes(hashlib.sha256(str(insight_id).encode()).digest()[:8], "big")


@frozen(order=True)
class _QueuePosition:
    # Fields compare in order: the team's turn, then never-scored first, then the oldest newest bucket.
    turn: int
    scored: bool
    newest_bucket: float
    tiebreak: int


def order_insights(
    insights: list[WatchedInsight], newest_buckets: dict[int, datetime.datetime | None]
) -> list[WatchedInsight]:
    """Never-scored insights first in a stable hashed order, then the stalest. Round robin over teams."""

    def position(insight: WatchedInsight, turn: int) -> _QueuePosition:
        newest = newest_buckets.get(insight.insight_id)
        return _QueuePosition(
            turn=turn,
            scored=newest is not None,
            newest_bucket=0.0 if newest is None else newest.timestamp(),
            tiebreak=_stable_hash(insight.insight_id),
        )

    turns: dict[int, int] = {}
    positions: dict[int, _QueuePosition] = {}
    for insight in sorted(insights, key=lambda insight: position(insight, 0)):
        turn = turns.get(insight.team_id, 0)
        turns[insight.team_id] = turn + 1
        positions[insight.insight_id] = position(insight, turn)
    return sorted(insights, key=lambda insight: positions[insight.insight_id])


def select_insights(config: AnomalyScoringConfig, now: datetime.datetime, limit: int) -> Selection:
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
    due = [insight for insight in due if insight.insight_id not in cooling]
    picks = [
        InsightPick(
            team_id=insight.team_id, insight_id=insight.insight_id, scored_through=state.get(insight.insight_id, {})
        )
        for insight in order_insights(due, newest_buckets)[:limit]
    ]
    return Selection(picks=picks, candidates=len(due))
