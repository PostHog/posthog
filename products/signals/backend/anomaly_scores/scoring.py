import json
import hashlib
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
from dateutil.relativedelta import relativedelta

from posthog.schema import BreakdownFilter, ChartDisplayType, DateRange, IntervalType, TrendsQuery

from posthog.api.services.query import ExecutionMode
from posthog.caching.calculate_results import calculate_for_query_based_insight
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.event_usage import EventSource
from posthog.models import Team
from posthog.schema_migrations.upgrade_manager import upgrade_insight
from posthog.tasks.alerts.detectors.registry import get_detector
from posthog.tasks.alerts.trends import _has_breakdown
from posthog.tasks.alerts.utils import WRAPPER_NODE_KINDS, is_non_time_series_trend

from products.product_analytics.backend.facade.models import Insight
from products.signals.backend.anomaly_scores.config import DEFAULT_CONFIG, AnomalyScoringConfig

SCORED_INTERVALS = (IntervalType.HOUR, IntervalType.DAY, IntervalType.WEEK, IntervalType.MONTH)

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
    detector: str
    detector_version: str
    series: list[ScoredSeries]


def _short_hash(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def detector_version(detector_config: dict[str, Any]) -> str:
    """Identifies the scoring behavior, so scores from different configs are never mixed in one series."""
    return _short_hash(detector_config)[:12]


def series_key(insight_id: int, series_definition: dict[str, Any], breakdown_value: str | None) -> str:
    return _short_hash({"insight": insight_id, "series": series_definition, "breakdown": breakdown_value})


def trends_query_for(insight: Insight) -> TrendsQuery:
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
    interval = trends.interval or IntervalType.DAY
    if interval not in SCORED_INTERVALS:
        raise UnsupportedInsightError(f"Interval {interval.value} is not scored")
    return trends


def build_scoring_query(query: TrendsQuery, config: AnomalyScoringConfig = DEFAULT_CONFIG) -> TrendsQuery:
    """Fetch the scorer's lookback instead of the chart's date range.

    Series, filters and formulas stay as they are, so the scores describe the series the chart shows.
    """
    interval = query.interval or IntervalType.DAY
    lookback = config.lookback_for(interval)
    if lookback is None:
        raise UnsupportedInsightError(f"Interval {interval.value} is not scored")

    days_of_week = query.dateRange.daysOfWeek if query.dateRange else None
    update: dict[str, Any] = {
        "dateRange": DateRange(date_from=lookback, daysOfWeek=days_of_week),
        "compareFilter": None,
    }
    if _has_breakdown(query):
        lines_per_value = len(_formulas(query)) or len(query.series)
        breakdown_filter = query.breakdownFilter or BreakdownFilter()
        # "Other" mixes whichever values fall outside the top N on each run, so it is not one series.
        update["breakdownFilter"] = breakdown_filter.model_copy(
            update={
                "breakdown_limit": max(1, min(config.max_breakdown_values, config.max_series // lines_per_value)),
                "breakdown_hide_other_aggregation": True,
            }
        )
    return query.model_copy(update=update)


def score_series(
    values: Sequence[float],
    buckets: Sequence[datetime],
    *,
    detector_config: dict[str, Any],
    interval: IntervalType,
    now: datetime,
    after: datetime | None = None,
    config: AnomalyScoringConfig = DEFAULT_CONFIG,
) -> list[ScoredPoint]:
    """Score one series and return its newest completed buckets later than ``after``.

    ``buckets`` are aware bucket starts in the project timezone.
    """
    if len(values) != len(buckets):
        raise ValueError("Each value needs a bucket")
    completed = [i for i, start in enumerate(buckets) if _bucket_end(start, interval) <= now]
    if not completed:
        return []
    # The ongoing bucket is still filling, so it must not shape any score.
    data = np.array(values[: completed[-1] + 1], dtype=float)
    result = get_detector(detector_config).detect_batch(data)
    triggered = set(result.triggered_indices)
    sub_results = result.metadata.get("sub_results", []) if detector_config.get("type") == "ensemble" else []
    warm_up = config.warm_up_for(interval)

    returned = [i for i in completed if after is None or buckets[i] > after][-config.max_backfill_buckets :]
    points: list[ScoredPoint] = []
    for i in returned:
        score = result.all_scores[i] if i < len(result.all_scores) else None
        sub_scores = {str(sub.get("type")): _score_at(sub.get("all_scores") or [], i) for sub in sub_results}
        # An AND ensemble needs every sub-detector, so a missing sub-score means the bucket is not scored yet.
        if i + 1 < warm_up or score is None or None in sub_scores.values():
            points.append(
                ScoredPoint(bucket_start=buckets[i], value=float(values[i]), score=None, flag=None, details={})
            )
            continue
        points.append(
            ScoredPoint(
                bucket_start=buckets[i],
                value=float(values[i]),
                score=float(score),
                flag=i in triggered,
                details={"sub_scores": sub_scores} if sub_scores else {},
            )
        )
    return points


def score_insight(
    insight: Insight,
    team: Team,
    *,
    now: datetime,
    after: datetime | None = None,
    config: AnomalyScoringConfig = DEFAULT_CONFIG,
) -> InsightScores:
    query = trends_query_for(insight)
    scoring_query = build_scoring_query(query, config)
    interval = scoring_query.interval or IntervalType.DAY
    detector_config = config.detector_config()

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
    for result in cast(list[dict[str, Any]], calculation.result)[: config.max_series]:
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
                    detector_config=detector_config,
                    interval=interval,
                    now=now,
                    after=after,
                    config=config,
                ),
            )
        )
    return InsightScores(
        interval=interval,
        detector=str(detector_config["type"]),
        detector_version=detector_version(detector_config),
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


def _bucket_end(start: datetime, interval: IntervalType) -> datetime:
    # Wall-clock arithmetic on an aware datetime, so a day stays one calendar day across DST changes.
    if interval == IntervalType.MONTH:
        return start + relativedelta(months=1)
    if interval == IntervalType.WEEK:
        return start + timedelta(weeks=1)
    if interval == IntervalType.DAY:
        return start + timedelta(days=1)
    return (start.astimezone(UTC) + timedelta(hours=1)).astimezone(start.tzinfo)


def _score_at(scores: list[float | None], index: int) -> float | None:
    score = scores[index] if index < len(scores) else None
    return None if score is None else float(score)


def _parse_bucket(day: str, timezone: ZoneInfo) -> datetime:
    # Trends returns bucket starts as naive strings in the project's timezone.
    parsed = datetime.fromisoformat(day)
    return parsed.astimezone(timezone) if parsed.tzinfo else parsed.replace(tzinfo=timezone)


def _breakdown_label(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        return "::".join(str(part) for part in value)
    return str(value)
