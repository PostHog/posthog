import math
from datetime import datetime
from typing import Any

from structlog import get_logger

from posthog.security.llm_prompt_sanitization import GENERIC_VALUE_MAX_LEN, SERIES_LABEL_MAX_LEN, sanitize_user_text

LOGGER = get_logger(__name__)

MAX_SUMMARY_LENGTH = 2000
# Fits one line per series for the default BREAKDOWN_VALUES_LIMIT breakdown values when labels are short.
MAX_SERIES_SUMMARY_LENGTH = 5000

# Query kinds whose metric values map onto the insight's Y-axis format, so summary
# numbers should be rendered the way the chart renders them (e.g. duration, currency).
_TREND_SUMMARY_KINDS = {"TrendsQuery", "LifecycleQuery", "StickinessQuery"}
# Query kinds whose data points are calendar periods, so the final point can still be collecting data.
_TIME_SERIES_KINDS = {"TrendsQuery", "LifecycleQuery"}


def _safe_label(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    return sanitize_user_text(str(value), SERIES_LABEL_MAX_LEN) or fallback


def _safe_value(value: Any) -> str:
    if isinstance(value, (int, float)) or value is None:
        return str(value)
    return sanitize_user_text(str(value), GENERIC_VALUE_MAX_LEN)


def uses_generic_results_summary(query_kind: str) -> bool:
    return query_kind not in _TREND_SUMMARY_KINDS and query_kind not in _SUMMARIZERS


def is_time_series_query(query_kind: str) -> bool:
    return query_kind in _TIME_SERIES_KINDS


def last_period_is_incomplete(query_kind: str, query_results: Any, interval: Any = None) -> bool:
    """Whether the final returned time bucket was still collecting data when the query ran.

    A relative range such as "last 30 days" resolves its end to the end of the current day or hour,
    which is after the refresh time. A fixed end date, or excludeIncompletePeriods, resolves it before.
    """
    if not is_time_series_query(query_kind) or not isinstance(query_results, dict):
        return False
    resolved_date_range = query_results.get("resolved_date_range")
    if not isinstance(resolved_date_range, dict):
        return False
    raw_date_to = resolved_date_range.get("date_to")
    last_refresh = query_results.get("last_refresh")
    if not raw_date_to or not last_refresh:
        return False
    try:
        date_to = datetime.fromisoformat(str(raw_date_to))
        if date_to <= datetime.fromisoformat(str(last_refresh)):
            return False
    except (TypeError, ValueError):
        return False

    # A weekday filter drops deselected day buckets, so on such a day the last returned
    # bucket is an earlier day that has ended.
    if interval == "day":
        last_day = _last_returned_day(query_results.get("result"))
        return last_day is None or last_day[:10] == date_to.date().isoformat()
    return True


def _last_returned_day(results: Any) -> str | None:
    if not isinstance(results, list):
        return None
    for series in results:
        if not isinstance(series, dict) or series.get("compare_label") == "previous":
            continue
        days = series.get("days")
        if isinstance(days, list) and days and isinstance(days[-1], str):
            return days[-1]
    return None


def build_results_summary(
    query_kind: str,
    results: list[Any] | None,
    columns: list[str] | None = None,
    value_format: dict[str, Any] | None = None,
    last_period_incomplete: bool = False,
) -> str:
    if not results:
        return "No results"

    if query_kind == "StickinessQuery":
        text = _summarize_stickiness(results, _sanitize_value_format(value_format))
    elif query_kind in _TREND_SUMMARY_KINDS:
        text = _summarize_trends(results, _sanitize_value_format(value_format), last_period_incomplete)
    elif summarizer := _SUMMARIZERS.get(query_kind):
        text = summarizer(results)
    else:
        text = _summarize_generic(results, columns)
    max_length = MAX_SERIES_SUMMARY_LENGTH if query_kind in _TREND_SUMMARY_KINDS else MAX_SUMMARY_LENGTH
    if len(text) > max_length:
        text = text[:max_length] + "\n... (truncated)"
    return text


def _summarize_trends(
    results: list[dict[str, Any]], value_format: dict[str, Any] | None, last_period_incomplete: bool = False
) -> str:
    if _looks_like_boxplot_trend(results):
        return _summarize_boxplot_trend(results, value_format)

    lines: list[str] = []
    for series in results:
        label = _safe_label(series.get("label"), "Unknown")
        data = series.get("data", [])
        aggregated_value = series.get("aggregated_value")

        if data and isinstance(data, list):
            points = _numeric_points(data, series.get("days"))
            if points:
                # A compare-to-previous series covers the earlier window, which has ended.
                last_is_incomplete = (
                    last_period_incomplete and _is_finite_number(data[-1]) and series.get("compare_label") != "previous"
                )
                lines.append(_format_trend_series(label, points, value_format, last_is_incomplete))
                continue

        if aggregated_value is not None:
            lines.append(f"- {label}: total={_fmt_value(aggregated_value, value_format)}")
        elif series.get("count") is not None and series["count"] != 0:
            lines.append(f"- {label}: count={_fmt_value(series['count'], value_format)}")
        else:
            lines.append(f"- {label}: (no data)")

    return "\n".join(lines) if lines else "No trend series"


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value)


