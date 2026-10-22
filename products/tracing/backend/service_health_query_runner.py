import datetime as dt
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from posthog.schema import DateRange, IntervalType, PropertyGroupsMode

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.hogql_queries.utils.caller_context import map_in_caller_context
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.tracing.backend.facade.contracts import ServiceHealthParams
from products.tracing.backend.facade.enums import (
    ServiceHealthCompare as Compare,
    ServiceHealthOrderBy as OrderBy,
    ServiceHealthSpanScope,
    ServiceHealthStatus as Status,
)
from products.tracing.backend.logic import TIME_BUCKET_DATE_RANGE_WHERE, fail_fast_scalar_settings

if TYPE_CHECKING:
    from posthog.models import Team

UTC = ZoneInfo("UTC")

SILENT_MIN_BASELINE_REQUESTS = 20
SILENT_GAP = dt.timedelta(minutes=10)
SILENT_MIN_EXPECTED_IN_GAP = 10
COMPARE_MIN_REQUESTS = 100
ERROR_RATE_DELTA_PP = 1.0
ERROR_RATE_RATIO = 2.0
P95_RISE_PCT = 50.0
DEGRADED_ERROR_RATE_PCT = 5.0
DEGRADED_MIN_REQUESTS = 20
MAX_REASON_LENGTH = 80
SERVICE_SCAN_LIMIT = 1000
NEXT_SERVICES_LIMIT = 5

_ENTRY_WHERE = "(is_root_span = 1 OR kind IN (2, 5))"
_ENVIRONMENT = (
    "coalesce(nullIf(resource_attributes['deployment.environment.name'], ''), "
    "nullIf(resource_attributes['deployment.environment'], ''), resource_attributes['env'], '')"
)
_ENVIRONMENT_WHERE = "lower(" + _ENVIRONMENT + ") = {env}"
_STATUS_ORDER = list(Status)
_UNHEALTHY = (Status.REGRESSED, Status.DEGRADED)
_SHIFT = {Compare.PREVIOUS_DAY: dt.timedelta(days=1), Compare.PREVIOUS_WEEK: dt.timedelta(days=7)}
_AGGREGATE_COMPARE_FILTER: dict[str, dict[str, Any]] = {
    Compare.PREVIOUS_PERIOD: {"compare": True},
    Compare.PREVIOUS_DAY: {"compare": True, "compare_to": "-1d"},
    Compare.PREVIOUS_WEEK: {"compare": True, "compare_to": "-7d"},
}
_ORDER_FIELD = {
    OrderBy.ERROR_RATE: "error_rate_pct",
    OrderBy.P95: "p95_ms",
    OrderBy.THROUGHPUT: "requests",
    OrderBy.ERROR_COUNT: "error_count",
}


Window = tuple[dt.datetime, dt.datetime]


@frozen
class ServiceWindowStats:
    requests: int
    errors: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    last_seen: dt.datetime

    @property
    def error_rate_pct(self) -> float:
        return self.errors / self.requests * 100 if self.requests else 0.0


def _iso(value: dt.datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _range(window: Window) -> dict[str, str]:
    return {"date_from": _iso(window[0]), "date_to": _iso(window[1])}


def _ms(value: float) -> str:
    return f"{value / 1000:.1f}s" if value >= 1000 else f"{value:.0f}ms"


def _clip(text: str) -> str:
    return text if len(text) <= MAX_REASON_LENGTH else text[: MAX_REASON_LENGTH - 1] + "…"


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 1)


def _since(value: dt.datetime, reference: dt.datetime) -> str:
    return value.strftime("%H:%MZ" if value.date() == reference.date() else "%Y-%m-%d %H:%MZ")


def _p95_change_pct(current: ServiceWindowStats, baseline: ServiceWindowStats) -> float | None:
    return (current.p95_ms - baseline.p95_ms) / baseline.p95_ms * 100 if baseline.p95_ms else None


