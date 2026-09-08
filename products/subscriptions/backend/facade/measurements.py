"""Canonical baseline snapshots from already-completed saved-insight evidence."""

from __future__ import annotations

import json
import math
import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import cast

from pydantic import ValidationError

from posthog.schema import ActionsNode, EventsNode, TrendsQuery

from products.product_analytics.backend.facade.api import saved_insight_identity
from products.product_analytics.backend.facade.contracts import SavedInsightIdentity
from products.subscriptions.backend.facade.contracts import Recommendation
from products.tasks.backend.facade.staged_evidence import CompletedMCPCallEvidence

_MEASUREMENT_VERSION = 1
_ALLOWED_ARGUMENT_KEYS = {"insightId", "output_format"}
_ALLOWED_OUTPUT_FORMATS = {"json", "optimized"}
_MAX_DATE_SPAN = timedelta(days=6)


SavedInsightResolver = Callable[[int, str | int], SavedInsightIdentity | None]


def canonicalize_measurement(
    *,
    team_id: int,
    recommendation: Recommendation,
    completed_mcp_calls: tuple[CompletedMCPCallEvidence, ...],
    resolve_insight: SavedInsightResolver | None = None,
) -> dict[str, object] | None:
    """Return a small immutable baseline only when all persisted evidence agrees."""

    call = _measurement_call(recommendation, completed_mcp_calls)
    if call is None or call.arguments is None:
        return None
    reference = _insight_reference(call.arguments)
    if reference is None:
        return None

    result_identity, query_data, results = _result_authority(call.result)
    if result_identity is None or query_data is None or results is None:
        return None

    resolver = resolve_insight or _saved_insight_resolver
    saved_insight = resolver(team_id, reference)
    if (
        saved_insight is None
        or saved_insight.team_id != team_id
        or saved_insight.id != result_identity[0]
        or saved_insight.short_id != result_identity[1]
    ):
        return None

    canonical_query, dates = _canonical_query(query_data)
    baseline_value = _baseline_value(results)
    direction = _direction(recommendation.metric_direction)
    if canonical_query is None or dates is None or baseline_value is None or direction is None:
        return None

    measurement: dict[str, object] = {
        "version": _MEASUREMENT_VERSION,
        "source_call_id": call.citation_id,
        "saved_insight": {
            "id": saved_insight.id,
            "short_id": saved_insight.short_id,
            "last_modified_at": saved_insight.last_modified_at.isoformat(),
        },
        "query": canonical_query,
        "baseline": {"value": baseline_value, "date_from": dates[0], "date_to": dates[1]},
        "metric": {
            "name": recommendation.metric_name,
            "expected_movement": recommendation.expected_metric_movement,
            "direction": direction,
        },
    }
    compact = _compact_json(measurement)
    if compact is None:
        return None
    measurement["hash"] = hashlib.sha256(compact.encode("utf-8")).hexdigest()
    return measurement


@dataclass(frozen=True)
class FrozenMeasurement:
    saved_insight_id: int
    saved_insight_short_id: str
    saved_insight_last_modified_at: datetime
    frozen_query: dict[str, object]
    baseline_value: Decimal
    baseline_from: date
    baseline_to: date
    metric_name: str
    expected_metric_movement: str
    direction: str


