import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from structlog import get_logger

from posthog.bucket_completeness import Period, bucket_starts, incomplete_from_index
from posthog.interval_specs import INTERVAL_SPECS, PERIOD_MAP
from posthog.security.llm_prompt_sanitization import GENERIC_VALUE_MAX_LEN, SERIES_LABEL_MAX_LEN, sanitize_user_text

LOGGER = get_logger(__name__)

MAX_SUMMARY_LENGTH = 2000

# Both LLM prompt templates tell the model to look for this prefix, so it is a cross-module contract.
INCOMPLETE_PERIOD_NOTE_PREFIX = "(Excluding"

# Query kinds whose metric values map onto the insight's Y-axis format, so summary
# numbers should be rendered the way the chart renders them (e.g. duration, currency).
_TREND_SUMMARY_KINDS = {"TrendsQuery", "LifecycleQuery", "StickinessQuery"}


def _safe_label(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    return sanitize_user_text(str(value), SERIES_LABEL_MAX_LEN) or fallback


def _safe_value(value: Any) -> str:
    if isinstance(value, (int, float)) or value is None:
        return str(value)
    return sanitize_user_text(str(value), GENERIC_VALUE_MAX_LEN)


def build_results_summary(
    query_kind: str,
    results: list[Any] | None,
    columns: list[str] | None = None,
    value_format: dict[str, Any] | None = None,
    query_ran_at: str | None = None,
    timezone: str | None = None,
) -> str:
    if not results:
        return "No results"

    if query_kind in _TREND_SUMMARY_KINDS:
        text = _summarize_trend_kind(results, value_format, query_ran_at=query_ran_at, timezone=timezone)
    elif summarizer := _SUMMARIZERS.get(query_kind):
        text = summarizer(results)
    else:
        text = _summarize_generic(results, columns)
    return _truncate(text, len(results))


def _summarize_trend_kind(
    results: list[Any], value_format: dict[str, Any] | None, *, query_ran_at: Any, timezone: Any
) -> str:
    value_fmt = _sanitize_value_format(value_format)
    if _looks_like_boxplot_trend(results):
        # Boxplot rows carry one bucket each, so there is no shared trailing period to trim.
        return _summarize_boxplot_trend(results, value_fmt)

    coverage = _coverage(results, query_ran_at=query_ran_at, timezone=timezone)
    if coverage is None or not _has_trimmable_series(results, coverage.excluded):
        # Total-value displays carry `days` but report one figure over the whole range, so a note
        # would describe a trim that never happened.
        return _summarize_trends(results, value_fmt, 0, in_progress=False, unit=None)

    return _prepend(
        coverage.note(), _summarize_trends(results, value_fmt, coverage.excluded, in_progress=True, unit=coverage.unit)
    )


def _prepend(note: str, text: str) -> str:
    # Prepended rather than appended so truncation cannot drop it.
    return f"{note}\n{text}"


def _truncate(text: str, series_count: int) -> str:
    """Keep whole lines and say up front that this is a sample of the largest series."""
    if len(text) <= MAX_SUMMARY_LENGTH:
        return text

    def notice(shown: int) -> str:
        # Directive, like the exclusion note: a model given only the count still wrote "all series".
        return (
            f"(These are the {shown} largest of {series_count} series — describe them as the top {shown}, "
            f"never as all series.)"
        )

    # Reserve the widest the notice can get, so prepending it afterwards cannot breach the budget.
    budget = MAX_SUMMARY_LENGTH - len(notice(series_count)) - 1
    kept: list[str] = []
    used = 0
    for line in text.split("\n"):
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    shown = sum(1 for line in kept if line.startswith("- "))
    return _prepend(notice(shown), "\n".join(kept))


def _summarize_trends(
    results: list[dict[str, Any]],
    value_format: dict[str, Any] | None,
    excluded: int,
    *,
    in_progress: bool,
    unit: str | None,
) -> str:
    lines: list[str] = []
    for series in results:
        label = _safe_label(series.get("label"), "Unknown")
        data = series.get("data", [])
        partial: Any = None
        if excluded and isinstance(data, list) and len(data) > excluded:
            partial = data[-excluded]
            data = data[:-excluded]
        aggregated_value = series.get("aggregated_value")

        if data and isinstance(data, list):
            numeric = [v for v in data if isinstance(v, (int, float)) and math.isfinite(v)]
            if numeric:
                latest = numeric[-1]
                avg = sum(numeric) / len(numeric)
                trend = _trend_direction(numeric)
                line = (
                    f"- {label}: latest={_fmt_value(latest, value_format)}, avg={_fmt_value(avg, value_format)}, "
                    f"min={_fmt_value(min(numeric), value_format)}, max={_fmt_value(max(numeric), value_format)}, "
                    # "(6 points)" next to formatted values reads as a magnitude; a model wrote
                    # "decreased by 6 points". The unit name cannot be misread that way.
                    f"trend={trend} ({len(numeric)} {_plural(unit, len(numeric)) if unit else 'points'})"
                )
                if in_progress and isinstance(partial, (int, float)) and math.isfinite(partial):
                    line += f", in_progress={_fmt_value(partial, value_format)}"
                lines.append(line)
                continue

        if aggregated_value is not None:
            lines.append(f"- {label}: total={_fmt_value(aggregated_value, value_format)}")
        elif series.get("count") is not None and series["count"] != 0:
            lines.append(f"- {label}: count={_fmt_value(series['count'], value_format)}")
        else:
            lines.append(f"- {label}: (no data)")

    return "\n".join(lines) if lines else "No trend series"


def _has_trimmable_series(results: list[Any], excluded: int) -> bool:
    return excluded > 0 and any(
        isinstance(series, dict) and isinstance(series.get("data"), list) and len(series["data"]) > excluded
        for series in results
    )


@dataclass(frozen=True, kw_only=True)
class _Coverage:
    """Which trailing buckets were unfinished when the query ran, and how to describe them."""

    total: int
    first_incomplete: int
    unit: str
    elapsed_pct: int | None

    @property
    def excluded(self) -> int:
        return self.total - self.first_incomplete

    def note(self) -> str:
        complete = self.first_incomplete
        elapsed = f", {self.elapsed_pct}% elapsed" if self.elapsed_pct is not None else ""
        return (
            f"{INCOMPLETE_PERIOD_NOTE_PREFIX} {self.excluded} {_plural(self.unit, self.excluded)} at the end of the "
            f"range that had not completed when the query ran; the per-period figures below cover {complete} "
            f"complete {_plural(self.unit, complete)}. in_progress= is how far the unfinished {self.unit} has "
            f"got{elapsed} — report it when describing the current {self.unit}, but never compare it to "
            f"latest= and never call it a rise or a fall.)"
        )


def _plural(unit: str, count: int) -> str:
    return unit if count == 1 else f"{unit}s"


def _coverage(results: list[Any], *, query_ran_at: Any, timezone: Any) -> _Coverage | None:
    """Locate the trailing buckets that had not finished when the query ran.

    Returns None whenever completeness cannot be established, which leaves every figure exactly as
    it was before this existed.
    """
    starts = bucket_starts(_first_days_list(results))
    reference = _local_reference(query_ran_at, timezone)
    period, unit = _period_and_unit(results, starts)
    if starts is None or reference is None or period is None:
        LOGGER.info(
            "subscription_summary.coverage_skipped",
            reason=_skip_reason(starts, reference, period),
            bucket_count=len(starts) if starts else 0,
        )
        return None

    first_incomplete = incomplete_from_index(starts, reference=reference, period=period)
    if first_incomplete is None:
        return None

    coverage = _Coverage(
        total=len(starts),
        first_incomplete=first_incomplete,
        unit=unit,
        elapsed_pct=_elapsed_pct(starts[first_incomplete], reference, period),
    )
    # Over-trimming is the failure worth catching, and it is otherwise only visible in a wrong digest.
    LOGGER.info(
        "subscription_summary.coverage",
        excluded=coverage.excluded,
        total_buckets=coverage.total,
        unit=unit,
    )
    return coverage


def _first_days_list(results: list[Any]) -> Any:
    """Every series in a trends response shares one bucket set, so the first usable `days` wins."""
    for series in results:
        if isinstance(series, dict) and isinstance(series.get("days"), list) and series["days"]:
            return series["days"]
    return None


def _period_and_unit(results: list[Any], starts: list[datetime] | None) -> tuple[Period | None, str]:
    """Prefer the query's own interval; fall back to the gap between buckets.

    `dateRange.daysOfWeek` removes buckets mid-axis, so spacing alone would read a weekdays-only
    daily trend as 3-day buckets. That only happens on trends, which is exactly where `interval` is
    present — lifecycle and stickiness carry no `filter` block but also no holes.
    """
    interval = _query_interval(results)
    if interval and interval in PERIOD_MAP:
        return PERIOD_MAP[interval], interval
    if starts and len(starts) >= 2:
        width = starts[-1] - starts[-2]
        for name, spec in INTERVAL_SPECS.items():
            if spec.period == width:
                return spec.period, name
        return width, "interval"
    return None, "interval"


def _query_interval(results: list[Any]) -> str | None:
    for series in results:
        if isinstance(series, dict) and isinstance(series.get("filter"), dict):
            interval = series["filter"].get("interval")
            if isinstance(interval, str):
                return interval
    return None


def _elapsed_pct(bucket_start: datetime, reference: datetime, period: Period) -> int | None:
    """How far into the unfinished bucket the query ran, so the model can read its value in context."""
    span = (bucket_start + period) - bucket_start
    if span.total_seconds() <= 0:
        return None
    return max(0, min(100, round((reference - bucket_start).total_seconds() / span.total_seconds() * 100)))


def _local_reference(query_ran_at: Any, timezone: Any) -> datetime | None:
    """The query's run time as naive wall clock in the team's timezone.

    Converting once here keeps DST out of the comparison: a spring-forward day is still one calendar
    day wide when both sides are wall clock.
    """
    if not isinstance(query_ran_at, str) or not query_ran_at:
        return None
    try:
        parsed = datetime.fromisoformat(query_ran_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(_resolve_timezone(timezone)).replace(tzinfo=None)


def _skip_reason(starts: list[datetime] | None, reference: datetime | None, period: Period | None) -> str:
    if reference is None:
        return "unusable_run_timestamp"
    if starts is None:
        # Stickiness puts integer day-counts in `days`, so it lands here with nothing parsed.
        return "no_parseable_bucket_starts"
    return "no_period" if period is None else "unknown"


def _resolve_timezone(timezone: Any) -> ZoneInfo:
    if isinstance(timezone, str) and timezone:
        try:
            return ZoneInfo(timezone)
        except (ZoneInfoNotFoundError, ValueError):
            LOGGER.info("subscription_summary.unknown_timezone", timezone=timezone)
            return ZoneInfo("UTC")
    # A missing timezone reads team-local bucket starts as UTC, which for a team east of UTC drops a
    # complete bucket — the one input whose absence produces a wrong trim rather than no trim.
    LOGGER.info("subscription_summary.missing_timezone")
    return ZoneInfo("UTC")


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
            f"median trend={trend} ({len(medians)} points)"
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
    frontend/src/scenes/insights/aggregationAxisFormat.ts. Falls back to plain numeric
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
