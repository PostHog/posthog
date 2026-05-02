from posthog.schema import CachedLogsQueryResponse, LogsQuery

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner

from products.logs.backend.logs_query_runner import LogsQueryResponse, LogsQueryRunnerMixin
from products.logs.backend.models import LogsExclusionRule


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
            settings=self.settings,
        )

        sparkline_response = execute_hogql_query(
            query_type="LogsQuery",
            query=self._sparkline_query(),
            modifiers=self.modifiers,
            team=self.team,
            workload=Workload.LOGS,
            timings=self.timings,
            limit_context=self.limit_context,
            settings=self.settings,
        )

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
                if rule.scope_service and rule.scope_service != service_name:
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
        for row in sparkline_response.results:
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

    def _sparkline_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                toStartOfInterval({time_field}, {one_interval_period}) AS time,
                service_name,
                count() AS event_count
            FROM logs
            WHERE {where}
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
            },
        )
        assert isinstance(query, ast.SelectQuery)
        return query
