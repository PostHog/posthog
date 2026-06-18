from typing import TYPE_CHECKING, Optional

from django.utils import timezone

from posthog.schema import (
    ExperimentDataWarehouseNode,
    ExperimentRetentionMetric,
    FunnelConversionWindowTimeUnit,
    StartHandling,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql

from products.experiments.backend.hogql_queries.base_query_utils import (
    conversion_window_to_seconds,
    data_warehouse_node_to_filter,
    event_or_action_to_filter,
)

if TYPE_CHECKING:
    from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder


class RetentionQueryBuilder:
    """
    Builds retention-metric queries.

    Retention reuses the shared exposure and conversion-window helpers already
    extracted from the experiment query builder, but has its own maturity
    semantics anchored on the start_event. To keep the move behavior-preserving,
    this class holds a reference to the owning ``ExperimentQueryBuilder`` and
    reaches through it for shared state (the metric, team, date range, entity
    key, breakdown injector) and the cross-cluster exposure and
    conversion-window helpers.
    """

    def __init__(self, builder: "ExperimentQueryBuilder"):
        self._b = builder

    def get_retention_maturity_seconds(self) -> int:
        """
        Returns the maturity window in seconds for retention metrics.
        Equals retention_window_end converted to seconds; conversion_window does
        not contribute because retention maturity is anchored on start_event.
        """
        assert isinstance(self._b.metric, ExperimentRetentionMetric)
        return conversion_window_to_seconds(
            self._b.metric.retention_window_end,
            self._b.metric.retention_window_unit,
        )

    def build_retention_maturity_having_clause(self) -> Optional[ast.Expr]:
        """
        Returns a HAVING clause for the retention query's start_events CTE that
        filters out users whose retention window has not yet fully elapsed since
        their start_event.

        Anchored on the user's start_event timestamp (min or max of start event
        timestamps, depending on start_handling).
        """
        if not isinstance(self._b.metric, ExperimentRetentionMetric):
            return None
        if not self._b.only_count_matured_users:
            return None

        maturity_seconds = self.get_retention_maturity_seconds()
        if maturity_seconds == 0:
            return None

        now = timezone.now().strftime("%Y-%m-%d %H:%M:%S")
        start_timestamp_expr = self.build_start_event_timestamp_expr()

        return parse_expr(
            "{start_ts} + toIntervalSecond({maturity_seconds}) <= toDateTime({now}, 'UTC')",
            placeholders={
                "start_ts": start_timestamp_expr,
                "maturity_seconds": ast.Constant(value=maturity_seconds),
                "now": ast.Constant(value=now),
            },
        )

    def build_retention_query(self) -> ast.SelectQuery:
        """
        Builds query for retention metrics.

        Retention measures the proportion of users who performed a "completion event"
        within a specified time window after performing a "start event".

        Statistical Treatment:
        This metric is treated as a ratio metric using RatioStatistic. Each entity has:
        - Numerator value: 1 if completed within retention window, 0 otherwise
        - Denominator value: 1 (they performed the start event)

        Unlike standard proportion tests (where sample size is fixed), retention metrics
        have a random denominator (count of users who started). This makes retention a
        ratio of two random variables, requiring delta method variance.

        Returns 7 fields for RatioStatistic:
        - Standard: num_users, total_sum, total_sum_of_squares
        - Ratio-specific: denominator_sum, denominator_sum_squares, numerator_denominator_sum_product

        The collected statistics are processed using RatioStatistic (not ProportionStatistic)
        for both frequentist and Bayesian analysis.

        Structure:
        - exposures: all exposures with variant assignment
        - start_events: when each entity performed the start_event (with start_handling logic)
        - completion_events: when each entity performed the completion_event
        - entity_metrics: join exposures + start_events + completion_events
                          Calculate retention per entity (1 if retained, 0 if not)
        - Final SELECT: aggregated statistics per variant

        Key Design Decision:
        Uses INNER JOIN between exposures and start_events, meaning only users who
        performed the start event are included in the retention calculation. This
        measures "Of users who did X, how many came back to do Y?" rather than
        "Of all exposed users, how many did X and then Y?"
        """
        assert isinstance(self._b.metric, ExperimentRetentionMetric)

        # Build the CTEs
        common_ctes = """
            exposures AS (
                {exposure_select_query}
            ),

            start_events AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    {start_timestamp_expr} AS start_timestamp,
                    {start_uuid_expr} AS start_uuid
                FROM events
                INNER JOIN exposures ON {entity_key} = exposures.entity_id
                WHERE {start_event_predicate}
                    AND {start_after_exposure_predicate}
                GROUP BY exposures.entity_id
            ),

            completion_events AS (
                SELECT
                    {entity_key} AS entity_id,
                    uuid AS completion_uuid,
                    timestamp AS completion_timestamp
                FROM events
                WHERE {completion_event_predicate}
            ),

            entity_metrics AS (
                SELECT
                    exposures.entity_id AS entity_id,
                    exposures.variant AS variant,
                    MAX(if(
                        completion_events.completion_timestamp IS NOT NULL
                        AND {truncated_completion_timestamp} >= {truncated_start_timestamp} + {retention_window_start_interval}
                        AND {truncated_completion_timestamp} <= {truncated_start_timestamp} + {retention_window_end_interval},
                        1,
                        0
                    )) AS value
                FROM exposures
                INNER JOIN start_events
                    ON exposures.entity_id = start_events.entity_id
                LEFT JOIN completion_events
                    ON exposures.entity_id = completion_events.entity_id
                    AND {completion_retention_window_predicate}
                    -- A completion must be a distinct event from the start occurrence.
                    -- Without this, a metric whose start and completion events are the
                    -- same would have every start trivially count as its own completion
                    -- (100% retention); event uuids are unique, so this is a no-op when
                    -- the two events differ.
                    AND completion_events.completion_uuid != start_events.start_uuid
                GROUP BY exposures.entity_id, exposures.variant
            )
        """

        placeholders = {
            "exposure_select_query": self._b._get_exposure_query(),
            "entity_key": parse_expr(self._b.entity_key),
            "start_timestamp_expr": self.build_start_event_timestamp_expr(),
            "start_uuid_expr": self.build_start_event_uuid_expr(),
            "start_event_predicate": self.build_start_event_predicate(),
            "completion_event_predicate": self.build_completion_event_predicate(),
            "retention_window_start_interval": self.build_retention_window_interval(
                self._b.metric.retention_window_start
            ),
            "retention_window_end_interval": self.build_retention_window_interval(self._b.metric.retention_window_end),
            "start_after_exposure_predicate": self.build_start_after_exposure_predicate(),
            "completion_retention_window_predicate": self.build_completion_retention_window_predicate(),
            "truncated_start_timestamp": self.get_retention_window_truncation_expr(
                parse_expr("start_events.start_timestamp")
            ),
            "truncated_completion_timestamp": self.get_retention_window_truncation_expr(
                parse_expr("completion_events.completion_timestamp")
            ),
        }

        query = parse_select(
            f"""
            WITH {common_ctes}

            SELECT
                entity_metrics.variant AS variant,
                count(entity_metrics.entity_id) AS num_users,
                sum(entity_metrics.value) AS total_sum,
                sum(power(entity_metrics.value, 2)) AS total_sum_of_squares,
                count(entity_metrics.entity_id) AS denominator_sum,
                count(entity_metrics.entity_id) AS denominator_sum_squares,
                sum(entity_metrics.value) AS numerator_denominator_sum_product
            FROM entity_metrics
            WHERE notEmpty(variant)
            GROUP BY entity_metrics.variant
            """,
            placeholders=placeholders,
        )

        assert isinstance(query, ast.SelectQuery)

        # Inject maturity HAVING clause into the start_events CTE, anchored on
        # the user's start_event timestamp so users whose retention window has
        # not yet elapsed are excluded from the denominator.
        retention_maturity = self.build_retention_maturity_having_clause()
        if retention_maturity is not None and query.ctes and "start_events" in query.ctes:
            start_events_cte = query.ctes["start_events"]
            if isinstance(start_events_cte, ast.CTE) and isinstance(start_events_cte.expr, ast.SelectQuery):
                if start_events_cte.expr.having is None:
                    start_events_cte.expr.having = retention_maturity
                else:
                    start_events_cte.expr.having = ast.And(exprs=[start_events_cte.expr.having, retention_maturity])

        # Inject breakdown columns if breakdown filter is present
        if self._b.breakdown_injector:
            self._b.breakdown_injector.inject_retention_breakdown_columns(query)

        return query

    def build_start_event_timestamp_expr(self) -> ast.Expr:
        """
        Returns expression to get start event timestamp based on start_handling.
        FIRST_SEEN: Use the first occurrence of start event
        LAST_SEEN: Use the last occurrence of start event
        """
        assert isinstance(self._b.metric, ExperimentRetentionMetric)

        if self._b.metric.start_handling == StartHandling.FIRST_SEEN:
            return parse_expr("min(timestamp)")
        else:  # LAST_SEEN
            return parse_expr("max(timestamp)")

    def build_start_event_uuid_expr(self) -> ast.Expr:
        """
        Returns the uuid of the start occurrence chosen by start_handling, so it can
        be excluded from its own completion window. Mirrors build_start_event_timestamp_expr:
        FIRST_SEEN picks the earliest occurrence, LAST_SEEN the latest.
        """
        assert isinstance(self._b.metric, ExperimentRetentionMetric)

        if self._b.metric.start_handling == StartHandling.FIRST_SEEN:
            return parse_expr("argMin(uuid, timestamp)")
        else:  # LAST_SEEN
            return parse_expr("argMax(uuid, timestamp)")

    def get_retention_window_truncation_expr(self, timestamp_expr: ast.Expr) -> ast.Expr:
        """
        Returns truncated timestamp expression for retention window comparisons.

        For DAY: returns toStartOfDay(timestamp)
        For HOUR: returns toStartOfHour(timestamp)
        For other units: returns timestamp unchanged

        This ensures [7,7] day window means "any time on day 7" rather than
        "exactly 7*24 hours after start event to the second".
        """
        assert isinstance(self._b.metric, ExperimentRetentionMetric)

        # Only truncate DAY and HOUR units for intuitive behavior
        unit_to_interval_name = {
            FunnelConversionWindowTimeUnit.DAY: "day",
            FunnelConversionWindowTimeUnit.HOUR: "hour",
        }

        interval_name = unit_to_interval_name.get(self._b.metric.retention_window_unit)
        if interval_name is None:
            return timestamp_expr

        return get_start_of_interval_hogql(interval=interval_name, team=self._b.team, source=timestamp_expr)

    def build_retention_window_interval(self, window_value: int) -> ast.Expr:
        """
        Converts retention window value to ClickHouse interval expression.
        """
        assert isinstance(self._b.metric, ExperimentRetentionMetric)

        unit_map = {
            FunnelConversionWindowTimeUnit.SECOND: "Second",
            FunnelConversionWindowTimeUnit.MINUTE: "Minute",
            FunnelConversionWindowTimeUnit.HOUR: "Hour",
            FunnelConversionWindowTimeUnit.DAY: "Day",
            FunnelConversionWindowTimeUnit.WEEK: "Week",
            FunnelConversionWindowTimeUnit.MONTH: "Month",
        }
        unit = unit_map[self._b.metric.retention_window_unit]
        return parse_expr(
            f"toInterval{unit}({{value}})",
            placeholders={"value": ast.Constant(value=window_value)},
        )

    def build_start_event_predicate(self) -> ast.Expr:
        """
        Builds the predicate for filtering start events.
        """
        assert isinstance(self._b.metric, ExperimentRetentionMetric)

        if isinstance(self._b.metric.start_event, ExperimentDataWarehouseNode):
            event_filter = data_warehouse_node_to_filter(self._b.team, self._b.metric.start_event)
        else:
            event_filter = event_or_action_to_filter(self._b.team, self._b.metric.start_event)
        conversion_window_seconds = self._b._get_conversion_window_seconds()

        return parse_expr(
            """
            timestamp >= {date_from}
            AND timestamp < {date_to} + toIntervalSecond({conversion_window_seconds})
            AND {event_filter}
            """,
            placeholders={
                "date_from": self._b.date_range_query.date_from_as_hogql(),
                "date_to": self._b.date_range_query.date_to_as_hogql(),
                "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                "event_filter": event_filter,
            },
        )

    def build_completion_event_predicate(self) -> ast.Expr:
        """
        Builds the predicate for filtering completion events.
        """
        assert isinstance(self._b.metric, ExperimentRetentionMetric)

        if isinstance(self._b.metric.completion_event, ExperimentDataWarehouseNode):
            event_filter = data_warehouse_node_to_filter(self._b.team, self._b.metric.completion_event)
        else:
            event_filter = event_or_action_to_filter(self._b.team, self._b.metric.completion_event)

        # Completion events can occur within the retention window after the start event
        # The retention window end could extend beyond the experiment end date
        conversion_window_seconds = self._b._get_conversion_window_seconds()
        retention_window_end_seconds = conversion_window_to_seconds(
            self._b.metric.retention_window_end,
            self._b.metric.retention_window_unit,
        )

        return parse_expr(
            """
            timestamp >= {date_from}
            AND timestamp < {date_to} + toIntervalSecond({total_window_seconds})
            AND {event_filter}
            """,
            placeholders={
                "date_from": self._b.date_range_query.date_from_as_hogql(),
                "date_to": self._b.date_range_query.date_to_as_hogql(),
                "total_window_seconds": ast.Constant(value=conversion_window_seconds + retention_window_end_seconds),
                "event_filter": event_filter,
            },
        )

    def build_start_after_exposure_predicate(self) -> ast.Expr:
        """
        Builds the predicate for filtering start events to only those after exposure.
        Applied inside the start_events CTE (pre-aggregation) so that min/max only
        considers events after the user's first exposure.
        """
        conversion_window_seconds = self._b._get_conversion_window_seconds()
        if conversion_window_seconds > 0:
            return parse_expr(
                """
                timestamp >= exposures.first_exposure_time
                AND timestamp <= exposures.first_exposure_time + toIntervalSecond({conversion_window_seconds})
                """,
                placeholders={
                    "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
                },
            )
        else:
            return parse_expr("timestamp >= exposures.first_exposure_time")

    def build_completion_retention_window_predicate(self) -> ast.Expr:
        """
        Builds the predicate for the join condition ensuring completion events
        are within a reasonable timeframe relative to start events.

        This is a performance optimization - we'll do the exact retention window
        calculation in the entity_metrics CTE.

        For DAY/HOUR units that use timestamp truncation, we add a buffer to account
        for the truncation window. This ensures that same-period retention (e.g., [0,0])
        captures all events within that period, not just events at the exact same second.
        """
        assert isinstance(self._b.metric, ExperimentRetentionMetric)

        retention_window_end_seconds = conversion_window_to_seconds(
            self._b.metric.retention_window_end,
            self._b.metric.retention_window_unit,
        )

        # For DAY/HOUR units, add a buffer to account for truncation
        # This ensures same-period retention windows work correctly
        truncation_buffer = 0
        if self._b.metric.retention_window_unit == FunnelConversionWindowTimeUnit.DAY:
            # For DAY units, allow completions within the same day (24 hours)
            truncation_buffer = 86400  # 1 day in seconds
        elif self._b.metric.retention_window_unit == FunnelConversionWindowTimeUnit.HOUR:
            # For HOUR units, allow completions within the same hour
            truncation_buffer = 3600  # 1 hour in seconds

        # Add buffer to retention window end
        buffered_window_end_seconds = retention_window_end_seconds + truncation_buffer

        return parse_expr(
            """
            completion_events.completion_timestamp >= start_events.start_timestamp
            AND completion_events.completion_timestamp <= start_events.start_timestamp + toIntervalSecond({retention_window_end_seconds})
            """,
            placeholders={
                "retention_window_end_seconds": ast.Constant(value=buffered_window_end_seconds),
            },
        )
