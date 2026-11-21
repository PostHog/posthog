"""Anomaly search and insight history: the read layer joined with insight access and usage.

Rows of insights that are deleted, or that the user cannot read, are dropped. A series that was not
scored in the range does not appear, so each answer also says how many insights were checked.
"""

import json
import datetime
from collections.abc import Collection, Mapping, Sequence
from typing import Any
from urllib.parse import quote

from django.db import models

from posthog.schema import IntervalType

from posthog.dataclasses import frozen
from posthog.interval_specs import interval_spec
from posthog.models import Team, User
from posthog.utils import absolute_uri

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.dashboards.backend.facade.api import (
    dashboards_by_insight,
    live_tile_insight_ids,
    viewable_dashboard_ids,
    viewable_dashboard_ref,
)
from products.dashboards.backend.facade.contracts import DashboardRef
from products.product_analytics.backend.facade.api import (
    insight_ids_named_like,
    viewable_insights,
    viewable_saved_queries,
)
from products.product_analytics.backend.facade.contracts import ViewableInsight
from products.signals.backend.anomaly_scores.config import (
    MAX_LIMITS,
    AnomalyScoringConfig,
    enrolls_team,
    parse_config,
    read_payload,
)
from products.signals.backend.anomaly_scores.queue import active_insights, turned_off_in_settings
from products.signals.backend.anomaly_scores.read import (
    MAX_BUCKETS,
    SCORED_HISTORY_READY_DAYS,
    FlaggedPoint,
    InsightRollup,
    ScoredBucket,
    SeriesImportance,
    SeriesPoint,
    SeriesSummary,
    bucket_starts,
    chart_from,
    chart_shares,
    latest_buckets,
    rank_series,
    rollup,
    scored_days,
    series_points,
    series_summaries,
)
from products.signals.backend.anomaly_scores.scoring import bucket_end
from products.signals.backend.anomaly_scores.selection import insight_usage
from products.signals.backend.facade.source_configs import analytics_source_enabled

TOP_SERIES = 3
FLAGGED_POINTS = 5
# The insight link shows enough buckets before the first flag to see what normal looked like, and few after the
# last one, so the newest flag sits near the right edge of the chart.
URL_BUCKETS_BEFORE = 24
URL_BUCKETS_AFTER = 3
# The scorer writes at most this many series per insight. More come from events any member can capture.
MAX_INSIGHT_SERIES = MAX_LIMITS.max_series
# A larger set of requested insights is filtered after the read, so the ClickHouse query stays small.
MAX_SCOPED_INSIGHTS = 1_000
# The fewest completed buckets of an interval that the range of its series holds. A short range such as the last
# 3 days rarely holds a completed weekly or monthly bucket, so without this those series are never checked in it.
MIN_RANGE_BUCKETS: Mapping[IntervalType, int] = {IntervalType.WEEK: 2, IntervalType.MONTH: 1}
SCORING_DISABLED_MESSAGE = "Anomaly scoring is not enabled for this project, so no insight is scored."
SCORING_SOURCE_OFF_MESSAGE = (
    "The Product analytics source is turned off in this project's self-driving settings, so no insight is scored. "
    "Scores written before it was turned off stay readable."
)
SCORING_TURNED_OFF_MESSAGE = (
    "Anomaly scoring is turned off in this project's Product analytics source, so no insight is scored. "
    "Scores written before it was turned off stay readable."
)


class AnomalyInterval(models.TextChoices):
    HOUR = "hour", "Hour"
    DAY = "day", "Day"
    WEEK = "week", "Week"
    MONTH = "month", "Month"


class AnomalyGroupBy(models.TextChoices):
    SERIES = "series", "Series"
    INSIGHT = "insight", "Insight"


class AnomalyOrder(models.TextChoices):
    UNUSUAL = "unusual", "Unusual"
    RECENT = "recent", "Recent"


class AnomalyDashboardNotFound(Exception):
    pass


@frozen
class AnomalySearchFilters:
    date_from: datetime.datetime
    date_to: datetime.datetime
    insight_id: int | None = None
    dashboard_id: int | None = None
    interval: IntervalType | None = None
    only_flagged: bool = True
    group_by: AnomalyGroupBy = AnomalyGroupBy.SERIES
    order: AnomalyOrder = AnomalyOrder.UNUSUAL
    limit: int = 25
    offset: int = 0
    # Part of an insight name, matched ignoring case.
    search: str | None = None
    # Adds the scored buckets of each series row in the chart window of its interval, at the cost of one more query.
    include_points: bool = False


@frozen
class AnomalyIntervalRange:
    """The range a search applied to the series of one interval."""

    interval: IntervalType
    date_from: datetime.datetime
    date_to: datetime.datetime


