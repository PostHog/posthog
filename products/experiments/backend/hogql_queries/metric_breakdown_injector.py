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

from typing import Union, cast

from posthog.schema import (
    Breakdown,
    BreakdownAttributionType,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    MultipleBreakdownType,
)

from posthog.hogql import ast
from posthog.hogql.constants import BREAKDOWN_VALUES_LIMIT
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.insights.trends.utils import get_properties_chain
from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL

MetricType = Union[ExperimentFunnelMetric, ExperimentMeanMetric, ExperimentRatioMetric, ExperimentRetentionMetric]


class MetricBreakdownInjector:
    def __init__(self, breakdowns: list[Breakdown], metric: MetricType):
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
        assert isinstance(self.metric, ExperimentFunnelMetric)
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

    def _breakdown_limit(self) -> int:
        """Top-N cap on breakdown values; mirrors insights' default of BREAKDOWN_VALUES_LIMIT."""
        breakdown_filter = self.metric.breakdownFilter
        limit = breakdown_filter.breakdown_limit if breakdown_filter else None
        return limit or BREAKDOWN_VALUES_LIMIT

    def _top_breakdowns_subquery(self, aliases: list[str]) -> ast.SelectQuery:
        """Top-N breakdown tuples by entity (user) count, pooled across variants.

        Selects from entity_metrics (one row per user) so the ranking measure is the
        number of experiment units in each breakdown bucket — the funnel analog of
        insights ranking by frequency.
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
            group_by=[ast.Field(chain=["entity_metrics", alias]) for alias in aliases],
            # Tie-break by breakdown value so the cutoff at the limit is deterministic
            # across executions; count() alone lets ClickHouse pick tied tuples arbitrarily.
            order_by=[
                ast.OrderExpr(expr=ast.Call(name="count", args=[]), order="DESC"),
                *[ast.OrderExpr(expr=ast.Field(chain=["entity_metrics", alias]), order="ASC") for alias in aliases],
            ],
            limit=ast.Constant(value=self._breakdown_limit()),
        )
        return subquery

    def _inject_final_breakdown_columns(
        self, query: ast.SelectQuery, aliases: list[str], final_cte_name: str = "entity_metrics"
    ) -> None:
        """Surface breakdown columns in the outer SELECT (after variant) and GROUP BY.

        Applies the top-N + "Other" limit: breakdown tuples beyond the limit (ranked by
        user count) are relabeled to BREAKDOWN_OTHER_STRING_LABEL before the final GROUP BY,
        capping output cardinality. The relabel collapses the whole tuple together so all
        breakdown columns of an "Other" row carry the Other label.

        ``final_cte_name`` is the CTE the outer SELECT reads from (``entity_metrics`` for funnels
        and non-winsorized mean, ``winsorized_entity_metrics`` for winsorized mean). Ranking is
        always computed from ``entity_metrics`` since winsorization doesn't change the set of
        (entity, variant, breakdown) tuples.
        """
        # Membership test against the top-N set, always ranked from entity_metrics (pre-winsorization).
        # Single breakdown compares the scalar value directly; multiple breakdowns compare the tuple.
        if len(aliases) == 1:
            left: ast.Expr = ast.Field(chain=[final_cte_name, aliases[0]])
        else:
            left = ast.Tuple(exprs=[ast.Field(chain=[final_cte_name, alias]) for alias in aliases])
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
                    "value": ast.Field(chain=[final_cte_name, alias]),
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

    def inject_mean_breakdown_columns(self, query: ast.SelectQuery, final_cte_name: str = "entity_metrics") -> None:
        """Inject breakdown columns into a mean query.

        Reads the breakdown property off the *metric event* (in ``metric_events``) and
        attributes each user to a single bucket via **first-touch** — ``argMin`` over the
        metric event timestamp. Mean has no attribution modes (unlike funnels), so the
        breakdown is always taken from the user's first qualifying metric event. The
        per-user conversion window is already enforced by the ``entity_metrics`` join, so
        no extra condition is needed on the ``argMin``.

        ``final_cte_name`` is ``entity_metrics`` for the plain query or
        ``winsorized_entity_metrics`` for the winsorized query; winsorization needs the
        breakdown carried through its percentiles/join CTEs.

        Session-property metrics have an extra ``metric_events_by_session`` layer; their
        ``metric_events`` CTE joins exposures and can't see raw event properties, so the
        breakdown is read (and deduped) in the by-session layer instead. See
        ``_read_breakdown_into_metric_events``.
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()

        # The session-property shape reads the breakdown a layer earlier; the attribution
        # timestamp is the session's first event time rather than the metric event timestamp.
        is_session_property = bool(query.ctes and "metric_events_by_session" in query.ctes)
        timestamp_field = "first_event_timestamp" if is_session_property else "timestamp"

        self._read_breakdown_into_metric_events(query, aliases, is_session_property)

        # Attribute first-touch per user: argMin over the (session-)first event timestamp.
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(
                            alias=alias,
                            expr=ast.Call(
                                name="argMin",
                                args=[
                                    ast.Field(chain=["metric_events", alias]),
                                    ast.Field(chain=["metric_events", timestamp_field]),
                                ],
                            ),
                        )
                    )

        # Carry the attributed breakdown through the winsorization CTEs.
        self._inject_winsorization_breakdown_columns(query, aliases, final_cte_name)

        self._inject_final_breakdown_columns(query, aliases, final_cte_name=final_cte_name)

    def _read_breakdown_into_metric_events(
        self, query: ast.SelectQuery, aliases: list[str], is_session_property: bool
    ) -> None:
        """Surface the breakdown value (and an attribution timestamp) in the ``metric_events`` CTE.

        Standard path: read the breakdown directly off the metric event in ``metric_events``.

        Session-property path: ``metric_events`` joins exposures and can't see raw event
        properties, so read the breakdown off raw events in ``metric_events_by_session``
        (deduped per session via ``any()``, mirroring ``session_value``), then carry both the
        breakdown and ``first_event_timestamp`` up into ``metric_events``.
        """
        if not query.ctes:
            return

        breakdown_exprs = self.build_breakdown_exprs(table_alias="")

        if not is_session_property:
            metric_events_cte = query.ctes.get("metric_events")
            if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    metric_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))
            return

        # Read + dedupe the breakdown per session in the by-session layer.
        by_session_cte = query.ctes.get("metric_events_by_session")
        if isinstance(by_session_cte, ast.CTE) and isinstance(by_session_cte.expr, ast.SelectQuery):
            for alias, expr in breakdown_exprs:
                by_session_cte.expr.select.append(ast.Alias(alias=alias, expr=ast.Call(name="any", args=[expr])))

        # Carry the breakdown and first_event_timestamp up into metric_events for attribution.
        metric_events_cte = query.ctes.get("metric_events")
        if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
            for alias in aliases:
                metric_events_cte.expr.select.append(
                    ast.Alias(alias=alias, expr=ast.Field(chain=["metric_events_by_session", alias]))
                )
            metric_events_cte.expr.select.append(
                ast.Alias(
                    alias="first_event_timestamp",
                    expr=ast.Field(chain=["metric_events_by_session", "first_event_timestamp"]),
                )
            )

    def _inject_winsorization_breakdown_columns(
        self, query: ast.SelectQuery, aliases: list[str], final_cte_name: str
    ) -> None:
        """Carry breakdown columns through the percentiles and winsorized_entity_metrics CTEs.

        Winsorization computes per-breakdown-group percentile thresholds (preserved here, not
        changed), so the breakdown must be grouped in ``percentiles`` and joined into
        ``winsorized_entity_metrics`` on the breakdown columns.
        """
        if not (query.ctes and "percentiles" in query.ctes):
            return

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

        if final_cte_name == "winsorized_entity_metrics" and "winsorized_entity_metrics" in query.ctes:
            winsorized_cte = query.ctes["winsorized_entity_metrics"]
            if isinstance(winsorized_cte, ast.CTE) and isinstance(winsorized_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    winsorized_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["entity_metrics", alias]))
                    )
                # Convert the CROSS JOIN with percentiles into a per-breakdown-group INNER JOIN.
                if winsorized_cte.expr.select_from:
                    join_expr = winsorized_cte.expr.select_from.next_join
                    if join_expr and isinstance(join_expr, ast.JoinExpr):
                        join_expr.join_type = "JOIN"
                        join_conditions: list[ast.Expr] = [
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["percentiles", alias]),
                                right=ast.Field(chain=["entity_metrics", alias]),
                            )
                            for alias in aliases
                        ]
                        condition_expr = join_conditions[0]
                        for condition in join_conditions[1:]:
                            condition_expr = ast.And(exprs=[condition_expr, condition])
                        join_expr.constraint = ast.JoinConstraint(expr=condition_expr, constraint_type="ON")

    def inject_retention_breakdown_columns(self, query: ast.SelectQuery) -> None:
        """Inject breakdown columns into a retention query.

        Reads the breakdown off the **start event** (in ``start_events``) and attributes each
        user first-touch via ``argMin`` over the start event timestamp. Retention is a ratio
        ``retained / cohort``; the cohort (denominator) is defined by the start event and every
        retained user has one, so the start event is the only attribution source that keeps the
        per-bucket denominator well-defined. The completion event is NOT used for the breakdown —
        non-retained users have no completion event, which would break the per-bucket denominator.

        ``start_events`` groups by entity, so the breakdown is deduped per user inside it; the
        attributed value is then carried into ``entity_metrics``.
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()
        breakdown_exprs = self.build_breakdown_exprs(table_alias="")

        # Read + first-touch attribute the breakdown off the start event, deduped per entity.
        if query.ctes and "start_events" in query.ctes:
            start_events_cte = query.ctes["start_events"]
            if isinstance(start_events_cte, ast.CTE) and isinstance(start_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    start_events_cte.expr.select.append(
                        ast.Alias(
                            alias=alias,
                            expr=ast.Call(name="argMin", args=[expr, ast.Field(chain=["timestamp"])]),
                        )
                    )

        # Carry the attributed breakdown into entity_metrics and group by it.
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(alias=alias, expr=ast.Field(chain=["start_events", alias]))
                    )
                if entity_metrics_cte.expr.group_by is None:
                    entity_metrics_cte.expr.group_by = []
                for alias in aliases:
                    entity_metrics_cte.expr.group_by.append(ast.Field(chain=["start_events", alias]))

        self._inject_final_breakdown_columns(query, aliases)

    def inject_ratio_breakdown_columns(self, query: ast.SelectQuery, winsorized: bool = False) -> None:
        """Inject breakdown columns into a ratio query.

        Ratio is ``Σnumerator / Σdenominator`` over two separate event streams, pre-aggregated
        per entity before joining exposures. To keep one experiment unit = one breakdown bucket
        (so per-breakdown rows sum to the overall), the whole user is attributed by their
        **numerator event** — read off ``numerator_events``, first-touch via ``argMin`` over the
        numerator timestamp in ``numerator_agg``, then carried through ``entity_metrics``.

        When ``winsorized`` the query has ``percentiles`` and ``winsorized_entity_metrics`` CTEs;
        per-breakdown-group thresholds are preserved (not changed).
        """
        if not self._has_breakdown():
            return

        aliases = self._get_breakdown_aliases()
        final_cte_name = "winsorized_entity_metrics" if winsorized else "entity_metrics"
        breakdown_exprs = self.build_breakdown_exprs(table_alias="")

        # Read the breakdown off the numerator event.
        if query.ctes and "numerator_events" in query.ctes:
            numerator_events_cte = query.ctes["numerator_events"]
            if isinstance(numerator_events_cte, ast.CTE) and isinstance(numerator_events_cte.expr, ast.SelectQuery):
                for alias, expr in breakdown_exprs:
                    numerator_events_cte.expr.select.append(ast.Alias(alias=alias, expr=expr))

        # First-touch attribute per entity in numerator_agg (it groups by entity).
        if query.ctes and "numerator_agg" in query.ctes:
            numerator_agg_cte = query.ctes["numerator_agg"]
            if isinstance(numerator_agg_cte, ast.CTE) and isinstance(numerator_agg_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    numerator_agg_cte.expr.select.append(
                        ast.Alias(
                            alias=alias,
                            expr=ast.Call(
                                name="argMin",
                                args=[
                                    ast.Field(chain=["numerator_events", alias]),
                                    ast.Field(chain=["numerator_events", "timestamp"]),
                                ],
                            ),
                        )
                    )

        # Carry the attributed breakdown into entity_metrics (which aggregates with any()).
        if query.ctes and "entity_metrics" in query.ctes:
            entity_metrics_cte = query.ctes["entity_metrics"]
            if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                for alias in aliases:
                    entity_metrics_cte.expr.select.append(
                        ast.Alias(
                            alias=alias, expr=ast.Call(name="any", args=[ast.Field(chain=["numerator_agg", alias])])
                        )
                    )

        # Winsorization carry-through (percentiles + winsorized_entity_metrics) reuses the mean helper.
        self._inject_winsorization_breakdown_columns(query, aliases, final_cte_name)

        self._inject_final_breakdown_columns(query, aliases, final_cte_name=final_cte_name)