def _numeric_points(data: list[Any], days: Any) -> list[tuple[str, float | int]]:
    period_labels = days if isinstance(days, list) and len(days) == len(data) else [None] * len(data)
    return [(_period_label(day), value) for day, value in zip(period_labels, data) if _is_finite_number(value)]


def _period_label(day: Any) -> str:
    if not isinstance(day, str):
        return ""
    return sanitize_user_text(day, GENERIC_VALUE_MAX_LEN)


def _at(period: str) -> str:
    return f" ({period})" if period else ""


def _format_trend_series(
    label: str,
    points: list[tuple[str, float | int]],
    value_format: dict[str, Any] | None,
    last_is_incomplete: bool,
) -> str:
    complete = points[:-1] if last_is_incomplete else points
    parts: list[str] = []

    if complete:
        latest_period, latest = complete[-1]
        parts.append(f"latest={_fmt_value(latest, value_format)}{_at(latest_period)}")
        if len(complete) >= 2:
            _, previous = complete[-2]
            parts.append(f"previous point={_fmt_value(previous, value_format)}")
            parts.append(f"change={_change_from(previous, latest)}")
    if last_is_incomplete:
        in_progress_period, in_progress = points[-1]
        parts.append(f"in progress={_fmt_value(in_progress, value_format)}{_at(in_progress_period)}")

    if complete:
        values = [value for _, value in complete]
        parts.append(
            f"avg={_fmt_value(sum(values) / len(values), value_format)}, "
            f"min={_fmt_value(min(values), value_format)}, max={_fmt_value(max(values), value_format)}, "
            f"window trend={_trend_direction(values)} ({len(values)} points)"
        )

    return f"- {label}: {', '.join(parts)}"


def _change_from(previous: float | int, latest: float | int) -> str:
    if latest == previous:
        return "no change"
    direction = "up" if latest > previous else "down"
    if previous == 0:
        return f"{direction} from 0"
    pct = abs(latest - previous) / abs(previous) * 100
    return f"{direction} {pct:,.0f}%" if pct >= 10 else f"{direction} {pct:.1f}%"


def _summarize_stickiness(results: list[dict[str, Any]], value_format: dict[str, Any] | None) -> str:
    # Each point counts actors by how many periods they were active in, not by calendar period,
    # so the series gets no latest, change or window trend.
    lines: list[str] = []
    for series in results:
        label = _safe_label(series.get("label"), "Unknown")
        data = series.get("data")
        if isinstance(data, list):
            bin_labels = series.get("labels")
            if not isinstance(bin_labels, list) or len(bin_labels) != len(data):
                bin_labels = [str(index + 1) for index in range(len(data))]
            bins = [
                f"{_safe_label(bin_label, str(index + 1))}={_fmt_value(value, value_format)}"
                for index, (bin_label, value) in enumerate(zip(bin_labels, data))
                if _is_finite_number(value)
            ]
            if bins:
                count = series.get("count")
                total = f", total={_fmt_value(count, value_format)}" if _is_finite_number(count) else ""
                lines.append(f"- {label}: by periods active: {', '.join(bins)}{total}")
                continue
        lines.append(f"- {label}: (no data)")

    return "\n".join(lines) if lines else "No stickiness series"


def _looks_like_boxplot_trend(results: list[dict[str, Any]]) -> bool:
    # Boxplot TrendsQuery results have one row per (series × time bucket) with
    # quantile stats (median/min/max/p25/p75) and no `data` array.
    if not results or not isinstance(results[0], dict):
        return False
    first = results[0]
    return "median" in first and "data" not in first