@frozen
class SeriesRow:
    summary: SeriesSummary
    insight: ViewableInsight
    insight_url: str
    expected_buckets: int
    # Newest first.
    flagged_points: tuple[FlaggedPoint, ...]
    # Oldest first, over the chart window of the interval, not the range. None when the request leaves points out.
    points: tuple[SeriesPoint, ...] | None = None
    # The dashboards the insight sits on that the user may view, oldest tile first.
    dashboards: tuple[DashboardRef, ...] = ()

    @property
    def coverage(self) -> float | None:
        return min(1.0, self.summary.scored_buckets / self.expected_buckets) if self.expected_buckets else None


@frozen
class InsightRow:
    insight: ViewableInsight
    insight_url: str
    rollup: InsightRollup
    top_series: list[SeriesSummary]


@frozen
class AnomalySearchResult:
    scoring_enabled: bool
    watched_insights: int
    insights_scored_in_range: int
    # Over a fixed window before now, not the requested range, so it says whether scores are ready to rely on.
    scored_days: int
    # One entry per interval the search covers. A weekly or monthly range can start before the requested one.
    interval_ranges: list[AnomalyIntervalRange]
    series: list[SeriesRow]
    insights: list[InsightRow]
    has_more: bool
    truncated: bool
    # The series read hit its cap and dropped series this result needed. Narrowing the range or filters fixes it.
    series_capped: bool
    # Says why the result is empty. None when it is not.
    message: str | None
    # The newest scored bucket of any series the filters match, so it does not change with the order or the page.
    scored_through: datetime.datetime | None

    @property
    def scored_history_ready(self) -> bool:
        return self.scored_days >= SCORED_HISTORY_READY_DAYS


@frozen
class AnomalySeriesRef:
    insight_id: int
    series_key: str
    interval: IntervalType


@frozen
class AnomalySeriesPoints:
    series: AnomalySeriesRef
    # The start of the chart window. The window ends now.
    date_from: datetime.datetime
    # Oldest first.
    points: tuple[SeriesPoint, ...]


@frozen
class AnomalyHistoryFilters:
    insight_id: int
    date_from: datetime.datetime
    date_to: datetime.datetime
    series_key: str | None = None
    include_buckets: bool = True
    include_warmup: bool = False


@frozen
class SeriesHistory:
    summary: SeriesSummary
    expected_buckets: int
    # Oldest first. Empty when the request leaves buckets out.
    buckets: list[ScoredBucket]

    @property
    def coverage(self) -> float | None:
        return min(1.0, self.summary.scored_buckets / self.expected_buckets) if self.expected_buckets else None


@frozen
class AnomalyInsightHistory:
    scoring_enabled: bool
    insight: ViewableInsight
    insight_url: str
    # From the newest scored bucket of the insight. None when no bucket was scored in the range.
    interval: IntervalType | None
    profile: str | None
    detector: str | None
    detector_version: str | None
    rollup: InsightRollup
    series: list[SeriesHistory]
    truncated: bool
    message: str | None


def insight_url(
    team: Team,
    insight: ViewableInsight,
    flagged: Sequence[datetime.datetime],
    interval: IntervalType | None,
    query: Mapping[str, Any] | None,
) -> str:
    """A link to the insight. With flagged buckets, its date range covers them and the buckets around them.

    The range goes in a copy of the saved query in the link, as in a shared insight link, so the link needs that
    query. A `filters_override` would open the insight as if a dashboard's filters were applied.
    """
    url = absolute_uri(f"/project/{team.project_id}/insights/{insight.short_id}")
    source = query.get("source") if query else None
    if not flagged or interval is None or query is None or not isinstance(source, dict):
        return url
    period = interval_spec(interval).period
    date_range = {
        "date_from": (min(flagged) - period * URL_BUCKETS_BEFORE).isoformat(),
        "date_to": (bucket_end(max(flagged), interval) + period * URL_BUCKETS_AFTER).isoformat(),
    }
    linked = {**query, "source": {**source, "dateRange": date_range}}
    return f"{url}#q={quote(json.dumps(linked, separators=(',', ':')))}"


def _saved_queries(team: Team, user: User, insights: Collection[ViewableInsight]) -> dict[str, dict[str, Any]]:
    return viewable_saved_queries(team=team, user=user, short_ids={insight.short_id for insight in insights})


def _flagged_starts(series: Sequence[SeriesSummary]) -> list[datetime.datetime]:
    return [point.bucket_start for summary in series for point in summary.flagged_points]


