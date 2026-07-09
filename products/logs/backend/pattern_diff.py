import datetime as dt
from typing import TYPE_CHECKING

from posthog.schema import DateRange, LogsQuery

from posthog.hogql_queries.query_runner import ExecutionMode

from products.logs.backend.log_patterns import _ERROR_SEVERITIES, _PLACEHOLDER_RE, _env
from products.logs.backend.patterns_query_runner import PatternsQueryRunner

if TYPE_CHECKING:
    from posthog.models import Team

_BASELINE_OFFSET = dt.timedelta(days=7)


def pattern_fingerprint(template: str) -> str:
    """Cross-run identity key for a mined template.

    Drain templates are not stable across independent mining runs — sampling and row-order
    differences can widen a placeholder ("User <*> not found" vs "User <*> not <*>"), so
    matching on the raw template string would false-split the same message across windows.
    Keying on the sorted set of literal runs between placeholders survives that wobble:
    placeholder kind and position drop out, literal content remains.
    """
    literals = sorted({literal.strip() for literal in _PLACEHOLDER_RE.split(template) if literal.strip()})
    return "\x00".join(literals) if literals else template


def _rate(estimated_count: float, window: tuple[dt.datetime, dt.datetime]) -> float:
    seconds = (window[1] - window[0]).total_seconds()
    return estimated_count / seconds if seconds > 0 else 0.0


def _has_error_severity(pattern: dict) -> bool:
    return any(severity in _ERROR_SEVERITIES for severity in pattern.get("severity_counts", {}))


