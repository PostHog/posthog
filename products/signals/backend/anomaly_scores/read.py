"""Read the `$anomaly_score` events of a project back, as anomaly rates per series and as scored buckets.

A bucket can be scored more than once, so every read keeps the newest result of each series and bucket.
A bucket is its declared `$anomaly_bucket_start`. Ingestion can move the event timestamp by some milliseconds.
Warm-up rows have a null score and count nowhere. A bucket that was not scored is unknown, never 0.
A raw score ranks buckets within one series only, so a ranking across series uses shares of flagged buckets, never scores.
"""

import json
import math
import datetime
from collections.abc import Collection, Mapping, Sequence
from typing import Any, cast
from zoneinfo import ZoneInfo

from django.core.cache import cache

from posthog.schema import IntervalType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.interval_specs import interval_spec
from posthog.models import Team

from products.signals.backend.anomaly_scores.config import DEFAULT_PROFILE
from products.signals.backend.anomaly_scores.queue import SCORE_EVENT, SOURCE_INSIGHT
from products.signals.backend.anomaly_scores.scoring import bucket_end

# One row is one series. Far more than the series of every active insight of one project.
MAX_SERIES = 10_000
MAX_BUCKETS = 2_000
# Enough for an hourly series over 14 days, or a daily series over a year.
MAX_SERIES_POINTS = 400
# The buckets a chart shows before the end of its window, by interval. It does not follow the requested range,
# so a short range still charts enough history to judge a flag. Each stays within MAX_SERIES_POINTS.
CHART_BUCKETS: Mapping[IntervalType, int] = {
    IntervalType.HOUR: 7 * 24,
    IntervalType.DAY: 14,
    IntervalType.WEEK: 26,
    IntervalType.MONTH: 24,
}
# A series needs this many scored buckets in its chart window before its share of flagged buckets orders it.
# A share of fewer buckets says little: 1 flagged of 3 scored reads as a third of the window.
MIN_CHART_BUCKETS = 10
# The intervals the scorer writes. Any member can capture a row with another interval, such as `second`,
# and stepping through its buckets over a long range would take hours.
SCORED_INTERVALS = frozenset(DEFAULT_PROFILE.intervals)
# The event scan reaches this far past the range, so a row whose timestamp ingestion moved stays in the scan.
TIMESTAMP_DRIFT = datetime.timedelta(hours=1)
# A project's scores are ready to rely on once this many days of the window have a scored daily bucket.
SCORED_HISTORY_WINDOW = datetime.timedelta(days=28)
SCORED_HISTORY_READY_DAYS = 14
# The count changes at most once a day. A ready count stays cached longer, because a project leaves the
# ready state only after it stops being scored for about two weeks.
SCORED_DAYS_CACHE_TIMEOUT = datetime.timedelta(hours=3)
SCORED_DAYS_READY_CACHE_TIMEOUT = datetime.timedelta(days=1)

_LATEST_BUCKETS = """
SELECT
    toInt(properties.$anomaly_insight_id) AS insight_id,
    properties.$anomaly_series_key AS series_key,
    coalesce(toDateTime(properties.$anomaly_bucket_start), timestamp) AS bucket_start,
    toFloat(properties.$anomaly_score) AS score,
    toInt(properties.$anomaly_flag) AS flag,
    toFloat(properties.$anomaly_value) AS value,
    properties.$anomaly_interval AS bucket_interval,
    properties.$anomaly_series_label AS series_label,
    properties.$anomaly_breakdown_value AS breakdown_value,
    properties.$anomaly_detector AS detector,
    properties.$anomaly_detector_version AS detector_version,
    properties.$anomaly_profile AS profile,
    JSONExtractString(properties, '$anomaly_details') AS details,
    toDateTime(properties.$anomaly_scored_at) AS scored_at
FROM events
WHERE event = {event}
    AND properties.$anomaly_source = {source}
    AND timestamp >= {scan_since}
    AND timestamp <= {scan_until}
    AND bucket_start >= {since}
    AND bucket_start <= {until}
    AND {scope}
ORDER BY scored_at DESC
LIMIT 1 BY series_key, bucket_start
"""

_SERIES_QUERY = f"""
SELECT
    insight_id,
    series_key,
    argMax(series_label, bucket_start),
    argMax(breakdown_value, bucket_start),
    argMax(bucket_interval, bucket_start) AS series_interval,
    argMax(detector, bucket_start),
    argMax(detector_version, bucket_start),
    argMax(profile, bucket_start),
    max(bucket_start),
    countIf(score IS NOT NULL),
    countIf(score IS NOT NULL AND flag = 1),
    maxIf(bucket_start, score IS NOT NULL),
    groupArrayIf(tuple(bucket_start, value, score), score IS NOT NULL AND flag = 1)
FROM ({_LATEST_BUCKETS})
GROUP BY insight_id, series_key
HAVING insight_id IS NOT NULL AND notEmpty(ifNull(series_key, '')) AND series_interval IN {{intervals}}
ORDER BY countIf(score IS NOT NULL AND flag = 1) > 0 DESC
LIMIT {{limit}}
"""

_BUCKETS_QUERY = f"""
SELECT series_key, bucket_start, score, flag, value, details, scored_at
FROM ({_LATEST_BUCKETS})
WHERE bucket_start >= {{date_from}} AND {{keep}}
ORDER BY bucket_start DESC, series_key
LIMIT {{limit}}
"""

_POINTS_QUERY = f"""
SELECT insight_id, series_key, bucket_start, value, flag
FROM ({_LATEST_BUCKETS})
WHERE score IS NOT NULL
ORDER BY insight_id, series_key, bucket_start DESC
LIMIT {{limit}} BY insight_id, series_key
LIMIT {{total_limit}}
"""

_CHART_SHARES_QUERY = f"""
SELECT insight_id, series_key, count(), countIf(flag = 1)
FROM ({_LATEST_BUCKETS})
WHERE score IS NOT NULL
GROUP BY insight_id, series_key
LIMIT {{limit}}
"""

_SCORED_DAYS_QUERY = """
SELECT count(DISTINCT toDate(toTimeZone(bucket_start, 'UTC')))
FROM (
    SELECT coalesce(toDateTime(properties.$anomaly_bucket_start), timestamp) AS bucket_start
    FROM events
    WHERE event = {event}
        AND properties.$anomaly_source = {source}
        AND properties.$anomaly_interval = {interval}
        AND toFloat(properties.$anomaly_score) IS NOT NULL
        AND timestamp >= {scan_since}
        AND timestamp <= {scan_until}
)
WHERE bucket_start >= {since} AND bucket_start <= {until}
"""


@frozen
class FlaggedPoint:
    bucket_start: datetime.datetime
    value: float | None
    score: float | None


@frozen
class SeriesPoint:
    bucket_start: datetime.datetime
    value: float | None
    flag: bool


@frozen
class SeriesSummary:
    """One series over the requested range. Counts cover scored buckets only."""

    insight_id: int
    series_key: str
    series_label: str | None
    breakdown_value: str | None
    interval: IntervalType
    detector: str | None
    detector_version: str | None
    profile: str | None
    # Any bucket of the series, scored or warm-up, so expected buckets can line up with its bucket starts.
    newest_bucket: datetime.datetime
    scored_buckets: int
    flagged_buckets: int
    # The newest scored bucket in the range. None when no bucket of the range was scored.
    scored_through: datetime.datetime | None
    # Every flagged bucket of the range, newest first.
    flagged_points: tuple[FlaggedPoint, ...]

    @property
    def anomaly_rate(self) -> float | None:
        return self.flagged_buckets / self.scored_buckets if self.scored_buckets else None

    @property
    def first_flagged_bucket(self) -> datetime.datetime | None:
        return self.flagged_points[-1].bucket_start if self.flagged_points else None

    @property
    def last_flagged_bucket(self) -> datetime.datetime | None:
        return self.flagged_points[0].bucket_start if self.flagged_points else None


@frozen
class SeriesSummaries:
    series: list[SeriesSummary]
    truncated: bool
    # The read keeps flagged series first, so the cap drops a flagged series only after every unflagged one.
    flagged_truncated: bool = False


