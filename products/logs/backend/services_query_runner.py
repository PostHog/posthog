from typing import Any

import re2

from posthog.schema import CachedLogsQueryResponse, HogQLFilters, LogsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin
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
        if operator in ("is_not", "not_in", "not_icontains", "not_regex"):
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


class ServicesQueryRunner(AnalyticsQueryRunner[LogsQueryResponse], LogsQueryRunnerMixin):
    """Returns per-service aggregates (volume, error count, error rate) and sparkline data."""

    query: LogsQuery
    cached_response: CachedLogsQueryResponse

    def _calculate(self) -> LogsQueryResponse:
        aggregates_response = execute_hogql_query(
            query_type="LogsQuery",
            query=self._aggregates_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            filters=HogQLFilters(dateRange=self.query.dateRange),
            settings=self.settings,
        )

        # The table only renders sparklines for the services in the aggregates
        # result (top 25 by volume), so scope the sparkline scan to those names
        # rather than every service in the window: service_name is in the table's
        # sort key, so the IN filter prunes the scan, and it removes the chance of
        # the row LIMIT truncating a displayed service's trend.
        top_service_names = [row[0] for row in aggregates_response.results]
        sparkline_rows: list[Any] = []
        if top_service_names:
            sparkline_response = execute_hogql_query(
                query_type="LogsQuery",
                query=self._sparkline_query(top_service_names),
                modifiers=self.modifiers,
                team=self.team,
                workload=Workload.LOGS,
                timings=self.timings,
                limit_context=self.limit_context,
                filters=HogQLFilters(dateRange=self.query.dateRange),
                settings=self.settings,
            )
            sparkline_rows = sparkline_response.results

        enabled_rules = list(
            LogsExclusionRule.objects.filter(team_id=self.team.pk, enabled=True).order_by("priority", "created_at")
        )

        services = []
        for row in aggregates_response.results:
            service_name = row[0] if row[0] else "(no service)"
            log_count = row[1]
            error_count = row[2]
            sev_debug = row[3]
            sev_info = row[4]
            sev_warn = row[5]
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
            services.append(
                {
                    "service_name": service_name,
                    "log_count": log_count,
                    "error_count": error_count,
                    "error_rate": round(error_rate, 4),
                    "severity_breakdown": {
                        "debug": int(sev_debug),
                        "info": int(sev_info),
                        "warn": int(sev_warn),
                        "error": int(error_count),
                    },
                    "active_rules": active_rules,
                }
            )

        total_logs = sum(int(s["log_count"]) for s in services) or 0
        for s in services:
            lc = int(s["log_count"])
            s["volume_share_pct"] = round(100.0 * lc / total_logs, 2) if total_logs else 0.0

        top_n = min(5, len(services))
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

        return LogsQueryResponse(
            results={
                "services": services,
                "sparkline": sparkline,
                "summary": {
                    "top_services_count": top_n,
                    "top_services_volume_share_pct": top_share,
                },
            }
        )

    def to_query(self) -> ast.SelectQuery:
        return self._aggregates_query()

    def _aggregates_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                service_name,
                sum(cnt) AS log_count,
                sumIf(cnt, in(severity_text, tuple('error', 'fatal'))) AS error_count,
                sumIf(cnt, in(severity_text, tuple('trace', 'debug'))) AS severity_debug,
                sumIf(cnt, severity_text = 'info') AS severity_info,
                sumIf(cnt, in(severity_text, tuple('warn', 'warning'))) AS severity_warn
            FROM (
                SELECT
                    service_name,
                    lower(severity_text) AS severity_text,
                    count() AS cnt,
                FROM logs
                WHERE {where}
                GROUP BY service_name, severity_text
            )
            GROUP BY service_name
            ORDER BY log_count DESC
            LIMIT 25
            """,
            placeholders={
                "where": self.where(),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query

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
                "where": self.where(),
                "service_names": ast.Tuple(exprs=[ast.Constant(value=str(sn)) for sn in service_names]),
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