def classify_service(
    *,
    current: ServiceWindowStats | None,
    baseline: ServiceWindowStats | None,
    has_baseline: bool,
    window_from: dt.datetime,
    window_to: dt.datetime,
    baseline_minutes: float | None = None,
) -> tuple[Status, str]:
    if current is None or not current.requests:
        quiet_for = window_to - baseline.last_seen if baseline is not None else dt.timedelta(0)
        minutes = baseline_minutes or max((window_to - window_from).total_seconds() / 60, 1.0)
        expected = baseline.requests / minutes * SILENT_GAP.total_seconds() / 60 if baseline is not None else 0.0
        if (
            baseline is not None
            and baseline.requests >= SILENT_MIN_BASELINE_REQUESTS
            and quiet_for >= SILENT_GAP
            and expected >= SILENT_MIN_EXPECTED_IN_GAP
        ):
            since = _since(baseline.last_seen, window_to)
            return Status.SILENT, f"no spans since {since} (baseline {baseline.requests} req)"
        return Status.OK, f"no spans; baseline {baseline.requests if baseline else 0} req is too few to call silent"

    gap = window_to - current.last_seen
    rate = current.requests / max((current.last_seen - window_from).total_seconds() / 60, 1.0)
    if gap >= SILENT_GAP and rate * gap.total_seconds() / 60 >= SILENT_MIN_EXPECTED_IN_GAP:
        return Status.SILENT, f"no spans since {_since(current.last_seen, window_to)} (was {rate:.1f}/min)"
    if has_baseline and (baseline is None or not baseline.requests):
        return Status.NEW, "no spans in baseline window"

    rate_now = current.error_rate_pct
    if baseline is not None and min(current.requests, baseline.requests) >= COMPARE_MIN_REQUESTS:
        rate_before = baseline.error_rate_pct
        p95_change = _p95_change_pct(current, baseline)
        errors_up = rate_now - rate_before >= ERROR_RATE_DELTA_PP and rate_now >= ERROR_RATE_RATIO * rate_before
        parts = [f"error rate {rate_before:.1f}% → {rate_now:.1f}%"] if errors_up else []
        if p95_change is not None and p95_change >= P95_RISE_PCT:
            parts.append(f"p95 {_ms(baseline.p95_ms)} → {_ms(current.p95_ms)} (+{p95_change:.0f}%)")
        if parts:
            return Status.REGRESSED, _clip("; ".join(parts))
        if rate_before - rate_now >= ERROR_RATE_DELTA_PP and rate_before >= ERROR_RATE_RATIO * rate_now:
            return Status.RECOVERED, f"error rate {rate_before:.1f}% → {rate_now:.1f}%"
        if rate_now < DEGRADED_ERROR_RATE_PCT and baseline.p95_ms >= current.p95_ms * (1 + P95_RISE_PCT / 100) > 0:
            return Status.IMPROVED, f"p95 {_ms(baseline.p95_ms)} → {_ms(current.p95_ms)} ({p95_change:.0f}%)"
    if current.requests >= DEGRADED_MIN_REQUESTS and rate_now >= DEGRADED_ERROR_RATE_PCT:
        before = f" (baseline {baseline.error_rate_pct:.1f}%)" if baseline is not None and baseline.requests else ""
        return Status.DEGRADED, f"error rate {rate_now:.1f}%{before}"
    return Status.OK, ""


def aggregate_compare_filter(compare: Compare) -> dict[str, Any] | None:
    return _AGGREGATE_COMPARE_FILTER.get(compare)


