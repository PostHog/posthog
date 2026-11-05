import datetime as dt
from collections.abc import Sequence
from functools import cached_property
from typing import Any

import re2

from posthog.schema import CachedLogsQueryResponse, DateRange, LogsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.dataclasses import frozen
from posthog.enums import LabeledStrEnum
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.caller_context import map_in_caller_context

from products.logs.backend.agent_window import utc_iso, window_echo
from products.logs.backend.compare_windows import baseline_bounds
from products.logs.backend.environment_filter import environment_filter_expr, rollup_environment_filter_expr
from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin, ilike_pattern
from products.logs.backend.models import LogsExclusionRule

# Three-valued logic for evaluating a rule's filter_group against a partial record
# at query time. We only know the row's `service_name`; everything else (severity,
# attributes) varies per log line. A leaf returning INDETERMINATE means we can't
# decide without seeing the full row, so the answer at the group level depends on
# how children combine: AND × INDETERMINATE → INDETERMINATE, OR × INDETERMINATE
# → INDETERMINATE (unless another child resolves it). The Services page treats
# INDETERMINATE as "rule might apply, show it" and only excludes when the result
# is provably FALSE — i.e. the rule cannot match any row from this service.
_FALSE, _INDETERMINATE, _TRUE = -1, 0, 1
_SERVICE_NAME_KEYS = {"service_name", "service.name"}


def rule_could_apply_to_service(filter_group: Any, service_name: str) -> bool:
    """
    Return True iff the rule's `config.filter_group` could match some log line
    with this `service_name`. Returns True for an absent/empty filter_group
    (no scoping → applies to everything). Returns False only when the filter
    group provably cannot match — e.g. an `AND` containing
    `service.name exact "other"` against `service_name == "api"`.

    Operates on three-valued logic so non-service-name predicates (severity,
    arbitrary attributes) remain INDETERMINATE and conservatively keep the rule
    visible in the Services tab. The Node ingestion worker remains the source
    of truth for per-record drop decisions; this helper only filters the
    display list of "rules active on each service".
    """
    if filter_group is None or not isinstance(filter_group, dict):
        return True
    return _evaluate_node(filter_group, service_name) != _FALSE


def _evaluate_node(node: Any, service_name: str) -> int:
    if not isinstance(node, dict):
        return _INDETERMINATE
    if _is_group(node):
        children = node.get("values") or []
        if not children:
            # Empty group: conservative — keep the rule visible (mirrors the
            # ingestion worker's "empty group → no match → don't drop" logic;
            # for display, "might apply" is the safer default).
            return _INDETERMINATE
        results = [_evaluate_node(child, service_name) for child in children]
        if str(node.get("type", "")).upper() == "OR":
            if _TRUE in results:
                return _TRUE
            if _INDETERMINATE in results:
                return _INDETERMINATE
            return _FALSE
        # AND (default for any unrecognised operator).
        if _FALSE in results:
            return _FALSE
        if _INDETERMINATE in results:
            return _INDETERMINATE
        return _TRUE
    # Property-filter leaf.
    key = str(node.get("key") or "").lower()
    if key not in _SERVICE_NAME_KEYS:
        # Any other key depends on per-row data we don't have at services-tab time.
        return _INDETERMINATE
    return _evaluate_service_leaf(node, service_name)


def _is_group(node: dict) -> bool:
    type_ = str(node.get("type", "")).upper()
    return type_ in ("AND", "OR") and isinstance(node.get("values"), list)


