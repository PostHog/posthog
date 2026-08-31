"""Typed, query-backed measurements shown on a signal report.

A metric is report content, not a copy of analytics data. The stored query remains the source of
truth, and the inbox derives a total-value query for its live whole-window value plus a time-series
query for its longitudinal buckets. An optional value is the latest saved fallback snapshot: an
author can seed it from an observed result, and a background refresh can replace it later. This
keeps inbox reads cheap while a reader opening the report gets fresh data through the normal query
service and its cache.

This module stays dependency-light for the same reason as ``report_charts``: report models and
Temporal payloads import it during process setup, so it must not pull in ``posthog.schema``.
"""

from __future__ import annotations

import re
import json
import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from posthog.hogql.errors import BaseHogQLError

from posthog.hogql_queries.utils.formula_ast import FormulaAST

from products.signals.backend.report_charts import validate_report_query

_METRIC_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_RELATIVE_DATE_FROM_RE = re.compile(r"^-([1-9]\d*)(h|d|w|m|y)$")

MAX_REPORT_METRICS = 6
MAX_REPORT_METRICS_QUERY_CHARS = 60_000
MAX_METRIC_ID_LENGTH = 100
MAX_METRIC_TITLE_LENGTH = 200
MAX_METRIC_CAPTION_LENGTH = 500
MAX_METRIC_UNIT_LENGTH = 40
# `value_at` is authored content, not a server timestamp, so allow a small clock-skew margin before
# treating a snapshot time as an impossible future one.
METRIC_VALUE_AT_MAX_CLOCK_SKEW = timedelta(minutes=5)
MAX_LIVE_METRIC_WINDOW_DAYS = 366
MAX_LIVE_METRIC_QUERY_SERIES = 10
# A detail view can execute all six report metrics together. Capping each longitudinal response at
# 1,000 estimated points keeps that worst case to 6,006 points including the separate one-value
# aggregate response, while still allowing one hourly series over roughly six weeks. The estimate
# includes both ends of the relative range because Trends responses can include the current partial
# bucket. Every metric must produce exactly one output series: without a formula that means one
# source, while a single formula may consume up to ten source series. Breakdowns and comparisons are
# refused because either can multiply that output at runtime.
MAX_LIVE_METRIC_QUERY_POINTS = 1_000

ReportMetricKind = Literal[
    "affected_users",
    "affected_sessions",
    "occurrences",
    "conversion_rate",
    "error_rate",
    "duration",
    "revenue",
    "custom",
]
REPORT_METRIC_KINDS: tuple[ReportMetricKind, ...] = (
    "affected_users",
    "affected_sessions",
    "occurrences",
    "conversion_rate",
    "error_rate",
    "duration",
    "revenue",
    "custom",
)
ReportMetricRole = Literal["primary", "supporting"]
REPORT_METRIC_ROLES: tuple[ReportMetricRole, ...] = ("primary", "supporting")
ReportMetricValueFormat = Literal[
    "number",
    "count",
    "percentage",
    "percentage_scaled",
    "duration",
    "currency",
]
REPORT_METRIC_VALUE_FORMATS: tuple[ReportMetricValueFormat, ...] = (
    "number",
    "count",
    "percentage",
    "percentage_scaled",
    "duration",
    "currency",
)

_LIVE_METRIC_QUERY_KINDS = frozenset({"InsightVizNode"})
_LIVE_METRIC_SERIES_KINDS = frozenset({"ActionsNode", "EventsNode"})
_RELATIVE_WINDOW_SECONDS = {"h": 3_600, "d": 86_400, "w": 604_800, "m": 2_635_200, "y": 31_622_400}
_LIVE_METRIC_INTERVAL_SECONDS = {
    "second": 1,
    "minute": 60,
    "hour": 3_600,
    "day": 86_400,
    "week": 604_800,
    "month": 2_635_200,
    "quarter": 7_905_600,
    "year": 31_622_400,
}
_TRENDS_FORMULA_KEYS = ("formula", "formulas", "formulaNodes")


def _validate_live_metric_formula(formula: object, series_count: int) -> None:
    # The output-series count proves how many results a formula shape declares, not that each
    # formula parses or refers to a defined series. A metric query runs live on every report open,
    # so an empty, malformed, or out-of-range formula fails there instead of at authoring time.
    # Replay the Trends formula parser against dummy series to reject it while the metric is written.
    if not isinstance(formula, str) or not formula.strip():
        raise ValueError("a live metric formula must be a non-empty arithmetic expression over the series")
    dummy_series = [[1.0] for _ in range(series_count)]
    try:
        FormulaAST(dummy_series).call(formula)
    except (BaseHogQLError, SyntaxError, ValueError, TypeError) as error:
        raise ValueError(f"a live metric formula must be executable arithmetic over the series: {error}") from None


class ReportMetricComparison(BaseModel):
    value: float = Field(description="Baseline or previous value, formatted like the metric value.")
    label: str = Field(description="Short context for the comparison, such as `Previous period`.")

    @field_validator("value", mode="before")
    @classmethod
    def value_must_not_be_a_boolean(cls, value: object) -> object:
        # Pydantic's lax mode coerces a JSON boolean into a float (`true` becomes 1.0, `false`
        # becomes 0.0), which would turn a malformed comparison into a real measurement. A report
        # value is never a boolean, so reject it before that coercion runs.
        if isinstance(value, bool):
            raise ValueError("must be a number, not a boolean")
        return value

    @field_validator("value")
    @classmethod
    def value_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("must be finite")
        return value

    @field_validator("label")
    @classmethod
    def label_must_be_bounded(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be empty or whitespace-only")
        if len(normalized) > MAX_METRIC_UNIT_LENGTH:
            raise ValueError(f"must not exceed {MAX_METRIC_UNIT_LENGTH} characters")
        return normalized


class ReportMetric(BaseModel):
    """One impact measurement backed by a bounded live Trends query.

    ``value`` is an optional point-in-time snapshot for cheap list/detail fallbacks. The report
    executes two shapes derived from ``query`` through the regular query endpoint: ``BoldNumber``
    supplies ``result[0].aggregated_value`` for the whole-window headline and ``ActionsBar`` supplies
    the longitudinal buckets. In particular, affected-user totals are never computed by summing
    per-bucket unique counts.
    """

    metric_id: str = Field(description="Stable slug identifying this metric within the report.")
    title: str = Field(description="Short human-readable label for the measurement.")
    kind: ReportMetricKind = Field(description="What the value measures, independent of how it is formatted.")
    role: ReportMetricRole = Field(
        default="supporting",
        description="`primary` for the report's key observation, otherwise `supporting`.",
    )
    value: float | None = Field(
        default=None,
        description=(
            "Latest saved snapshot, initially observed during authoring and optionally replaced by a "
            "background refresh; null when no snapshot is available."
        ),
    )
    value_at: datetime | None = Field(
        default=None,
        description="When the snapshot value was measured; required whenever value is present.",
    )
    value_format: ReportMetricValueFormat = Field(
        default="number",
        description=(
            "Formatting for the numeric value; semantic meaning remains in kind. `percentage` "
            "expects percentage points, while `percentage_scaled` expects a 0–1 ratio. Sessions "
            "and occurrences use count, duration uses duration with ms/s, and revenue uses currency."
        ),
    )
    unit: str | None = Field(
        default=None,
        description="Optional short suffix or currency code, such as `users`, `ms`, or `USD`.",
    )
    query: dict[str, Any] = Field(
        description=(
            "Required live InsightVizNode wrapping one TrendsQuery. The inbox derives a BoldNumber "
            "query for the first series' whole-window aggregated_value and an ActionsBar query for "
            "the longitudinal buckets; time-series buckets must never be summed. It must produce "
            "exactly one output series, though one formula may consume up to "
            f"{MAX_LIVE_METRIC_QUERY_SERIES} source series. Its relative window and interval may "
            f"produce at most {MAX_LIVE_METRIC_QUERY_POINTS} estimated longitudinal points. "
            "Every source series must be an event or action so reader access can be checked without "
            "an unbounded list-query fan-out. Breakdowns and comparisons are not accepted because "
            "one report metric represents one measurement."
        ),
    )
    caption: str | None = Field(default=None, description="Optional context shown below the measurement.")
    comparison: ReportMetricComparison | None = Field(
        default=None,
        description="Optional baseline or previous-period value shown with the current value.",
    )

    @field_validator("metric_id")
    @classmethod
    def metric_id_must_be_reference_safe(cls, value: str) -> str:
        if len(value) > MAX_METRIC_ID_LENGTH:
            raise ValueError(f"must not exceed {MAX_METRIC_ID_LENGTH} characters")
        normalized = value.strip()
        if not _METRIC_ID_RE.fullmatch(normalized):
            raise ValueError(
                "must contain only lowercase letters, numbers, underscores, or hyphens, "
                "and must start with a lowercase letter or number"
            )
        return normalized

    @field_validator("title")
    @classmethod
    def title_must_be_bounded(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty or whitespace-only")
        if len(value) > MAX_METRIC_TITLE_LENGTH:
            raise ValueError(f"must not exceed {MAX_METRIC_TITLE_LENGTH} characters")
        return value

    @field_validator("value", mode="before")
    @classmethod
    def value_must_not_be_a_boolean(cls, value: object) -> object:
        # Pydantic's lax mode coerces a JSON boolean into a float (`true` becomes 1.0, `false`
        # becomes 0.0), which would store a bogus snapshot that clears the finite, count, and rate
        # guards below. A snapshot value is never a boolean, so reject it before that coercion runs.
        if isinstance(value, bool):
            raise ValueError("must be a number, not a boolean")
        return value

    @field_validator("value")
    @classmethod
    def value_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("must be finite")
        return value

    @field_validator("value_at")
    @classmethod
    def value_at_must_be_a_bounded_past_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a timezone")
        # The snapshot time is authored, not stamped by the server, so an LLM can emit a wrong year
        # or a clock-confused date. A future time makes every background refresh look older than the
        # stored snapshot, so the sweep keeps the stale value until real time catches up. Reject a
        # time past now plus a small clock-skew allowance.
        if value > datetime.now(tz=UTC) + METRIC_VALUE_AT_MAX_CLOCK_SKEW:
            raise ValueError("must not be in the future")
        return value

    @field_validator("unit")
    @classmethod
    def unit_must_be_bounded(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > MAX_METRIC_UNIT_LENGTH:
            raise ValueError(f"must not exceed {MAX_METRIC_UNIT_LENGTH} characters")
        return normalized

    @field_validator("caption")
    @classmethod
    def caption_must_be_bounded(cls, value: str | None) -> str | None:
        if value is not None and len(value) > MAX_METRIC_CAPTION_LENGTH:
            raise ValueError(f"must not exceed {MAX_METRIC_CAPTION_LENGTH} characters")
        return value

    @field_validator("query")
    @classmethod
    def query_must_be_a_live_trends_node(cls, value: dict[str, Any]) -> dict[str, Any]:
        validate_report_query(value, allowed_kinds=_LIVE_METRIC_QUERY_KINDS)
        try:
            # Import only while validating authored content: importing the generated schema at module
            # load would put it back on every signals model and Temporal worker startup path.
            from posthog.schema import InsightVizNode  # noqa: PLC0415 — keeps the generated schema off startup

            InsightVizNode.model_validate(value)
        except ValidationError as error:
            first_error = error.errors(include_input=False)[0]
            location = ".".join(str(part) for part in first_error["loc"])
            raise ValueError(
                f"query must match the canonical InsightVizNode schema; {location}: {first_error['msg']}"
            ) from None
        source = value.get("source")
        if not isinstance(source, dict) or source.get("kind") != "TrendsQuery":
            raise ValueError("query must wrap one TrendsQuery in an InsightVizNode")
        series = source.get("series")
        if not isinstance(series, list) or not series or any(not isinstance(item, dict) for item in series):
            raise ValueError("query.source.series must contain at least one Trends series")
        if len(series) > MAX_LIVE_METRIC_QUERY_SERIES:
            raise ValueError(f"query.source.series accepts at most {MAX_LIVE_METRIC_QUERY_SERIES} series")
        if any(item.get("kind") not in _LIVE_METRIC_SERIES_KINDS for item in series):
            raise ValueError("a live metric query must use only event or action series so reader access can be checked")
        for item in series:
            if item["kind"] == "EventsNode":
                event = item.get("event")
                if not isinstance(event, str) or not event.strip():
                    raise ValueError("a live metric event series needs a non-empty event name")
            else:
                action_id = item.get("id")
                if not isinstance(action_id, int) or isinstance(action_id, bool) or action_id <= 0:
                    raise ValueError("a live metric action series needs a positive integer action id")
        if source.get("breakdownFilter") or source.get("breakdown"):
            raise ValueError("a live metric query must not use a breakdown because it represents one measurement")
        compare_filter = source.get("compareFilter")
        if isinstance(compare_filter, dict) and compare_filter.get("compare"):
            raise ValueError("a live metric query must not use compare mode because it represents one measurement")
        trends_filter = source.get("trendsFilter")
        if isinstance(trends_filter, dict):
            if trends_filter.get("compare"):
                raise ValueError("a live metric query must not use compare mode because it represents one measurement")
            if (
                trends_filter.get("display") == "Metric"
                and trends_filter.get("metricShowChange", True) is not False
                and trends_filter.get("metricSummary", "total") != "latest"
            ):
                raise ValueError(
                    "a live metric query using the Metric display must disable metricShowChange or use the latest "
                    "summary so the Trends runner does not enable compare mode"
                )
        date_range = source.get("dateRange")
        if not isinstance(date_range, dict):
            raise ValueError("query.source.dateRange.date_from must be a relative time window such as `-30d`")
        date_from = date_range.get("date_from")
        if not isinstance(date_from, str):
            raise ValueError("query.source.dateRange.date_from must be a relative time window such as `-30d`")
        relative_window = _RELATIVE_DATE_FROM_RE.fullmatch(date_from)
        if relative_window is None:
            raise ValueError("query.source.dateRange.date_from must be a relative time window such as `-30d`")
        amount, unit = relative_window.groups()
        window_seconds = int(amount) * _RELATIVE_WINDOW_SECONDS[unit]
        if window_seconds > MAX_LIVE_METRIC_WINDOW_DAYS * _RELATIVE_WINDOW_SECONDS["d"]:
            raise ValueError(
                f"query.source.dateRange must not exceed {MAX_LIVE_METRIC_WINDOW_DAYS} days for a live metric"
            )
        if date_range.get("date_to") not in (None, ""):
            raise ValueError("query.source.dateRange.date_to must be empty so a live metric advances with time")
        interval = source.get("interval")
        if interval is None:
            interval = "day"
        if not isinstance(interval, str) or interval not in _LIVE_METRIC_INTERVAL_SECONDS:
            accepted_intervals = ", ".join(_LIVE_METRIC_INTERVAL_SECONDS)
            raise ValueError(f"query.source.interval must be one of {accepted_intervals}")
        output_series_count = len(series)
        selected_formulas: list[object] = []
        if isinstance(trends_filter, dict):
            formula_nodes = trends_filter.get("formulaNodes")
            formulas = trends_filter.get("formulas")
            formula = trends_filter.get("formula")
            if isinstance(formula_nodes, list) and formula_nodes:
                output_series_count = len(formula_nodes)
                selected_formulas = [node.get("formula") if isinstance(node, dict) else node for node in formula_nodes]
            elif isinstance(formulas, list) and formulas:
                output_series_count = len(formulas)
                selected_formulas = list(formulas)
            elif isinstance(formula, str) and formula:
                output_series_count = 1
                selected_formulas = [formula]
        if output_series_count != 1:
            raise ValueError(
                "a live metric query must produce exactly one output series; use one source or combine up to "
                f"{MAX_LIVE_METRIC_QUERY_SERIES} source series with exactly one formula"
            )
        for selected_formula in selected_formulas:
            _validate_live_metric_formula(selected_formula, len(series))
        interval_seconds = _LIVE_METRIC_INTERVAL_SECONDS[interval]
        estimated_buckets = (window_seconds + interval_seconds - 1) // interval_seconds + 1
        estimated_points = estimated_buckets * output_series_count
        if estimated_points > MAX_LIVE_METRIC_QUERY_POINTS:
            raise ValueError(
                "query.source date range, interval, and output series would produce approximately "
                f"{estimated_points} points; live metrics accept at most {MAX_LIVE_METRIC_QUERY_POINTS}"
            )
        return value

    @model_validator(mode="after")
    def measurement_must_be_available_and_consistent(self) -> ReportMetric:
        if (self.value is None) != (self.value_at is None):
            raise ValueError("value and value_at must be provided together")
        if self.kind == "affected_users":
            if self.value_format != "count":
                raise ValueError("an affected_users metric must use count formatting")
            source = self.query["source"]
            series = source.get("series")
            if not isinstance(series, list) or len(series) != 1 or not isinstance(series[0], dict):
                raise ValueError("an affected_users query must contain exactly one Trends series")
            affected_users_series = series[0]
            if affected_users_series.get("math") != "dau":
                raise ValueError("an affected_users query must use `math: dau` to count unique people")
            if affected_users_series.get("math_group_type_index") is not None:
                raise ValueError("an affected_users query must count people, not unique groups")
            trends_filter = source.get("trendsFilter")
            if isinstance(trends_filter, dict):
                if any(trends_filter.get(key) for key in _TRENDS_FORMULA_KEYS):
                    raise ValueError(
                        "an affected_users query must not use a formula because its total comes from `math: dau`"
                    )
        if self.kind in {"affected_sessions", "occurrences"} and self.value_format != "count":
            raise ValueError("an affected_sessions or occurrences metric must use count formatting")
        if self.kind == "duration":
            if self.value_format != "duration":
                raise ValueError("a duration metric must use duration formatting")
            if self.unit not in {"ms", "s"}:
                raise ValueError("a duration metric must use `ms` or `s` as its unit")
            if self.value is not None and self.value < 0:
                raise ValueError("a duration snapshot must be non-negative")
            if self.comparison is not None and self.comparison.value < 0:
                raise ValueError("a duration comparison must be non-negative")
        if self.kind == "revenue":
            if self.value_format != "currency":
                raise ValueError("a revenue metric must use currency formatting")
            if self.unit is None or re.fullmatch(r"[A-Z]{3}", self.unit) is None:
                raise ValueError("a revenue metric must use a three-letter ISO currency code as its unit")
        if self.value_format == "count" and self.value is not None:
            if self.value < 0 or not self.value.is_integer():
                raise ValueError("a count snapshot must be a non-negative whole number")
        if self.value_format == "count" and self.comparison is not None:
            if self.comparison.value < 0 or not self.comparison.value.is_integer():
                raise ValueError("a count comparison must be a non-negative whole number")
        percentage_formats = {"percentage", "percentage_scaled"}
        if self.kind in {"conversion_rate", "error_rate"}:
            if self.value_format not in percentage_formats:
                raise ValueError("a conversion_rate or error_rate metric must use percentage formatting")
            upper_bound = 1 if self.value_format == "percentage_scaled" else 100
            if self.value is not None and not 0 <= self.value <= upper_bound:
                raise ValueError(f"a {self.value_format} rate snapshot must be between 0 and {upper_bound}")
            if self.comparison is not None and not 0 <= self.comparison.value <= upper_bound:
                raise ValueError(f"a {self.value_format} rate comparison must be between 0 and {upper_bound}")
        if self.value_format in percentage_formats:
            trends_filter = self.query["source"].get("trendsFilter")
            axis_format = trends_filter.get("aggregationAxisFormat") if isinstance(trends_filter, dict) else None
            if axis_format != self.value_format:
                raise ValueError(
                    "a percentage metric query needs an aggregationAxisFormat that matches the metric value_format"
                )
        return self


def metric_batch_query_chars(metrics: Sequence[ReportMetric]) -> int:
    return sum(len(json.dumps(metric.query)) for metric in metrics)


def metric_batch_error(metrics: Sequence[ReportMetric]) -> str | None:
    if len(metrics) > MAX_REPORT_METRICS:
        return f"a report accepts at most {MAX_REPORT_METRICS} metrics ({len(metrics)})"
    total_query_chars = metric_batch_query_chars(metrics)
    if total_query_chars > MAX_REPORT_METRICS_QUERY_CHARS:
        return (
            f"the metrics' queries total {total_query_chars} characters, "
            f"the limit is {MAX_REPORT_METRICS_QUERY_CHARS} across one report"
        )
    seen: set[str] = set()
    primary_count = 0
    affected_users_count = 0
    for metric in metrics:
        if metric.metric_id in seen:
            return f"duplicate metric_id {metric.metric_id!r} — metric_ids must be unique within a report"
        seen.add(metric.metric_id)
        primary_count += metric.role == "primary"
        affected_users_count += metric.kind == "affected_users"
    if primary_count > 1:
        return "a report accepts at most one primary metric"
    if affected_users_count > 1:
        return "a report accepts at most one affected_users metric"
    return None
