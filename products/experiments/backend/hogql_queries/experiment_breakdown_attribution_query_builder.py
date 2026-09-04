"""
Builder for experiment breakdown attribution on metric events.

Takes an ``ExperimentBreakdownAttributionContext`` and constructs the HogQL AST
that reads each breakdown property off the metric event, attributes it across
funnel steps with the context's resolved aggregation, and injects the breakdown
columns into the funnel query CTEs.

Scope: funnel metrics only, for now.
"""

from typing import cast

from posthog.schema import MultipleBreakdownType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.trends.utils import get_properties_chain
from posthog.hogql_queries.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL

from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.hogql_queries.experiment_breakdown_attribution_query_context import (
    ExperimentBreakdownAttributionContext,
)


class ExperimentBreakdownAttributionQueryBuilder:
    def __init__(self, context: ExperimentBreakdownAttributionContext):
        self.context = context

    def attributes_from_exposure(self) -> bool:
        """This builder attributes from the metric event, so the exposure query stays breakdown-free."""
        return False

    def build_breakdown_exprs(self, table_alias: str = "events") -> list[tuple[str, ast.Expr]]:
        """Returns (alias, expression) tuples reading each breakdown property off the metric event.

        A missing property and a property set to an empty string both become
        BREAKDOWN_NULL_STRING_LABEL. The UI labels both as "None", so keeping them apart would
        show two identical rows, each with its own samples and statistics. Empty list if no
        breakdowns.
        """
        if not self.context.has_breakdown():
            return []

        result = []
        for i, breakdown in enumerate(self.context.breakdowns):
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
                "coalesce(nullIf(toString({property_expr}), ''), {null_label})",
                placeholders={
                    "property_expr": property_expr,
                    "null_label": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                },
            )
            result.append((f"breakdown_value_{i + 1}", expr))

        return result

    def _attribution_condition(self, step_indexes: list[int]) -> ast.Expr:
        """Match a metric event at any of the attribution step columns (``step_i = 1``)."""
        comparisons: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=[f"step_{index}"]),
                right=ast.Constant(value=1),
            )
            for index in step_indexes
        ]
        return comparisons[0] if len(comparisons) == 1 else ast.Or(exprs=comparisons)

    def _value_present_condition(self, breakdown_fields: list[ast.Expr]) -> ast.Expr:
        """Match a row that carries at least one breakdown value.

        The property is coalesced to the null label before attribution, so a row with no value
        would otherwise be an equal candidate and win on timestamp alone, hiding a later event
        that carries a real one.
        """
        comparisons: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=field,
                right=ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
            )
            for field in breakdown_fields
        ]
        return comparisons[0] if len(comparisons) == 1 else ast.Or(exprs=comparisons)

    def _attribution_expr(self, breakdown_field: ast.Expr, breakdown_fields: list[ast.Expr]) -> ast.Expr:
        """Attributed breakdown value at the configured step(s).

        A candidate row must match an attribution step and carry a breakdown value. Every alias
        shares that one condition, and orders by (timestamp, uuid) rather than timestamp alone, so
        all breakdown values of a user come from the same event. With ties on timestamp each alias
        would otherwise pick its own row, forming a value tuple the user never had.

        argMinIf/argMaxIf over zero matching rows returns ClickHouse's empty string. The UI labels
        that as "None" too, but it is a different value from the null label, so it would form a
        second no-value bucket and steal a top-N slot. Users with no attributable metric event get
        the null label instead.
        """
        resolution = self.context.resolve_attribution()
        condition: ast.Expr = ast.And(
            exprs=[
                self._attribution_condition(resolution.step_indexes),
                self._value_present_condition(breakdown_fields),
            ]
        )
        ordering_key = ast.Tuple(exprs=[ast.Field(chain=["timestamp"]), ast.Field(chain=["uuid"])])
        attributed = ast.Call(
            name=resolution.aggregation_fn,
            args=[breakdown_field, ordering_key, condition],
        )
        return parse_expr(
            "if({has_match} = 0, {null_label}, {attributed})",
            placeholders={
                "has_match": ast.Call(name="countIf", args=[condition]),
                "null_label": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
                "attributed": attributed,
            },
        )

    def _top_breakdowns_subquery(self, aliases: list[str]) -> ast.SelectQuery:
        """Top-N breakdown tuples by entity (user) count, pooled across variants.

        Selects from entity_metrics (one row per user) so the ranking measure is the
        number of experiment units in each breakdown bucket — the funnel analog of
        insights ranking by frequency.

        Only users who reach the result are ranked. Users with no variant are dropped by the
        final SELECT, and under "exclude" handling the runner drops multi-variant users after
        the query, so counting either here would let a bucket take a top-N slot and then show
        no row.
        """
        # Project a scalar for a single breakdown, or a tuple for multiple, so the
        # membership test on the outer query matches shapes.
        if len(aliases) == 1:
            projection: ast.Expr = ast.Field(chain=["entity_metrics", aliases[0]])
        else:
            projection = ast.Tuple(exprs=[ast.Field(chain=["entity_metrics", alias]) for alias in aliases])
        subquery = ast.SelectQuery(
            select=[projection],
            select_from=ast.JoinExpr(table=ast.Field(chain=["entity_metrics"])),
            where=parse_expr(
                "notEmpty(entity_metrics.variant) and entity_metrics.variant != {multiple_variant_key}",
                placeholders={"multiple_variant_key": ast.Constant(value=MULTIPLE_VARIANT_KEY)},
            ),
            group_by=[ast.Field(chain=["entity_metrics", alias]) for alias in aliases],
            # Tie-break by breakdown value so the cutoff at the limit is deterministic
            # across executions; count() alone lets ClickHouse pick tied tuples arbitrarily.
            order_by=[
                ast.OrderExpr(expr=ast.Call(name="count", args=[]), order="DESC"),
                *[ast.OrderExpr(expr=ast.Field(chain=["entity_metrics", alias]), order="ASC") for alias in aliases],
            ],
            limit=ast.Constant(value=self.context.breakdown_limit()),
        )
        return subquery

    def _inject_final_breakdown_columns(self, query: ast.SelectQuery, aliases: list[str]) -> None:
        """Surface breakdown columns in the outer SELECT (after variant) and GROUP BY.

        Applies the top-N + "Other" limit: breakdown tuples beyond the limit (ranked by
        user count) are relabeled to BREAKDOWN_OTHER_STRING_LABEL before the final GROUP BY,
        capping output cardinality. The relabel collapses the whole tuple together so all
        breakdown columns of an "Other" row carry the Other label.
        """
        # Membership test against the top-N set. Single breakdown compares the scalar value
        # directly; multiple breakdowns compare the value tuple element-wise.
        if len(aliases) == 1:
            left: ast.Expr = ast.Field(chain=["entity_metrics", aliases[0]])
        else:
            left = ast.Tuple(exprs=[ast.Field(chain=["entity_metrics", alias]) for alias in aliases])
        in_top = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=left,
            right=self._top_breakdowns_subquery(aliases),
        )

        for i, alias in enumerate(aliases):
            limited_expr = parse_expr(
                "if({in_top}, {value}, {other})",
                placeholders={
                    "in_top": in_top,
                    "value": ast.Field(chain=["entity_metrics", alias]),
                    "other": ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL),
                },
            )
            query.select.insert(1 + i, ast.Alias(alias=alias, expr=limited_expr))

        if query.group_by is None:
            query.group_by = []
        for alias in aliases:
            query.group_by.append(ast.Field(chain=[alias]))

    def inject_funnel_breakdown_columns(self, query: ast.SelectQuery) -> None:
        """Legacy 3-CTE path: exposures + metric_events + entity_metrics.

        The breakdown is always attributed from the metric event (never carried
        from exposures), so attribution is uniform regardless of funnel order.
        """
        if not self.context.has_breakdown():
            return

        aliases = self.context.breakdown_aliases()
        breakdown_exprs = self.build_breakdown_exprs(table_alias="")

        if query.ctes and "metric_events" in query.ctes:
            metric_events_cte = query.ctes["metric_events"]
            if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    metric_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))

        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                breakdown_fields: list[ast.Expr] = [ast.Field(chain=["metric_events", alias]) for alias in aliases]
                for alias, field in zip(aliases, breakdown_fields):
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=self._attribution_expr(field, breakdown_fields))
                    )

        self._inject_final_breakdown_columns(query, aliases)

    def inject_funnel_breakdown_columns_optimized(self, query: ast.SelectQuery) -> None:
        """Optimized 2-CTE path: base_events + entity_metrics (no exposures CTE)."""
        if not self.context.has_breakdown():
            return

        aliases = self.context.breakdown_aliases()
        breakdown_exprs = self.build_breakdown_exprs(table_alias="")

        if query.ctes and "base_events" in query.ctes:
            base_events_cte = query.ctes["base_events"]
            if isinstance(base_events_cte, ast.CTE) and isinstance(base_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    base_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))

        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                breakdown_fields: list[ast.Expr] = [ast.Field(chain=[alias]) for alias in aliases]
                for alias, field in zip(aliases, breakdown_fields):
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=self._attribution_expr(field, breakdown_fields))
                    )

        self._inject_final_breakdown_columns(query, aliases)
