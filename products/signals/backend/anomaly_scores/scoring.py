import json
import hashlib
import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np

from posthog.schema import BreakdownFilter, ChartDisplayType, DateRange, IntervalType, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.hogql_queries.utils.breakdowns import has_breakdown_filter
from posthog.interval_specs import interval_spec
from posthog.models import Team
from posthog.schema_migrations.upgrade_manager import upgrade_insight
from posthog.tasks.alerts.detectors.base import DetectionResult
from posthog.tasks.alerts.detectors.registry import get_detector
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, is_non_time_series_trend

from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.config import (
    DEFAULT_LIMITS,
    IntervalScoring,
    ScoringLimits,
    ScoringProfile,
    resolve_profile,
)

# Naming fields do not change what a series counts, so a rename keeps its key.
_SERIES_NAMING_FIELDS = {"custom_name", "name"}


class UnsupportedInsightError(Exception):
    """The insight is not a shape we score. The caller skips it; it is not an error."""


@frozen
class ScoredPoint:
    bucket_start: datetime
    value: float
    # Both are None during warm-up, so an average of the flag stays a true anomaly rate.
    score: float | None
    flag: bool | None
    details: dict[str, Any]


@frozen
class ScoredSeries:
    series_key: str
    label: str
    breakdown_value: str | None
    points: list[ScoredPoint]


@frozen
class InsightScores:
    interval: IntervalType
    profile: str
    detector: str
    detector_version: str
    series: list[ScoredSeries]


def _short_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def detector_version(scoring: IntervalScoring) -> str:
    """Identifies the scoring behavior, so scores from different settings are never mixed in one series."""
    return _short_hash(dataclasses.asdict(scoring))


def series_key(insight_id: int, series_definition: dict[str, Any], breakdown_value: str | None) -> str:
    return _short_hash({"insight": insight_id, "series": series_definition, "breakdown": breakdown_value})


def trends_query_for(insight: Insight, profile: ScoringProfile) -> TrendsQuery:
    if insight.query is None:
        raise UnsupportedInsightError("Insight has no query")
    with upgrade_insight(insight):
        query = insight.query
    if query.get("kind") in WRAPPER_NODE_KINDS:
        query = query.get("source") or {}
    if query.get("kind") != "TrendsQuery":
        raise UnsupportedInsightError(f"Only trends insights are scored, not {query.get('kind')}")
    trends = TrendsQuery.model_validate(query)
    if is_non_time_series_trend(trends):
        raise UnsupportedInsightError("Insight shows a single value, not a time series")
    if trends.trendsFilter and trends.trendsFilter.display == ChartDisplayType.ACTIONS_LINE_GRAPH_CUMULATIVE:
        raise UnsupportedInsightError("Cumulative insights are not scored")
    interval_scoring(profile, _interval(trends))
    return trends


def interval_scoring(profile: ScoringProfile, interval: IntervalType) -> IntervalScoring:
    scoring = profile.for_interval(interval)
    if scoring is None:
        raise UnsupportedInsightError(f"Interval {interval.value} is not scored")
    return scoring


