from posthog.schema import (
    CachedWebStatsTableQueryResponse,
    WebAnalyticsPreComputeStrategy,
    WebVitalsMetric,
    WebVitalsMetricBand,
    WebVitalsPathBreakdownQuery,
    WebVitalsPathBreakdownQueryResponse,
    WebVitalsPathBreakdownResult,
    WebVitalsPathBreakdownResultItem,
    WebVitalsPercentile,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import get_property_type, property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.queries.trends.util import PROPERTY_MATH_FUNCTIONS

from products.web_analytics.backend.hogql_queries.web_analytics_query_runner import WebAnalyticsQueryRunner
from products.web_analytics.backend.hogql_queries.web_vitals_paths_lazy_precompute import (
    can_use_lazy_precompute,
    execute_lazy_precomputed_read,
)

# p75 is the percentile the Google Core Web Vitals bands are defined at, so it's the
# default when a query omits `percentile` (e.g. a minimal MCP `query-web-vitals` call).
DEFAULT_WEB_VITALS_PERCENTILE = WebVitalsPercentile.P75

# Standard Google Core Web Vitals [good, poor] band boundaries, keyed by metric. Mirrors
# WEB_VITALS_THRESHOLDS in frontend/src/queries/nodes/WebVitals/definitions.ts. Used as the
# default when a query omits `thresholds`, so callers only have to supply the metric.
DEFAULT_WEB_VITALS_THRESHOLDS: dict[WebVitalsMetric, tuple[float, float]] = {
    WebVitalsMetric.LCP: (2500, 4000),
    WebVitalsMetric.INP: (200, 500),
    WebVitalsMetric.CLS: (0.1, 0.25),
    WebVitalsMetric.FCP: (1800, 3000),
}


class WebVitalsPathBreakdownQueryRunner(WebAnalyticsQueryRunner[WebVitalsPathBreakdownQueryResponse]):
    query: WebVitalsPathBreakdownQuery
    cached_response: CachedWebStatsTableQueryResponse

    @property
    def resolved_percentile(self) -> WebVitalsPercentile:
        return self.query.percentile or DEFAULT_WEB_VITALS_PERCENTILE

    @property
    def resolved_thresholds(self) -> tuple[float, float]:
        if self.query.thresholds is not None:
            return self.query.thresholds[0], self.query.thresholds[1]
        return DEFAULT_WEB_VITALS_THRESHOLDS[self.query.metric]

    def to_query(self):
        return parse_select(
            """
SELECT * FROM (
    SELECT multiIf(
        value <= {good_threshold}, 'good',
        value <= {needs_improvements_threshold}, 'needs_improvements',
        'poor'
    ) AS band,
    path,
    value
    FROM {inner_query}
)
ORDER BY value ASC, path ASC
LIMIT 20 BY band
""",
            timings=self.timings,
            placeholders={
                "inner_query": self._inner_query(),
                "good_threshold": ast.Constant(value=self.resolved_thresholds[0]),
                "needs_improvements_threshold": ast.Constant(value=self.resolved_thresholds[1]),
            },
        )

    # NOTE: Hardcoded to return at most 20 results per band, but we can change that if needed
    def _inner_query(self):
        return parse_select(
            """
SELECT
    {breakdown_by} AS path,
    {percentile} AS value
FROM events
WHERE and(event == '$web_vitals', path IS NOT NULL, {inside_periods_expr}, {event_properties_expr})
GROUP BY path
HAVING value >= 0
            """,
            timings=self.timings,
            placeholders={
                "breakdown_by": self._apply_path_cleaning(ast.Field(chain=["events", "properties", "$pathname"])),
                "percentile": self._percentile_expr(),
                "inside_periods_expr": self._periods_expression(),
                "event_properties_expr": self._event_properties(),
            },
        )

    def _event_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def _percentile_expr(self) -> ast.Expr:
        percentile_function = PROPERTY_MATH_FUNCTIONS[self.resolved_percentile]
        metric_value_field = f"properties.$web_vitals_{self.query.metric.value}_value"

        # nosemgrep: hogql-injection-taint - percentile_function from dict lookup, metric from enum
        return parse_expr(f"{percentile_function}(toFloat({metric_value_field}))")

    def _calculate(self):
        # Lazy precompute path: short-circuits the raw events scan when the team
        # opted in via the per-query toggle and the shared gate accepts the
        # request. Any failure (gate rejection, INSERT/READ error) returns None
        # and falls through to the raw path below.
        if can_use_lazy_precompute(self):
            lazy_response = execute_lazy_precomputed_read(self)
            if lazy_response is not None:
                return lazy_response

        query = self.to_query()
        response = execute_hogql_query(
            query_type="web_vitals_path_breakdown_query",
            query=query,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        assert response.results is not None

        # Return a list because Pydantic is boring, but it will always be a single entry
        return WebVitalsPathBreakdownQueryResponse(
            results=[
                WebVitalsPathBreakdownResult(
                    good=self._get_results_for_band(response.results, WebVitalsMetricBand.GOOD),
                    needs_improvements=self._get_results_for_band(
                        response.results, WebVitalsMetricBand.NEEDS_IMPROVEMENTS
                    ),
                    poor=self._get_results_for_band(response.results, WebVitalsMetricBand.POOR),
                )
            ],
            timings=response.timings,
            hogql=response.hogql,
            modifiers=self.modifiers,
            preComputeStrategy=WebAnalyticsPreComputeStrategy.LIVE,
        )

    def _get_results_for_band(
        self, results: list[tuple[str, str, float]], band: WebVitalsMetricBand
    ) -> list[WebVitalsPathBreakdownResultItem]:
        return [WebVitalsPathBreakdownResultItem(path=row[1], value=row[2]) for row in results if row[0] == band.value]