def _evaluate_service_leaf(leaf: dict, service_name: str) -> int:
    operator = str(leaf.get("operator") or "exact").lower()
    value = leaf.get("value")
    sn = service_name or ""

    if operator == "is_set":
        return _TRUE if sn else _FALSE
    if operator == "is_not_set":
        return _TRUE if not sn else _FALSE
    # Every remaining operator requires both an override and a filter value.

    if value is None:
        return _INDETERMINATE
    if not sn:
        # For negation operators, empty string doesn't match non-empty values
        if operator in ("is_not", "not_in", "not_icontains", "not_starts_with", "not_ends_with", "not_regex"):
            return _TRUE
        # For positive match operators, empty string can't match
        return _FALSE

    if operator in ("exact", "in"):
        return _TRUE if _matches_any(value, sn) else _FALSE
    if operator in ("is_not", "not_in"):
        return _FALSE if _matches_any(value, sn) else _TRUE
    if operator == "icontains":
        return _TRUE if str(value).lower() in sn.lower() else _FALSE
    if operator == "not_icontains":
        return _FALSE if str(value).lower() in sn.lower() else _TRUE
    if operator == "starts_with":
        return _TRUE if sn.lower().startswith(str(value).lower()) else _FALSE
    if operator == "not_starts_with":
        return _FALSE if sn.lower().startswith(str(value).lower()) else _TRUE
    if operator == "ends_with":
        return _TRUE if sn.lower().endswith(str(value).lower()) else _FALSE
    if operator == "not_ends_with":
        return _FALSE if sn.lower().endswith(str(value).lower()) else _TRUE
    if operator in ("regex", "not_regex"):
        # RE2 (linear-time, no catastrophic backtracking) — same engine the Node
        # ingestion worker uses via `tracked-re2`. A project member can pick the
        # regex operator on the drop-rule form, so a pathological pattern run
        # through Python's backtracking `re` engine here would be a ReDoS vector
        # on every Services-tab request.
        try:
            # `(?is)` inline flags = case-insensitive + DOTALL, matching the worker's
            # `re.IGNORECASE | re.DOTALL` and `compileLeafRegex`'s `is` flags.
            matched = re2.compile(f"(?is){str(value)}").search(sn) is not None
        except re2.error:
            # Invalid regex: for `regex` it can never match → FALSE.
            # For `not_regex` it trivially never matches → the "not" condition is
            # always satisfied → INDETERMINATE (shown on every service row), which
            # is the conservative choice and consistent with the PR's invariant that
            # only a provably-FALSE result hides the rule.
            return _FALSE if operator == "regex" else _INDETERMINATE
        if operator == "regex":
            return _TRUE if matched else _FALSE
        return _FALSE if matched else _TRUE
    # Numeric / semver / date operators don't apply to service_name strings —
    # unknown for our purposes, so be conservative and keep the rule visible.
    return _INDETERMINATE


def _matches_any(value: Any, sn: str) -> bool:
    sn_lower = sn.lower()
    if isinstance(value, list):
        return any(str(v).lower() == sn_lower for v in value)
    return str(value).lower() == sn_lower


def _sampling_rule_summary(rule: LogsExclusionRule) -> str:
    if rule.rule_type == LogsExclusionRule.RuleType.PATH_DROP:
        patterns = (rule.config or {}).get("patterns") or []
        key = (rule.config or {}).get("match_attribute_key")
        if key:
            return f"Drop rule on `{key}` ({len(patterns)} pattern(s))"
        return f"Drop rule ({len(patterns)} pattern(s))"
    if rule.rule_type == LogsExclusionRule.RuleType.SEVERITY_SAMPLING:
        return "Drop by severity rule"
    if rule.rule_type == LogsExclusionRule.RuleType.RATE_LIMIT:
        return "Rate limit (planned)"
    return str(rule.rule_type)


# Response caps. SERVICES_LIMIT bounds the per-request payload against
# user-controlled service_name cardinality (a misconfigured SDK can emit a
# unique name per pod or instance). Names beyond the cap stay reachable via
# serviceNameSearch, which filters before aggregation.
# The LIMIT applies after the GROUP BY, so raising it costs response bytes rather
# than query time. The aggregation reads the same window either way.
SERVICES_LIMIT = 10000
# Sparklines are fetched per displayed page: the bucket grid is
# time × service and the sparkline query's row LIMIT would silently drop the
# most recent buckets if scoped to all SERVICES_LIMIT names at once.
SPARKLINE_SERVICES_LIMIT = 25

MIN_LOGS_FOR_RATE = 100
DEGRADED_ERROR_RATE_PCT = 5.0
CHANGE_MIN_DELTA_PP = 1.0
CHANGE_MIN_RATIO = 2.0
SILENT_MIN_BASELINE_LOGS = 10