def parse_frozen_measurement(value: object, *, allow_decimal: bool = False) -> FrozenMeasurement | None:
    """Read the bounded Task 11 snapshot without introducing a second validator."""
    if not isinstance(value, Mapping):
        return None
    saved_insight = value.get("saved_insight")
    query = value.get("query")
    baseline = value.get("baseline")
    metric = value.get("metric")
    if not all(isinstance(item, Mapping) for item in (saved_insight, query, baseline, metric)):
        return None
    insight_id = saved_insight.get("id")
    short_id = saved_insight.get("short_id")
    modified = saved_insight.get("last_modified_at")
    if isinstance(insight_id, bool) or not isinstance(insight_id, int) or insight_id <= 0:
        return None
    if not isinstance(short_id, str) or not short_id or len(short_id) > 12 or not isinstance(modified, str):
        return None
    try:
        last_modified_at = datetime.fromisoformat(modified)
    except ValueError:
        return None
    if last_modified_at.tzinfo is None:
        return None
    frozen_query = dict(query)
    if frozen_query.get("kind") != "TrendsQuery" or "dateRange" not in frozen_query:
        return None
    date_range = frozen_query.pop("dateRange")
    if not isinstance(date_range, Mapping):
        return None
    baseline_from, baseline_to = _parse_baseline_dates(date_range)
    baseline_value = _decimal_value(baseline.get("value"), allow_decimal=allow_decimal)
    metric_name = metric.get("name")
    expected_movement = metric.get("expected_movement")
    direction = metric.get("direction")
    if (
        baseline_from is None
        or baseline_to is None
        or baseline_value is None
        or not isinstance(metric_name, str)
        or not metric_name
        or len(metric_name) > 300
        or not isinstance(expected_movement, str)
        or len(expected_movement) > 1000
        or direction not in {"increase", "decrease"}
    ):
        return None
    return FrozenMeasurement(
        saved_insight_id=insight_id,
        saved_insight_short_id=short_id,
        saved_insight_last_modified_at=last_modified_at,
        frozen_query=frozen_query,
        baseline_value=baseline_value,
        baseline_from=baseline_from,
        baseline_to=baseline_to,
        metric_name=metric_name,
        expected_metric_movement=expected_movement,
        direction=direction,
    )


def _parse_baseline_dates(value: Mapping[str, object]) -> tuple[date | None, date | None]:
    date_from = value.get("date_from")
    date_to = value.get("date_to")
    if not isinstance(date_from, str) or not isinstance(date_to, str):
        return None, None
    try:
        parsed_from = date.fromisoformat(date_from)
        parsed_to = date.fromisoformat(date_to)
    except ValueError:
        return None, None
    if parsed_from.isoformat() != date_from or parsed_to.isoformat() != date_to or parsed_to < parsed_from:
        return None, None
    return parsed_from, parsed_to


def _decimal_value(value: object, *, allow_decimal: bool = False) -> Decimal | None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        and not (allow_decimal and isinstance(value, Decimal))
    ):
        return None
    try:
        decimal = Decimal(str(value))
    except InvalidOperation:
        return None
    if (
        not decimal.is_finite()
        or decimal.as_tuple().exponent < -10
        or len(decimal.as_tuple().digits) > 30
        or decimal.adjusted() > 19
    ):
        return None
    return decimal


def _measurement_call(
    recommendation: Recommendation, calls: tuple[CompletedMCPCallEvidence, ...]
) -> CompletedMCPCallEvidence | None:
    candidate = recommendation.measurement_call_id
    if candidate is None or candidate not in recommendation.citation_ids:
        return None
    matches = [call for call in calls if call.citation_id == candidate]
    if len(matches) != 1 or matches[0].tool_name != "insight-query":
        return None
    return matches[0]


def _insight_reference(arguments: Mapping[str, object]) -> str | int | None:
    if set(arguments) - _ALLOWED_ARGUMENT_KEYS:
        return None
    reference = arguments.get("insightId")
    if isinstance(reference, bool) or not isinstance(reference, (str, int)):
        return None
    if isinstance(reference, str) and not reference.strip():
        return None
    output_format = arguments.get("output_format")
    if output_format is not None and output_format not in _ALLOWED_OUTPUT_FORMATS:
        return None
    return reference.strip() if isinstance(reference, str) else reference


def _result_authority(
    result: Mapping[str, object],
) -> tuple[tuple[int, str] | None, Mapping[str, object] | None, list[object] | None]:
    insight = result.get("insight")
    query = result.get("query")
    results = result.get("results")
    if not isinstance(insight, Mapping) or not isinstance(query, Mapping) or not isinstance(results, list):
        return None, None, None
    insight_id = insight.get("id")
    short_id = insight.get("short_id")
    if isinstance(insight_id, bool) or not isinstance(insight_id, int) or insight_id <= 0:
        return None, None, None
    if not isinstance(short_id, str) or not short_id.strip():
        return None, None, None
    return (insight_id, short_id), query, results


