from typing import TYPE_CHECKING, Optional, cast

from django.utils import timezone

from posthog.schema import ExperimentDataWarehouseNode, ExperimentFunnelMetric, MultipleVariantHandling, StepOrderValue

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.dataclasses import frozen

from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY
from products.experiments.backend.hogql_queries.base_query_utils import (
    data_warehouse_node_to_filter,
    funnel_evaluation_expr,
    funnel_steps_to_filter,
)
from products.experiments.backend.hogql_queries.funnel_step_builder import FunnelStepBuilder
from products.experiments.backend.hogql_queries.funnel_validation import FunnelDWValidator
from products.experiments.backend.hogql_queries.metric_source import MetricSourceInfo

if TYPE_CHECKING:
    from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder


@frozen
class FunnelTemporalSetup:
    first_exposures_cte: str
    temporal_join: str
    having_clause: str


class FunnelQueryBuilder:
    """
    Builds funnel-metric queries (aggregate results and the metric-events
    precomputation write query).

    Funnel construction is coupled to the rest of the experiment query builder:
    it reads the metric and CUPED config, calls shared exposure and metric-value
    helpers, and the CUPED and maturity helpers call back into the funnel helpers.
    So this class holds a reference to the owning ``ExperimentQueryBuilder`` and
    reads that shared state and those helpers through it.
    """

    def __init__(self, builder: "ExperimentQueryBuilder"):
        self._b = builder

    def build_funnel_query(self) -> ast.SelectQuery:
        if self.should_use_optimized_funnel_query():
            return self.build_funnel_query_optimized()
        return self.build_funnel_query_legacy()

    def should_use_optimized_funnel_query(self) -> bool:
        # With precomputed exposures, the exposures CTE of the legacy path reads from a
        # cheap preaggregated table, so its second scan costs little.
        if self._b.preaggregation_job_ids and not self._b.breakdowns:
            return False
        # Only the legacy path implements the UNION ALL pattern for DW funnels.
        if isinstance(self._b.metric, ExperimentFunnelMetric) and self.has_datawarehouse_steps():
            return False
        # Activation-mode exposure is a join against flag exposures, not a single-event
        # predicate, so it cannot be inlined into the single-scan WHERE and its step_0
        # variant attribution. The legacy path consumes the exposures CTE as a black box.
        if self._b.context.activation_config is not None:
            return False
        return True

    def build_funnel_query_legacy(self) -> ast.SelectQuery:
        """
        3-CTE funnel query: exposures, metric_events, entity_metrics.
        The name "legacy" comes from before the single-scan optimized path existed.
        It is still the primary path for precomputed queries, because both the
        exposures and the metric_events CTEs can read from precomputed tables here.

        Supports two patterns:
        1. Events-only: Single query with boolean step columns
        2. With DW steps: UNION ALL pattern with separate subqueries per source
        """
        assert isinstance(self._b.metric, ExperimentFunnelMetric)

        FunnelDWValidator.validate_funnel_metric(self._b.metric)

        num_steps = len(self._b.metric.series) + 1  # +1 for step_0, the exposure step

        has_dw_steps = self.has_datawarehouse_steps()

        # Precomputed metric events already extract the step columns from the steps
        # array, so the step column injection below is skipped for them.
        inject_step_columns = True

        if self._b.metric_events_preaggregation_job_ids and not has_dw_steps:
            inject_step_columns = False
            step_extracts = ", ".join(f"arrayElement(t.steps, {i + 1}) AS step_{i}" for i in range(num_steps))
            entity_id_cast = "toUUID(t.entity_id)" if self._b.entity_key == "person_id" else "t.entity_id"

            # Filter by experiment date range: jobs can cover broader time ranges
            # than the experiment for cache reusability, so we must filter on read.
            # Upper bound includes conversion window since funnel step events can
            # occur after experiment end.
            conversion_window_seconds = self._b._get_conversion_window_seconds()
            if conversion_window_seconds > 0:
                upper_bound = f"{{metric_events_date_to}} + toIntervalSecond({conversion_window_seconds})"
            else:
                upper_bound = "{metric_events_date_to}"

            metric_events_cte_str = f"""
                    metric_events AS (
                        SELECT
                            {entity_id_cast} AS entity_id,
                            t.timestamp AS timestamp,
                            t.event_uuid AS uuid,
                            {step_extracts}
                        FROM experiment_metric_events_preaggregated AS t
                        WHERE t.job_id IN {{metric_events_job_ids}}
                            AND t.team_id = {{metric_events_team_id}}
                            AND t.timestamp >= {{metric_events_date_from}}
                            AND t.timestamp <= {upper_bound}
                    )
            """
        elif has_dw_steps:
            metric_events_cte_str = """
                    metric_events AS (
                        SELECT 1 AS placeholder
                        -- This will be replaced with UNION ALL query
                    )
            """
        else:
            metric_events_cte_str = f"""
                    metric_events AS (
                        SELECT
                            {{entity_key}} AS entity_id,
                            {{variant_property}} as variant,
                            timestamp,
                            uuid,
                            -- step_0, step_1, ... step_N columns added programmatically below
                        FROM events
                        WHERE ({{exposure_predicate}} OR {{funnel_steps_filter}})
                    )
            """

        is_unordered_funnel = self._b.metric.funnel_order_type == StepOrderValue.UNORDERED

        # Unordered funnels need the temporal filter because the funnel UDF does not drop
        # events before the exposure. Ordered funnels do not need it, because the UDF
        # enforces the step order. Activation mode needs it for ordered funnels too:
        # step_0 rows are plain activation-event matches, and the UDF's ordering cannot
        # express "at or after the first flag exposure", so the join must exclude events
        # before the qualifying activation.
        is_activation_mode = self._b.context.activation_config is not None
        temporal_filter = (
            "AND metric_events.timestamp >= exposures.first_exposure_time"
            if is_unordered_funnel or is_activation_mode
            else ""
        )

        # DW steps join via events_join_key (e.g. properties.$user_id) → data_warehouse_join_key
        # (e.g. userid). The exposure CTE uses person_id (UUID) as entity_id. To bridge
        # these, we add an exposure_identifier column and join on that instead.
        if has_dw_steps:
            entity_id_join = "ON toString(exposures.exposure_identifier) = metric_events.entity_id"
        else:
            entity_id_join = "ON exposures.entity_id = metric_events.entity_id"

        ctes_sql = f"""
            exposures AS (
                {{exposure_select_query}}
            ),

            {metric_events_cte_str},

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    {{funnel_aggregation}} AS value
                    -- covariate_value added programmatically below when CUPED is enabled
                FROM exposures
                LEFT JOIN metric_events
                    {entity_id_join}
                    {temporal_filter}
                GROUP BY
                    exposures.entity_id,
                    exposures.variant
            )
        """

        exposure_query = self._b._get_exposure_query()
        if has_dw_steps:
            # FunnelDWValidator guarantees that all DW steps use the same events_join_key
            first_dw_step = next(s for s in self._b.metric.series if isinstance(s, ExperimentDataWarehouseNode))
            events_join_key_parts = cast(list[str | int], first_dw_step.events_join_key.split("."))

            # argMin takes the join key value from the first exposure. This prevents fan-out
            # when the exposures of one entity have different join key values.
            exposure_query.select.append(
                ast.Alias(
                    alias="exposure_identifier",
                    expr=ast.Call(
                        name="argMin",
                        args=[ast.Field(chain=events_join_key_parts), ast.Field(chain=["timestamp"])],
                    ),
                )
            )

        placeholders: dict[str, ast.Expr | ast.SelectQuery] = {
            "exposure_predicate": self._b._build_exposure_step_predicate(),
            "variant_property": self._b._build_variant_property(),
            "variant_expr": self.build_variant_expr_for_funnel(),
            "entity_key": parse_expr(self._b.entity_key),
            "funnel_steps_filter": self.build_funnel_steps_filter(),
            "funnel_aggregation": self.build_funnel_aggregation_expr(),
            "num_steps_minus_1": ast.Constant(value=num_steps - 1),
            "exposure_select_query": exposure_query,
            "date_from": self._b.date_range_query.date_from_as_hogql(),
            "date_to": self._b.date_range_query.date_to_as_hogql(),
        }
        if self._b.metric_events_preaggregation_job_ids:
            placeholders["metric_events_job_ids"] = ast.Constant(value=self._b.metric_events_preaggregation_job_ids)
            placeholders["metric_events_team_id"] = ast.Constant(value=self._b.team.id)
            placeholders["metric_events_date_from"] = self._b.date_range_query.date_from_as_hogql()
            placeholders["metric_events_date_to"] = self._b.date_range_query.date_to_as_hogql()

        query = parse_select(
            f"""
            WITH
            {ctes_sql}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                -- The funnel UDF returns a zero-indexed step, so an entity that reaches the
                -- last step returns num_steps - 1
                countIf(entity_metrics.value.1 = {{num_steps_minus_1}}) AS total_sum,
                countIf(entity_metrics.value.1 = {{num_steps_minus_1}}) AS total_sum_of_squares
                -- CUPED aggregation columns added programmatically below
                -- step_counts added programmatically below
                -- breakdown columns added programmatically below
            FROM entity_metrics
            WHERE notEmpty(variant)
            GROUP BY entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        if self._b.cuped_config.enabled:
            self._b._inject_funnel_covariate_into_entity_metrics(
                query,
                events_alias="metric_events",
                last_step_index=num_steps - 1,
                exposure_alias="exposures",
            )

        if self._b.breakdown_injector:
            self._b.breakdown_injector.inject_funnel_breakdown_columns(query)

        if query.ctes and "metric_events" in query.ctes:
            if has_dw_steps:
                union_query = self.build_funnel_metric_events_union_query()
                query.ctes["metric_events"] = ast.CTE(name="metric_events", expr=union_query, cte_type="subquery")
            else:
                if inject_step_columns:
                    metric_events_cte = query.ctes["metric_events"]
                    if isinstance(metric_events_cte, ast.CTE) and isinstance(metric_events_cte.expr, ast.SelectQuery):
                        step_columns = self.build_funnel_step_columns()
                        metric_events_cte.expr.select.extend(step_columns)

        # step_counts feeds the funnel chart: the number of entities that reached each step
        step_count_exprs = []
        for i in range(1, num_steps):
            step_count_exprs.append(f"countIf(entity_metrics.value.1 >= {i})")
        step_counts_expr = f"tuple({', '.join(step_count_exprs)}) as step_counts"

        query.select.append(parse_expr(step_counts_expr))

        return query

    def build_funnel_query_optimized(self) -> ast.SelectQuery:
        """
        Optimized funnel query: eliminates the second events table scan and the
        intermediate JOIN. Uses 2 CTEs for ordered funnels, 3 for unordered:

        Ordered:   base_events -> entity_metrics -> final SELECT
        Unordered: base_events -> first_exposures -> entity_metrics -> final SELECT

        base_events: single scan of events, computes step_0/step_1/variant_value inline
        first_exposures: (unordered only) min exposure time per entity for temporal filtering
        entity_metrics: GROUP BY entity_id, conditional aggregation for variant, funnel UDF
        """
        assert isinstance(self._b.metric, ExperimentFunnelMetric)

        num_steps = len(self._b.metric.series) + 1  # +1 for step_0, the exposure step

        # WHERE admits both exposure and conversion events. Exclusion filters are
        # embedded in step_0 only, not the WHERE clause, so conversion events from
        # internal users pass through (they only matter if the user has a valid exposure).
        base_events_cte_str = f"""
                base_events AS (
                    SELECT
                        {{entity_key}} AS entity_id,
                        {{variant_property}} AS variant_value,
                        timestamp,
                        uuid,
                        -- step_0, step_1, ... step_N columns added programmatically below
                    FROM events
                    WHERE ({{exposure_predicate}} OR {{funnel_steps_filter}})
                )
        """

        is_unordered_funnel = self._b.metric.funnel_order_type == StepOrderValue.UNORDERED

        temporal_setup = self.build_funnel_optimized_temporal_setup(is_unordered_funnel)

        ctes_sql = f"""
            {base_events_cte_str},
            {temporal_setup.first_exposures_cte}
            entity_metrics AS (
                SELECT
                    base_events.entity_id AS entity_id,
                    {{variant_expr}} AS variant,
                    {{funnel_aggregation}} AS value
                    -- covariate_value added programmatically below when CUPED is enabled
                FROM base_events
                {temporal_setup.temporal_join}
                GROUP BY base_events.entity_id{temporal_setup.having_clause}
            )
        """

        placeholders: dict[str, ast.Expr | ast.SelectQuery] = {
            "exposure_predicate": self._b._build_exposure_predicate(),
            "variant_property": self._b._build_variant_property(),
            "variant_expr": self.build_variant_expr_for_funnel_optimized(),
            "entity_key": parse_expr(self._b.entity_key),
            "funnel_steps_filter": self.build_funnel_steps_filter(),
            "funnel_aggregation": self.build_funnel_aggregation_expr_optimized(),
            "num_steps_minus_1": ast.Constant(value=num_steps - 1),
        }

        query = parse_select(
            f"""
            WITH
            {ctes_sql}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                -- The funnel UDF returns a zero-indexed step, so an entity that reaches the
                -- last step returns num_steps - 1
                countIf(entity_metrics.value.1 = {{num_steps_minus_1}}) AS total_sum,
                countIf(entity_metrics.value.1 = {{num_steps_minus_1}}) AS total_sum_of_squares
                -- CUPED aggregation columns added programmatically below
                -- step_counts added programmatically below
                -- breakdown columns added programmatically below
            FROM entity_metrics
            WHERE notEmpty(variant)
            GROUP BY entity_metrics.variant
            -- breakdown columns added programmatically below
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        if self._b.cuped_config.enabled:
            self._b._inject_funnel_covariate_into_entity_metrics(
                query,
                events_alias="base_events",
                last_step_index=num_steps - 1,
                exposure_alias="first_exposures",
            )

        if self._b.breakdown_injector:
            self._b.breakdown_injector.inject_funnel_breakdown_columns_optimized(query)

        if query.ctes and "base_events" in query.ctes:
            base_events_cte = query.ctes["base_events"]
            if isinstance(base_events_cte, ast.CTE) and isinstance(base_events_cte.expr, ast.SelectQuery):
                step_columns = self.build_funnel_step_columns()
                base_events_cte.expr.select.extend(step_columns)

        maturity_having = self.build_maturity_having_clause_optimized()
        if maturity_having is not None:
            if query.ctes and "entity_metrics" in query.ctes:
                entity_metrics_cte = query.ctes["entity_metrics"]
                if isinstance(entity_metrics_cte, ast.CTE) and isinstance(entity_metrics_cte.expr, ast.SelectQuery):
                    if entity_metrics_cte.expr.having is None:
                        entity_metrics_cte.expr.having = maturity_having
                    else:
                        entity_metrics_cte.expr.having = ast.And(
                            exprs=[entity_metrics_cte.expr.having, maturity_having]
                        )

        # step_counts feeds the funnel chart: the number of entities that reached each step
        step_count_exprs = []
        for i in range(1, num_steps):
            step_count_exprs.append(f"countIf(entity_metrics.value.1 >= {i})")
        step_counts_expr = f"tuple({', '.join(step_count_exprs)}) as step_counts"

        query.select.append(parse_expr(step_counts_expr))

        return query

    def build_funnel_optimized_temporal_setup(self, is_unordered_funnel: bool) -> FunnelTemporalSetup:
        """
        The first_exposures CTE, temporal join and HAVING clause of the optimized
        funnel query depend on three cases:

        - Unordered funnels need temporal filtering because the UDF doesn't
          enforce that step_0 (exposure) precedes step_1..N. We exclude events
          before first exposure with an INNER JOIN + WHERE.
        - CUPED needs the per-entity exposure timestamp to scope the pre-window
          covariate, so we materialize first_exposures even when ordered. No
          WHERE filter is added: the aggregate_funnel_array UDF anchors on
          step_0 (date-bounded by the exposure predicate), so pre-window events
          with step_X=1 (X>0) are never used in the post-window result.
        - Otherwise, no first_exposures CTE; HAVING countIf(step_0 = 1) > 0
          is the cheapest way to keep only exposed entities.
        """
        needs_first_exposures = is_unordered_funnel or self._b.cuped_config.enabled

        first_exposures_cte_str = (
            """
            first_exposures AS (
                SELECT entity_id, min(timestamp) AS first_exposure_time
                FROM base_events
                WHERE step_0 = 1
                GROUP BY entity_id
            ),"""
            if needs_first_exposures
            else ""
        )

        if is_unordered_funnel:
            temporal_join = """INNER JOIN first_exposures
                    ON base_events.entity_id = first_exposures.entity_id
                WHERE base_events.timestamp >= first_exposures.first_exposure_time"""
            having_clause = ""
        elif self._b.cuped_config.enabled:
            temporal_join = """INNER JOIN first_exposures
                    ON base_events.entity_id = first_exposures.entity_id"""
            having_clause = ""
        else:
            temporal_join = ""
            having_clause = """
                HAVING countIf(step_0 = 1) > 0"""

        return FunnelTemporalSetup(
            first_exposures_cte=first_exposures_cte_str,
            temporal_join=temporal_join,
            having_clause=having_clause,
        )

    def build_variant_expr_for_funnel(self) -> ast.Expr:
        if self._b.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            return parse_expr(
                "argMinIf(variant, timestamp, step_0 = 1)",
            )
        else:
            return parse_expr(
                "if(uniqExactIf(variant, step_0 = 1) > 1, {multiple_key}, anyIf(variant, step_0 = 1))",
                placeholders={
                    "multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )

    def get_funnel_metric_events_query_for_precomputation(self) -> tuple[str, dict[str, ast.Expr]]:
        """
        Returns the SELECT query that the lazy computation system wraps in an
        INSERT INTO experiment_metric_events_preaggregated. This is the write
        path: it scans the events table and stores one row per matching event,
        with the step indicators packed into an Array(UInt8).

        The query uses {time_window_min} and {time_window_max} placeholders filled
        by the lazy computation system for each daily bucket.
        """
        assert isinstance(self._b.metric, ExperimentFunnelMetric)

        step_builder = FunnelStepBuilder(self._b.metric.series, self._b.team)

        exposure_filter_sql = """
            timestamp >= {experiment_date_from}
            AND timestamp <= {experiment_date_to}
            AND {exposure_event_predicate}
            AND {test_accounts_filter}
            AND {variant_property} IN {variants}
        """
        step_filter_placeholders: dict[str, ast.Expr] = {}
        step_exprs_sql = [f"_toUInt8(if({exposure_filter_sql}, 1, 0))"]
        for step_index, step_source in enumerate(self._b.metric.series, start=1):
            placeholder_name = f"step_filter_{step_index}"
            step_filter_placeholders[placeholder_name] = step_builder._build_step_filter(step_source)
            step_exprs_sql.append(f"_toUInt8(if({{{placeholder_name}}}, 1, 0))")

        steps_array_sql = f"[{', '.join(step_exprs_sql)}]"
        conversion_window_seconds = self._b._get_conversion_window_seconds()

        funnel_steps_filter_sql = """
            timestamp >= {experiment_date_from}
            AND timestamp <= {experiment_date_to} + toIntervalSecond({conversion_window_seconds})
            AND {funnel_steps_filter}
            """

        query_string = f"""
            SELECT
                {{entity_key}} AS entity_id,
                timestamp AS timestamp,
                uuid AS event_uuid,
                `$session_id` AS session_id,
                {steps_array_sql} AS steps
            FROM events
            WHERE timestamp >= {{time_window_min}}
                AND timestamp < {{time_window_max}}
                AND (({exposure_filter_sql}) OR ({funnel_steps_filter_sql}))
        """

        placeholders: dict[str, ast.Expr] = {
            "entity_key": parse_expr(self._b.entity_key),
            **step_filter_placeholders,
            "exposure_event_predicate": self._b._exposure_query_builder().build_exposure_event_predicate(),
            "test_accounts_filter": self._b._exposure_query_builder().build_test_accounts_filter(),
            "variant_property": self._b._build_variant_property(),
            "variants": ast.Constant(value=list(self._b.variants)),
            "experiment_date_from": self._b.date_range_query.date_from_as_hogql(),
            "experiment_date_to": self._b.date_range_query.date_to_as_hogql(),
            "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
            "funnel_steps_filter": funnel_steps_to_filter(self._b.team, self._b.metric.series),
        }

        return query_string, placeholders

    def build_funnel_step_columns(self) -> list[ast.Alias]:
        assert isinstance(self._b.metric, ExperimentFunnelMetric)

        has_dw_nodes = any(isinstance(step, ExperimentDataWarehouseNode) for step in self._b.metric.series)

        if has_dw_nodes:
            raise NotImplementedError(
                "ExperimentDataWarehouseNode is not yet supported in funnel metrics. "
                "Mixed-source UNION ALL query pattern needs to be implemented."
            )

        step_builder = FunnelStepBuilder(self._b.metric.series, self._b.team)
        exposure_filter = self._b._build_exposure_step_predicate()
        return step_builder.build_boolean_columns(exposure_filter)

    def build_funnel_steps_filter(self) -> ast.Expr:
        """
        Returns the expression to filter funnel steps (matches ANY step) within
        the time period of the experiment + the conversion window if set.

        When CUPED is enabled, the lower bound is rolled back by `lookback_days`
        so the same scan also feeds the CUPED pre-exposure window.
        """
        assert isinstance(self._b.metric, ExperimentFunnelMetric)

        conversion_window_seconds = self._b._get_conversion_window_seconds()
        if conversion_window_seconds > 0:
            date_to = parse_expr(
                "{to_date} + toIntervalSecond({conversion_window_seconds})",
                placeholders={
                    "to_date": self._b.date_range_query.date_to_as_hogql(),
                    "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                },
            )
        else:
            date_to = self._b.date_range_query.date_to_as_hogql()

        date_from = self._b._extend_date_from_for_funnel_cuped(self._b.date_range_query.date_from_as_hogql())

        return parse_expr(
            """
            timestamp >= {date_from} AND timestamp <= {date_to}
            AND {funnel_steps_filter}
            """,
            placeholders={
                "date_from": date_from,
                "date_to": date_to,
                "funnel_steps_filter": funnel_steps_to_filter(self._b.team, self._b.metric.series),
            },
        )

    def build_funnel_aggregation_expr(self) -> ast.Expr:
        """
        Returns the funnel evaluation expression using aggregate_funnel_array.
        """
        assert isinstance(self._b.metric, ExperimentFunnelMetric)
        return funnel_evaluation_expr(self._b.team, self._b.metric, events_alias="metric_events", include_exposure=True)

    def has_datawarehouse_steps(self) -> bool:
        assert isinstance(self._b.metric, ExperimentFunnelMetric)
        return any(isinstance(step, ExperimentDataWarehouseNode) for step in self._b.metric.series)

    def build_funnel_metric_events_union_query(self) -> ast.SelectSetQuery:
        """metric_events as a UNION ALL of one events subquery and one subquery per DW step."""
        assert isinstance(self._b.metric, ExperimentFunnelMetric)

        step_builder = FunnelStepBuilder(self._b.metric.series, self._b.team)

        # FunnelDWValidator guarantees that all DW steps use the same events_join_key
        first_dw_step = next(s for s in self._b.metric.series if isinstance(s, ExperimentDataWarehouseNode))
        events_join_key = first_dw_step.events_join_key

        # The events subquery is always present, because it carries the exposure step
        events_subquery = self.build_funnel_events_subquery_for_union(step_builder, events_join_key)

        dw_subqueries = []
        for i, step in enumerate(self._b.metric.series):
            if isinstance(step, ExperimentDataWarehouseNode):
                dw_subquery = self.build_funnel_dw_step_subquery(step, i + 1, step_builder)
                dw_subqueries.append(dw_subquery)

        all_subqueries = [events_subquery, *dw_subqueries]
        result = ast.SelectSetQuery.create_from_queries(all_subqueries, "UNION ALL")

        # create_from_queries returns a SelectQuery for one query, but there are always at least two: events and DW
        assert isinstance(result, ast.SelectSetQuery)
        return result

    def build_funnel_events_subquery_for_union(
        self, step_builder: FunnelStepBuilder, events_join_key: str
    ) -> ast.SelectQuery:
        """
        Events subquery for the UNION ALL pattern, with these step columns:
        - step_0: 1 for an exposure event, else 0
        - step_N for an event or action step: 1 when the event matches, else 0
        - step_N for a DW step: always 0, because the DW subqueries supply those rows
        """
        assert isinstance(self._b.metric, ExperimentFunnelMetric)

        # Use events_join_key as entity_id so it matches the DW subquery's
        # data_warehouse_join_key (both resolve to the same user identifier).
        events_join_key_parts = cast(list[str | int], events_join_key.split("."))
        entity_id_expr = ast.Call(name="toString", args=[ast.Field(chain=events_join_key_parts)])

        select_fields: list[ast.Expr] = [
            ast.Alias(alias="entity_id", expr=entity_id_expr),
            ast.Alias(alias="variant", expr=self._b._build_variant_property()),
            ast.Alias(alias="timestamp", expr=ast.Field(chain=["timestamp"])),
            ast.Alias(alias="uuid", expr=ast.Field(chain=["uuid"])),
            ast.Alias(alias="session_id", expr=ast.Field(chain=["properties", "$session_id"])),
        ]

        exposure_filter = self._b._build_exposure_step_predicate()

        step_0 = ast.Alias(
            alias="step_0",
            expr=ast.Call(
                name="if",
                args=[exposure_filter, ast.Constant(value=1), ast.Constant(value=0)],
            ),
        )
        select_fields.append(step_0)

        # Build step filters once, reuse for both SELECT and WHERE
        step_filters: dict[int, ast.Expr] = {}
        for i, step_source in enumerate(self._b.metric.series):
            if not isinstance(step_source, ExperimentDataWarehouseNode):
                step_filters[i + 1] = step_builder._build_step_filter(step_source)

        for i, step_source in enumerate(self._b.metric.series):
            step_index = i + 1  # +1 because step_0 is exposure

            if isinstance(step_source, ExperimentDataWarehouseNode):
                step_col = ast.Alias(
                    alias=f"step_{step_index}",
                    expr=ast.Constant(value=0),
                )
            else:
                step_col = ast.Alias(
                    alias=f"step_{step_index}",
                    expr=ast.Call(
                        name="if",
                        args=[step_filters[step_index], ast.Constant(value=1), ast.Constant(value=0)],
                    ),
                )

            select_fields.append(step_col)

        event_action_filters = list(step_filters.values())

        conversion_window_seconds = self._b._get_conversion_window_seconds()
        date_to_expr: ast.Expr
        if conversion_window_seconds > 0:
            date_to_expr = ast.Call(
                name="plus",
                args=[
                    self._b.date_range_query.date_to_as_hogql(),
                    ast.Call(
                        name="toIntervalSecond",
                        args=[ast.Constant(value=conversion_window_seconds)],
                    ),
                ],
            )
        else:
            date_to_expr = self._b.date_range_query.date_to_as_hogql()

        time_range_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=self._b.date_range_query.date_from_as_hogql(),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=ast.Field(chain=["timestamp"]),
                    right=date_to_expr,
                ),
            ]
        )

        where: ast.Expr
        if event_action_filters:
            step_match = ast.Or(exprs=[self._b._build_exposure_step_predicate(), ast.Or(exprs=event_action_filters)])
            where = ast.And(exprs=[time_range_filter, step_match])
        else:
            # All steps are DW steps, so this subquery only needs the exposure events
            where = ast.And(exprs=[time_range_filter, self._b._build_exposure_step_predicate()])

        query = ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=where,
        )

        return query

    def build_funnel_dw_step_subquery(
        self,
        step: ExperimentDataWarehouseNode,
        step_index: int,
        step_builder: FunnelStepBuilder,
    ) -> ast.SelectQuery:
        """Subquery for one DW step. `step_index` is 1-based, because step_0 is the exposure step."""
        assert isinstance(self._b.metric, ExperimentFunnelMetric)

        source_info = MetricSourceInfo.from_source(step, entity_key=None)

        # list is invariant, so list[Alias] needs a cast to list[Expr]
        select_fields: list[ast.Expr] = cast(list[ast.Expr], source_info.build_select_fields())

        step_columns = step_builder.build_constant_columns(active_step_index=step_index)
        select_fields.extend(step_columns)

        where = self.build_dw_step_predicate(step, source_info)

        query = ast.SelectQuery(
            select=select_fields,
            select_from=ast.JoinExpr(table=ast.Field(chain=[source_info.table_name])),
            where=where,
        )

        return query

    def build_dw_step_predicate(
        self,
        step: ExperimentDataWarehouseNode,
        source_info: MetricSourceInfo,
    ) -> ast.Expr:
        """
        Filters the DW table on the experiment date range plus the conversion window,
        and on the DW node's property filters.
        """
        assert isinstance(self._b.metric, ExperimentFunnelMetric)

        conversion_window_seconds = self._b._get_conversion_window_seconds()

        # Use the unqualified field name, because a qualified name breaks for dotted DW table names
        timestamp_field = ast.Field(chain=[source_info.timestamp_field])

        # date_from <= timestamp < date_to + conversion_window
        date_from_expr = self._b.date_range_query.date_from_as_hogql()
        date_to_expr = self._b.date_range_query.date_to_as_hogql()

        date_to_with_window: ast.Expr
        if conversion_window_seconds > 0:
            date_to_with_window = ast.Call(
                name="plus",
                args=[
                    date_to_expr,
                    ast.Call(
                        name="toIntervalSecond",
                        args=[ast.Constant(value=conversion_window_seconds)],
                    ),
                ],
            )
        else:
            date_to_with_window = date_to_expr

        timestamp_filter = ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=timestamp_field,
                    right=date_from_expr,
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Lt,
                    left=timestamp_field,
                    right=date_to_with_window,
                ),
            ]
        )

        dw_filter = data_warehouse_node_to_filter(self._b.team, step)

        return ast.And(exprs=[timestamp_filter, dw_filter])

    def build_variant_expr_for_funnel_optimized(self) -> ast.Expr:
        """
        Variant expression for the optimized funnel path.
        References variant_value (raw property) instead of variant (column in legacy metric_events).
        """
        if self._b.multiple_variant_handling == MultipleVariantHandling.FIRST_SEEN:
            return parse_expr(
                "argMinIf(variant_value, timestamp, step_0 = 1)",
            )
        else:
            return parse_expr(
                "if(uniqExactIf(variant_value, step_0 = 1) > 1, {multiple_key}, anyIf(variant_value, step_0 = 1))",
                placeholders={
                    "multiple_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )

    def build_funnel_aggregation_expr_optimized(self) -> ast.Expr:
        """
        Funnel aggregation for the optimized path. References base_events instead of metric_events.
        """
        assert isinstance(self._b.metric, ExperimentFunnelMetric)
        return funnel_evaluation_expr(self._b.team, self._b.metric, events_alias="base_events", include_exposure=True)

    def build_maturity_having_clause_optimized(self) -> Optional[ast.Expr]:
        """
        Maturity HAVING clause for the optimized path.
        Uses minIf to anchor maturity on the user's first exposure (step_0 = 1),
        matching how the variant is assigned (argMinIf on first exposure). Anchoring
        on the last exposure would keep resetting the window for flags re-evaluated
        repeatedly (e.g. backend flags), so active users would never mature.
        """
        if self._b.metric is None:
            return None
        if not self._b.only_count_matured_users:
            return None

        maturity_seconds = self._b._get_maturity_window_seconds()
        if maturity_seconds == 0:
            return None

        now = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        return parse_expr(
            "minIf(timestamp, step_0 = 1) + toIntervalSecond({maturity_seconds}) <= toDateTime({now}, 'UTC')",
            placeholders={
                "maturity_seconds": ast.Constant(value=maturity_seconds),
                "now": ast.Constant(value=now),
            },
        )