def _expected_buckets(
    summary: SeriesSummary, date_from: datetime.datetime, date_to: datetime.datetime, now: datetime.datetime
) -> int:
    return len(bucket_starts(summary.newest_bucket, summary.interval, date_from=date_from, date_to=date_to, now=now))


def interval_ranges(
    team: Team,
    intervals: Sequence[IntervalType],
    *,
    date_from: datetime.datetime,
    date_to: datetime.datetime,
    now: datetime.datetime,
) -> list[AnomalyIntervalRange]:
    """The range of each interval: the requested range, started earlier when needed to hold ``MIN_RANGE_BUCKETS``.

    The buckets counted are the newest that completed by the end of the range, or by ``now`` when that is earlier.
    They line up with the project's week start day, as the scored insight buckets do.
    """
    end = min(date_to, now).astimezone(team.timezone_info)
    ranges: list[AnomalyIntervalRange] = []
    for interval in intervals:
        start = date_from
        buckets = MIN_RANGE_BUCKETS.get(interval)
        if buckets:
            spec = interval_spec(interval)
            start = min(date_from, spec.align(end, team.week_start_day) - spec.period * buckets)
        ranges.append(AnomalyIntervalRange(interval=interval, date_from=start, date_to=date_to))
    return ranges


def _importance(team: Team, insight_ids: Collection[int], now: datetime.datetime) -> dict[int, SeriesImportance]:
    if not insight_ids:
        return {}
    usage = insight_usage(team_id=team.id, insight_ids=insight_ids, now=now)
    on_dashboard = dashboards_by_insight(insight_ids, team_id=team.id)
    return {
        insight_id: SeriesImportance(on_dashboard=insight_id in on_dashboard, viewers=usage[insight_id].viewers)
        for insight_id in insight_ids
    }


def _viewable_dashboards(team: Team, user: User, insight_ids: Collection[int]) -> dict[int, tuple[DashboardRef, ...]]:
    if not insight_ids:
        return {}
    by_insight = dashboards_by_insight(insight_ids, team_id=team.id)
    viewable = viewable_dashboard_ids(
        team_id=team.id,
        dashboard_ids={ref.id for refs in by_insight.values() for ref in refs},
        user_access_control=UserAccessControl(user=user, team=team),
    )
    return {insight_id: tuple(ref for ref in refs if ref.id in viewable) for insight_id, refs in by_insight.items()}


def _requested_insight_ids(team: Team, user: User, filters: AnomalySearchFilters) -> set[int] | None:
    """The insights the filters allow, or None for every insight."""
    insight_ids: set[int] | None = None
    if filters.dashboard_id is not None:
        if viewable_dashboard_ref(filters.dashboard_id, team=team, user=user) is None:
            raise AnomalyDashboardNotFound()
        insight_ids = set(live_tile_insight_ids(filters.dashboard_id))
    if filters.insight_id is not None:
        insight_ids = {filters.insight_id} if insight_ids is None else insight_ids & {filters.insight_id}
    if filters.search:
        named = insight_ids_named_like(team_id=team.id, search=filters.search)
        insight_ids = named if insight_ids is None else insight_ids & named
    return insight_ids


def _scoring_off_message(config: AnomalyScoringConfig, team: Team) -> str | None:
    """Why the tick does not score this team's insights, or None when it does."""
    if not enrolls_team(config, team):
        return SCORING_DISABLED_MESSAGE
    if not analytics_source_enabled(team.id):
        return SCORING_SOURCE_OFF_MESSAGE
    if turned_off_in_settings(team):
        return SCORING_TURNED_OFF_MESSAGE
    return None


def _empty_message(*, off_message: str | None, watched: int, scored_in_range: int) -> str:
    if off_message is not None:
        return off_message
    if not scored_in_range:
        return f"No insight was scored in this range. Scoring checks {watched} active insights, a few at a time."
    return (
        f"Nothing was flagged in this range among the {scored_in_range} insights scored. "
        "Insights that were not scored in the range were not checked."
    )


