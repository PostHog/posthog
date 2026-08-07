from typing import TYPE_CHECKING, cast

from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentMeanMetric,
    MultipleBreakdownType,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.insights.trends.utils import get_properties_chain
from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_NULL_STRING_LABEL, BREAKDOWN_OTHER_STRING_LABEL

from products.experiments.backend.hogql_queries.base_query_utils import (
    event_or_action_to_filter,
    is_session_property_metric,
    validate_session_property,
)
from products.experiments.backend.hogql_queries.metric_source import MetricSourceInfo

if TYPE_CHECKING:
    from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder

# ponytail: top-20 fixed; make configurable if anyone asks
VALUE_BREAKDOWN_MAX_BUCKETS = 20


class MeanQueryBuilder:
    """
    Builds mean-metric queries (count, sum, avg, etc.), including the
    winsorized and session-property variants.

    Mean construction reuses the shared exposure, metric-value, and CUPED
    helpers already extracted from the experiment query builder. To keep the
    move behavior-preserving, this class holds a reference to the owning
    ``ExperimentQueryBuilder`` and reaches through it for shared state (the
    metric, entity key, CUPED config, breakdown injector) and those
    cross-cluster helpers.
    """

    def __init__(self, builder: "ExperimentQueryBuilder"):
        self._b = builder

    def get_session_property_ctes(self) -> str:
        """
        Returns CTEs for session property metrics with proper deduplication.

        Session properties require special handling to avoid the multiplication bug:
        - Without deduplication: each event in a session contributes the full session value
        - With deduplication: each session contributes exactly once

        Pattern:
        1. metric_events_by_session: GROUP BY $session_id, get any(session.$property)
        2. metric_events: Join with exposures, filter by temporal ordering
        3. entity_metrics: Aggregate across sessions per entity
        """
        assert isinstance(self._b.metric, ExperimentMeanMetric)
        assert isinstance(self._b.metric.source, (ActionsNode, EventsNode))

        session_property = validate_session_property(self._b.metric.source)

        return f"""
            exposures AS (
                {{exposure_select_query}}
            ),

            -- Layer 1: Deduplicate within sessions
            -- Each session contributes exactly one value regardless of event count
            metric_events_by_session AS (
                SELECT
                    {{entity_key}} AS entity_id,
                    `$session_id` AS session_id,
                    any(session.`{session_property}`) AS session_value,
                    min(timestamp) AS first_event_timestamp
                FROM events
                WHERE {{metric_predicate}}
                    AND `$session_id` IS NOT NULL
                    AND `$session_id` != ''
                GROUP BY {{entity_key}}, `$session_id`
            ),

            -- Layer 2: Join with exposures, filter by temporal ordering
            metric_events AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    toFloat(coalesce(metric_events_by_session.session_value, 0)) AS value,
                    metric_events_by_session.session_id AS session_id
                FROM exposures
                INNER JOIN metric_events_by_session
                    ON exposures.entity_id = metric_events_by_session.entity_id
                    AND metric_events_by_session.first_event_timestamp >= exposures.first_exposure_time
                    AND {{session_conversion_window_predicate}}
            ),

            -- Layer 3: Aggregate across sessions per entity
            entity_metrics AS (
                SELECT
                    entity_id,
                    variant,
                    {{value_agg}} AS value
                FROM metric_events
                GROUP BY entity_id, variant
            )
        """

    def get_mean_query_common_ctes(self) -> str:
        """
        Returns the common CTEs used by both regular and winsorized mean queries.
        Supports both regular events and data warehouse sources.
        """
        assert isinstance(self._b.metric, ExperimentMeanMetric)

        # Check if this is a session property metric - use special CTE structure
        if isinstance(self._b.metric.source, (ActionsNode, EventsNode)) and is_session_property_metric(
            self._b.metric.source
        ):
            return self.get_session_property_ctes()

        # Use MetricSourceInfo abstraction for source metadata
        source_info = MetricSourceInfo.from_source(self._b.metric.source, entity_key=self._b.entity_key)

        # Determine join condition based on source type
        if source_info.kind == "datawarehouse":
            join_condition = "{join_condition}"
        else:
            join_condition = "exposures.entity_id = metric_events.entity_id"

        if self._b.cuped_config.enabled:
            join_window_predicate = "({conversion_window_predicate} OR {cuped_pre_window_predicate})"
            entity_metric_selects = """
                    {value_agg} AS value,
                    {covariate_value_agg} AS covariate_value"""
        else:
            join_window_predicate = "{conversion_window_predicate}"
            entity_metric_selects = """
                    {value_agg} AS value"""

        if self._b.metric_events_preaggregation_job_ids:
            # Read from the precomputed table instead of scanning events. Only reachable
            # for eligible metrics (no breakdowns/CUPED/DW/session properties), so the
            # branches above never coexist with this one.
            # Filter by experiment date range: jobs can cover broader time ranges than
            # the experiment for cache reusability, so we must filter on read. The upper
            # bound includes the conversion window since metric events can occur after
            # experiment end, mirroring build_metric_predicate() on the direct path.
            # GROUP BY collapses replayed rows by event identity: ReplacingMergeTree only
            # dedups at merge time and this read doesn't use FINAL, so a re-applied build
            # INSERT would otherwise double-count sums. Same defense as the exposures read;
            # the funnel read skips it because funnel evaluation tolerates duplicate events.
            entity_id_cast = "toUUID(t.entity_id)" if self._b.entity_key == "person_id" else "t.entity_id"
            metric_events_cte = f"""
            metric_events AS (
                SELECT
                    {entity_id_cast} AS entity_id,
                    t.timestamp AS timestamp,
                    any(t.numeric_value) AS value
                FROM experiment_metric_events_preaggregated AS t
                WHERE t.job_id IN {{metric_events_job_ids}}
                    AND t.team_id = {{metric_events_team_id}}
                    AND t.timestamp >= {{metric_events_date_from}}
                    AND t.timestamp < {{metric_events_date_to}} + toIntervalSecond({{metric_events_conversion_window_seconds}})
                GROUP BY t.entity_id, t.timestamp, t.event_uuid
            )"""
        else:
            metric_events_cte = """
            metric_events AS (
                SELECT
                    {entity_key} AS entity_id,
                    {metric_timestamp_field} AS timestamp,
                    {value_expr} AS value
                    -- breakdown columns added programmatically below
                FROM {metric_table}
                WHERE {metric_predicate}
            )"""

        return f"""
            exposures AS (
                {{exposure_select_query}}
            ),

            {metric_events_cte},

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
{entity_metric_selects}
                    -- breakdown columns added programmatically below
                FROM exposures
                LEFT JOIN metric_events ON {join_condition}
                    AND {join_window_predicate}
                GROUP BY exposures.entity_id, exposures.variant
                -- breakdown columns added programmatically below
            )
        """

    def get_mean_query_common_placeholders(self) -> dict:
        """
        Returns the common placeholders used by both regular and winsorized mean queries.
        Supports both regular events and data warehouse sources.
        """
        assert isinstance(self._b.metric, ExperimentMeanMetric)

        # Check if this is a session property metric - use different placeholders
        is_session_property = isinstance(
            self._b.metric.source, (ActionsNode, EventsNode)
        ) and is_session_property_metric(self._b.metric.source)

        if is_session_property:
            return self.get_session_property_placeholders()

        # Use MetricSourceInfo abstraction for source metadata
        source_info = MetricSourceInfo.from_source(self._b.metric.source, entity_key=self._b.entity_key)

        # Build exposure query with exposure_identifier for data warehouse
        exposure_query = self._b._get_exposure_query()
        if source_info.kind == "datawarehouse":
            assert isinstance(self._b.metric.source, ExperimentDataWarehouseNode)
            events_join_key_parts = cast(list[str | int], self._b.metric.source.events_join_key.split("."))

            # Use argMin to pick one exposure_identifier per entity_id (from first exposure)
            # This prevents fan-out when a user has multiple exposures with different join key values
            exposure_query.select.append(
                ast.Alias(
                    alias="exposure_identifier",
                    expr=ast.Call(
                        name="argMin",
                        args=[ast.Field(chain=events_join_key_parts), ast.Field(chain=["timestamp"])],
                    ),
                )
            )
            # Do NOT add to GROUP BY - that would cause fan-out when join key varies across exposures

        metric_predicate = self._b._build_metric_predicate(
            table_alias=source_info.table_name,
            cuped_lookback_days=self._b.cuped_config.lookback_days if self._b.cuped_config.enabled else None,
        )
        conversion_window_predicate = self._b._build_conversion_window_predicate()

        placeholders: dict = {
            "exposure_select_query": exposure_query,
            "entity_key": source_info.entity_key,
            "metric_timestamp_field": ast.Field(chain=[source_info.timestamp_field]),
            "metric_table": ast.Field(chain=[source_info.table_name]),
            "metric_predicate": metric_predicate,
            "value_expr": self._b._build_value_expr(),
            "value_agg": self._b._build_value_aggregation_expr(
                value_expr=self._b._build_windowed_metric_value_expr(conversion_window_predicate)
                if self._b.cuped_config.enabled
                else None
            ),
            "conversion_window_predicate": conversion_window_predicate,
        }

        if self._b.cuped_config.enabled:
            cuped_pre_window_predicate = self._b._build_cuped_pre_window_predicate()
            placeholders["cuped_pre_window_predicate"] = cuped_pre_window_predicate
            placeholders["covariate_value_agg"] = self._b._build_value_aggregation_expr(
                value_expr=self._b._build_windowed_metric_value_expr(cuped_pre_window_predicate)
            )

        if self._b.metric_events_preaggregation_job_ids:
            placeholders["metric_events_job_ids"] = ast.Constant(value=self._b.metric_events_preaggregation_job_ids)
            placeholders["metric_events_team_id"] = ast.Constant(value=self._b.team.id)
            placeholders["metric_events_date_from"] = self._b.date_range_query.date_from_as_hogql()
            placeholders["metric_events_date_to"] = self._b.date_range_query.date_to_as_hogql()
            placeholders["metric_events_conversion_window_seconds"] = ast.Constant(
                value=self._b._get_conversion_window_seconds()
            )

        # Add join condition for data warehouse
        if source_info.kind == "datawarehouse":
            placeholders["join_condition"] = parse_expr(
                "toString(exposures.exposure_identifier) = toString(metric_events.entity_id)"
            )

        return placeholders

    def get_session_property_placeholders(self) -> dict:
        """
        Returns placeholders specific to session property metrics.
        Session properties use a different CTE structure with deduplication per session.
        """
        assert isinstance(self._b.metric, ExperimentMeanMetric)

        exposure_query = self._b._get_exposure_query()

        return {
            "exposure_select_query": exposure_query,
            "entity_key": parse_expr(self._b.entity_key),
            "metric_predicate": self._b._build_metric_predicate(table_alias="events"),
            "value_agg": self._b._build_value_aggregation_expr(),
            "session_conversion_window_predicate": self._b._build_session_conversion_window_predicate(),
        }

    def get_mean_metric_events_query_for_precomputation(self) -> tuple[str, dict[str, ast.Expr]]:
        """
        Returns the SELECT query that the lazy computation system wraps in an
        INSERT INTO experiment_metric_events_preaggregated. This is the write
        path — it scans the events table and stores one row per matching metric
        event with its per-event value in numeric_value. The value is already
        coalesced to a non-null float by _build_value_expr(), so storing it in
        the non-nullable numeric_value column is lossless.

        The query uses {time_window_min} and {time_window_max} placeholders filled
        by the lazy computation system for each daily bucket. The experiment date
        bounds must stay named placeholders (the caller declares experiment_date_to
        a sentinel) rather than reusing _build_metric_predicate(), which bakes the
        resolved dates into the AST — a running experiment's moving window end
        would then change the job hash and defeat cache reuse.

        Returns:
            Tuple of (query_string, placeholders_dict)
        """
        assert isinstance(self._b.metric, ExperimentMeanMetric)
        source = self._b.metric.source
        assert isinstance(source, (ActionsNode, EventsNode))

        query_string = """
            SELECT
                {entity_key} AS entity_id,
                timestamp AS timestamp,
                uuid AS event_uuid,
                `$session_id` AS session_id,
                {value_expr} AS numeric_value
            FROM events
            WHERE timestamp >= {time_window_min}
                AND timestamp < {time_window_max}
                AND timestamp >= {experiment_date_from}
                AND timestamp < {experiment_date_to} + toIntervalSecond({conversion_window_seconds})
                AND {metric_event_filter}
        """

        placeholders: dict[str, ast.Expr] = {
            "entity_key": parse_expr(self._b.entity_key),
            "value_expr": self._b._build_value_expr(),
            "experiment_date_from": self._b.date_range_query.date_from_as_hogql(),
            "experiment_date_to": self._b.date_range_query.date_to_as_hogql(),
            "conversion_window_seconds": ast.Constant(value=self._b._get_conversion_window_seconds()),
            "metric_event_filter": event_or_action_to_filter(self._b.team, source),
        }

        return query_string, placeholders

    def build_mean_query(self) -> ast.SelectQuery:
        """
        Builds query for mean metrics (count, sum, avg, etc.)
        """
        assert isinstance(self._b.metric, ExperimentMeanMetric)

        # Check if we need to apply winsorization (outlier handling)
        needs_winsorization = (
            self._b.metric.lower_bound_percentile is not None or self._b.metric.upper_bound_percentile is not None
        )

        if needs_winsorization:
            return self.build_mean_query_with_winsorization()

        common_ctes = self.get_mean_query_common_ctes()
        cuped_selects = (
            """,
                sum(entity_metrics.covariate_value) AS covariate_sum,
                sum(power(entity_metrics.covariate_value, 2)) AS covariate_sum_squares,
                sum(entity_metrics.value * entity_metrics.covariate_value) AS covariate_sum_product"""
            if self._b.cuped_config.enabled
            else ""
        )

        # When a threshold is set, each user's value collapses to a binary "reached the
        # threshold" outcome, turning the mean into a proportion. total_sum becomes the
        # count of users who crossed; sum_of_squares equals it since 1^2 = 1 and 0^2 = 0.
        if self._b.metric.threshold is not None:
            per_user_value = "if(entity_metrics.value >= {threshold}, 1, 0)"
            total_sum_expr = f"sum({per_user_value})"
            total_sum_squares_expr = total_sum_expr
        else:
            total_sum_expr = "sum(entity_metrics.value)"
            total_sum_squares_expr = "sum(power(entity_metrics.value, 2))"

        placeholders = self.get_mean_query_common_placeholders()
        if self._b.metric.threshold is not None:
            placeholders["threshold"] = ast.Constant(value=self._b.metric.threshold)

        query = parse_select(
            f"""
            WITH {common_ctes}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                {total_sum_expr} AS total_sum,
                {total_sum_squares_expr} AS total_sum_of_squares{cuped_selects}
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
            self._b.breakdown_injector.inject_mean_breakdown_columns(query, final_cte_name="entity_metrics")

        return query

    def build_mean_query_with_winsorization(self) -> ast.SelectQuery:
        """
        Builds query for mean metrics with winsorization (outlier handling).
        This clamps entity-level values to percentile-based bounds.
        """
        assert isinstance(self._b.metric, ExperimentMeanMetric)

        # Build lower bound expression
        if self._b.metric.lower_bound_percentile is not None:
            lower_bound_expr = parse_expr(
                "quantileExact({level})(entity_metrics.value)",
                placeholders={"level": ast.Constant(value=self._b.metric.lower_bound_percentile)},
            )
        else:
            lower_bound_expr = parse_expr("min(entity_metrics.value)")

        # Build upper bound expression
        if self._b.metric.upper_bound_percentile is not None:
            # Handle ignore_zeros flag for upper bound calculation
            if getattr(self._b.metric, "ignore_zeros", False):
                upper_bound_expr = parse_expr(
                    "quantileExact({level})(if(entity_metrics.value != 0, entity_metrics.value, null))",
                    placeholders={"level": ast.Constant(value=self._b.metric.upper_bound_percentile)},
                )
            else:
                upper_bound_expr = parse_expr(
                    "quantileExact({level})(entity_metrics.value)",
                    placeholders={"level": ast.Constant(value=self._b.metric.upper_bound_percentile)},
                )
        else:
            upper_bound_expr = parse_expr("max(entity_metrics.value)")

        common_ctes = self.get_mean_query_common_ctes()
        placeholders = self.get_mean_query_common_placeholders()
        winsorized_cuped_select = (
            """,
                    entity_metrics.covariate_value AS covariate_value"""
            if self._b.cuped_config.enabled
            else ""
        )
        cuped_selects = (
            """,
                sum(winsorized_entity_metrics.covariate_value) AS covariate_sum,
                sum(power(winsorized_entity_metrics.covariate_value, 2)) AS covariate_sum_squares,
                sum(winsorized_entity_metrics.value * winsorized_entity_metrics.covariate_value) AS covariate_sum_product"""
            if self._b.cuped_config.enabled
            else ""
        )

        # Add winsorization-specific placeholders
        placeholders["lower_bound"] = lower_bound_expr
        placeholders["upper_bound"] = upper_bound_expr

        query = parse_select(
            f"""
            WITH {common_ctes},

            percentiles AS (
                SELECT
                    {{lower_bound}} AS lower_bound,
                    {{upper_bound}} AS upper_bound
                    -- breakdown columns added programmatically below
                FROM entity_metrics
                -- GROUP BY added programmatically below if breakdowns exist
            ),

            winsorized_entity_metrics AS (
                SELECT
                    entity_metrics.entity_id AS entity_id,
                    entity_metrics.variant AS variant,
                    least(greatest(percentiles.lower_bound, entity_metrics.value), percentiles.upper_bound) AS value{winsorized_cuped_select}
                    -- breakdown columns added programmatically below
                FROM entity_metrics
                CROSS JOIN percentiles
                -- JOIN conditions added programmatically below if breakdowns exist
            )

            SELECT
                winsorized_entity_metrics.variant AS variant,
                count(winsorized_entity_metrics.entity_id) AS num_users,
                sum(winsorized_entity_metrics.value) AS total_sum,
                sum(power(winsorized_entity_metrics.value, 2)) AS total_sum_of_squares{cuped_selects}
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
            self._b.breakdown_injector.inject_mean_breakdown_columns(query, final_cte_name="winsorized_entity_metrics")

        return query

    def _build_value_breakdown_expr(self, breakdown_property: str, table_alias: str) -> ast.Expr:
        """
        Builds the expression that reads the split property off the metric event.

        Mirrors BreakdownInjector's NULL handling (coalesce to the shared null label) so an
        absent property lands in a single, recognizable bucket instead of vanishing.
        """
        properties_chain = get_properties_chain(
            breakdown_type=cast(MultipleBreakdownType, "event"),
            breakdown_field=breakdown_property,
            group_type_index=None,
        )
        property_expr = ast.Field(chain=[table_alias, *properties_chain])
        return parse_expr(
            "coalesce(toString({property_expr}), {null_label})",
            placeholders={
                "property_expr": property_expr,
                "null_label": ast.Constant(value=BREAKDOWN_NULL_STRING_LABEL),
            },
        )

    def build_mean_value_breakdown_query(self, breakdown_property: str) -> ast.SelectQuery:
        """
        Builds the effect-decomposition query: one row per (variant, metric-event property value).

        This is deliberately *not* the breakdown path. Breakdown partitions users (one bucket per
        user, attributed from the exposure event) and gives each segment its own denominator. This
        instead splits the metric *value* read off the metric event across the full exposed
        population: a single user can contribute to several values, and every split keeps the full
        per-variant exposure count as its denominator. Because each metric event maps to exactly one
        value, the per-value sums add back to the un-split total (Σ_v sum_v == total_sum), so the
        per-value means decompose the overall mean.

        Only valid for count ('total') and 'sum' math, with an event/action source — both enforced
        by the runner before this is called.

        High-cardinality properties are capped: only the top VALUE_BREAKDOWN_MAX_BUCKETS values by
        total |contribution| keep their own bucket; the rest roll into the shared "Other" label.
        """
        assert isinstance(self._b.metric, ExperimentMeanMetric)
        assert isinstance(self._b.metric.source, (ActionsNode, EventsNode)), (
            "value breakdown only supports event/action sources"
        )

        source_info = MetricSourceInfo.from_source(self._b.metric.source, entity_key=self._b.entity_key)

        placeholders: dict = {
            "exposure_select_query": self._b._get_exposure_query(),
            "entity_key": source_info.entity_key,
            "metric_timestamp_field": ast.Field(chain=[source_info.timestamp_field]),
            "metric_table": ast.Field(chain=[source_info.table_name]),
            "metric_predicate": self._b._build_metric_predicate(table_alias=source_info.table_name),
            "value_expr": self._b._build_value_expr(),
            "breakdown_value_expr": self._build_value_breakdown_expr(breakdown_property, source_info.table_name),
            "value_agg": self._b._build_value_aggregation_expr(),
            "conversion_window_predicate": self._b._build_conversion_window_predicate(),
            "other_label": ast.Constant(value=BREAKDOWN_OTHER_STRING_LABEL),
            "max_buckets": ast.Constant(value=VALUE_BREAKDOWN_MAX_BUCKETS),
        }

        query = parse_select(
            """
            WITH
            exposures AS (
                {exposure_select_query}
            ),

            raw_metric_events AS (
                SELECT
                    {entity_key} AS entity_id,
                    {metric_timestamp_field} AS timestamp,
                    {value_expr} AS value,
                    {breakdown_value_expr} AS breakdown_value
                FROM {metric_table}
                WHERE {metric_predicate}
            ),

            -- The values that keep their own bucket, ranked by total |contribution|. Ranked over the
            -- raw event scan (pre-join, so it can include never-exposed users) — which values are
            -- named vs rolled into "Other" is a display choice; the per-value sums still add back to
            -- the un-split total either way.
            top_buckets AS (
                SELECT breakdown_value
                FROM raw_metric_events
                GROUP BY breakdown_value
                ORDER BY sum(abs(value)) DESC, breakdown_value ASC
                LIMIT {max_buckets}
            ),

            -- The remap to "Other" happens here, before the per-entity aggregation below, so the
            -- Other bucket's sum-of-squares is computed from per-entity Other totals. Merging
            -- already-aggregated buckets instead would drop the cross terms and understate its
            -- variance.
            metric_events AS (
                SELECT
                    raw_metric_events.entity_id AS entity_id,
                    raw_metric_events.timestamp AS timestamp,
                    raw_metric_events.value AS value,
                    if(
                        raw_metric_events.breakdown_value IN (SELECT breakdown_value FROM top_buckets),
                        raw_metric_events.breakdown_value,
                        {other_label}
                    ) AS breakdown_value
                FROM raw_metric_events
            ),

            -- One row per (user, variant, property value): the user's accumulated metric value for
            -- that value. The INNER JOIN is fine here — a user with no events for a value just
            -- contributes no row, and the full denominator is restored by the cross join below.
            entity_value_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    metric_events.breakdown_value AS breakdown_value,
                    {value_agg} AS value
                FROM exposures
                INNER JOIN metric_events ON exposures.entity_id = metric_events.entity_id
                    AND {conversion_window_predicate}
                GROUP BY exposures.entity_id, exposures.variant, metric_events.breakdown_value
            ),

            -- Per (variant, value): the summed contribution and sum-of-squares, over users who hit
            -- the value. Missing (variant, value) pairs are filled back in by the cross join below.
            value_aggregates AS (
                SELECT
                    variant,
                    breakdown_value,
                    sum(value) AS total_sum,
                    sum(power(value, 2)) AS total_sum_of_squares
                FROM entity_value_metrics
                GROUP BY variant, breakdown_value
            ),

            -- Full exposure denominator per variant — the same count the un-split metric uses.
            variant_exposures AS (
                SELECT
                    variant,
                    count(entity_id) AS num_users
                FROM exposures
                GROUP BY variant
            ),

            -- Every value seen for ANY variant. Crossing this with variant_exposures emits a row for
            -- every (variant, value) pair — including pairs where a variant had zero events — so each
            -- split reports the full denominator with a 0 sum rather than going missing (which would
            -- otherwise pad that variant with 0 samples, breaking the full-denominator guarantee).
            breakdown_values AS (
                SELECT DISTINCT breakdown_value FROM value_aggregates
            )

            SELECT
                variant_exposures.variant AS variant,
                breakdown_values.breakdown_value AS breakdown_value_1,
                variant_exposures.num_users AS num_users,
                coalesce(value_aggregates.total_sum, 0) AS total_sum,
                coalesce(value_aggregates.total_sum_of_squares, 0) AS total_sum_of_squares
            FROM variant_exposures
            CROSS JOIN breakdown_values
            LEFT JOIN value_aggregates
                ON value_aggregates.variant = variant_exposures.variant
                AND value_aggregates.breakdown_value = breakdown_values.breakdown_value
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)
        return query