class LogsCompareMode(LabeledStrEnum):
    NONE = "none", "No baseline"
    PREVIOUS_PERIOD = "previous_period", "Previous period"
    PREVIOUS_DAY = "previous_day", "Same window a day earlier"
    PREVIOUS_WEEK = "previous_week", "Same window a week earlier"


COMPARE_MODES = LogsCompareMode.values


class LogsServiceStatus(LabeledStrEnum):
    OK = "ok", "OK"
    DEGRADED = "degraded", "Error rate 5% or more"
    REGRESSED = "regressed", "Error rate worse than the baseline"
    IMPROVED = "improved", "Error rate better than the baseline"
    RECOVERED = "recovered", "No longer degraded"
    NEW = "new", "No logs in the baseline"
    SILENT = "silent", "Logs stopped"


class LogsServicesSource(LabeledStrEnum):
    ROLLUP = "rollup"
    ROLLUP_RAW = "rollup+raw"
    RAW = "raw"


SERVICE_STATUSES = LogsServiceStatus.values
ROLLUP_BUCKET_SECONDS = 300
ROLLUP_RETENTION = dt.timedelta(days=42)

_COUNT_COLUMNS = ("log_count", "error_count", "debug", "info", "warn")
_NO_LOGS: dict = {**dict.fromkeys(_COUNT_COLUMNS, 0), "last_seen": None}


def _error_rate_pct(counts: dict | None) -> float:
    return 100.0 * counts["error_count"] / counts["log_count"] if counts and counts["log_count"] else 0.0


@frozen
class ServiceVerdict:
    status: str
    reason: str


@frozen
class _WindowCounts:
    counts: dict[str, dict]
    total_services: int
    source: str


def classify_service(current: dict | None, baseline: dict | None, compared: bool) -> ServiceVerdict:
    log_count = current["log_count"] if current else 0
    rate = _error_rate_pct(current)
    base_count = baseline["log_count"] if baseline else 0
    if compared and not base_count:
        return ServiceVerdict(status="new", reason=f"no logs in baseline, {log_count} now")
    if compared and not log_count:
        return ServiceVerdict(status="silent", reason=f"no logs in window (baseline {base_count})")
    if compared and min(log_count, base_count) >= MIN_LOGS_FOR_RATE:
        base_rate = _error_rate_pct(baseline)
        change = f"error rate {base_rate:.1f}% → {rate:.1f}%"
        if rate - base_rate >= CHANGE_MIN_DELTA_PP and rate >= CHANGE_MIN_RATIO * base_rate:
            return ServiceVerdict(status="regressed", reason=change)
        if base_rate - rate >= CHANGE_MIN_DELTA_PP and base_rate >= CHANGE_MIN_RATIO * rate:
            return ServiceVerdict(
                status="recovered" if base_rate >= DEGRADED_ERROR_RATE_PCT > rate else "improved", reason=change
            )
    if log_count >= MIN_LOGS_FOR_RATE and rate >= DEGRADED_ERROR_RATE_PCT:
        return ServiceVerdict(status="degraded", reason=f"error rate {rate:.1f}%")
    return ServiceVerdict(status="ok", reason=f"error rate {rate:.1f}%")


def _floor_to_bucket(value: dt.datetime) -> dt.datetime:
    seconds = int(value.timestamp()) // ROLLUP_BUCKET_SECONDS * ROLLUP_BUCKET_SECONDS
    return dt.datetime.fromtimestamp(seconds, tz=dt.UTC)


def _counts_by_service(rows: list) -> tuple[dict[str, dict], int]:
    counts = {
        row[0]: {**dict(zip(_COUNT_COLUMNS, (int(v) for v in row[1:6]))), "last_seen": row[7].replace(tzinfo=dt.UTC)}
        for row in rows
    }
    return counts, int(rows[0][6]) if rows else 0


class ServicesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def __init__(
        self,
        *args: Any,
        service_name_search: str | None = None,
        environment: str | None = None,
        compare: str = "none",
        baseline_date_range: DateRange | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self.service_name_search = service_name_search.strip() if service_name_search else None
        self.environment = environment.strip() if environment and environment.strip() else None
        self.compare = compare
        self.baseline_date_range = baseline_date_range
        self._pristine_scope = self._scope()

    def get_cache_payload(self) -> dict[str, Any]:
        return {
            **super().get_cache_payload(),
            "service_name_search": self.service_name_search,
            "environment": self.environment,
            "compare": self.compare,
            "baseline_date_range": self.baseline_date_range.model_dump() if self.baseline_date_range else None,
        }

    @cached_property
    def _baseline_runner(self) -> "ServicesQueryRunner | None":
        date_range = self.baseline_date_range
        if date_range is None:
            bounds = baseline_bounds(self.compare, self.query_date_range.date_from(), self.query_date_range.date_to())
            if bounds is None:
                return None
            date_range = DateRange(
                date_from=bounds.date_from.isoformat(), date_to=bounds.date_to.isoformat(), explicitDate=True
            )
        return ServicesQueryRunner(
            team=self.team,
            query=self.query.model_copy(deep=True, update={"dateRange": date_range}),
            service_name_search=self.service_name_search,
            environment=self.environment,
            limit_context=self.limit_context,
            modifiers=self.modifiers,
        )

    def _execute(self, query: ast.SelectQuery) -> list:
        return execute_hogql_query(
            query_type="LogsQuery",
            query=query,
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            filters=self.query_date_range.to_hogql_filters(),
            settings=self.settings,
        ).results

    def _use_rollup(self) -> bool:
        query = self.query
        groups = query.filterGroup.values if query.filterGroup else []
        if any(getattr(group, "values", None) for group in groups) or query.searchTerm or query.resourceFingerprint:
            return False
        if query.personId is not None or query.sessionId is not None:
            return False
        return self.query_date_range.date_from() >= dt.datetime.now(dt.UTC) - ROLLUP_RETENTION

    def _window_counts(self) -> _WindowCounts:
        date_from, date_to = self.query_date_range.date_from(), self.query_date_range.date_to()
        start = _floor_to_bucket(date_from)
        start = start if start == date_from else start + dt.timedelta(seconds=ROLLUP_BUCKET_SECONDS)
        end = _floor_to_bucket(date_to)
        if start >= end or not self._use_rollup():
            counts, total = _counts_by_service(self._execute(self._aggregates_query()))
            return _WindowCounts(counts=counts, total_services=total, source="raw")
        counts, total = _counts_by_service(self._execute(self._rollup_query(start, end)))
        edges = [(lower, upper) for lower, upper in ((date_from, start), (end, date_to)) if lower < upper]
        if not edges:
            return _WindowCounts(counts=counts, total_services=total, source="rollup")
        edge_counts, edge_total = _counts_by_service(self._execute(self._aggregates_query(edges)))
        if max(len(counts), len(edge_counts)) >= SERVICES_LIMIT:
            counts, total = _counts_by_service(self._execute(self._aggregates_query()))
            return _WindowCounts(counts=counts, total_services=total, source="raw")
        for name, edge in edge_counts.items():
            merged = counts.setdefault(name, {**edge, **dict.fromkeys(_COUNT_COLUMNS, 0)})
            for column in _COUNT_COLUMNS:
                merged[column] += edge[column]
            merged["last_seen"] = max(merged["last_seen"], edge["last_seen"])
        ordered = dict(sorted(counts.items(), key=lambda item: -item[1]["log_count"])[:SERVICES_LIMIT])
        return _WindowCounts(counts=ordered, total_services=max(total, edge_total, len(counts)), source="rollup+raw")

    def _calculate(self) -> LogsQueryResponse:
        baseline_runner = self._baseline_runner
        runners = [self, baseline_runner] if baseline_runner else [self]
        windows = map_in_caller_context(
            lambda runner: runner._window_counts(), runners, thread_name_prefix="logs_services"
        )
        current, total_services, source = windows[0].counts, windows[0].total_services, windows[0].source
        baseline = windows[1].counts if baseline_runner else None
        current_cut = len(current) >= SERVICES_LIMIT
        baseline_cut = baseline is not None and len(baseline) >= SERVICES_LIMIT

        # Sparklines cover only the top services by volume; callers wanting
        # trends for other rows re-request with `serviceNames` scoped to the
        # rows they display. service_name is in the table's sort key, so the IN
        # filter prunes the scan, and the bounded name list keeps the grid of
        # time × service rows under the sparkline query's row LIMIT (which
        # truncates the most recent buckets first).
        top_service_names = list(current)[:SPARKLINE_SERVICES_LIMIT]
        sparkline_rows = self._execute(self._sparkline_query(top_service_names)) if top_service_names else []

        silent_names = [
            name
            for name, counts in (baseline or {}).items()
            if name not in current and counts["log_count"] >= SILENT_MIN_BASELINE_LOGS and not current_cut
        ]
        silent_last_seen = self._last_seen_in_rollup(silent_names) if silent_names and self._use_rollup() else {}

        enabled_rules = list(
            LogsExclusionRule.objects.filter(team_id=self.team.pk, enabled=True).order_by("priority", "created_at")
        )

        services = []
        for name in [*current, *silent_names]:
            counts = current.get(name, _NO_LOGS)
            base = baseline.get(name, _NO_LOGS) if baseline is not None else None
            service_name = name if name else "(no service)"
            log_count = counts["log_count"]
            error_count = counts["error_count"]
            error_rate = error_count / log_count if log_count > 0 else 0.0
            active_rules = []
            for rule in enabled_rules:
                # Legacy scope_service column (still honored for rules that predate
                # the universal filter_group).
                if rule.scope_service and rule.scope_service != service_name:
                    continue
                # Modern: scope via `config.filter_group`. Three-valued evaluation
                # against the partial record (we only know service_name at this
                # point); INDETERMINATE keeps the rule visible.
                filter_group = (rule.config or {}).get("filter_group")
                if not rule_could_apply_to_service(filter_group, service_name):
                    continue
                active_rules.append(
                    {
                        "rule_id": str(rule.id),
                        "rule_name": rule.name,
                        "summary_string": _sampling_rule_summary(rule),
                    }
                )
            verdict = classify_service(
                counts, base, baseline is not None and not (baseline_cut and name not in baseline)
            )
            status, reason = verdict.status, verdict.reason
            last_seen = counts["last_seen"] or silent_last_seen.get(name)
            base_count = base["log_count"] if base else None
            if status == "silent" and last_seen:
                reason = f"no logs since {utc_iso(last_seen)[5:16]}Z (baseline {base_count})"
            services.append(
                {
                    "service_name": service_name,
                    "status": status,
                    "reason": reason,
                    "log_count": log_count,
                    "error_count": error_count,
                    "error_rate": round(error_rate, 4),
                    "error_rate_pct": round(100 * error_rate, 1),
                    "baseline_log_count": base_count,
                    "error_rate_delta_pp": round(_error_rate_pct(counts) - _error_rate_pct(base), 1)
                    if base_count and log_count
                    else None,
                    "log_count_change_pct": round(100.0 * (log_count - base_count) / base_count, 1)
                    if base_count
                    else None,
                    "last_seen": utc_iso(last_seen) if last_seen else None,
                    "severity_breakdown": {
                        "debug": counts["debug"],
                        "info": counts["info"],
                        "warn": counts["warn"],
                        "error": error_count,
                    },
                    "active_rules": active_rules,
                }
            )

        total_logs = sum(int(s["log_count"]) for s in services) or 0
        for s in services:
            lc = int(s["log_count"])
            s["volume_share_pct"] = round(100.0 * lc / total_logs, 2) if total_logs else 0.0

        top_n = min(5, len(current))
        top_share = round(sum(float(s["volume_share_pct"]) for s in services[:top_n]), 2) if services else 0.0

        sparkline = []
        for row in sparkline_rows:
            sparkline.append(
                {
                    "time": row[0],
                    "service_name": row[1] if row[1] else "(no service)",
                    "count": row[2],
                }
            )

        current_window = (self.query_date_range.date_from(), self.query_date_range.date_to())
        baseline_window = (
            (baseline_runner.query_date_range.date_from(), baseline_runner.query_date_range.date_to())
            if baseline_runner
            else None
        )
        return LogsQueryResponse(
            results={
                "window": window_echo(current_window, baseline_window),
                "services": services,
                "sparkline": sparkline,
                "total_services": total_services,
                "source": source,
                "summary": {
                    "top_services_count": top_n,
                    "top_services_volume_share_pct": top_share,
                    "status_counts": {
                        status: sum(1 for s in services if s["status"] == status) for status in SERVICE_STATUSES
                    },
                    "truncated": total_services > len(current) or baseline_cut,
                },
                "next": []
                if self.environment
                else _next_steps(
                    [(name, s["status"]) for name, s in zip([*current, *silent_names], services)],
                    current_window,
                    baseline_window,
                    self._pristine_scope,
                ),
            }
        )

    def to_query(self) -> ast.SelectQuery:
        return self._aggregates_query()

    def _search_exprs(self, *, rollup: bool) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []
        if self.service_name_search:
            exprs.append(
                parse_expr(
                    "service_name ILIKE {pattern}",
                    placeholders={"pattern": ast.Constant(value=ilike_pattern(self.service_name_search))},
                )
            )
        if self.environment:
            env_filter = rollup_environment_filter_expr if rollup else environment_filter_expr
            exprs.append(env_filter(self.environment))
        return exprs

    @cached_property
    def _where_with_search(self) -> ast.Expr:
        exprs = [self.where(), *self._search_exprs(rollup=False)]
        return exprs[0] if len(exprs) == 1 else ast.And(exprs=exprs)

    def _aggregates_query(self, time_ranges: list[tuple[dt.datetime, dt.datetime]] | None = None) -> ast.SelectQuery:
        where = self._where_with_search
        if time_ranges:
            where = ast.And(exprs=[where, ast.Or(exprs=[_time_range_expr("timestamp", *r) for r in time_ranges])])
        query = parse_select(
            """
            SELECT
                service_name,
                sum(cnt) AS log_count,
                sumIf(cnt, in(severity_text, tuple('error', 'fatal'))) AS error_count,
                sumIf(cnt, in(severity_text, tuple('trace', 'debug'))) AS severity_debug,
                sumIf(cnt, severity_text = 'info') AS severity_info,
                sumIf(cnt, in(severity_text, tuple('warn', 'warning'))) AS severity_warn,
                -- Counts the grouped rows before LIMIT, so the caller learns the
                -- true service count without a second scan of the window.
                count() OVER () AS total_services,
                max(last_seen) AS last_seen
            FROM (
                SELECT
                    service_name,
                    lower(severity_text) AS severity_text,
                    count() AS cnt,
                    max(timestamp) AS last_seen
                FROM logs
                WHERE {where}
                GROUP BY service_name, severity_text
            )
            GROUP BY service_name
            ORDER BY log_count DESC
            LIMIT {limit}
            """,
            placeholders={
                "where": where,
                "limit": ast.Constant(value=SERVICES_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _rollup_where(self) -> list[ast.Expr]:
        exprs: list[ast.Expr] = []
        if self.query.serviceNames:
            exprs.append(parse_expr("service_name IN {names}", placeholders={"names": _tuple(self.query.serviceNames)}))
        if self.query.severityLevels:
            exprs.append(
                parse_expr("severity_text IN {levels}", placeholders={"levels": _tuple(self.query.severityLevels)})
            )
        return [*exprs, *self._search_exprs(rollup=True)]

    def _rollup_query(self, start: dt.datetime, end: dt.datetime) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                service_name,
                sum(log_count) AS total,
                sumIf(log_count, in(severity_text, tuple('error', 'fatal'))),
                sumIf(log_count, in(severity_text, tuple('trace', 'debug'))),
                sumIf(log_count, severity_text = 'info'),
                sumIf(log_count, in(severity_text, tuple('warn', 'warning'))),
                count() OVER () AS total_services,
                max(time_bucket)
            FROM posthog.logs_volume_buckets
            WHERE {where}
            GROUP BY service_name
            ORDER BY total DESC
            LIMIT {limit}
            """,
            placeholders={
                "where": ast.And(exprs=[_time_range_expr("time_bucket", start, end), *self._rollup_where()]),
                "limit": ast.Constant(value=SERVICES_LIMIT),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

    def _last_seen_in_rollup(self, service_names: list[str]) -> dict[str, dt.datetime]:
        until = self.query_date_range.date_to()
        exprs = [_time_range_expr("time_bucket", until - ROLLUP_RETENTION, until), *self._rollup_where()]
        exprs.append(parse_expr("service_name IN {names}", placeholders={"names": _tuple(service_names)}))
        query = parse_select(
            "SELECT service_name, max(time_bucket) FROM posthog.logs_volume_buckets WHERE {where} GROUP BY service_name LIMIT {limit}",
            placeholders={"where": ast.And(exprs=exprs), "limit": ast.Constant(value=len(service_names))},
        )
        assert isinstance(query, ast.SelectQuery)
        return {row[0]: row[1] for row in self._execute(query)}

    def _scope(self) -> dict[str, Any]:
        filters = [
            prop.model_dump(exclude_none=True)
            for group in (self.query.filterGroup.values if self.query.filterGroup else [])
            for prop in getattr(group, "values", [])
        ]
        scope = {
            "searchTerm": self.query.searchTerm,
            "filterGroup": filters,
            "severityLevels": self.query.severityLevels,
        }
        return {key: value for key, value in scope.items() if value}

    def _sparkline_query(self, service_names: list[str]) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                toStartOfInterval({time_field}, {one_interval_period}) AS time,
                service_name,
                count() AS event_count
            FROM logs
            WHERE {where} AND service_name IN {service_names}
            GROUP BY service_name, time
            ORDER BY time ASC, service_name ASC
            LIMIT 10000
            """,
            placeholders={
                **self.query_date_range.to_placeholders(),
                "time_field": ast.Call(name="toStartOfMinute", args=[ast.Field(chain=["timestamp"])])
                if self.query_date_range.interval_name != "second"
                else ast.Field(chain=["timestamp"]),
                "where": self._where_with_search,
                "service_names": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in service_names]),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query


def _tuple(values: Sequence[object]) -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=str(value)) for value in values])