def build_scoring_query(
    query: TrendsQuery, scoring: IntervalScoring, limits: ScoringLimits = DEFAULT_LIMITS
) -> TrendsQuery:
    """Fetch the scorer's lookback instead of the chart's date range.

    Series, filters and formulas stay as they are, so the scores describe the series the chart shows.
    """
    days_of_week = query.dateRange.daysOfWeek if query.dateRange else None
    update: dict[str, Any] = {
        "dateRange": DateRange(date_from=scoring.lookback, daysOfWeek=days_of_week),
        "compareFilter": None,
    }
    if has_breakdown_filter(query.breakdownFilter):
        lines_per_value = len(_formulas(query)) or len(query.series)
        breakdown_filter = query.breakdownFilter or BreakdownFilter()
        # "Other" mixes whichever values fall outside the top N on each run, so it is not one series.
        update["breakdownFilter"] = breakdown_filter.model_copy(
            update={
                "breakdown_limit": max(1, min(limits.max_breakdown_values, limits.max_series // lines_per_value)),
                "breakdown_hide_other_aggregation": True,
            }
        )
    return query.model_copy(update=update)


def score_series(
    values: Sequence[float],
    buckets: Sequence[datetime],
    *,
    scoring: IntervalScoring,
    interval: IntervalType,
    now: datetime,
    after: datetime | None = None,
    limits: ScoringLimits = DEFAULT_LIMITS,
) -> list[ScoredPoint]:
    """Score one series and return its newest completed buckets later than ``after``.

    ``buckets`` are aware bucket starts in the project timezone.
    """
    if len(values) != len(buckets):
        raise ValueError("Each value needs a bucket")
    completed = [i for i, start in enumerate(buckets) if bucket_end(start, interval) <= now]
    returned = [i for i in completed if after is None or buckets[i] > after][-limits.max_backfill_buckets :]
    detector = get_detector(scoring.detector)
    data = np.array(values, dtype=float)

    points: list[ScoredPoint] = []
    for i in returned:
        # Score each bucket on the history up to it, so the ongoing bucket and later buckets never shape the score.
        # detect() fits once per call; detect_batch() refits at every point of the lookback for model-based detectors.
        result = detector.detect(data[: i + 1]) if i + 1 >= scoring.min_points else None
        score = None if result is None or result.score is None else float(result.score)
        points.append(
            ScoredPoint(
                bucket_start=buckets[i],
                value=float(values[i]),
                score=score,
                flag=None if result is None or score is None else result.is_anomaly,
                details={} if result is None or score is None else _details(result),
            )
        )
    return points


def score_insight(
    insight: Insight,
    team: Team,
    *,
    now: datetime,
    after: datetime | None = None,
    limits: ScoringLimits = DEFAULT_LIMITS,
) -> InsightScores:
    profile = resolve_profile(team, insight)
    query = trends_query_for(insight, profile)
    interval = _interval(query)
    scoring = interval_scoring(profile, interval)
    scoring_query = build_scoring_query(query, scoring, limits)

    tag_queries(product=Product.SIGNALS, feature=Feature.ALERTING)
    calculation = calculate_for_query_based_insight(
        insight,
        team=team,
        execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
        # No request user. Run as the insight's creator so warehouse access control resolves for them.
        user=insight.created_by,
        query_override=scoring_query.model_dump(exclude_none=True),
        analytics_props={"source": EventSource.SELF_DRIVING},
    )
    if calculation.result is None:
        raise RuntimeError(f"No results for insight {insight.pk}")

    timezone = team.timezone_info
    series: list[ScoredSeries] = []
    for result in cast(list[dict[str, Any]], calculation.result)[: limits.max_series]:
        buckets = [_parse_bucket(day, timezone) for day in result.get("days") or []]
        breakdown_value = _breakdown_label(result.get("breakdown_value"))
        series.append(
            ScoredSeries(
                series_key=series_key(insight.pk, _series_definition(scoring_query, result), breakdown_value),
                label=str(result.get("label") or ""),
                breakdown_value=breakdown_value,
                points=score_series(
                    result.get("data") or [],
                    buckets,
                    scoring=scoring,
                    interval=interval,
                    now=now,
                    after=after,
                    limits=limits,
                ),
            )
        )
    return InsightScores(
        interval=interval,
        profile=profile.name,
        detector=str(scoring.detector["type"]),
        detector_version=detector_version(scoring),
        series=series,
    )


def _formulas(query: TrendsQuery) -> list[str]:
    trends_filter = query.trendsFilter
    if trends_filter is None:
        return []
    if trends_filter.formulaNodes:
        return [node.formula for node in trends_filter.formulaNodes]
    if trends_filter.formulas:
        return list(trends_filter.formulas)
    return [trends_filter.formula] if trends_filter.formula else []


def _series_node_definition(node: Any) -> dict[str, Any]:
    return node.model_dump(exclude_none=True, exclude=_SERIES_NAMING_FIELDS)


def _series_definition(query: TrendsQuery, result: dict[str, Any]) -> dict[str, Any]:
    """What a result line counts, independent of where its series sits in the query."""
    formulas = _formulas(query)
    if formulas:
        # A formula refers to series by letter, so its meaning includes every series in order.
        order = result.get("order") or 0
        return {
            "formula": formulas[order] if order < len(formulas) else None,
            "series": [_series_node_definition(node) for node in query.series],
        }
    order = (result.get("action") or {}).get("order")
    if order is None or order >= len(query.series):
        return {"label": result.get("label")}
    return _series_node_definition(query.series[order])


def _interval(query: TrendsQuery) -> IntervalType:
    return query.interval or IntervalType.DAY


def bucket_end(start: datetime, interval: IntervalType) -> datetime:
    if interval == IntervalType.HOUR:
        # An hour is elapsed time, so step in UTC to stay one hour long across DST changes.
        return (start.astimezone(UTC) + timedelta(hours=1)).astimezone(start.tzinfo)
    # Wall-clock arithmetic on an aware datetime, so a day stays one calendar day across DST changes.
    return start + interval_spec(interval).period


def _details(result: DetectionResult) -> dict[str, Any]:
    """Detector-specific values for one bucket. Only scalars are kept, so the event property stays small."""
    sub_results = result.metadata.get("sub_results")
    if isinstance(sub_results, list):
        return {
            "sub_scores": {
                f"{sub.get('type')}_{position}": sub.get("score") for position, sub in enumerate(sub_results)
            }
        }
    return {
        key: value for key, value in result.metadata.items() if value is None or isinstance(value, int | float | str)
    }


def _parse_bucket(day: str, timezone: ZoneInfo) -> datetime:
    # Trends returns bucket starts in the project's timezone, usually as naive strings.
    parsed = datetime.fromisoformat(day)
    return parsed.astimezone(timezone) if parsed.tzinfo else parsed.replace(tzinfo=timezone)


def _breakdown_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "::".join(str(part) for part in value)
    return str(value)
