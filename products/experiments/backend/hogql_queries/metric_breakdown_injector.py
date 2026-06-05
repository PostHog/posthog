"""
Metric-event breakdown injection for experiment funnel queries.

Unlike ``BreakdownInjector`` (which attributes the breakdown value from the
exposure event), this injector reads the breakdown property off the *metric*
event and attributes it across funnel steps using the metric's configured
``breakdownAttributionType`` — aligning experiment funnel breakdowns with how
insights funnels behave.

Scope: funnel metrics only. This is a standalone class (it does not subclass
``BreakdownInjector``); the old injector is removed once all metric types
migrate to metric-event breakdowns.
"""

from typing import cast

from posthog.schema import Breakdown, BreakdownAttributionType, ExperimentFunnelMetric, MultipleBreakdownType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.trends.utils import get_properties_chain
from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL


class MetricBreakdownInjector:
    def __init__(self, breakdowns: list[Breakdown], metric: ExperimentFunnelMetric):
        self.breakdowns = breakdowns
        self.metric = metric

    def attributes_from_exposure(self) -> bool:
        """This injector attributes from the metric event, so the exposure query stays breakdown-free."""
        return False

    def _has_breakdown(self) -> bool:
        return len(self.breakdowns) > 0

    def _get_breakdown_aliases(self) -> list[str]:
        return [f"breakdown_value_{i + 1}" for i in range(len(self.breakdowns))]

    def build_breakdown_exprs(self, table_alias: str = "events") -> list[tuple[str, ast.Expr]]:
        """Returns (alias, expression) tuples reading each breakdown property off the metric event.

        Coalesces NULL to BREAKDOWN_NULL_STRING_LABEL. Empty list if no breakdowns.
        """
        if not self._has_breakdown():
            return []

        result = []
        for i, breakdown in enumerate(self.breakdowns):
            breakdown_type = breakdown.type or cast(MultipleBreakdownType, "event")
            breakdown_field = str(breakdown.property)

            properties_chain = get_properties_chain(
                breakdown_type=breakdown_type,
                breakdown_field=breakdown_field,
                group_type_index=breakdown.group_type_index,
            )

            if table_alias and properties_chain[0] == "properties":
                property_expr: ast.Expr = ast.Field(chain=[table_alias, *properties_chain])
            else:
                property_expr = ast.Field(chain=properties_chain)

            expr = parse_expr(
                "coalesce(toString({property_expr}), {null_label})",
                placeholders={
                    "property_expr": property_expr,
                    "null_label": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                },
            )
            result.append((f"breakdown_value_{i + 1}", expr))

        return result

    def _attribution_step(self) -> tuple[str, int]:
        """Resolve (aggregation_fn, step_column_index) for the configured attribution mode.

        In experiment funnels ``step_0`` is the exposure event and the metric series
        events are ``step_1 .. step_N`` (N = len(series)). The breakdown is read off
        the metric events, so attribution targets those steps, never the exposure step.

        - first_touch / all_events: argMinIf from the first metric step (step_1).
        - last_touch: argMaxIf from the last metric step (step_N).
        - step: argMinIf from ``breakdownAttributionValue`` (0-indexed into the series,
          mapped to the corresponding step column step_{value + 1}).
        """
        attribution = self.metric.breakdownAttributionType or BreakdownAttributionType.FIRST_TOUCH
        num_metric_steps = len(self.metric.series)

        if attribution == BreakdownAttributionType.LAST_TOUCH:
            return "argMaxIf", num_metric_steps
        if attribution == BreakdownAttributionType.STEP:
            series_index = self.metric.breakdownAttributionValue
            if series_index is None or series_index < 0 or series_index >= num_metric_steps:
                raise ValueError(
                    f"breakdownAttributionValue must be in [0, {num_metric_steps - 1}] for step attribution, "
                    f"got {series_index}"
                )
            return "argMinIf", series_index + 1
        return "argMinIf", 1

    def _attribution_expr(self, breakdown_field: ast.Expr) -> ast.Call:
        """argMin/argMax that picks the attributed breakdown value at the configured step."""
        agg, step_index = self._attribution_step()
        return ast.Call(
            name=agg,
            args=[
                breakdown_field,
                ast.Field(chain=["timestamp"]),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[f"step_{step_index}"]),
                    right=ast.Constant(value=1),
                ),
            ],
        )

    def _inject_final_breakdown_columns(self, query: ast.SelectQuery, aliases: list[str]) -> None:
        """Surface breakdown columns in the outer SELECT (after variant) and GROUP BY."""
        for i, alias in enumerate(aliases):
            query.select.insert(1 + i, ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias])))
        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=["entity_metrics", alias]))

    def inject_funnel_breakdown_columns(self, query: ast.SelectQuery) -> None:
        """Legacy 3-CTE path: exposures + metric_events + entity_metrics.

        The breakdown is always attributed from the metric event (never carried
        from exposures), so attribution is uniform regardless of funnel order.
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()
        breakdown_exprs = self.build_breakdown_exprs(table_alias="")

        if query.ctes and "metric_events" in query.ctes:
            metric_events_cte = query.ctes["metric_events"]
            if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    metric_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))

        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=self._attribution_expr(ast.Field(chain=["metric_events", alias])))
                    )

        self._inject_final_breakdown_columns(query, aliases)

    def inject_funnel_breakdown_columns_optimized(self, query: ast.SelectQuery) -> None:
        """Optimized 2-CTE path: base_events + entity_metrics (no exposures CTE)."""
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()
        breakdown_exprs = self.build_breakdown_exprs(table_alias="")

        if query.ctes and "base_events" in query.ctes:
            base_events_cte = query.ctes["base_events"]
            if isinstance(base_events_cte, ast.CTE) and isinstance(base_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    base_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))

        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=self._attribution_expr(ast.Field(chain=[alias])))
                    )

        self._inject_final_breakdown_columns(query, aliases)
