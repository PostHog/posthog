"""Breakdown column injection for experiment metric queries (funnel, mean, ratio, retention)."""

from typing import Union, cast

from posthog.schema import (
    Breakdown,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    MultipleBreakdownType,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL

from products.product_analytics.backend.facade.queries import get_properties_chain


class BreakdownInjector:
    """
    Adds breakdown columns to the intermediate CTEs and the final SELECT/GROUP BY of an
    experiment query. Each entity takes its breakdown value from its first exposure.
    """

    def __init__(
        self,
        breakdowns: list[Breakdown],
        metric: Union[ExperimentFunnelMetric, ExperimentMeanMetric, ExperimentRatioMetric, ExperimentRetentionMetric],
    ):
        self.breakdowns = breakdowns
        self.metric = metric

    def _has_breakdown(self) -> bool:
        return len(self.breakdowns) > 0

    def _get_breakdown_aliases(self) -> list[str]:
        return [f"breakdown_value_{i + 1}" for i in range(len(self.breakdowns))]

    def build_breakdown_exprs(self, table_alias: str = "events") -> list[tuple[str, ast.Expr]]:
        """
        Returns (alias, expression) pairs that read each breakdown property, with NULL replaced
        by BREAKDOWN_NULL_STRING_LABEL. ExposureQueryBuilder also calls this.
        """
        if not self._has_breakdown():
            return []

        result = []
        for i, breakdown in enumerate(self.breakdowns):
            # Default to event type for backward compatibility
            breakdown_type = breakdown.type or cast(MultipleBreakdownType, "event")

            # The schema allows an int property.
            breakdown_field = str(breakdown.property)

            properties_chain = get_properties_chain(
                breakdown_type=breakdown_type,
                breakdown_field=breakdown_field,
                group_type_index=breakdown.group_type_index,
            )

            # Only event properties take the table alias. Person, group, and session chains
            # reference other tables.
            if table_alias and properties_chain[0] == "properties":
                property_expr = ast.Field(chain=[table_alias, *properties_chain])
            else:
                property_expr = ast.Field(chain=properties_chain)

            expr = parse_expr(
                "coalesce(toString({property_expr}), {null_label})",
                placeholders={
                    "property_expr": property_expr,
                    "null_label": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                },
            )
            alias = f"breakdown_value_{i + 1}"
            result.append((alias, expr))

        return result

    def inject_funnel_breakdown_columns(self, query: ast.SelectQuery) -> None:
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
                # Only the unordered funnel has an exposures CTE, and the breakdown there is
                # already attributed. The ordered funnel attributes it from the first step_0
                # (exposure) row in metric_events.
                has_exposures = "exposures" in query.ctes if query.ctes else False

                for alias in aliases:
                    if has_exposures:
                        entity_metrics_cte.expr.select.append(
                            ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias]))
                        )
                    else:
                        # Qualify the field with metric_events to avoid an ambiguous reference.
                        entity_metrics_cte.expr.select.append(
                            ast.Alias(
                                alias=alias,
                                expr=ast.Call(
                                    name="argMinIf",
                                    args=[
                                        ast.Field(chain=["metric_events", alias]),
                                        ast.Field(chain=["timestamp"]),
                                        ast.CompareOperation(
                                            op=ast.CompareOperationOp.Eq,
                                            left=ast.Field(chain=["step_0"]),
                                            right=ast.Constant(value=1),
                                        ),
                                    ],
                                ),
                            )
                        )

                if has_exposures:
                    if entity_metrics_cte.expr.group_by is None:
                        entity_metrics_cte.expr.group_by = []
                    for alias in aliases:
                        entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias])),
            )

        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=["entity_metrics", alias]))

    def inject_funnel_breakdown_columns_optimized(self, query: ast.SelectQuery) -> None:
        """The optimized funnel query has base_events and entity_metrics CTEs, and no exposures CTE."""
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()
        breakdown_exprs = self.build_breakdown_exprs(table_alias="")

        if query.ctes and "base_events" in query.ctes:
            base_events_cte = query.ctes["base_events"]
            if isinstance(base_events_cte, ast.CTE) and isinstance(base_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    base_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))

        # Attribute from the first step_0 (exposure) row.
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(
                            alias=alias,
                            expr=ast.Call(
                                name="argMinIf",
                                args=[
                                    ast.Field(chain=[alias]),
                                    ast.Field(chain=["timestamp"]),
                                    ast.CompareOperation(
                                        op=ast.CompareOperationOp.Eq,
                                        left=ast.Field(chain=["step_0"]),
                                        right=ast.Constant(value=1),
                                    ),
                                ],
                            ),
                        )
                    )

        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias])),
            )

        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=["entity_metrics", alias]))

    def inject_mean_breakdown_columns(self, query: ast.SelectQuery, final_cte_name: str = "entity_metrics") -> None:
        """final_cte_name is the CTE the main SELECT reads: 'entity_metrics' or 'winsorized_entity_metrics'."""
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()

        assert isinstance(self.metric, ExperimentMeanMetric)
        is_dw = isinstance(self.metric.source, ExperimentDataWarehouseNode)

        breakdown_exprs = self.build_breakdown_exprs(table_alias="metric_events" if is_dw else "events")

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
                        ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias]))
                    )
                if entity_metrics_cte.expr.group_by is None:
                    entity_metrics_cte.expr.group_by = []
                for alias in aliases:
                    entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        # Group the winsorization percentiles by breakdown, so that each breakdown group gets
        # its own thresholds.
        if query.ctes and "percentiles" in query.ctes:
            percentiles_cte = query.ctes["percentiles"]
            if isinstance(percentiles_cte, ast.CTE) and isinstance(percentiles_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    percentiles_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias]))
                    )
                if percentiles_cte.expr.group_by is None:
                    percentiles_cte.expr.group_by = []
                for alias in aliases:
                    percentiles_cte.expr.group_by.append(ast.Field(chain=["entity_metrics", alias]))

        if query.ctes and final_cte_name == "winsorized_entity_metrics":
            winsorized_cte = query.ctes["winsorized_entity_metrics"]
            if isinstance(winsorized_cte, ast.CTE) and isinstance(winsorized_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    winsorized_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias]))
                    )
                # Replace the CROSS JOIN to percentiles with a per-breakdown JOIN, so that each
                # entity is capped at the thresholds of its own breakdown group.
                if winsorized_cte.expr.select_from:
                    join_expr = winsorized_cte.expr.select_from.next_join
                    if join_expr and isinstance(join_expr, ast.JoinExpr):
                        join_expr.join_type = "JOIN"
                        join_conditions = []
                        for alias in aliases:
                            join_conditions.append(
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["percentiles", alias]),
                                    right=ast.Field(chain=["entity_metrics", alias]),
                                )
                            )
                        condition_expr: ast.Expr
                        if len(join_conditions) == 1:
                            condition_expr = join_conditions[0]
                        else:
                            combined: ast.Expr = join_conditions[0]
                            for condition in join_conditions[1:]:
                                combined = ast.And(exprs=[combined, condition])
                            condition_expr = combined
                        join_expr.constraint = ast.JoinConstraint(expr=condition_expr, constraint_type="ON")

        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=[final_cte_name, alias])),
            )

        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=[final_cte_name, alias]))

    def inject_ratio_breakdown_columns(self, query: ast.SelectQuery, winsorized: bool = False) -> None:
        """
        Breakdowns come from exposures, not from numerator or denominator events. So
        entity_metrics reads them from exposures, and the event joins need no breakdown conditions.

        When ``winsorized`` is set the query has extra ``percentiles`` and
        ``winsorized_entity_metrics`` CTEs: percentiles are computed per breakdown group
        (so each group is capped at its own threshold, pooled across variations) and the
        final aggregation reads from ``winsorized_entity_metrics``.
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()
        final_cte_name = "winsorized_entity_metrics" if winsorized else "entity_metrics"

        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias]))
                    )
                if entity_metrics_cte.expr.group_by is None:
                    entity_metrics_cte.expr.group_by = []
                for alias in aliases:
                    entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        # Group the winsorization percentiles by breakdown, so that each breakdown group gets its
        # own thresholds, pooled across variations.
        if winsorized and query.ctes and "percentiles" in query.ctes:
            percentiles_cte = query.ctes["percentiles"]
            if isinstance(percentiles_cte, ast.CTE) and isinstance(percentiles_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    percentiles_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias]))
                    )
                if percentiles_cte.expr.group_by is None:
                    percentiles_cte.expr.group_by = []
                for alias in aliases:
                    percentiles_cte.expr.group_by.append(ast.Field(chain=["entity_metrics", alias]))

        # Replace the CROSS JOIN to percentiles with a per-breakdown JOIN.
        if winsorized and query.ctes and "winsorized_entity_metrics" in query.ctes:
            winsorized_cte = query.ctes["winsorized_entity_metrics"]
            if isinstance(winsorized_cte, ast.CTE) and isinstance(winsorized_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    winsorized_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias]))
                    )
                if winsorized_cte.expr.select_from:
                    join_expr = winsorized_cte.expr.select_from.next_join
                    if join_expr and isinstance(join_expr, ast.JoinExpr):
                        join_expr.join_type = "JOIN"
                        join_conditions: list[ast.Expr] = []
                        for alias in aliases:
                            join_conditions.append(
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Eq,
                                    left=ast.Field(chain=["percentiles", alias]),
                                    right=ast.Field(chain=["entity_metrics", alias]),
                                )
                            )
                        condition_expr: ast.Expr
                        if len(join_conditions) == 1:
                            condition_expr = join_conditions[0]
                        else:
                            combined: ast.Expr = join_conditions[0]
                            for condition in join_conditions[1:]:
                                combined = ast.And(exprs=[combined, condition])
                            condition_expr = combined
                        join_expr.constraint = ast.JoinConstraint(expr=condition_expr, constraint_type="ON")

        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=[final_cte_name, alias])),
            )

        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=[final_cte_name, alias]))

    def inject_retention_breakdown_columns(self, query: ast.SelectQuery) -> None:
        """Breakdowns come from exposures, so only entity_metrics and the final SELECT need them."""
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()

        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for i, alias in enumerate(aliases):
                    entity_metrics_cte.expr.select.insert(
                        2 + i,  # After entity_id (0), variant (1)
                        ast.Alias(alias=alias, expr=ast.Field(chain=["exposures", alias])),
                    )

                if entity_metrics_cte.expr.group_by is None:
                    entity_metrics_cte.expr.group_by = []
                for alias in aliases:
                    entity_metrics_cte.expr.group_by.append(ast.Field(chain=["exposures", alias]))

        for i, alias in enumerate(aliases):
            query.select.insert(
                1 + i,  # Position after variant column (index 0)
                ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias])),
            )

        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=["entity_metrics", alias]))
