"""Anomaly search and insight history: the read layer joined with insight access and usage.

Rows of insights that are deleted, or that the user cannot read, are dropped. A series that was not
scored in the range does not appear, so each answer also says how many insights were checked.
"""

import json
import datetime
from collections.abc import Collection, Sequence
from urllib.parse import urlencode

from django.db import models

from posthog.schema import IntervalType

from posthog.dataclasses import frozen
from posthog.interval_specs import interval_spec
from posthog.models import Team, User
from posthog.utils import absolute_uri

from products.dashboards.backend.facade.api import dashboards_by_insight, live_tile_insight_ids, viewable_dashboard_ref
from products.product_analytics.backend.facade.api import viewable_insights
from products.product_analytics.backend.facade.contracts import ViewableInsight
from products.signals.backend.anomaly_scores.config import (
    MAX_LIMITS,
    AnomalyScoringConfig,
    covers_team,
    parse_config,
    read_payload,
)
from products.signals.backend.anomaly_scores.queue import active_insights, turned_off_in_settings
from products.signals.backend.anomaly_scores.read import (
    MAX_BUCKETS,
    FlaggedPoint,
    InsightRollup,
    ScoredBucket,
    SeriesImportance,
    SeriesSummary,
    bucket_starts,
    latest_buckets,
    prior_rate,
    rank_series,
    rollup,
    series_summaries,
)
from products.signals.backend.anomaly_scores.scoring import bucket_end
from products.signals.backend.anomaly_scores.selection import insight_usage

TOP_SERIES = 3
FLAGGED_POINTS = 5
# The insight link shows this many buckets before the first flag and after the last one.
URL_PADDING_BUCKETS = 7
# The scorer writes at most this many series per insight. More come from events any member can capture.
MAX_INSIGHT_SERIES = MAX_LIMITS.max_series
SCORING_DISABLED_MESSAGE = "Anomaly scoring is not enabled for this project, so no insight is scored."
SCORING_TURNED_OFF_MESSAGE = (
    "Anomaly scoring is turned off in this project's self-driving settings, so no insight is scored. "
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
    limit: int = 25


@frozen
class SeriesRow:
    summary: SeriesSummary
    insight: ViewableInsight
    insight_url: str
    expected_buckets: int
    # Newest first.
    flagged_points: tuple[FlaggedPoint, ...]

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
    series: list[SeriesRow]
    insights: list[InsightRow]
    truncated: bool
    # Says why the result is empty. None when it is not.
    message: str | None


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
    team: Team, insight: ViewableInsight, flagged: Sequence[datetime.datetime], interval: IntervalType | None
) -> str:
    """A link to the insight. With flagged buckets, its date range covers them with a few buckets around."""
    url = absolute_uri(f"/project/{team.project_id}/insights/{insight.short_id}")
    if not flagged or interval is None:
        return url
    padding = interval_spec(interval).period * URL_PADDING_BUCKETS
    date_range = {
        "date_from": (min(flagged) - padding).isoformat(),
        "date_to": (bucket_end(max(flagged), interval) + padding).isoformat(),
    }
    return f"{url}?{urlencode({'filters_override': json.dumps(date_range, separators=(',', ':'))})}"


def _flagged_starts(series: Sequence[SeriesSummary]) -> list[datetime.datetime]:
    return [point.bucket_start for summary in series for point in summary.flagged_points]


def _expected_buckets(
    summary: SeriesSummary, date_from: datetime.datetime, date_to: datetime.datetime, now: datetime.datetime
) -> int:
    return len(bucket_starts(summary.newest_bucket, summary.interval, date_from=date_from, date_to=date_to, now=now))


def _importance(team: Team, insight_ids: Collection[int], now: datetime.datetime) -> dict[int, SeriesImportance]:
    if not insight_ids:
        return {}
    usage = insight_usage(team_id=team.id, insight_ids=insight_ids, now=now)
    on_dashboard = dashboards_by_insight(insight_ids, team_id=team.id)
    return {
        insight_id: SeriesImportance(on_dashboard=insight_id in on_dashboard, viewers=usage[insight_id].viewers)
        for insight_id in insight_ids
    }


def _requested_insight_ids(team: Team, user: User, filters: AnomalySearchFilters) -> set[int] | None:
    """The insights the filters allow, or None for every insight."""
    insight_ids: set[int] | None = None
    if filters.dashboard_id is not None:
        if viewable_dashboard_ref(filters.dashboard_id, team=team, user=user) is None:
            raise AnomalyDashboardNotFound()
        insight_ids = set(live_tile_insight_ids(filters.dashboard_id))
    if filters.insight_id is not None:
        insight_ids = {filters.insight_id} if insight_ids is None else insight_ids & {filters.insight_id}
    return insight_ids


def _scoring_off_message(config: AnomalyScoringConfig, team: Team) -> str | None:
    """Why the tick does not score this team's insights, or None when it does."""
    if not covers_team(config, team):
        return SCORING_DISABLED_MESSAGE
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
    """The anomaly rate of each series in the range, most anomalous first, by series or by insight."""
    config = parse_config(read_payload())
    off_message = _scoring_off_message(config, team)
    requested = _requested_insight_ids(team, user, filters)
    intervals = (filters.interval,) if filters.interval is not None else config.intervals
    watched = {insight.insight_id for insight in active_insights([team.id], intervals, now, config.active_window_days)}
    if requested is not None:
        watched &= requested

    summaries = series_summaries(team, date_from=filters.date_from, date_to=filters.date_to, insight_ids=requested)
    insights = {
        insight.id: insight
        for insight in viewable_insights(
            team=team, user=user, insight_ids=watched | {summary.insight_id for summary in summaries.series}
        )
    }
    readable = [summary for summary in summaries.series if summary.insight_id in insights]
    in_range = [
        summary
        for summary in readable
        if summary.scored_buckets and (filters.interval is None or summary.interval == filters.interval)
    ]
    ranked = rank_series(
        in_range,
        prior=prior_rate(readable),
        importance=_importance(team, {summary.insight_id for summary in in_range}, now),
    )
    scored_in_range = len({summary.insight_id for summary in in_range})

    series_rows: list[SeriesRow] = []
    insight_rows: list[InsightRow] = []
    if filters.group_by == AnomalyGroupBy.SERIES:
        matching = [summary for summary in ranked if summary.flagged_buckets or not filters.only_flagged]
        truncated = len(matching) > filters.limit
        series_rows = [
            SeriesRow(
                summary=summary,
                insight=insights[summary.insight_id],
                insight_url=insight_url(
                    team, insights[summary.insight_id], _flagged_starts([summary]), summary.interval
                ),
                expected_buckets=_expected_buckets(summary, filters.date_from, filters.date_to, now),
                flagged_points=summary.flagged_points[:FLAGGED_POINTS],
            )
            for summary in matching[: filters.limit]
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
        truncated = len(matching_insights) > filters.limit
        insight_rows = [
            InsightRow(
                insight=insights[insight_id],
                insight_url=insight_url(team, insights[insight_id], _flagged_starts(series), series[0].interval),
                rollup=rollup(series),
                top_series=[summary for summary in series if summary.flagged_buckets][:TOP_SERIES],
            )
            for insight_id, series in matching_insights[: filters.limit]
        ]

    watched_count = len(watched & insights.keys())
    return AnomalySearchResult(
        scoring_enabled=off_message is None,
        watched_insights=watched_count,
        insights_scored_in_range=scored_in_range,
        series=series_rows,
        insights=insight_rows,
        truncated=truncated or summaries.truncated,
        message=None
        if series_rows or insight_rows
        else _empty_message(off_message=off_message, watched=watched_count, scored_in_range=scored_in_range),
    )


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
    # A series with only baseline rows was not scored in the range at all.
    in_range = [summary for summary in summaries.series if summary.newest_bucket >= filters.date_from]
    ranked = rank_series(in_range, prior=prior_rate(summaries.series), importance={})
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

    newest = max(in_range, key=lambda summary: summary.newest_bucket, default=None)
    message = None
    if newest is None:
        message = off_message or "No bucket of this insight was scored in this range."
    return AnomalyInsightHistory(
        scoring_enabled=off_message is None,
        insight=insight,
        insight_url=insight_url(team, insight, _flagged_starts(ranked), newest.interval if newest else None),
        interval=newest.interval if newest else None,
        profile=newest.profile if newest else None,
        detector=newest.detector if newest else None,
        detector_version=newest.detector_version if newest else None,
        rollup=rollup(in_range),
        series=series,
        truncated=truncated,
        message=message,
    )