def _group_by_fingerprint(patterns: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for pattern in patterns:
        grouped.setdefault(pattern_fingerprint(pattern["pattern"]), []).append(pattern)
    return grouped


def _representative(group: list[dict]) -> dict:
    return max(group, key=lambda p: p["estimated_count"])


def _group_totals(group: list[dict]) -> tuple[int, int, float]:
    # (raw sample count, estimated count, volume share) summed across templates that share a
    # fingerprint — template wobble can split one message across clusters within a single run too.
    return (
        sum(p["count"] for p in group),
        sum(p["estimated_count"] for p in group),
        round(sum(p["volume_share_pct"] for p in group), 2),
    )


def diff_patterns(
    current: list[dict],
    baseline: list[dict],
    *,
    current_window: tuple[dt.datetime, dt.datetime],
    baseline_window: tuple[dt.datetime, dt.datetime],
) -> list[dict]:
    """Classify serialized mined patterns from a current window against a baseline window.

    Classifications:
    * ``new`` — in current only, above the novelty floor (volume share, or any error/fatal line).
      Sampled mining cannot see arbitrarily rare templates, so below the floor absence from the
      baseline is not evidence of novelty and the entry stays ``unchanged``.
    * ``rate_shift`` — on both sides with the window-length-normalized rate changed by at least
      the shift ratio, and enough raw samples on both sides to trust the estimates.
    * ``gone`` — in baseline only, above the same floor. Below-floor disappearances are dropped
      entirely (nothing useful to show).
    * ``unchanged`` — everything else; "no confident claim", not "provably identical".
    """
    new_min_share = _env("LOGS_PATTERNS_DIFF_NEW_MIN_SHARE", 1.0, float)
    shift_ratio = _env("LOGS_PATTERNS_DIFF_SHIFT_RATIO", 2.0, float)
    min_samples = _env("LOGS_PATTERNS_DIFF_MIN_SAMPLES", 5, int)

    current_groups = _group_by_fingerprint(current)
    baseline_groups = _group_by_fingerprint(baseline)

    entries = []
    for fingerprint, group in current_groups.items():
        pattern = _representative(group)
        raw_count, estimated_count, share = _group_totals(group)
        baseline_group = baseline_groups.get(fingerprint)

        if baseline_group is None:
            above_floor = share >= new_min_share or _has_error_severity(pattern)
            entries.append(_entry("new" if above_floor else "unchanged", pattern, None))
            continue

        base_raw, base_estimated, _base_share = _group_totals(baseline_group)
        baseline_rate = _rate(base_estimated, baseline_window)
        current_rate = _rate(estimated_count, current_window)
        ratio = round(current_rate / baseline_rate, 2) if baseline_rate > 0 else None
        shifted = (
            ratio is not None
            and (ratio >= shift_ratio or ratio <= 1 / shift_ratio)
            and min(raw_count, base_raw) >= min_samples
        )
        entries.append(_entry("rate_shift" if shifted else "unchanged", pattern, baseline_group, rate_ratio=ratio))

    for fingerprint, group in baseline_groups.items():
        if fingerprint in current_groups:
            continue
        pattern = _representative(group)
        _raw, _estimated, share = _group_totals(group)
        if share >= new_min_share or _has_error_severity(pattern):
            entries.append(_entry("gone", pattern, group))

    order = {"new": 0, "rate_shift": 1, "gone": 2, "unchanged": 3}

    def magnitude(entry: dict) -> float:
        ratio = entry["rate_ratio"]
        if entry["classification"] == "rate_shift" and ratio:
            return max(ratio, 1 / ratio)
        return float(entry["pattern"]["estimated_count"])

    entries.sort(key=lambda e: (order[e["classification"]], -magnitude(e), e["pattern"]["pattern"]))
    return entries


def _entry(
    classification: str,
    pattern: dict,
    baseline_group: list[dict] | None,
    *,
    rate_ratio: float | None = None,
) -> dict:
    baseline_estimated: int | None = None
    baseline_share: float | None = None
    if baseline_group is not None:
        _raw, baseline_estimated, baseline_share = _group_totals(baseline_group)
    return {
        "classification": classification,
        "rate_ratio": rate_ratio,
        "pattern": pattern,
        "baseline_estimated_count": baseline_estimated,
        "baseline_volume_share_pct": baseline_share,
    }


def run_patterns_diff(team: "Team", query: LogsQuery, baseline_date_range: DateRange | None) -> dict:
    """Mine the query's window and a baseline window, and return classified diff entries.

    The baseline defaults to the same window shifted back one week — log streams have strong
    daily/weekly cycles, so last week's identical window is a fairer expectation than the
    preceding hour. The current window is resolved once and the baseline derived from the
    resolved bounds, so a relative ``date_from`` (e.g. ``-1h``) can't drift between the two runs.
    """
    current_runner = PatternsQueryRunner(team=team, query=query)
    current_from = current_runner.query_date_range.date_from()
    current_to = current_runner.query_date_range.date_to()

    if baseline_date_range is None:
        baseline_date_range = DateRange(
            date_from=(current_from - _BASELINE_OFFSET).isoformat(),
            date_to=(current_to - _BASELINE_OFFSET).isoformat(),
        )
    baseline_query = query.model_copy(update={"dateRange": baseline_date_range})
    baseline_runner = PatternsQueryRunner(team=team, query=baseline_query)
    baseline_from = baseline_runner.query_date_range.date_from()
    baseline_to = baseline_runner.query_date_range.date_to()

    current_results = current_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS).results
    baseline_results = baseline_runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS).results

    entries = diff_patterns(
        current_results["patterns"],
        baseline_results["patterns"],
        current_window=(current_from, current_to),
        baseline_window=(baseline_from, baseline_to),
    )
    return {
        "entries": entries,
        "current": _window_meta(current_results, current_from, current_to),
        "baseline": _window_meta(baseline_results, baseline_from, baseline_to),
    }


def _window_meta(results: dict, date_from: dt.datetime, date_to: dt.datetime) -> dict:
    return {
        "scanned_count": results["scanned_count"],
        "total_count": results["total_count"],
        "sampled": results["sampled"],
        "sample_coverage_pct": results["sample_coverage_pct"],
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }
