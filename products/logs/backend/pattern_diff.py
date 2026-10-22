import datetime as dt
from collections.abc import Callable
from typing import TYPE_CHECKING

from posthog.schema import DateRange, LogsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.errors import CHQueryErrorTooManyBytes
from posthog.exceptions import ClickHouseQueryTimeOut
from posthog.hogql_queries.query_runner import ExecutionMode

from products.logs.backend.agent_window import utc_iso, window_echo
from products.logs.backend.log_patterns import ERROR_SEVERITIES, _env, pattern_fingerprint
from products.logs.backend.logs_query_runner import fail_fast_aggregate_settings
from products.logs.backend.patterns_query_runner import PatternsQueryRunner

if TYPE_CHECKING:
    from posthog.models import Team, User

_BASELINE_OFFSET = dt.timedelta(days=7)
FIRST_SEEN_LOOKBACK = dt.timedelta(days=14)
_FIRST_SEEN_MAX_MEMBERS = 5000


def _rate(estimated_count: float, window: tuple[dt.datetime, dt.datetime]) -> float:
    seconds = (window[1] - window[0]).total_seconds()
    return estimated_count / seconds if seconds > 0 else 0.0


def _has_error_severity(pattern: dict) -> bool:
    return any(severity in ERROR_SEVERITIES for severity in pattern.get("severity_counts", {}))


def _fingerprint_key(pattern: dict) -> str:
    return pattern_fingerprint(pattern["pattern"])