def _time_range_expr(field: str, lower: dt.datetime, upper: dt.datetime) -> ast.Expr:
    return parse_expr(
        f"{field} >= {{lower}} AND {field} < {{upper}}",
        placeholders={"lower": ast.Constant(value=lower), "upper": ast.Constant(value=upper)},
    )


def _next_steps(statuses: list[tuple[str, str]], current: tuple, baseline: tuple | None, scope: dict) -> list[dict]:
    window = {"date_from": utc_iso(current[0]), "date_to": utc_iso(current[1])}
    steps: list[dict] = []
    silent = next((name for name, status in statuses if status == "silent"), None)
    if silent is not None and baseline:
        since_baseline = {"date_from": utc_iso(baseline[0]), "date_to": window["date_to"]}
        query = {**scope, "dateRange": since_baseline, "serviceNames": [silent], "targetBuckets": 24}
        steps.append({"tool": "logs-count-ranges", "why": f"when {silent} stopped logging", "query": query})
    worse = next((name for name, status in statuses if status in ("regressed", "degraded")), None)
    if worse is not None:
        errors = {**scope, "dateRange": window, "serviceNames": [worse], "severityLevels": ["error", "fatal"]}
        diff: dict = {
            "tool": "logs-patterns-diff",
            "why": f"error patterns behind {worse or '(no service)'}",
            "query": errors,
        }
        if baseline:
            diff["baselineDateRange"] = {"date_from": utc_iso(baseline[0]), "date_to": utc_iso(baseline[1])}
        steps.append(diff)
        spike = {**errors, "targetBuckets": 30}
        steps.append({"tool": "logs-count-ranges", "why": f"when errors in {worse} started", "query": spike})
    return steps[:3]
