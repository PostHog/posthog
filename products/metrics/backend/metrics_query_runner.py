"""Runner for the `MetricsQuery` schema node (insights, dashboards, /query).

A thin translation layer: schema `MetricsQuery` -> facade `MetricQueryRequest`
-> `run_metric_query` -> schema `MetricsQuerySeries`. The single-clause HogQL
engine lives in `metric_query_runner.py` (singular); this runner never
bypasses the facade, so the viewer, MCP tools, and insights all share one
query path.
"""

from datetime import datetime
from typing import TYPE_CHECKING

from posthog.schema import (
    CachedMetricsQueryResponse,
    DashboardFilter,
    DateRange,
    MetricsQuery,
    MetricsQueryPoint,
    MetricsQueryResponse,
    MetricsQuerySeries,
)

from posthog.hogql import ast

from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.rbac.user_access_control import UserAccessControl

from products.metrics.backend.facade.api import run_metric_query
from products.metrics.backend.facade.contracts import MetricFilter, MetricGroupBy, MetricQueryClause, MetricQueryRequest
from products.metrics.backend.facade.enums import AttributeScope, FilterOp, MetricAggregation

if TYPE_CHECKING:
    from posthog.models import User

# Metrics dashboards are usually about "what is happening now", so the
# node defaults to a tighter window than the analytics-wide -7d.
DEFAULT_DATE_FROM = "-24h"


class MetricsQueryRunner(AnalyticsQueryRunner[MetricsQueryResponse]):
    query: MetricsQuery
    cached_response: CachedMetricsQueryResponse

    def validate_query_runner_access(self, user: "User") -> bool:
        user_access_control = UserAccessControl(user=user, team=self.team)
        return user_access_control.assert_access_level_for_resource("metrics", "viewer")

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        raise NotImplementedError(
            "MetricsQuery composes one HogQL query per clause via the metrics facade; there is no single statement"
        )

    def _query_date_range(self) -> QueryDateRange:
        # explicitDate keeps second-granular windows intact; without it,
        # QueryDateRange rounds date_to up to end of day.
        date_range = DateRange(
            date_from=(self.query.dateRange.date_from if self.query.dateRange else None) or DEFAULT_DATE_FROM,
            date_to=self.query.dateRange.date_to if self.query.dateRange else None,
            explicitDate=True,
        )
        return QueryDateRange(date_range=date_range, team=self.team, interval=None, now=datetime.now())

    def _to_request(self) -> MetricQueryRequest:
        date_range = self._query_date_range()
        clauses = tuple(
            MetricQueryClause(
                name=clause.name,
                metric_name=clause.metricName,
                aggregation=MetricAggregation(clause.aggregation.value),
                filters=tuple(
                    MetricFilter(
                        key=f.key,
                        op=FilterOp(f.op.value),
                        value=f.value,
                        scope=AttributeScope(f.scope.value) if f.scope is not None else AttributeScope.AUTO,
                    )
                    for f in clause.filters or []
                ),
                group_by=tuple(
                    MetricGroupBy(
                        key=g.key,
                        scope=AttributeScope(g.scope.value) if g.scope is not None else AttributeScope.AUTO,
                    )
                    for g in clause.groupBy or []
                ),
                quantile=clause.quantile,
            )
            for clause in self.query.clauses
        )
        return MetricQueryRequest(
            clauses=clauses,
            date_from=date_range.date_from(),
            date_to=date_range.date_to(),
            interval=self.query.interval,
            formula=self.query.formula,
        )

    def _calculate(self) -> MetricsQueryResponse:
        series = run_metric_query(team=self.team, request=self._to_request())
        return MetricsQueryResponse(
            results=[
                MetricsQuerySeries(
                    labels=s.labels,
                    points=[MetricsQueryPoint(time=p.time, value=p.value) for p in s.points],
                    metricName=s.metric_name,
                    clause=s.clause,
                )
                for s in series
            ]
        )

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter) -> None:
        # Metric label predicates are not PostHog property filters, so only the
        # dashboard's date range applies to this tile.
        if dashboard_filter.date_from or dashboard_filter.date_to:
            self.query.dateRange = DateRange(
                date_from=dashboard_filter.date_from,
                date_to=dashboard_filter.date_to,
            )