def search(team: Team, user: User, filters: AnomalySearchFilters, now: datetime.datetime) -> AnomalySearchResult:
    """The anomaly rate of each series in the range, in the requested order, by series or by insight."""
    config = parse_config(read_payload())
    off_message = _scoring_off_message(config, team)
    requested = _requested_insight_ids(team, user, filters)
    intervals = (filters.interval,) if filters.interval is not None else config.intervals
    watched = {insight.insight_id for insight in active_insights([team.id], intervals, now, config.active_window_days)}
    if requested is not None:
        watched &= requested

    ranges = interval_ranges(
        team,
        (filters.interval,)
        if filters.interval is not None
        else [IntervalType(value) for value in AnomalyInterval.values],
        date_from=filters.date_from,
        date_to=filters.date_to,
        now=now,
    )
    range_from = {interval_range.interval: interval_range.date_from for interval_range in ranges}

    scope = requested if requested is None or len(requested) <= MAX_SCOPED_INSIGHTS else None
    summaries = series_summaries(
        team,
        date_from=filters.date_from,
        date_to=filters.date_to,
        insight_ids=scope,
        interval_from={interval: start for interval, start in range_from.items() if start != filters.date_from},
    )
    requested_series = [summary for summary in summaries.series if requested is None or summary.insight_id in requested]
    insights = {
        insight.id: insight
        for insight in viewable_insights(
            team=team, user=user, insight_ids=watched | {summary.insight_id for summary in requested_series}
        )
    }
    readable = [summary for summary in requested_series if summary.insight_id in insights]
    in_range = [
        summary
        for summary in readable
        if summary.scored_buckets and (filters.interval is None or summary.interval == filters.interval)
    ]
    ranked = rank_series(
        in_range,
        chart_shares=chart_shares(
            team,
            date_to=filters.date_to,
            series={
                (summary.insight_id, summary.series_key): summary.interval
                for summary in in_range
                if summary.flagged_buckets
            },
        ),
        importance=_importance(team, {summary.insight_id for summary in in_range}, now),
        recent_first=filters.order == AnomalyOrder.RECENT,
    )
    scored_in_range = len({summary.insight_id for summary in in_range})

    page = slice(filters.offset, filters.offset + filters.limit)
    series_rows: list[SeriesRow] = []
    insight_rows: list[InsightRow] = []
    if filters.group_by == AnomalyGroupBy.SERIES:
        matching = [summary for summary in ranked if summary.flagged_buckets or not filters.only_flagged]
        matched = len(matching)
        page_series = matching[page]
        points = (
            series_points(
                team,
                date_to=filters.date_to,
                series={(summary.insight_id, summary.series_key): summary.interval for summary in page_series},
            )
            if filters.include_points
            else None
        )
        dashboards = _viewable_dashboards(team, user, {summary.insight_id for summary in page_series})
        queries = _saved_queries(team, user, [insights[summary.insight_id] for summary in page_series])
        series_rows = [
            SeriesRow(
                summary=summary,
                insight=insights[summary.insight_id],
                insight_url=insight_url(
                    team,
                    insights[summary.insight_id],
                    _flagged_starts([summary]),
                    summary.interval,
                    queries.get(insights[summary.insight_id].short_id),
                ),
                expected_buckets=_expected_buckets(
                    summary, range_from.get(summary.interval, filters.date_from), filters.date_to, now
                ),
                flagged_points=summary.flagged_points[:FLAGGED_POINTS],
                points=None if points is None else tuple(points[(summary.insight_id, summary.series_key)]),
                dashboards=dashboards.get(summary.insight_id, ()),
            )
            for summary in page_series
        ]
    else:
        by_insight: dict[int, list[SeriesSummary]] = {}
        for summary in ranked:
            by_insight.setdefault(summary.insight_id, []).append(summary)
        matching_insights = [
            (insight_id, series)
            for insight_id, series in by_insight.items()
            if any(summary.flagged_buckets for summary in series) or not filters.only_flagged
        ]
        matched = len(matching_insights)
        page_insights = matching_insights[page]
        queries = _saved_queries(team, user, [insights[insight_id] for insight_id, _ in page_insights])
        insight_rows = [
            InsightRow(
                insight=insights[insight_id],
                insight_url=insight_url(
                    team,
                    insights[insight_id],
                    _flagged_starts(series),
                    series[0].interval,
                    queries.get(insights[insight_id].short_id),
                ),
                rollup=rollup(series),
                top_series=[summary for summary in series if summary.flagged_buckets][:TOP_SERIES],
            )
            for insight_id, series in page_insights
        ]

    has_more = matched > page.stop
    # Flagged series rows need only flagged series. Insight rollups count every series of an insight.
    series_capped = (
        summaries.flagged_truncated
        if filters.only_flagged and filters.group_by == AnomalyGroupBy.SERIES
        else summaries.truncated
    )
    watched_count = len(watched & insights.keys())
    return AnomalySearchResult(
        scoring_enabled=off_message is None,
        watched_insights=watched_count,
        insights_scored_in_range=scored_in_range,
        scored_days=scored_days(team, now=now),
        interval_ranges=ranges,
        series=series_rows,
        insights=insight_rows,
        has_more=has_more,
        truncated=has_more or series_capped,
        series_capped=series_capped,
        message=None
        if matched
        else _empty_message(off_message=off_message, watched=watched_count, scored_in_range=scored_in_range),
        scored_through=max(
            (summary.scored_through for summary in in_range if summary.scored_through is not None), default=None
        ),
    )