def _canonical_query(query_data: Mapping[str, object]) -> tuple[dict[str, object] | None, tuple[str, str] | None]:
    try:
        query = TrendsQuery.model_validate(query_data)
    except ValidationError:
        return None, None

    if (
        query.interval != "day"
        or len(query.series) != 1
        or query.breakdownFilter is not None
        or query.compareFilter is not None
        or query.calendarHeatmapFilter is not None
        or query.conversionGoal is not None
        or query.samplingFactor is not None
        or query.modifiers is not None
        or query.aggregation_group_type_index is not None
        or _contains_hogql(query_data)
        or not _supported_trends_filter(query)
    ):
        return None, None

    dates = _absolute_dates(query)
    if dates is None or not _supported_series(query.series[0]):
        return None, None

    dumped = query.model_dump(mode="json", by_alias=True, exclude_none=True)
    canonical = _strip_runtime_fields(dumped)
    _set_explicit_total_math(canonical)
    return canonical, dates


def _supported_trends_filter(query: TrendsQuery) -> bool:
    trends_filter = query.trendsFilter
    if trends_filter is None:
        return True
    display = str(getattr(trends_filter.display, "value", trends_filter.display))
    return (
        trends_filter.formula is None
        and trends_filter.formulas is None
        and trends_filter.formulaNodes is None
        and display in {"None", "ActionsLineGraph"}
        and (trends_filter.smoothingIntervals is None or trends_filter.smoothingIntervals <= 1)
    )


def _absolute_dates(query: TrendsQuery) -> tuple[str, str] | None:
    date_range = query.dateRange
    if (
        date_range is None
        or date_range.daysOfWeek
        or date_range.excludeIncompletePeriods
        or date_range.explicitDate
        or not isinstance(date_range.date_from, str)
        or not isinstance(date_range.date_to, str)
    ):
        return None
    try:
        date_from = date.fromisoformat(date_range.date_from)
        date_to = date.fromisoformat(date_range.date_to)
    except ValueError:
        return None
    if date_from.isoformat() != date_range.date_from or date_to.isoformat() != date_range.date_to:
        return None
    if date_to < date_from or date_to - date_from > _MAX_DATE_SPAN:
        return None
    return date_from.isoformat(), date_to.isoformat()


def _supported_series(series: object) -> bool:
    if not isinstance(series, (EventsNode, ActionsNode)):
        return False
    math_type = str(getattr(series.math, "value", series.math))
    if math_type not in {"None", "total"}:
        return False
    if any(
        getattr(series, field) is not None
        for field in (
            "math_group_type_index",
            "math_hogql",
            "math_multiplier",
            "math_property",
            "math_property_revenue_currency",
            "math_property_type",
        )
    ):
        return False
    if isinstance(series, EventsNode):
        return isinstance(series.event, str) and bool(series.event.strip())
    return series.id > 0


def _contains_hogql(value: object) -> bool:
    if isinstance(value, Mapping):
        return value.get("type") == "hogql" or any(_contains_hogql(child) for child in value.values())
    if isinstance(value, list):
        return any(_contains_hogql(child) for child in value)
    return False


def _baseline_value(results: list[object]) -> int | float | None:
    if len(results) != 1 or not isinstance(results[0], Mapping):
        return None
    count = results[0].get("count")
    if isinstance(count, bool) or not isinstance(count, (int, float)) or not math.isfinite(count):
        return None
    return count


def _direction(value: str) -> str | None:
    normalized = value.strip().lower()
    return normalized if normalized in {"increase", "decrease"} else None


def _strip_runtime_fields(value: object) -> dict[str, object]:
    stripped = _strip_runtime_value(value)
    return cast(dict[str, object], stripped)


def _set_explicit_total_math(query: dict[str, object]) -> None:
    series = query.get("series")
    if not isinstance(series, list) or len(series) != 1 or not isinstance(series[0], dict):
        raise ValueError("validated TrendsQuery must have one series")
    series[0]["math"] = "total"


def _strip_runtime_value(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _strip_runtime_value(child)
            for key, child in value.items()
            if key not in {"response", "tags", "modifiers"}
        }
    if isinstance(value, list):
        return [_strip_runtime_value(child) for child in value]
    return value


def _compact_json(value: Mapping[str, object]) -> str | None:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        return None


def _saved_insight_resolver(team_id: int, reference: str | int) -> SavedInsightIdentity | None:
    return saved_insight_identity(team_id=team_id, reference=reference)