class ServiceHealthQueryRunner:
    def __init__(self, *, team: "Team", params: ServiceHealthParams) -> None:
        self.team = team
        self.params = params
        self.modifiers = create_default_modifiers_for_team(team)
        self.modifiers.convertToProjectTimezone = False
        self.modifiers.propertyGroupsMode = PropertyGroupsMode.OPTIMIZED
        self.current = self._resolve(params.date_from, params.date_to)
        self.baseline = self._baseline_window()

    def _resolve(self, date_from: str | None, date_to: str | None) -> Window:
        query_date_range = QueryDateRange(
            date_range=DateRange(date_from=date_from, date_to=date_to, explicitDate=True),
            team=self.team,
            interval=IntervalType.MINUTE,
            now=dt.datetime.now(),
            timezone_info=UTC,
            exact_timerange=True,
        )
        return query_date_range.date_from().astimezone(UTC), query_date_range.date_to().astimezone(UTC)

    def _baseline_window(self) -> Window | None:
        compare, (start, end) = self.params.compare, self.current
        if compare == Compare.NONE:
            return None
        if compare == Compare.CUSTOM:
            return self._resolve(self.params.compare_date_from, self.params.compare_date_to)
        shift = _SHIFT.get(compare, end - start)
        return start - shift, end - shift

    def window(self) -> dict[str, Any]:
        baseline = _range(self.baseline) if self.baseline else None
        return {"current": _range(self.current), "baseline": baseline, "timezone": "UTC"}

    def byte_cap_message(self) -> str:
        seconds = max(int((self.current[1] - self.current[0]).total_seconds() / 2), 1)
        window = (
            f"-{seconds // 3600}h"
            if seconds % 3600 == 0
            else f"-{seconds // 60}m"
            if seconds % 60 == 0
            else f"-{seconds}s"
        )
        baseline = " and a shorter baselineDateRange" if self.params.compare == Compare.CUSTOM else ""
        return (
            f'This query read more than the 10 GB cap. Retry with a shorter dateRange, at most {{"date_from": "{window}"}}{baseline}, '
            "or pass serviceNames to read fewer services."
        )

    def _execute(self, sql: str, window: Window, service_names: list[str], **placeholders: ast.Expr) -> list:
        dates: dict[str, ast.Expr] = {
            "date_from": ast.Constant(value=window[0]),
            "date_to": ast.Constant(value=window[1]),
        }
        where = [
            parse_expr(TIME_BUCKET_DATE_RANGE_WHERE, placeholders=dates),
            parse_expr("timestamp >= {date_from} AND timestamp < {date_to}", placeholders=dates),
        ]
        if self.params.span_scope == ServiceHealthSpanScope.ENTRY:
            where.append(parse_expr(_ENTRY_WHERE))
        if service_names:
            names = ast.Tuple(exprs=[ast.Constant(value=name) for name in service_names])
            where.append(parse_expr("service_name IN {names}", placeholders={"names": names}))
        if self.params.environment:
            environment = ast.Constant(value=self.params.environment.lower())
            where.append(parse_expr(_ENVIRONMENT_WHERE, placeholders={"env": environment}))
        response = execute_hogql_query(
            query_type="TraceSpansServiceHealthQuery",
            query=parse_select(sql, placeholders={"where": ast.And(exprs=where), **placeholders}),
            team=self.team,
            modifiers=self.modifiers,
            workload=Workload.LOGS,
            limit_context=LimitContext.QUERY,
            settings=fail_fast_scalar_settings(),
        )
        return response.results or []

    def _service_stats(self, window: Window) -> dict[str, ServiceWindowStats]:
        rows = self._execute(
            """
            SELECT service_name, count() AS requests, countIf(status_code = 2),
                quantiles(0.5, 0.95, 0.99)(duration_nano), max(timestamp)
            FROM posthog.trace_spans
            WHERE {where}
            GROUP BY service_name
            ORDER BY requests DESC, service_name ASC
            LIMIT {limit}
            """,
            window,
            list(self.params.service_names),
            limit=ast.Constant(value=SERVICE_SCAN_LIMIT + 1),
        )
        return {
            service: ServiceWindowStats(
                requests=requests,
                errors=errors,
                p50_ms=(quantiles[0] or 0) / 1e6,
                p95_ms=(quantiles[1] or 0) / 1e6,
                p99_ms=(quantiles[2] or 0) / 1e6,
                last_seen=last_seen.replace(tzinfo=UTC) if last_seen.tzinfo is None else last_seen,
            )
            for service, requests, errors, quantiles, last_seen in rows
        }

    def _row(
        self, service: str, current: ServiceWindowStats | None, baseline: ServiceWindowStats | None, cut: bool = False
    ) -> dict:
        status, reason = classify_service(
            current=current,
            baseline=baseline,
            has_baseline=self.baseline is not None and not cut,
            window_from=self.current[0],
            window_to=self.current[1],
            baseline_minutes=(self.baseline[1] - self.baseline[0]).total_seconds() / 60 if self.baseline else None,
        )
        live = current if current is not None and current.requests else None
        delta_pp = p95_change = None
        if live is not None and baseline is not None and baseline.requests:
            delta_pp = _round(live.error_rate_pct - baseline.error_rate_pct)
            p95_change = _round(_p95_change_pct(live, baseline))
        last_seen = live.last_seen if live else (baseline.last_seen if baseline else None)
        minutes = max((self.current[1] - self.current[0]).total_seconds() / 60, 1 / 60)
        return {
            "service": service,
            "status": status,
            "reason": reason,
            "requests": live.requests if live else 0,
            "throughput_per_min": round((live.requests if live else 0) / minutes, 1),
            "error_count": live.errors if live else 0,
            "error_rate_pct": _round(live.error_rate_pct) if live else None,
            "error_rate_delta_pp": delta_pp,
            "p50_ms": _round(live.p50_ms) if live else None,
            "p95_ms": _round(live.p95_ms) if live else None,
            "p95_change_pct": p95_change,
            "p99_ms": _round(live.p99_ms) if live else None,
            "baseline_requests": (baseline.requests if baseline else 0) if self.baseline else None,
            "last_seen": _iso(last_seen) if last_seen else None,
        }

    def _next_calls(self, rows: list[dict]) -> list[dict[str, Any]]:
        unhealthy = [row for row in rows if row["status"] in _UNHEALTHY]
        if self.params.environment or not unhealthy:
            return []
        names = [row["service"] for row in unhealthy[:NEXT_SERVICES_LIMIT]]
        query: dict[str, Any] = {"dateRange": _range(self.current), "serviceNames": names, "limit": 20}
        if compare_filter := aggregate_compare_filter(self.params.compare):
            query["compareFilter"] = compare_filter
        calls = [{"tool": "apm-spans-aggregate", "why": _clip(f"operations behind {', '.join(names)}"), "query": query}]
        worst = next((row for row in unhealthy if row["error_count"]), None)
        if worst:
            query = {"dateRange": _range(self.current), "serviceNames": [worst["service"]], "statusCodes": [2]}
            query = {**query, "flatSpans": True, "rootSpans": False, "limit": 10, "excludeAttributes": True}
            calls.append(
                {"tool": "query-apm-spans", "why": _clip(f"recent error spans in {worst['service']}"), "query": query}
            )
        return calls

    def _notes(self, rows: list[dict], scan_truncated: bool) -> list[str]:
        notes = {
            "No baseline: set compare to get new, regressed, recovered and improved statuses.": self.baseline is None,
            f"Only the {SERVICE_SCAN_LIMIT} busiest services were scored. Pass serviceNames for others.": scan_truncated,
            "No spans matched. spanScope=all also counts internal and client spans. The environment filter reads "
            "deployment.environment.name, deployment.environment, then env.": not rows,
        }
        return [note for note, applies in notes.items() if applies]

    def run(self) -> dict[str, Any]:
        windows = [self.current] if self.baseline is None else [self.current, self.baseline]
        stats = map_in_caller_context(self._service_stats, windows, thread_name_prefix="tracing_service_health")
        current, baseline = stats[0], stats[1] if len(stats) > 1 else {}
        current_cut, baseline_cut = len(current) > SERVICE_SCAN_LIMIT, len(baseline) > SERVICE_SCAN_LIMIT
        names = [*current, *([] if current_cut else sorted(set(baseline) - set(current)))]
        rows = [
            self._row(name, current.get(name), baseline.get(name), baseline_cut and name not in baseline)
            for name in names
        ]

        rows.sort(
            key=lambda row: (
                _STATUS_ORDER.index(row["status"]),
                -row["requests"],
                -(row["baseline_requests"] or 0),
                row["service"],
            )
        )
        field = _ORDER_FIELD.get(self.params.order_by)
        ordered = sorted(rows, key=lambda row: (row[field] is None, -(row[field] or 0))) if field else rows
        page = ordered[: self.params.limit]
        scan_truncated = max(len(current), len(baseline)) > SERVICE_SCAN_LIMIT
        result: dict[str, Any] = {
            "window": self.window(),
            "summary": {
                "services": len(rows),
                "requests": sum(row["requests"] for row in rows),
                **{status.value: sum(row["status"] == status for row in rows) for status in Status},
            },
            "services": page,
            "next": self._next_calls(rows),
            "truncated": len(rows) > self.params.limit or scan_truncated,
            "notes": self._notes(rows, scan_truncated),
        }
        return result


def run_service_health_query(*, team: "Team", params: ServiceHealthParams) -> dict[str, Any]:
    return ServiceHealthQueryRunner(team=team, params=params).run()


def service_health_byte_cap_message(*, team: "Team", params: ServiceHealthParams) -> str:
    return ServiceHealthQueryRunner(team=team, params=params).byte_cap_message()