@frozen
class ChartShare:
    """The scored and flagged buckets of one series in the chart window of its interval."""

    scored_buckets: int
    flagged_buckets: int

    @property
    def share(self) -> float | None:
        """None when too few buckets were scored for the share to order a series."""
        return self.flagged_buckets / self.scored_buckets if self.scored_buckets >= MIN_CHART_BUCKETS else None


@frozen
class ScoredBucket:
    series_key: str
    bucket_start: datetime.datetime
    # False for a completed bucket of the range that has no score row. Its value, score and flag are unknown.
    scored: bool
    value: float | None = None
    # Null on a warm-up row.
    score: float | None = None
    flag: bool | None = None
    scored_at: datetime.datetime | None = None
    details: dict[str, Any] | None = None


@frozen
class ScoredBuckets:
    buckets: list[ScoredBucket]
    truncated: bool


@frozen
class SeriesImportance:
    on_dashboard: bool
    viewers: int


@frozen(order=True)
class _RankKey:
    """Sorts smallest first, field by field, so each measure is negated to put the largest first."""

    # 0 for every series unless the newest flag sorts first.
    negative_flag_end: float
    # 0 for every series unless the anomaly rate sorts first.
    negative_rate: float
    unflagged: bool
    # A series without a share of its own sorts after every series with one.
    no_chart_share: bool
    chart_share: float
    negative_flagged_buckets: int
    negative_last_flagged: float
    off_dashboard: bool
    negative_viewers: int
    insight_id: int
    series_key: str


@frozen
class InsightRollup:
    """Buckets summed over the series of one insight. Rates of series are never averaged."""

    series_count: int
    flagged_series: int
    scored_buckets: int
    flagged_buckets: int
    last_flagged_bucket: datetime.datetime | None

    @property
    def anomaly_rate(self) -> float | None:
        return self.flagged_buckets / self.scored_buckets if self.scored_buckets else None


def _local(value: datetime.datetime, timezone: ZoneInfo) -> datetime.datetime:
    aware = value.replace(tzinfo=datetime.UTC) if value.tzinfo is None else value
    return aware.astimezone(timezone)