def _group_by_key(patterns: list[dict], key: Callable[[dict], str]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for pattern in patterns:
        grouped.setdefault(key(pattern), []).append(pattern)
    return grouped


def stored_pattern_keys(current: list[dict], baseline: list[dict]) -> Callable[[dict], str]:
    parent: dict[str, str] = {}

    def find(member: str) -> str:
        while parent.setdefault(member, member) != member:
            parent[member] = parent[parent[member]]
            member = parent[member]
        return member

    for group in (*current, *baseline):
        roots = {find(member) for member in group["match_patterns"]}
        root = min(roots)
        for other in roots:
            parent[other] = root

    def key(pattern: dict) -> str:
        return find(pattern["match_patterns"][0])

    return key


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
    key: Callable[[dict], str] = _fingerprint_key,
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
    if shift_ratio <= 1:
        # A ratio at or below 1 is meaningless (everything or nothing shifts) and 0 would
        # divide by zero below — treat a misconfigured env var as the default.
        shift_ratio = 2.0

    current_groups = _group_by_key(current, key)
    baseline_groups = _group_by_key(baseline, key)

    def above_floor(share: float, group: list[dict]) -> bool:
        # Error severity is checked across every template in the group, not just the
        # representative: within-run fingerprint collision can bury a genuinely new
        # error-severity template behind a larger non-error one.
        return share >= new_min_share or any(_has_error_severity(p) for p in group)

    entries = []
    for fingerprint, group in current_groups.items():
        pattern = _representative(group)
        raw_count, estimated_count, share = _group_totals(group)
        baseline_group = baseline_groups.get(fingerprint)

        if baseline_group is None:
            entries.append(_entry("new" if above_floor(share, group) else "unchanged", pattern))
            continue

        base_raw, base_estimated, base_share = _group_totals(baseline_group)
        baseline_rate = _rate(base_estimated, baseline_window)
        current_rate = _rate(estimated_count, current_window)
        ratio = round(current_rate / baseline_rate, 2) if baseline_rate > 0 else None
        shifted = (
            ratio is not None
            and (ratio >= shift_ratio or ratio <= 1 / shift_ratio)
            and min(raw_count, base_raw) >= min_samples
        )
        entries.append(
            _entry(
                "rate_shift" if shifted else "unchanged",
                pattern,
                baseline_estimated=base_estimated,
                baseline_share=base_share,
                rate_ratio=ratio,
            )
        )

    for fingerprint, group in baseline_groups.items():
        if fingerprint in current_groups:
            continue
        pattern = _representative(group)
        _raw, base_estimated, base_share = _group_totals(group)
        if above_floor(base_share, group):
            entries.append(_entry("gone", pattern, baseline_estimated=base_estimated, baseline_share=base_share))

    order = {"new": 0, "rate_shift": 1, "gone": 2, "unchanged": 3}

    def magnitude(entry: dict) -> float:
        ratio = entry["rate_ratio"]
        if entry["classification"] == "rate_shift" and ratio is not None:
            # A ratio rounded down to 0.0 is the most extreme drop we can express, not "no shift".
            return max(ratio, 1 / ratio) if ratio > 0 else float("inf")
        return float(entry["pattern"]["estimated_count"])

    entries.sort(key=lambda e: (order[e["classification"]], -magnitude(e), e["pattern"]["pattern"]))
    return entries


def _entry(
    classification: str,
    pattern: dict,
    *,
    baseline_estimated: int | None = None,
    baseline_share: float | None = None,
    rate_ratio: float | None = None,
) -> dict:
    return {
        "classification": classification,
        "rate_ratio": rate_ratio,
        "pattern": pattern,
        "baseline_estimated_count": baseline_estimated,
        "baseline_volume_share_pct": baseline_share,
    }


def run_patterns_diff(
    team: "Team",
    query: LogsQuery,
    baseline_date_range: DateRange | None,
    *,
    user: "User | None" = None,
    limit: int | None = None,
) -> dict:
    """Mine the query's window and a baseline window, and return classified diff entries.

    The baseline defaults to the same window shifted back one week — log streams have strong
    daily/weekly cycles, so last week's identical window is a fairer expectation than the
    preceding hour. The current window is resolved once and the baseline derived from the
    resolved bounds, so a relative ``date_from`` (e.g. ``-1h``) can't drift between the two runs.
    """
    current_runner = PatternsQueryRunner(team=team, query=query, user=user)
    current_from = current_runner.query_date_range.date_from()
    current_to = current_runner.query_date_range.date_to()

    if baseline_date_range is None:
        baseline_date_range = DateRange(
            date_from=(current_from - _BASELINE_OFFSET).isoformat(),
            date_to=(current_to - _BASELINE_OFFSET).isoformat(),
        )
    baseline_query = query.model_copy(update={"dateRange": baseline_date_range})
    baseline_runner = PatternsQueryRunner(team=team, query=baseline_query, user=user)
    baseline_from = baseline_runner.query_date_range.date_from()
    baseline_to = baseline_runner.query_date_range.date_to()

    versions = {runner.stored_version() for runner in (current_runner, baseline_runner)}
    version = versions.pop() if len(versions) == 1 else None
    if version is None:
        current_runner.use_stored_patterns = baseline_runner.use_stored_patterns = False
    results = [
        runner.run(ExecutionMode.CALCULATE_BLOCKING_ALWAYS).results for runner in (current_runner, baseline_runner)
    ]
    current_results, baseline_results = results

    entries = diff_patterns(
        current_results["patterns"],
        baseline_results["patterns"],
        current_window=(current_from, current_to),
        baseline_window=(baseline_from, baseline_to),
        key=stored_pattern_keys(current_results["patterns"], baseline_results["patterns"])
        if version
        else _fingerprint_key,
    )
    truncated = limit is not None and len(entries) > limit
    entries = entries[:limit]
    first_seen = _first_seen_ever(team, query, entries, version, current_to) if version else {}
    history_failed = first_seen is None
    first_seen = first_seen or {}
    for entry in entries:
        pattern = entry["pattern"]
        seen = [first_seen[member] for member in pattern.get("match_patterns") or [] if member in first_seen]
        entry.update(
            masked_example=pattern["pattern"],
            services=pattern.get("services") or [],
            first_seen_ever=utc_iso(min(seen)) if seen else None,
        )

    notes = [
        "first_seen_ever reads the pattern rollup up to 14 days back, filtered by serviceNames and severityLevels only."
        if version
        else "Body mining fallback: counts are sample estimates and first_seen_ever is null."
    ]
    if history_failed:
        notes.append("The first_seen_ever lookup hit its read budget, so first_seen_ever is null.")
    if baseline_results["total_count"] == 0:
        notes.append("The baseline window has no matching logs, so every pattern reads as new.")

    return {
        "window": window_echo((current_from, current_to), (baseline_from, baseline_to)),
        "source": "stored_patterns" if version else "body_mining",
        "pattern_version": version,
        "sampled": not version,
        "truncated": truncated,
        "entries": entries,
        "current": _window_meta(current_results, current_from, current_to),
        "baseline": _window_meta(baseline_results, baseline_from, baseline_to),
        "notes": notes,
        "next": [
            call
            for entry in entries
            if entry["classification"] in ("new", "rate_shift")
            and (call := _raw_lines_call(entry, query, current_from, current_to)) is not None
        ][:3],
    }


def _first_seen_ever(
    team: "Team", query: LogsQuery, entries: list[dict], version: int, current_to: dt.datetime
) -> dict[str, dt.datetime] | None:
    members = list(dict.fromkeys(member for entry in entries for member in entry["pattern"]["match_patterns"]))
    members = members[:_FIRST_SEEN_MAX_MEMBERS] or [""]
    where = "pattern_version = {version} AND pattern IN {members} AND time_bucket >= {date_from} AND time_bucket < {date_to}"
    if query.serviceNames:
        where += " AND service_name IN {services}"
    if query.severityLevels:
        where += " AND severity_text IN {severities}"
    placeholders: dict[str, ast.Expr] = {
        "version": ast.Constant(value=version),
        "members": ast.Constant(value=members),
        "date_from": ast.Constant(value=current_to - FIRST_SEEN_LOOKBACK),
        "date_to": ast.Constant(value=current_to),
        "services": ast.Constant(value=list(query.serviceNames or [])),
        "severities": ast.Constant(value=[str(level) for level in query.severityLevels or []]),
    }
    select = parse_select(
        "SELECT pattern, min(time_bucket) FROM posthog.logs_pattern_buckets WHERE {where} GROUP BY pattern LIMIT {limit}",
        placeholders={"where": parse_expr(where, placeholders=placeholders), "limit": ast.Constant(value=len(members))},
    )
    try:
        response = execute_hogql_query(
            query_type="LogsPatternsFirstSeen",
            query=select,
            team=team,
            workload=Workload.LOGS,
            settings=fail_fast_aggregate_settings(),
        )
    except (CHQueryErrorTooManyBytes, ClickHouseQueryTimeOut):
        return None
    return {row[0]: row[1] for row in response.results}


def _raw_lines_call(entry: dict, query: LogsQuery, date_from: dt.datetime, date_to: dt.datetime) -> dict | None:
    pattern = entry["pattern"]
    regex = pattern.get("match_regex")
    if not pattern.get("pattern_version") and not regex and not pattern.get("match_literal"):
        return None
    scope = [
        prop.model_dump(exclude_none=True)
        for group in (query.filterGroup.values if query.filterGroup else [])
        for prop in getattr(group, "values", [])
    ]
    pivot = (
        [
            {"key": "pattern", "value": pattern["match_patterns"], "operator": "exact", "type": "log"},
            {"key": "pattern_version", "value": pattern["pattern_version"], "operator": "exact", "type": "log"},
        ]
        if pattern.get("pattern_version")
        else [
            {
                "key": "message",
                "value": regex or pattern["match_literal"],
                "operator": "regex" if regex else "icontains",
                "type": "log",
            }
        ]
    )
    scoped = {
        name: value
        for name, value in (
            ("severityLevels", [str(level) for level in query.severityLevels or []]),
            ("searchTerm", query.searchTerm),
            ("personId", query.personId),
            ("sessionId", query.sessionId),
        )
        if value
    }
    return {
        "tool": "query-logs",
        "why": f"raw lines for {entry['classification']} pattern {entry['masked_example'][:60]}",
        "query": {
            "dateRange": {"date_from": utc_iso(date_from), "date_to": utc_iso(date_to)},
            "serviceNames": entry["services"] or list(query.serviceNames or []),
            **scoped,
            "filterGroup": scope + pivot,
            "limit": 20,
        },
    }


def _window_meta(results: dict, date_from: dt.datetime, date_to: dt.datetime) -> dict:
    return {
        "source": results.get("source"),
        "pattern_version": results.get("pattern_version"),
        "fallback_reason": results.get("fallback_reason"),
        "scanned_count": results["scanned_count"],
        "total_count": results["total_count"],
        "sampled": results["sampled"],
        "sample_coverage_pct": results["sample_coverage_pct"],
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
    }