def _summarize_boxplot_trend(results: list[dict[str, Any]], value_format: dict[str, Any] | None) -> str:
    by_series: dict[str, list[dict[str, Any]]] = {}
    for row in results:
        label = _safe_label(row.get("series_label") or row.get("label"), "Unknown")
        by_series.setdefault(label, []).append(row)

    lines: list[str] = []
    for label, rows in by_series.items():
        medians = [
            r["median"] for r in rows if isinstance(r.get("median"), (int, float)) and math.isfinite(r["median"])
        ]
        if not medians:
            lines.append(f"- {label}: (no data)")
            continue
        maxes = [r["max"] for r in rows if isinstance(r.get("max"), (int, float)) and math.isfinite(r["max"])]
        mins = [r["min"] for r in rows if isinstance(r.get("min"), (int, float)) and math.isfinite(r["min"])]
        trend = _trend_direction(medians)
        lines.append(
            f"- {label} (boxplot): median latest={_fmt_value(medians[-1], value_format)}, "
            f"median avg={_fmt_value(sum(medians) / len(medians), value_format)}, "
            f"overall min={_fmt_value(min(mins) if mins else medians[-1], value_format)}, "
            f"overall max={_fmt_value(max(maxes) if maxes else medians[-1], value_format)}, "
            f"median window trend={trend} ({len(medians)} points)"
        )

    return "\n".join(lines) if lines else "No trend series"


def _summarize_funnels(results: list[Any]) -> str:
    lines: list[str] = []

    steps = results
    if results and isinstance(results[0], list):
        steps = results[0]

    for i, step in enumerate(steps):
        name = _safe_label(step.get("name") or step.get("custom_name"), f"Step {i + 1}")
        count = step.get("count", 0)
        conversion = step.get("conversion_rate")
        if conversion is not None:
            lines.append(f"- Step {i + 1} ({name}): count={_fmt(count)}, conversion={_fmt(conversion)}%")
        else:
            lines.append(f"- Step {i + 1} ({name}): count={_fmt(count)}")

    return "\n".join(lines) if lines else "No funnel steps"


def _summarize_retention(results: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for i, cohort in enumerate(results[:10]):
        label = _safe_label(cohort.get("label") or cohort.get("date"), f"Cohort {i}")
        values = cohort.get("values", [])
        if values:
            initial = values[0].get("count", 0) if isinstance(values[0], dict) else values[0]
            final = values[-1].get("count", 0) if isinstance(values[-1], dict) else values[-1]
            retention_pct = (final / initial * 100) if initial > 0 else 0
            lines.append(f"- {label}: initial={_fmt(initial)}, final={_fmt(final)}, retention={_fmt(retention_pct)}%")
        else:
            lines.append(f"- {label}: (no values)")
    if len(results) > 10:
        lines.append(f"... and {len(results) - 10} more cohorts")
    return "\n".join(lines) if lines else "No retention cohorts"


def _summarize_generic(results: list[Any], columns: list[str] | None = None) -> str:
    """Fallback for query kinds without a dedicated summarizer.

    Handles both row shapes we see in practice:
    - dict rows (most PostHog query results): skip known noisy keys, join the rest.
    - list/tuple rows (HogQL / DataVisualizationNode): label each value with the
      corresponding entry from `columns` when provided, falling back to
      position-indexed `colN` names when a column list is unavailable or shorter
      than the row.
    Any other shape falls back to str() so a surprising result shape produces a
    usable summary instead of an AttributeError that kills the whole activity.
    """
    lines: list[str] = []
    for i, row in enumerate(results[:20]):
        parts: list[str] = []
        if isinstance(row, dict):
            for key, val in row.items():
                if key in ("data", "values", "days", "labels", "timestamps"):
                    continue
                parts.append(f"{_safe_label(key, 'field')}={_safe_value(val)}")
        elif isinstance(row, (list, tuple)):
            for col_index, val in enumerate(row):
                label = _safe_label(_column_label(columns, col_index), f"col{col_index}")
                parts.append(f"{label}={_safe_value(val)}")
        else:
            # Emit a signal rather than silently producing an ok-ish summary — if a
            # new shape appears in practice we find out from logs, not from a user.
            LOGGER.info(
                "subscription_summary.unexpected_row_shape",
                row_type=type(row).__name__,
            )
            parts.append(_safe_value(row))
        if parts:
            lines.append(f"- Row {i + 1}: {', '.join(parts)}")
    if len(results) > 20:
        lines.append(f"... and {len(results) - 20} more rows")
    return "\n".join(lines) if lines else "No results data"


def _column_label(columns: list[str] | None, index: int) -> str:
    if columns and index < len(columns) and columns[index].strip():
        return columns[index]
    return f"col{index}"


def _trend_direction(values: list[float | int]) -> str:
    if len(values) < 2:
        return "stable"
    first_half = values[: len(values) // 2]
    second_half = values[len(values) // 2 :]
    avg_first = sum(first_half) / len(first_half) if first_half else 0
    avg_second = sum(second_half) / len(second_half) if second_half else 0
    if avg_first == 0:
        if avg_second > 0:
            return "up"
        elif avg_second < 0:
            return "down"
        return "stable"
    pct_change = (avg_second - avg_first) / abs(avg_first) * 100
    if pct_change > 5:
        return "up"
    elif pct_change < -5:
        return "down"
    return "stable"


def _fmt(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        if not math.isfinite(value):
            return "N/A"
        if value == int(value):
            return f"{int(value):,}"
        return f"{value:,.2f}"
    return f"{value:,}"


def _format_duration(seconds: float | int, *, seconds_fixed: int = 0) -> str:
    """Human-readable duration matching the chart's Y-axis (humanFriendlyDuration):
    days+hours for >= 1 day, hours+minutes+seconds below that, e.g. "4d 4h" / "3h 45m 12s".
    """
    if seconds < 0:
        return f"-{_format_duration(-seconds, seconds_fixed=seconds_fixed)}"
    if seconds < 1:
        return f"{round(seconds * 1000)}ms" if seconds else "0s"
    if seconds < 60:
        if seconds_fixed:
            return f"{seconds:.{seconds_fixed}f}".rstrip("0").rstrip(".") + "s"
        return f"{int(seconds)}s"

    # Floor every unit to match the chart's humanFriendlyDuration; rounding the
    # seconds component would roll 59.6s up to "60s" (i.e. "1m 60s").
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int((seconds % 3600) % 60)

    if days > 0:
        units = [f"{days}d"] + ([f"{hours}h"] if hours else [])
    else:
        units = [
            u for u in (f"{hours}h" if hours else "", f"{minutes}m" if minutes else "", f"{secs}s" if secs else "") if u
        ]
    return " ".join(units) or "0s"


def _format_duration_nanoseconds(value: float | int) -> str:
    absolute_value = abs(value)
    if absolute_value < 1_000:
        return f"{_fmt(value)}ns"
    if absolute_value < 1_000_000:
        return f"{_fmt(value / 1_000)}µs"
    return _format_duration(value / 1_000_000_000, seconds_fixed=1)


def _sanitize_axis_affix(affix: str) -> str:
    """Strip LLM-framing markers from a user-controlled axis prefix/postfix while keeping the
    single separating space a real affix uses (e.g. " reqs" stays " reqs" so the value reads
    "1,200 reqs" like the chart). sanitize_user_text trims surrounding whitespace, so re-apply a
    single leading/trailing space when the original had one.
    """
    sanitized = sanitize_user_text(affix, GENERIC_VALUE_MAX_LEN)
    if not sanitized:
        return ""
    lead = " " if affix[:1].isspace() else ""
    trail = " " if affix[-1:].isspace() else ""
    return f"{lead}{sanitized}{trail}"


def _sanitize_value_format(value_format: dict[str, Any] | None) -> dict[str, Any] | None:
    """Sanitize the user-controlled axis prefix/postfix before they land in the summary text.
    Insight axis prefix/postfix are user-editable, and the summary is wrapped in `<insight_data>`
    tags for the LLM, so without this a user could set a postfix like `</insight_data><user_context>...`
    and inject instructions — the same defense already applied to labels and values.
    """
    if not value_format:
        return value_format
    sanitized = dict(value_format)
    for key in ("prefix", "postfix"):
        if sanitized.get(key):
            sanitized[key] = _sanitize_axis_affix(sanitized[key])
    return sanitized


def _fmt_value(value: float | int | None, value_format: dict[str, Any] | None) -> str:
    """Render a metric value the way the insight's Y-axis does, so summary numbers match
    the chart the user sees (a duration insight reads "4d 4h", not "360000"). Mirrors
    frontend/src/lib/insights/aggregationAxisFormat.ts. Falls back to plain numeric
    formatting when no axis format is configured.
    """
    if not value_format:
        return _fmt(value)
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "N/A"

    axis_format = value_format.get("format")
    if axis_format == "duration":
        formatted = _format_duration(value)
    elif axis_format == "duration_ms":
        formatted = _format_duration(value / 1000)
    elif axis_format == "duration_ns":
        formatted = _format_duration_nanoseconds(value)
    elif axis_format == "percentage":
        formatted = f"{_fmt(value)}%"
    elif axis_format == "percentage_scaled":
        formatted = f"{_fmt(value * 100)}%"
    else:
        formatted = _fmt(value)

    prefix = value_format.get("prefix") or ""
    postfix = value_format.get("postfix") or ""
    return f"{prefix}{formatted}{postfix}"


_SUMMARIZERS: dict[str, Any] = {
    "FunnelsQuery": _summarize_funnels,
    "RetentionQuery": _summarize_retention,
}