def _float(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and math.isfinite(value) else None


def _text(value: Any) -> str | None:
    return None if value is None or value == "" else str(value)


def _details(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    try:
        details = json.loads(value)
    except ValueError:
        return None
    return details if isinstance(details, dict) else None


def _scope(insight_ids: Collection[int] | None, series_key: str | None) -> ast.Expr:
    exprs: list[ast.Expr] = []
    if insight_ids is not None:
        exprs.append(
            parse_expr(
                "toInt(properties.$anomaly_insight_id) IN {insight_ids}",
                placeholders={
                    "insight_ids": ast.Tuple(
                        exprs=[ast.Constant(value=insight_id) for insight_id in sorted(insight_ids)]
                    )
                },
            )
        )
    if series_key is not None:
        exprs.append(
            parse_expr("properties.$anomaly_series_key = {series_key}", {"series_key": ast.Constant(value=series_key)})
        )
    if not exprs:
        return ast.Constant(value=True)
    return ast.And(exprs=exprs)


def _chart_windows(series: Mapping[tuple[int, str], IntervalType], date_to: datetime.datetime) -> ast.Expr:
    """Keeps the rows of each ``(insight_id, series_key)`` in the chart window of the interval the caller asked for.

    It filters before the read keeps the newest result of each bucket, so other series and older buckets never reach
    that sort. A series key keeps its rows when its insight changes interval, so the stored interval of a row can
    differ from the requested one.
    """
    by_interval: dict[IntervalType, list[tuple[int, str]]] = {}
    for key, interval in series.items():
        by_interval.setdefault(interval, []).append(key)
    return ast.Or(
        exprs=[
            parse_expr(
                "(insight_id, series_key) IN {series} AND bucket_start >= {chart_from}",
                placeholders={
                    "series": ast.Tuple(
                        exprs=[
                            ast.Tuple(exprs=[ast.Constant(value=insight_id), ast.Constant(value=key)])
                            for insight_id, key in sorted(keys)
                        ]
                    ),
                    "chart_from": ast.Constant(value=chart_from(interval, date_to)),
                },
            )
            for interval, keys in sorted(by_interval.items())
        ]
    )


def _placeholders(*, since: datetime.datetime, until: datetime.datetime, scope: ast.Expr) -> dict[str, ast.Expr]:
    return {
        "event": ast.Constant(value=SCORE_EVENT),
        "source": ast.Constant(value=SOURCE_INSIGHT),
        "since": ast.Constant(value=since),
        "until": ast.Constant(value=until),
        "scan_since": ast.Constant(value=since - TIMESTAMP_DRIFT),
        "scan_until": ast.Constant(value=until + TIMESTAMP_DRIFT),
        "scope": scope,
    }


def series_summaries(
    team: Team,
    *,
    date_from: datetime.datetime,
    date_to: datetime.datetime,
    insight_ids: Collection[int] | None = None,
    series_key: str | None = None,
) -> SeriesSummaries:
    """Each series with a score row from ``date_from`` to ``date_to``, in one scan."""
    if insight_ids is not None and not insight_ids:
        return SeriesSummaries(series=[], truncated=False)
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    response = execute_hogql_query(
        _SERIES_QUERY,
        team,
        query_type="AnomalyScoresSeriesSummaries",
        placeholders={
            **_placeholders(since=date_from, until=date_to, scope=_scope(insight_ids, series_key)),
            # Any member can capture an event with any properties, so a row may not name a real series.
            # The query drops those rows before the cap, so they neither take a place nor decide `flagged_truncated`.
            "intervals": ast.Tuple(exprs=[ast.Constant(value=interval) for interval in sorted(SCORED_INTERVALS)]),
            "limit": ast.Constant(value=MAX_SERIES + 1),
        },
        ch_user=ClickHouseUser.DEFAULT,
    )
    rows = cast(list[tuple[Any, ...]], response.results or [])
    timezone = team.timezone_info
    series: list[SeriesSummary] = []
    for (
        insight_id,
        key,
        label,
        breakdown_value,
        interval,
        detector,
        detector_version,
        profile,
        newest_bucket,
        scored,
        flagged,
        scored_through,
        points,
    ) in rows[:MAX_SERIES]:
        flagged_points = sorted(
            (
                FlaggedPoint(bucket_start=_local(start, timezone), value=_float(value), score=_float(score))
                for start, value, score in points
            ),
            key=lambda point: point.bucket_start,
            reverse=True,
        )
        series.append(
            SeriesSummary(
                insight_id=int(insight_id),
                series_key=str(key),
                series_label=_text(label),
                breakdown_value=_text(breakdown_value),
                interval=IntervalType(interval),
                detector=_text(detector),
                detector_version=_text(detector_version),
                profile=_text(profile),
                newest_bucket=_local(newest_bucket, timezone),
                scored_buckets=int(scored),
                flagged_buckets=int(flagged),
                scored_through=_local(scored_through, timezone) if scored else None,
                flagged_points=tuple(flagged_points),
            )
        )
    return SeriesSummaries(
        series=series,
        truncated=len(rows) > MAX_SERIES,
        flagged_truncated=len(rows) > MAX_SERIES and bool(rows[MAX_SERIES][10]),
    )


def scored_days(team: Team, *, now: datetime.datetime) -> int:
    """Distinct UTC days with a scored daily bucket of any insight series from ``SCORED_HISTORY_WINDOW`` before ``now``.

    The count is cached for each team, so ``now`` applies only when the cache is empty.
    """
    cache_key = f"signals:anomaly_scores:scored_days:v1:{team.id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return int(cached)
    days = _count_scored_days(team, now=now)
    timeout = SCORED_DAYS_READY_CACHE_TIMEOUT if days >= SCORED_HISTORY_READY_DAYS else SCORED_DAYS_CACHE_TIMEOUT
    cache.set(cache_key, days, timeout=int(timeout.total_seconds()))
    return days


def _count_scored_days(team: Team, *, now: datetime.datetime) -> int:
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    response = execute_hogql_query(
        _SCORED_DAYS_QUERY,
        team,
        query_type="AnomalyScoresScoredDays",
        placeholders={
            **_placeholders(since=now - SCORED_HISTORY_WINDOW, until=now, scope=_scope(None, None)),
            "interval": ast.Constant(value=IntervalType.DAY.value),
        },
        ch_user=ClickHouseUser.DEFAULT,
    )
    rows = cast(list[tuple[Any, ...]], response.results or [])
    return int(rows[0][0]) if rows else 0


def latest_buckets(
    team: Team,
    *,
    insight_id: int,
    date_from: datetime.datetime,
    date_to: datetime.datetime,
    series_key: str | None = None,
    include_warmup: bool = False,
    limit: int = MAX_BUCKETS,
) -> ScoredBuckets:
    """The newest result of each scored bucket of one insight in the range, newest first, up to ``limit``."""
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    response = execute_hogql_query(
        _BUCKETS_QUERY,
        team,
        query_type="AnomalyScoresLatestBuckets",
        placeholders={
            **_placeholders(since=date_from, until=date_to, scope=_scope([insight_id], series_key)),
            "date_from": ast.Constant(value=date_from),
            "keep": ast.Constant(value=True) if include_warmup else parse_expr("score IS NOT NULL"),
            "limit": ast.Constant(value=limit + 1),
        },
        ch_user=ClickHouseUser.DEFAULT,
    )
    rows = cast(list[tuple[Any, ...]], response.results or [])
    timezone = team.timezone_info
    buckets = [
        ScoredBucket(
            series_key=str(key),
            bucket_start=_local(start, timezone),
            scored=True,
            value=_float(value),
            score=_float(score),
            flag=None if flag is None else bool(flag),
            scored_at=None if scored_at is None else _local(scored_at, timezone),
            details=_details(details),
        )
        for key, start, score, flag, value, details, scored_at in rows[:limit]
        if key
    ]
    return ScoredBuckets(buckets=buckets, truncated=len(rows) > limit)


def chart_from(interval: IntervalType, date_to: datetime.datetime) -> datetime.datetime:
    """The start of the chart window of a series with this interval that ends at ``date_to``."""
    return date_to - interval_spec(interval).period * CHART_BUCKETS[interval]


def series_points(
    team: Team,
    *,
    date_to: datetime.datetime,
    series: Mapping[tuple[int, str], IntervalType],
) -> dict[tuple[int, str], list[SeriesPoint]]:
    """The scored buckets of each ``(insight_id, series_key)`` in the chart window of its interval, oldest first.

    Warm-up rows are left out. A bucket that was not scored has no point, so a gap stays a gap.
    Each series keeps at most its newest ``MAX_SERIES_POINTS`` buckets.
    """
    if not series:
        return {}
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    response = execute_hogql_query(
        _POINTS_QUERY,
        team,
        query_type="AnomalyScoresSeriesPoints",
        placeholders={
            **_placeholders(
                since=min(chart_from(interval, date_to) for interval in series.values()),
                until=date_to,
                scope=_chart_windows(series, date_to),
            ),
            "limit": ast.Constant(value=MAX_SERIES_POINTS),
            # Without a limit of its own, the query gets the default HogQL row cap, and most series lose their points.
            "total_limit": ast.Constant(value=MAX_SERIES_POINTS * len(series)),
        },
        ch_user=ClickHouseUser.DEFAULT,
    )
    rows = cast(list[tuple[Any, ...]], response.results or [])
    timezone = team.timezone_info
    points: dict[tuple[int, str], list[SeriesPoint]] = {key: [] for key in series}
    for insight_id, key, start, value, flag in reversed(rows):
        points[(insight_id, key)].append(
            SeriesPoint(bucket_start=_local(start, timezone), value=_float(value), flag=bool(flag))
        )
    return points


def chart_shares(
    team: Team,
    *,
    date_to: datetime.datetime,
    series: Mapping[tuple[int, str], IntervalType],
) -> dict[tuple[int, str], ChartShare]:
    """The scored and flagged buckets of each ``(insight_id, series_key)`` in the chart window of its interval.

    A series with no scored bucket in its window has no entry.
    """
    if not series:
        return {}
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    response = execute_hogql_query(
        _CHART_SHARES_QUERY,
        team,
        query_type="AnomalyScoresChartShares",
        placeholders={
            **_placeholders(
                since=min(chart_from(interval, date_to) for interval in series.values()),
                until=date_to,
                scope=_chart_windows(series, date_to),
            ),
            "limit": ast.Constant(value=len(series)),
        },
        ch_user=ClickHouseUser.DEFAULT,
    )
    rows = cast(list[tuple[Any, ...]], response.results or [])
    return {
        (insight_id, key): ChartShare(scored_buckets=int(scored), flagged_buckets=int(flagged))
        for insight_id, key, scored, flagged in rows
    }


def _previous_start(start: datetime.datetime, interval: IntervalType) -> datetime.datetime:
    if interval == IntervalType.HOUR:
        return (start.astimezone(datetime.UTC) - datetime.timedelta(hours=1)).astimezone(start.tzinfo)
    return start - interval_spec(interval).period


def bucket_starts(
    anchor: datetime.datetime,
    interval: IntervalType,
    *,
    date_from: datetime.datetime,
    date_to: datetime.datetime,
    now: datetime.datetime,
) -> list[datetime.datetime]:
    """The completed bucket starts from ``date_from`` to ``date_to``, oldest first, aligned to ``anchor``.

    ``anchor`` is any bucket start of the series, so the buckets line up with the insight's own buckets.
    """
    start = anchor
    while start > date_from:
        start = _previous_start(start, interval)
    while start < date_from:
        start = bucket_end(start, interval)
    starts: list[datetime.datetime] = []
    while start <= date_to and bucket_end(start, interval) <= now:
        starts.append(start)
        start = bucket_end(start, interval)
    return starts


def rank_series(
    series: Sequence[SeriesSummary],
    *,
    chart_shares: Mapping[tuple[int, str], ChartShare],
    importance: Mapping[int, SeriesImportance],
    recent_first: bool = False,
    rate_first: bool = False,
) -> list[SeriesSummary]:
    """Most anomalous first, using only measures that compare across series and intervals.

    Series with a flag in the range first, the lowest share of flagged buckets in the chart window first among them,
    because a flag on a series that rarely flags is the surprising one. A series with fewer than ``MIN_CHART_BUCKETS``
    scored buckets in its chart window, or none in ``chart_shares``, sorts after the series with a share.
    Then flagged buckets, then the newest flag, then the insight's importance.
    With ``recent_first``, the newest flagged bucket that ended last sorts first, and a series without a flag sorts
    last. It compares bucket ends, not starts, so a day that ended at midnight is newer than an hour that ended
    before it.
    With ``rate_first``, the anomaly rate in the range sorts first, as a person reads it off a row.
    """
    unknown = SeriesImportance(on_dashboard=False, viewers=0)

    def key(summary: SeriesSummary) -> _RankKey:
        last_flagged = summary.last_flagged_bucket
        negative_last_flagged = -last_flagged.timestamp() if last_flagged else math.inf
        negative_flag_end = -bucket_end(last_flagged, summary.interval).timestamp() if last_flagged else math.inf
        insight_importance = importance.get(summary.insight_id, unknown)
        chart_share = chart_shares.get((summary.insight_id, summary.series_key))
        share = chart_share.share if chart_share else None
        return _RankKey(
            negative_flag_end=negative_flag_end if recent_first else 0.0,
            negative_rate=-(summary.anomaly_rate or 0.0) if rate_first else 0.0,
            unflagged=not summary.flagged_buckets,
            no_chart_share=share is None,
            chart_share=share or 0.0,
            negative_flagged_buckets=-summary.flagged_buckets,
            negative_last_flagged=negative_last_flagged,
            off_dashboard=not insight_importance.on_dashboard,
            negative_viewers=-insight_importance.viewers,
            insight_id=summary.insight_id,
            series_key=summary.series_key,
        )

    return sorted(series, key=key)


def rollup(series: Sequence[SeriesSummary]) -> InsightRollup:
    last_flagged = [summary.last_flagged_bucket for summary in series if summary.last_flagged_bucket is not None]
    return InsightRollup(
        series_count=len(series),
        flagged_series=sum(1 for summary in series if summary.flagged_buckets),
        scored_buckets=sum(summary.scored_buckets for summary in series),
        flagged_buckets=sum(summary.flagged_buckets for summary in series),
        last_flagged_bucket=max(last_flagged) if last_flagged else None,
    )
