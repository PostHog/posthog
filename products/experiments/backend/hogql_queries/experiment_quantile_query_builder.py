from typing import TYPE_CHECKING

from posthog.schema import ExperimentQuantileMetric

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.parser import parse_select

from products.experiments.backend.hogql_queries.experiment_exposure_query_builder import ExposureQueryBuilder
from products.experiments.backend.hogql_queries.metric_source import MetricSourceInfo
from products.experiments.stats.shared.statistics import quantile_grid_levels

if TYPE_CHECKING:
    from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder


def quantile_query_levels(quantile: float) -> list[float]:
    """
    The probability levels of quantilesExact: the quantile level, then L and U for each grid size.

    utils.read_variant_quantile reads the returned quantile_grid array in this order.
    """
    levels = [quantile]
    for grid_level in quantile_grid_levels(quantile):
        levels.extend([grid_level.lower_level, grid_level.upper_level])
    return levels


class QuantileQueryBuilder:
    """
    Builds event-level quantile-metric queries.

    The quantile is taken over all qualifying events of a variant, pooled across
    entities. The query also returns the per-entity sums that the clustered variance
    of QuantileStatistic needs: Σ S_i, Σ S_i², Σ N_i, Σ N_i² and Σ S_i·N_i, where
    N_i is the number of events of entity i and S_i the number of those events
    with a value at or below the variant quantile.

    With breakdowns, each row holds a variant and a breakdown, and S_i counts against the
    quantile of that breakdown. Quantiles do not add up, so the row also returns the sums
    with S_i counted against the quantile of the whole variant, in the overall_* columns.
    Those sums add up over the breakdowns of a variant to its overall row.
    """

    def __init__(self, builder: "ExperimentQueryBuilder", exposure: ExposureQueryBuilder):
        self._b = builder
        self._exposure = exposure

    def build_quantile_query(self) -> ast.SelectQuery:
        metric = self._b.metric
        assert isinstance(metric, ExperimentQuantileMetric)

        # Metric validation rejects this. The check guards stored or ad-hoc queries that skip it.
        if not metric.source.math_property:
            raise ExposedHogQLError("A percentile metric needs a numeric property to measure.")

        source_info = MetricSourceInfo.from_source(metric.source, entity_key=self._b.entity_key)

        has_breakdowns = bool(self._b.breakdowns)
        overall_quantiles_cte = (
            """
            overall_quantiles AS (
                SELECT
                    variant_events.variant AS variant,
                    {overall_quantile_grid_expr} AS quantile_grid
                FROM variant_events
                GROUP BY variant_events.variant
            ),
"""
            if has_breakdowns
            else ""
        )
        overall_entity_columns = (
            """,
                    countIf(variant_events.value <= overall_quantiles.quantile_grid[1]) AS events_below_overall_quantile,
                    any(overall_quantiles.quantile_grid) AS overall_quantile_grid"""
            if has_breakdowns
            else ""
        )
        overall_quantiles_join = (
            """
                JOIN overall_quantiles ON variant_events.variant = overall_quantiles.variant"""
            if has_breakdowns
            else ""
        )
        overall_columns = (
            """,
                sum(coalesce(entity_stats.events_below_overall_quantile, 0)) AS overall_total_sum,
                sum(power(coalesce(entity_stats.events_below_overall_quantile, 0), 2)) AS overall_total_sum_of_squares,
                sum(coalesce(entity_stats.events_below_overall_quantile, 0) * coalesce(entity_stats.event_count, 0)) AS overall_numerator_denominator_sum_product,
                anyIf(entity_stats.overall_quantile_grid, notEmpty(entity_stats.overall_quantile_grid)) AS overall_quantile_grid"""
            if has_breakdowns
            else ""
        )

        # nosemgrep: hogql-fstring-audit (the f-string only inserts the constant overall_* fragments above; values go through placeholders)
        query = parse_select(
            f"""
            WITH
            exposures AS (
                {{exposure_select_query}}
            ),

            metric_events AS (
                SELECT
                    {{entity_key}} AS entity_id,
                    {{metric_timestamp_field}} AS timestamp,
                    {{value_expr}} AS value
                FROM {{metric_table}}
                WHERE {{metric_predicate}}
            ),

            variant_events AS (
                SELECT
                    exposures.variant AS variant,
                    exposures.entity_id AS entity_id,
                    metric_events.value AS value
                FROM metric_events
                JOIN exposures ON exposures.entity_id = metric_events.entity_id
                WHERE {{conversion_window_predicate}}
                    AND metric_events.value IS NOT NULL
            ),

            variant_quantiles AS (
                SELECT
                    variant_events.variant AS variant,
                    {{quantile_grid_expr}} AS quantile_grid
                FROM variant_events
                GROUP BY variant_events.variant
            ),
{overall_quantiles_cte}
            -- ClickHouse runs a CTE once per reference, so the grid travels through entity_stats and the
            -- quantile aggregation runs once. An exposed user without events gets an empty grid from the
            -- LEFT JOIN, and anyIf skips it, so a variant without events keeps an empty grid.
            entity_stats AS (
                SELECT
                    variant_events.variant AS variant,
                    variant_events.entity_id AS entity_id,
                    countIf(variant_events.value <= variant_quantiles.quantile_grid[1]) AS events_below_quantile,
                    count() AS event_count,
                    any(variant_quantiles.quantile_grid) AS quantile_grid{overall_entity_columns}
                FROM variant_events
                JOIN variant_quantiles ON variant_events.variant = variant_quantiles.variant{overall_quantiles_join}
                GROUP BY variant_events.variant, variant_events.entity_id
            )

            SELECT
                exposures.variant AS variant,
                count(exposures.entity_id) AS num_users,
                sum(coalesce(entity_stats.events_below_quantile, 0)) AS total_sum,
                sum(power(coalesce(entity_stats.events_below_quantile, 0), 2)) AS total_sum_of_squares,
                sum(coalesce(entity_stats.event_count, 0)) AS denominator_sum,
                sum(power(coalesce(entity_stats.event_count, 0), 2)) AS denominator_sum_squares,
                sum(coalesce(entity_stats.events_below_quantile, 0) * coalesce(entity_stats.event_count, 0)) AS numerator_denominator_sum_product,
                anyIf(entity_stats.quantile_grid, notEmpty(entity_stats.quantile_grid)) AS quantile_grid{overall_columns}
            FROM exposures
            LEFT JOIN entity_stats
                ON exposures.entity_id = entity_stats.entity_id
                AND exposures.variant = entity_stats.variant
            GROUP BY exposures.variant
            """,
            placeholders={
                "exposure_select_query": self._exposure.select_query(),
                "entity_key": source_info.entity_key,
                "metric_timestamp_field": ast.Field(chain=[source_info.timestamp_field]),
                "metric_table": ast.Field(chain=[source_info.table_name]),
                "metric_predicate": self._b._build_metric_predicate(
                    source=metric.source, table_alias=source_info.table_name
                ),
                # `math` does not apply to a quantile metric, so read the property directly instead of
                # through build_value_expr(), which returns a constant 1 for count math. HogQL toFloat()
                # returns NULL for a missing or non-numeric value, and the IS NOT NULL filter drops those
                # events: a missing load time is not a load time of 0.
                "value_expr": ast.Call(
                    name="toFloat", args=[ast.Field(chain=["properties", metric.source.math_property])]
                ),
                "conversion_window_predicate": self._b._build_conversion_window_predicate(),
                "quantile_grid_expr": self._quantile_grid_expr(metric.quantile),
                "overall_quantile_grid_expr": self._quantile_grid_expr(metric.quantile),
            },
        )
        assert isinstance(query, ast.SelectQuery)

        if self._b.breakdown_injector:
            self._b.breakdown_injector.inject_quantile_breakdown_columns(query)

        return query

    @staticmethod
    def _quantile_grid_expr(quantile: float) -> ast.Call:
        # quantilesExact, because the approximate quantile functions have an error larger than
        # the distance between the grid levels at large n*, which would turn Y_U - Y_L into noise.
        return ast.Call(
            name="quantilesExact",
            params=[ast.Constant(value=level) for level in quantile_query_levels(quantile)],
            args=[ast.Field(chain=["variant_events", "value"])],
        )