def chart_points(
    team: Team, user: User, series: Sequence[AnomalySeriesRef], now: datetime.datetime
) -> list[AnomalySeriesPoints]:
    """The chart points of each requested series whose insight the user can read, in one query scoped to them."""
    readable = {
        insight.id
        for insight in viewable_insights(team=team, user=user, insight_ids={ref.insight_id for ref in series})
    }
    by_key = {(ref.insight_id, ref.series_key): ref for ref in series if ref.insight_id in readable}
    points = series_points(team, date_to=now, series={key: ref.interval for key, ref in by_key.items()})
    return [
        AnomalySeriesPoints(series=ref, date_from=chart_from(ref.interval, now), points=tuple(points[key]))
        for key, ref in by_key.items()
    ]


def _series_buckets(
    series_key: str,
    starts: list[datetime.datetime],
    scored: list[ScoredBucket],
    *,
    scored_since: datetime.datetime | None,
) -> list[ScoredBucket]:
    """Scored rows and a `scored: false` row for each completed bucket without one, oldest first.

    ``scored_since`` is the oldest scored row a capped query returned, so no gap is made up before it.
    """
    by_start = {
        start: ScoredBucket(series_key=series_key, bucket_start=start, scored=False)
        for start in starts
        if scored_since is None or start >= scored_since
    }
    for bucket in scored:
        by_start[bucket.bucket_start] = bucket
    return [by_start[start] for start in sorted(by_start)]


def insight_history(
    team: Team, user: User, filters: AnomalyHistoryFilters, now: datetime.datetime
) -> AnomalyInsightHistory | None:
    """Every series of one insight with its scored buckets, or None when the user cannot read the insight."""
    readable = viewable_insights(team=team, user=user, insight_ids=[filters.insight_id])
    if not readable:
        return None
    insight = readable[0]
    off_message = _scoring_off_message(parse_config(read_payload()), team)
    summaries = series_summaries(
        team,
        date_from=filters.date_from,
        date_to=filters.date_to,
        insight_ids=[insight.id],
        series_key=filters.series_key,
    )
    ranked = rank_series(summaries.series, chart_shares={}, importance={})
    truncated = summaries.truncated or len(ranked) > MAX_INSIGHT_SERIES
    ranked = ranked[:MAX_INSIGHT_SERIES]

    scored_by_series: dict[str, list[ScoredBucket]] = {}
    scored_since: datetime.datetime | None = None
    if filters.include_buckets and ranked:
        latest = latest_buckets(
            team,
            insight_id=insight.id,
            date_from=filters.date_from,
            date_to=filters.date_to,
            series_key=filters.series_key,
            include_warmup=filters.include_warmup,
        )
        for bucket in latest.buckets:
            scored_by_series.setdefault(bucket.series_key, []).append(bucket)
        if latest.truncated and latest.buckets:
            truncated = True
            scored_since = min(bucket.bucket_start for bucket in latest.buckets)

    # Each series keeps at most an equal share of the cap, its newest buckets, so the total stays within it.
    per_series = MAX_BUCKETS // max(1, len(ranked))
    series: list[SeriesHistory] = []
    for summary in ranked:
        starts = bucket_starts(
            summary.newest_bucket, summary.interval, date_from=filters.date_from, date_to=filters.date_to, now=now
        )
        buckets = (
            _series_buckets(
                summary.series_key, starts, scored_by_series.get(summary.series_key, []), scored_since=scored_since
            )
            if filters.include_buckets
            else []
        )
        if len(buckets) > per_series:
            truncated = True
            buckets = buckets[-per_series:]
        series.append(SeriesHistory(summary=summary, expected_buckets=len(starts), buckets=buckets))

    newest = max(summaries.series, key=lambda summary: summary.newest_bucket, default=None)
    message = None
    if newest is None:
        message = off_message or "No bucket of this insight was scored in this range."
    return AnomalyInsightHistory(
        scoring_enabled=off_message is None,
        insight=insight,
        insight_url=insight_url(
            team,
            insight,
            _flagged_starts(ranked),
            newest.interval if newest else None,
            _saved_queries(team, user, [insight]).get(insight.short_id),
        ),
        interval=newest.interval if newest else None,
        profile=newest.profile if newest else None,
        detector=newest.detector if newest else None,
        detector_version=newest.detector_version if newest else None,
        rollup=rollup(summaries.series),
        series=series,
        truncated=truncated,
        message=message,
    )
