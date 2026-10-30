"""Read the `$anomaly_score` events of a project back, as anomaly rates per series and as scored buckets.

A bucket can be scored more than once, so every read keeps the newest result of each series and bucket.
Warm-up rows have a null score and count nowhere. A bucket that was not scored is unknown, never 0.
A raw score ranks buckets within one series only, so a ranking across series uses rates, never scores.
"""

import json
import math
import datetime
from collections.abc import Collection, Mapping, Sequence
from typing import Any, cast
from zoneinfo import ZoneInfo

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

# The window before the requested range that `baseline_rate` covers.
BASELINE_WINDOW = datetime.timedelta(days=30)
# One row is one series. Far more than the series of every active insight of one project.
MAX_SERIES = 10_000
MAX_BUCKETS = 2_000
# Each rate shrinks toward its baseline by this many buckets, so 1 flagged of 1 scored does not top a ranking.
PRIOR_BUCKETS = 10
# The prior when no series of the project has a scored baseline: about what a 0.95 threshold flags on noise.
DEFAULT_PRIOR_RATE = 0.05
# The intervals the scorer writes. Any member can capture a row with another interval, such as `second`,
# and stepping through its buckets over a long range would take hours.
SCORED_INTERVALS = frozenset(DEFAULT_PROFILE.intervals)

_LATEST_BUCKETS = """
SELECT
    toInt(properties.$anomaly_insight_id) AS insight_id,
    properties.$anomaly_series_key AS series_key,
    timestamp AS bucket_start,
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
    AND timestamp >= {since}
    AND timestamp <= {until}
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
    argMax(bucket_interval, bucket_start),
    argMax(detector, bucket_start),
    argMax(detector_version, bucket_start),
    argMax(profile, bucket_start),
    max(bucket_start),
    countIf(score IS NOT NULL AND bucket_start >= {{date_from}}),
    countIf(score IS NOT NULL AND bucket_start >= {{date_from}} AND flag = 1),
    countIf(score IS NOT NULL AND bucket_start < {{date_from}}),
    countIf(score IS NOT NULL AND bucket_start < {{date_from}} AND flag = 1),
    maxIf(bucket_start, score IS NOT NULL AND bucket_start >= {{date_from}}),
    groupArrayIf(tuple(bucket_start, value, score), score IS NOT NULL AND bucket_start >= {{date_from}} AND flag = 1)
FROM ({_LATEST_BUCKETS})
GROUP BY insight_id, series_key
LIMIT {{limit}}
"""

_BUCKETS_QUERY = f"""
SELECT series_key, bucket_start, score, flag, value, details, scored_at
FROM ({_LATEST_BUCKETS})
WHERE bucket_start >= {{date_from}} AND {{keep}}
ORDER BY bucket_start DESC, series_key
LIMIT {{limit}}
"""


@frozen
class FlaggedPoint:
    bucket_start: datetime.datetime
    value: float | None
    score: float | None


@frozen
class SeriesSummary:
    """One series over the requested range and the baseline window before it. Counts cover scored buckets only."""

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
    baseline_scored_buckets: int
    baseline_flagged_buckets: int
    # The newest scored bucket in the range. None when no bucket of the range was scored.
    scored_through: datetime.datetime | None
    # Every flagged bucket of the range, newest first.
    flagged_points: tuple[FlaggedPoint, ...]

    @property
    def anomaly_rate(self) -> float | None:
        return self.flagged_buckets / self.scored_buckets if self.scored_buckets else None

    @property
    def baseline_rate(self) -> float | None:
        return self.baseline_flagged_buckets / self.baseline_scored_buckets if self.baseline_scored_buckets else None

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

    negative_lift: float
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


def _placeholders(
    *,
    since: datetime.datetime,
    until: datetime.datetime,
    insight_ids: Collection[int] | None,
    series_key: str | None,
) -> dict[str, ast.Expr]:
    return {
        "event": ast.Constant(value=SCORE_EVENT),
        "source": ast.Constant(value=SOURCE_INSIGHT),
        "since": ast.Constant(value=since),
        "until": ast.Constant(value=until),
        "scope": _scope(insight_ids, series_key),
    }


def series_summaries(
    team: Team,
    *,
    date_from: datetime.datetime,
    date_to: datetime.datetime,
    insight_ids: Collection[int] | None = None,
    series_key: str | None = None,
) -> SeriesSummaries:
    """Each series with a score row from ``date_from - BASELINE_WINDOW`` to ``date_to``, in one scan."""
    if insight_ids is not None and not insight_ids:
        return SeriesSummaries(series=[], truncated=False)
    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    response = execute_hogql_query(
        _SERIES_QUERY,
        team,
        query_type="AnomalyScoresSeriesSummaries",
        placeholders={
            **_placeholders(
                since=date_from - BASELINE_WINDOW, until=date_to, insight_ids=insight_ids, series_key=series_key
            ),
            "date_from": ast.Constant(value=date_from),
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
        baseline_scored,
        baseline_flagged,
        scored_through,
        points,
    ) in rows[:MAX_SERIES]:
        # Any member can capture an event with any properties, so a row may not name a real series.
        if insight_id is None or not key or interval not in SCORED_INTERVALS:
            continue
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
                baseline_scored_buckets=int(baseline_scored),
                baseline_flagged_buckets=int(baseline_flagged),
                scored_through=_local(scored_through, timezone) if scored else None,
                flagged_points=tuple(flagged_points),
            )
        )
    return SeriesSummaries(series=series, truncated=len(rows) > MAX_SERIES)


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
            **_placeholders(since=date_from, until=date_to, insight_ids=[insight_id], series_key=series_key),
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


def prior_rate(series: Sequence[SeriesSummary]) -> float:
    """The project's baseline rate, summed over every series, for series that have no baseline of their own."""
    scored = sum(summary.baseline_scored_buckets for summary in series)
    flagged = sum(summary.baseline_flagged_buckets for summary in series)
    return flagged / scored if scored else DEFAULT_PRIOR_RATE


def rate_lift(summary: SeriesSummary, prior: float) -> float:
    """The smoothed rate in the range less the smoothed baseline rate. Only a ranking uses it.

    Both rates shrink toward the same smoothed baseline, so a series with no scored bucket gets a lift of 0.
    """
    smoothed_baseline = (summary.baseline_flagged_buckets + PRIOR_BUCKETS * prior) / (
        summary.baseline_scored_buckets + PRIOR_BUCKETS
    )
    rate = (summary.flagged_buckets + PRIOR_BUCKETS * smoothed_baseline) / (summary.scored_buckets + PRIOR_BUCKETS)
    return rate - smoothed_baseline


def rank_series(
    series: Sequence[SeriesSummary], *, prior: float, importance: Mapping[int, SeriesImportance]
) -> list[SeriesSummary]:
    """Most anomalous first, using only measures that compare across series and intervals.

    Rate lift first, then flagged buckets, then the newest flag, then the insight's importance.
    """
    unknown = SeriesImportance(on_dashboard=False, viewers=0)

    def key(summary: SeriesSummary) -> _RankKey:
        last_flagged = summary.last_flagged_bucket
        insight_importance = importance.get(summary.insight_id, unknown)
        return _RankKey(
            negative_lift=-rate_lift(summary, prior),
            negative_flagged_buckets=-summary.flagged_buckets,
            negative_last_flagged=-last_flagged.timestamp() if last_flagged else math.inf,
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
