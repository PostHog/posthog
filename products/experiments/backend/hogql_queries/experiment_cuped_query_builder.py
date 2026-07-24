from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

if TYPE_CHECKING:
    from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder


class CupedQueryBuilder:
    """
    Builds the CUPED (Controlled-experiment Using Pre-Experiment Data) query
    fragments shared across mean and funnel metrics.

    CUPED reduces variance by regressing the post-exposure metric on a
    covariate computed from a pre-exposure lookback window. The fragments here
    are the cross-cutting pieces that mean and funnel orchestration both reach
    for; metric-shaped wiring (how the fragments are slotted into each metric's
    SELECT/placeholders) stays with the respective metric builders.

    Output columns
    --------------
    When CUPED is enabled, the query output includes:

    - ``covariate_sum``        — sum of the per-entity covariate
    - ``covariate_sum_squares``— sum of the squared per-entity covariate
    - ``covariate_sum_product``— sum of (metric value x covariate) per entity

    These three sums are consumed by ``cuped_adjust`` downstream. For mean
    metrics the covariate is the pre-window metric value; for funnel metrics it
    is a binary indicator (see ``build_funnel_covariate_value_expr``).

    Scan-window behavior
    --------------------
    The covariate is computed over the pre-exposure lookback window
    ``[first_exposure_time - lookback_days, first_exposure_time)``. To populate
    that window without a second scan, the metric event scan is widened so its
    ``date_from`` rolls back by ``lookback_days`` (see
    ``extend_date_from_for_funnel_cuped`` for the funnel case; mean metrics widen
    via ``build_metric_predicate``'s ``cuped_lookback_days`` argument).

    To keep the move behavior-preserving, this class holds a reference to the
    owning ``ExperimentQueryBuilder`` and reaches through it for the CUPED
    config.
    """

    def __init__(self, builder: "ExperimentQueryBuilder"):
        self._b = builder

    def build_cuped_pre_window_predicate(
        self,
        events_alias: str = "metric_events",
        exposure_alias: str = "exposures",
    ) -> ast.Expr:
        return parse_expr(
            f"""
            {events_alias}.timestamp >= {exposure_alias}.first_exposure_time - toIntervalDay({{lookback_days}})
            AND {events_alias}.timestamp < {exposure_alias}.first_exposure_time
            """,
            placeholders={"lookback_days": ast.Constant(value=self._b.cuped_config.lookback_days)},
        )

    def build_windowed_metric_value_expr(
        self, window_predicate: ast.Expr, events_alias: str = "metric_events"
    ) -> ast.Expr:
        return parse_expr(
            "if({window_predicate}, {metric_value}, NULL)",
            placeholders={
                "window_predicate": window_predicate,
                "metric_value": ast.Field(chain=[events_alias, "value"]),
            },
        )

    def build_funnel_covariate_value_expr(
        self,
        *,
        events_alias: str,
        last_step_index: int,
        exposure_alias: str,
    ) -> ast.Expr:
        """
        Per-entity binary covariate for funnel CUPED: 1 if the entity fired the
        funnel's last step inside the pre-exposure window, else 0.

        The covariate has to be binary to keep the same Bernoulli scale as the
        post-window proportion metric, and aligns with the example pattern of
        treating the conversion event as both the metric and the covariate.
        """
        return parse_expr(
            f"coalesce(maxIf(1, {events_alias}.step_{last_step_index} = 1 AND {{pre_window}}), 0)",
            placeholders={"pre_window": self.build_cuped_pre_window_predicate(events_alias, exposure_alias)},
        )

    def build_funnel_cuped_aggregation_aliases(self, last_step_index: int) -> list[ast.Expr]:
        """
        Outer-SELECT aliases that aggregate the per-entity covariate into the
        sums consumed by `cuped_adjust`. The cross-product term multiplies the
        user-level conversion indicator (value.1 = last_step_index) with the
        binary covariate.
        """
        return [
            parse_expr("sum(entity_metrics.covariate_value) AS covariate_sum"),
            parse_expr("sum(power(entity_metrics.covariate_value, 2)) AS covariate_sum_squares"),
            parse_expr(
                "sum(if(entity_metrics.value.1 = {n}, 1, 0) * entity_metrics.covariate_value) AS covariate_sum_product",
                placeholders={"n": ast.Constant(value=last_step_index)},
            ),
        ]

    def inject_funnel_covariate_into_entity_metrics(
        self,
        query: ast.SelectQuery,
        *,
        events_alias: str,
        last_step_index: int,
        exposure_alias: str,
    ) -> None:
        """
        Adds `covariate_value` to the entity_metrics CTE, plus the aggregation
        aliases (`covariate_sum`, `covariate_sum_squares`, `covariate_sum_product`)
        to the outer SELECT.

        Asserts the expected `entity_metrics` CTE shape: this method is called
        right after the funnel SELECT is parsed in the funnel builder, so the
        shape is an invariant — a violation means the SQL above changed without
        updating CUPED, and we want a loud failure rather than zeroed covariates.
        """
        assert query.ctes is not None and "entity_metrics" in query.ctes
        entity_metrics_cte = query.ctes["entity_metrics"]
        assert isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery)
        entity_metrics_cte.expr.select.append(
            ast.Alias(
                alias="covariate_value",
                expr=self.build_funnel_covariate_value_expr(
                    events_alias=events_alias,
                    last_step_index=last_step_index,
                    exposure_alias=exposure_alias,
                ),
            )
        )
        query.select.extend(self.build_funnel_cuped_aggregation_aliases(last_step_index))

    def extend_date_from_for_funnel_cuped(self, date_from: ast.Expr) -> ast.Expr:
        """
        Roll the funnel's `date_from` back by `lookback_days` when CUPED is
        enabled, so the same scan also feeds the CUPED pre-exposure window.
        Returns the input unchanged when CUPED is off.
        """
        if not self._b.cuped_config.enabled:
            return date_from
        return parse_expr(
            "{date_from} - toIntervalDay({lookback_days})",
            placeholders={
                "date_from": date_from,
                "lookback_days": ast.Constant(value=self._b.cuped_config.lookback_days),
            },
        )
