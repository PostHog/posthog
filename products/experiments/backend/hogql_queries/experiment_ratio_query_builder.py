from typing import TYPE_CHECKING, cast

from posthog.schema import ExperimentDataWarehouseNode, ExperimentMetricOutlierHandling, ExperimentRatioMetric

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from products.experiments.backend.hogql_queries.metric_source import MetricSourceInfo

if TYPE_CHECKING:
    from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder


class RatioQueryBuilder:
    """
    Builds ratio-metric queries, including the winsorized variant.

    Ratio construction reuses the shared exposure and metric-value helpers
    already extracted from the experiment query builder. To keep the move
    behavior-preserving, this class holds a reference to the owning
    ``ExperimentQueryBuilder`` and reaches through it for shared state (the
    metric, entity key, breakdown injector) and those cross-cluster helpers.
    """

    def __init__(self, builder: "ExperimentQueryBuilder"):
        self._b = builder

    def build_ratio_query(self) -> ast.SelectQuery:
        """
        Builds query for ratio metrics.

        Dispatches to the winsorized variant when outlier handling is configured for
        either the numerator or the denominator.
        """
        assert isinstance(self._b.metric, ExperimentRatioMetric)

        if self.ratio_needs_winsorization():
            return self.build_ratio_query_with_winsorization()

        common_ctes, placeholders = self.get_ratio_query_common()

        query = parse_select(
            f"""
            WITH {common_ctes}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                sum(entity_metrics.numerator_value) AS total_sum,
                sum(power(entity_metrics.numerator_value, 2)) AS total_sum_of_squares,
                sum(entity_metrics.denominator_value) AS denominator_sum,
                sum(power(entity_metrics.denominator_value, 2)) AS denominator_sum_squares,
                sum(entity_metrics.numerator_value * entity_metrics.denominator_value) AS numerator_denominator_sum_product
                -- breakdown columns added programmatically below
            FROM entity_metrics
            GROUP BY entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        if self._b.breakdown_injector:
            self._b.breakdown_injector.inject_ratio_breakdown_columns(query)

        return query

    def ratio_needs_winsorization(self) -> bool:
        """Whether either component of a ratio metric has outlier handling configured."""
        assert isinstance(self._b.metric, ExperimentRatioMetric)
        for outlier_handling in (
            self._b.metric.numerator_outlier_handling,
            self._b.metric.denominator_outlier_handling,
        ):
            if outlier_handling is not None and (
                outlier_handling.lower_bound_percentile is not None
                or outlier_handling.upper_bound_percentile is not None
            ):
                return True
        return False

    def build_winsorization_bound_exprs(
        self,
        outlier_handling: ExperimentMetricOutlierHandling | None,
        value_field: str,
    ) -> tuple[ast.Expr, ast.Expr]:
        """
        Build (lower_bound, upper_bound) expressions over entity_metrics.<value_field>.

        When a bound is not configured the threshold falls back to min()/max() so the
        least(greatest(...)) clamp becomes a no-op for that side. This lets the numerator
        and denominator be capped independently — a binomial denominator simply leaves its
        outlier handling unset and is never clamped.

        value_field is an internal column name (numerator_value / denominator_value), never
        user input, so interpolating it into the expression string is safe.
        """
        lower_pct = outlier_handling.lower_bound_percentile if outlier_handling else None
        upper_pct = outlier_handling.upper_bound_percentile if outlier_handling else None
        ignore_zeros = bool(outlier_handling.ignore_zeros) if outlier_handling else False

        if lower_pct is not None:
            lower_bound_expr = parse_expr(
                f"quantileExact({{level}})(entity_metrics.{value_field})",
                placeholders={"level": ast.Constant(value=lower_pct)},
            )
        else:
            lower_bound_expr = parse_expr(f"min(entity_metrics.{value_field})")

        if upper_pct is not None:
            if ignore_zeros:
                upper_bound_expr = parse_expr(
                    f"quantileExact({{level}})(if(entity_metrics.{value_field} != 0, entity_metrics.{value_field}, null))",
                    placeholders={"level": ast.Constant(value=upper_pct)},
                )
            else:
                upper_bound_expr = parse_expr(
                    f"quantileExact({{level}})(entity_metrics.{value_field})",
                    placeholders={"level": ast.Constant(value=upper_pct)},
                )
        else:
            upper_bound_expr = parse_expr(f"max(entity_metrics.{value_field})")

        return lower_bound_expr, upper_bound_expr

    def build_ratio_query_with_winsorization(self) -> ast.SelectQuery:
        """
        Builds query for ratio metrics with winsorization (outlier handling).

        The numerator and denominator are capped independently, each as if it were its own
        mean metric: percentile thresholds are computed separately for each component (pooled
        across all variations) and the per-entity numerator and denominator values are clamped
        against their own bounds. The capped components flow into the same aggregate columns
        (including the cross-product) so the delta-method variance stays consistent with the
        capped point estimate.
        """
        assert isinstance(self._b.metric, ExperimentRatioMetric)

        common_ctes, placeholders = self.get_ratio_query_common()

        num_lower_bound, num_upper_bound = self.build_winsorization_bound_exprs(
            self._b.metric.numerator_outlier_handling, "numerator_value"
        )
        denom_lower_bound, denom_upper_bound = self.build_winsorization_bound_exprs(
            self._b.metric.denominator_outlier_handling, "denominator_value"
        )

        placeholders["numerator_lower_bound"] = num_lower_bound
        placeholders["numerator_upper_bound"] = num_upper_bound
        placeholders["denominator_lower_bound"] = denom_lower_bound
        placeholders["denominator_upper_bound"] = denom_upper_bound

        query = parse_select(
            f"""
            WITH {common_ctes},

            percentiles AS (
                SELECT
                    {{numerator_lower_bound}} AS numerator_lower_bound,
                    {{numerator_upper_bound}} AS numerator_upper_bound,
                    {{denominator_lower_bound}} AS denominator_lower_bound,
                    {{denominator_upper_bound}} AS denominator_upper_bound
                    -- breakdown columns added programmatically below
                FROM entity_metrics
                -- GROUP BY added programmatically below if breakdowns exist
            ),

            winsorized_entity_metrics AS (
                SELECT
                    entity_metrics.entity_id AS entity_id,
                    entity_metrics.variant AS variant,
                    least(greatest(percentiles.numerator_lower_bound, entity_metrics.numerator_value), percentiles.numerator_upper_bound) AS numerator_value,
                    least(greatest(percentiles.denominator_lower_bound, entity_metrics.denominator_value), percentiles.denominator_upper_bound) AS denominator_value
                    -- breakdown columns added programmatically below
                FROM entity_metrics
                CROSS JOIN percentiles
                -- JOIN conditions added programmatically below if breakdowns exist
            )

            SELECT
                winsorized_entity_metrics.variant AS variant,
                count(winsorized_entity_metrics.entity_id) AS num_users,
                sum(winsorized_entity_metrics.numerator_value) AS total_sum,
                sum(power(winsorized_entity_metrics.numerator_value, 2)) AS total_sum_of_squares,
                sum(winsorized_entity_metrics.denominator_value) AS denominator_sum,
                sum(power(winsorized_entity_metrics.denominator_value, 2)) AS denominator_sum_squares,
                sum(winsorized_entity_metrics.numerator_value * winsorized_entity_metrics.denominator_value) AS numerator_denominator_sum_product
                -- breakdown columns added programmatically below
            FROM winsorized_entity_metrics
            GROUP BY winsorized_entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject breakdown columns into the query AST
        if self._b.breakdown_injector:
            self._b.breakdown_injector.inject_ratio_breakdown_columns(query, winsorized=True)

        return query

    def get_ratio_query_common(self) -> tuple[str, dict[str, ast.Expr]]:
        """
        Builds the shared CTE chain and placeholders for ratio metric queries.

        Optimized structure using pre-aggregation to reduce join operations:
        - exposures: all exposures with variant assignment (with exposure_identifier for data warehouse)
        - numerator_events / denominator_events: events for each component with value
        - numerator_agg / denominator_agg: per-entity aggregates joined to exposures
        - entity_metrics: single row per entity carrying numerator_value and denominator_value

        This approach reduces memory pressure by joining exposures to events only once
        per component instead of fanning out the raw event rows.
        """
        assert isinstance(self._b.metric, ExperimentRatioMetric)

        # Use MetricSourceInfo abstraction for both numerator and denominator
        num_source_info = MetricSourceInfo.from_source(self._b.metric.numerator, entity_key=self._b.entity_key)
        denom_source_info = MetricSourceInfo.from_source(self._b.metric.denominator, entity_key=self._b.entity_key)

        # Extract field names for numerator
        num_table = num_source_info.table_name
        num_entity_field = num_source_info.entity_key
        num_timestamp_field = num_source_info.timestamp_field

        # Extract field names for denominator
        denom_table = denom_source_info.table_name
        denom_entity_field = denom_source_info.entity_key
        denom_timestamp_field = denom_source_info.timestamp_field

        # Build exposure query with conditional exposure_identifier(s)
        exposure_query = self._b._get_exposure_query()
        if num_source_info.kind == "datawarehouse" or denom_source_info.kind == "datawarehouse":
            # Add exposure_identifier fields for data warehouse joins
            # Support different join keys for numerator and denominator
            if num_source_info.kind == "datawarehouse":
                num_source = cast(ExperimentDataWarehouseNode, self._b.metric.numerator)
                num_join_key_parts = cast(list[str | int], num_source.events_join_key.split("."))

                # Use argMin to pick one exposure_identifier per entity_id (from first exposure)
                # This prevents fan-out when a user has multiple exposures with different join key values
                exposure_query.select.append(
                    ast.Alias(
                        alias="exposure_identifier_num",
                        expr=ast.Call(
                            name="argMin",
                            args=[ast.Field(chain=num_join_key_parts), ast.Field(chain=["timestamp"])],
                        ),
                    )
                )
                # Do NOT add to GROUP BY - that would cause fan-out when join key varies across exposures

            if denom_source_info.kind == "datawarehouse":
                denom_source = cast(ExperimentDataWarehouseNode, self._b.metric.denominator)
                denom_join_key_parts = cast(list[str | int], denom_source.events_join_key.split("."))

                # Use argMin to pick one exposure_identifier per entity_id (from first exposure)
                # This prevents fan-out when a user has multiple exposures with different join key values
                exposure_query.select.append(
                    ast.Alias(
                        alias="exposure_identifier_denom",
                        expr=ast.Call(
                            name="argMin",
                            args=[ast.Field(chain=denom_join_key_parts), ast.Field(chain=["timestamp"])],
                        ),
                    )
                )
                # Do NOT add to GROUP BY - that would cause fan-out when join key varies across exposures

        # Build join conditions for pre-aggregation CTEs based on DW scenario
        if num_source_info.kind == "datawarehouse":
            num_preagg_join = "toString(exposures.exposure_identifier_num) = toString(numerator_events.entity_id)"
        else:
            num_preagg_join = "exposures.entity_id = numerator_events.entity_id"

        if denom_source_info.kind == "datawarehouse":
            denom_preagg_join = "toString(exposures.exposure_identifier_denom) = toString(denominator_events.entity_id)"
        else:
            denom_preagg_join = "exposures.entity_id = denominator_events.entity_id"

        # Pre-aggregation approach: aggregate events per entity_id FIRST, then join
        # This dramatically reduces memory usage by avoiding large intermediate result sets
        # Memory impact: 471M rows → ~2M rows in joins
        common_ctes = f"""
            exposures AS (
                {{exposure_select_query}}
            ),

            numerator_events AS (
                SELECT
                    {{num_entity_key}} AS entity_id,
                    {{num_timestamp_field}} AS timestamp,
                    {{numerator_value_expr}} AS value
                FROM {{num_table}}
                WHERE {{numerator_predicate}}
            ),

            denominator_events AS (
                SELECT
                    {{denom_entity_key}} AS entity_id,
                    {{denom_timestamp_field}} AS timestamp,
                    {{denominator_value_expr}} AS value
                FROM {{denom_table}}
                WHERE {{denominator_predicate}}
            ),

            numerator_agg AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    {{numerator_agg}} AS value
                FROM numerator_events
                JOIN exposures ON {num_preagg_join}
                WHERE {{numerator_conversion_window}}
                GROUP BY exposures.entity_id
            ),

            denominator_agg AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    {{denominator_agg}} AS value
                FROM denominator_events
                JOIN exposures ON {denom_preagg_join}
                WHERE {{denominator_conversion_window}}
                GROUP BY exposures.entity_id
            ),

            entity_metrics AS (
                SELECT
                    exposures.variant AS variant,
                    exposures.entity_id AS entity_id,
                    any(coalesce(numerator_agg.value, 0)) AS numerator_value,
                    any(coalesce(denominator_agg.value, 0)) AS denominator_value
                    -- breakdown columns added programmatically below
                FROM exposures
                LEFT JOIN numerator_agg ON exposures.entity_id = numerator_agg.entity_id
                LEFT JOIN denominator_agg ON exposures.entity_id = denominator_agg.entity_id
                GROUP BY exposures.variant, exposures.entity_id
                -- breakdown columns added programmatically below
            )
        """

        placeholders: dict[str, ast.Expr] = {
            "exposure_select_query": exposure_query,
            "num_entity_key": num_entity_field,
            "denom_entity_key": denom_entity_field,
            "num_timestamp_field": ast.Field(chain=[num_timestamp_field]),
            "num_table": ast.Field(chain=[num_table]),
            "denom_timestamp_field": ast.Field(chain=[denom_timestamp_field]),
            "denom_table": ast.Field(chain=[denom_table]),
            "numerator_predicate": self._b._build_metric_predicate(
                source=self._b.metric.numerator, table_alias=num_table
            ),
            "numerator_value_expr": self._b._build_value_expr(source=self._b.metric.numerator),
            "numerator_agg": self._b._build_value_aggregation_expr(
                source=self._b.metric.numerator, events_alias="numerator_events", column_name="value"
            ),
            "numerator_conversion_window": self._b._build_conversion_window_predicate_for_events("numerator_events"),
            "denominator_predicate": self._b._build_metric_predicate(
                source=self._b.metric.denominator, table_alias=denom_table
            ),
            "denominator_value_expr": self._b._build_value_expr(source=self._b.metric.denominator),
            "denominator_agg": self._b._build_value_aggregation_expr(
                source=self._b.metric.denominator, events_alias="denominator_events", column_name="value"
            ),
            "denominator_conversion_window": self._b._build_conversion_window_predicate_for_events(
                "denominator_events"
            ),
        }

        return common_ctes, placeholders
