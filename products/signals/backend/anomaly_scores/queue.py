"""Pick the watched insights that the next anomaly scoring tick scores.

There is no stored state. One query per team reads the newest scored bucket of each series back
from the `$anomaly_score` events. Insights that were never scored come first, then the insight whose
newest scored bucket is oldest, so coverage rotates over every eligible insight.
"""

import hashlib
import datetime
from typing import Any, cast

from django.core.cache import cache
from django.db.models import Q, TextField, Value
from django.db.models.fields.json import KT
from django.db.models.functions import Coalesce

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
from products.product_analytics.backend.facade.models import Insight
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
WHERE event = {event} AND timestamp >= {since} AND properties.$anomaly_source = {source}
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
    if not team_ids:
        return []
    trends = (
        Insight.objects.filter(team_id__in=team_ids, saved=True)
        .annotate(
            # A wrapper node holds the trends query in `source`.
            scored_kind=Coalesce(KT("query__source__kind"), KT("query__kind")),
            scored_interval=Coalesce(
                KT("query__source__interval"),
                KT("query__interval"),
                Value(IntervalType.DAY.value),
                output_field=TextField(),
            ),
            scored_display=Coalesce(
                KT("query__source__trendsFilter__display"),
                KT("query__trendsFilter__display"),
                Value(""),
                output_field=TextField(),
            ),
        )
        .filter(scored_kind="TrendsQuery", scored_interval__in=[interval.value for interval in intervals])
        .exclude(scored_display__in=_UNSCORED_DISPLAYS)
    )
    # Two queries instead of one OR, so Postgres never multiplies dashboard tiles by views.
    on_dashboard = trends.filter(
        Q(dashboard_tiles__deleted=False) | Q(dashboard_tiles__deleted__isnull=True),
        dashboard_tiles__dashboard__deleted=False,
    )
    viewed = trends.filter(insightviewed__last_viewed_at__gte=now - VIEW_WINDOW)
    rows: set[tuple[int, int, str]] = set()
    for queryset in (on_dashboard, viewed):
        rows.update(cast(list[tuple[int, int, str]], queryset.values_list("team_id", "id", "scored_interval")))
    return [
        WatchedInsight(team_id=team_id, insight_id=insight_id, interval=IntervalType(interval))
        for team_id, insight_id, interval in sorted(rows)
    ]


def scored_state_since(config: AnomalyScoringConfig, now: datetime.datetime) -> datetime.datetime:
    """How far back the scored state reaches: one bucket more than the backfill cap of the longest interval."""
    return min(
        now - interval_spec(interval).period * (config.limits.max_backfill_buckets + 1) for interval in config.intervals
    )


def _utc(value: datetime.datetime) -> datetime.datetime:
    return value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value.astimezone(datetime.UTC)


def scored_buckets(team: Team, since: datetime.datetime) -> dict[int, dict[str, datetime.datetime]]:
    """Insight id to the newest scored bucket start of each of its series."""
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    response = execute_hogql_query(
        _SCORED_BUCKETS_QUERY,
        team,
        query_type="AnomalyScoresScoredBuckets",
        placeholders={
            "event": ast.Constant(value=SCORE_EVENT),
            "source": ast.Constant(value=SOURCE_INSIGHT),
            "since": ast.Constant(value=since),
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


def order_insights(
    insights: list[WatchedInsight], newest_buckets: dict[int, datetime.datetime | None]
) -> list[WatchedInsight]:
    """Never-scored insights first in a stable hashed order, then the stalest. Round robin over teams."""

    def staleness(insight: WatchedInsight) -> tuple[int, float, int]:
        newest = newest_buckets.get(insight.insight_id)
        return (
            0 if newest is None else 1,
            0.0 if newest is None else newest.timestamp(),
            _stable_hash(insight.insight_id),
        )

    rank_in_team: dict[int, int] = {}
    ranked: list[tuple[int, tuple[int, float, int], WatchedInsight]] = []
    for insight in sorted(insights, key=staleness):
        rank = rank_in_team.get(insight.team_id, 0)
        rank_in_team[insight.team_id] = rank + 1
        ranked.append((rank, staleness(insight), insight))
    return [insight for _, _, insight in sorted(ranked, key=lambda item: item[:2])]


def select_insights(config: AnomalyScoringConfig, now: datetime.datetime, limit: int) -> Selection:
    teams = {team.id: team for team in eligible_teams(config)}
    insights = watched_insights(list(teams), config.intervals, now)
    since = scored_state_since(config, now)
    state: dict[int, dict[str, datetime.datetime]] = {}
    for team_id in sorted({insight.team_id for insight in insights}):
        state.update(scored_buckets(teams[team_id], since))

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
