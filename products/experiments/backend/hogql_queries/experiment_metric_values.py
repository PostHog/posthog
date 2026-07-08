from typing import Union

from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentMetricMathType,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team

from products.experiments.backend.hogql_queries.base_query_utils import (
    conversion_window_to_seconds,
    data_warehouse_node_to_filter,
    event_or_action_to_filter,
    get_source_value_expr,
)
from products.experiments.backend.hogql_queries.hogql_aggregation_utils import (
    aggregation_needs_numeric_input,
    build_aggregation_call,
    extract_aggregation_and_inner_expr,
)

ExperimentMetric = Union[ExperimentMeanMetric, ExperimentFunnelMetric, ExperimentRatioMetric, ExperimentRetentionMetric]
MetricSource = Union[EventsNode, ActionsNode, ExperimentDataWarehouseNode]


def get_conversion_window_seconds(metric: ExperimentMetric) -> int:
    """
    Returns the conversion window in seconds for the current metric.
    Returns 0 if no conversion window is configured.
    """
    if metric.conversion_window and metric.conversion_window_unit:
        return conversion_window_to_seconds(
            metric.conversion_window,
            metric.conversion_window_unit,
        )
    return 0


def build_conversion_window_predicate(conversion_window_seconds: int) -> ast.Expr:
    """
    Build the predicate for limiting metric events to the conversion window for the user.
    Uses "metric_events" as the events alias.
    """
    return build_conversion_window_predicate_for_events("metric_events", conversion_window_seconds)


def build_session_conversion_window_predicate(conversion_window_seconds: int) -> ast.Expr:
    """
    Build the predicate for limiting session metric events to the conversion window.
    Uses first_event_timestamp from metric_events_by_session for temporal filtering.
    """
    if conversion_window_seconds > 0:
        return parse_expr(
            """
            metric_events_by_session.first_event_timestamp
                < exposures.last_exposure_time + toIntervalSecond({conversion_window_seconds})
            """,
            placeholders={
                "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
            },
        )
    else:
        # No conversion window limit - just return true since temporal filtering
        # is already handled by the >= first_exposure_timestamp condition in the join
        return ast.Constant(value=True)


def build_conversion_window_predicate_for_events(events_alias: str, conversion_window_seconds: int) -> ast.Expr:
    """
    Build the predicate for limiting metric events to the conversion window for the user.
    Parameterized to support different event table aliases (for ratio metrics).
    """
    if conversion_window_seconds > 0:
        return parse_expr(
            f"""
            {events_alias}.timestamp >= exposures.first_exposure_time
            AND {events_alias}.timestamp
                < exposures.last_exposure_time + toIntervalSecond({{conversion_window_seconds}})
            """,
            placeholders={
                "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
            },
        )
    else:
        return parse_expr(f"{events_alias}.timestamp >= exposures.first_exposure_time")


def build_metric_predicate(
    *,
    team: Team,
    source: MetricSource,
    date_range_query: QueryDateRange,
    conversion_window_seconds: int,
    table_alias: str = "events",
    cuped_lookback_days: int | None = None,
) -> ast.Expr:
    """
    Builds the metric predicate as an AST expression.
    For ratio metrics, pass the specific source (numerator or denominator) and table_alias.
    For mean metrics, pass the resolved metric source explicitly with "events" alias.
    """
    # Data warehouse sources use different table and predicate logic
    timestamp_field_chain: list[str | int]
    if isinstance(source, ExperimentDataWarehouseNode):
        # For DW tables, don't prefix with table name since:
        # 1. We're in a single-table CTE context where field names are unambiguous
        # 2. DW table names may contain dots (e.g., "bigquery.table_name") which
        #    confuse HogQL field resolution when used as a prefix
        timestamp_field_chain = [source.timestamp_field]
        metric_event_filter = data_warehouse_node_to_filter(team, source)
    else:
        timestamp_field_chain = [table_alias, "timestamp"]
        metric_event_filter = event_or_action_to_filter(team, source)

    date_from = date_range_query.date_from_as_hogql()
    if cuped_lookback_days is not None:
        date_from = parse_expr(
            "{date_from} - toIntervalDay({lookback_days})",
            placeholders={
                "date_from": date_from,
                "lookback_days": ast.Constant(value=cuped_lookback_days),
            },
        )

    return parse_expr(
        """
        {timestamp_field} >= {date_from}
        AND {timestamp_field} < {date_to} + toIntervalSecond({conversion_window_seconds})
        AND {metric_event_filter}
        """,
        placeholders={
            "timestamp_field": ast.Field(chain=timestamp_field_chain),
            "date_from": date_from,
            "date_to": date_range_query.date_to_as_hogql(),
            "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
            "metric_event_filter": metric_event_filter,
        },
    )


def build_value_expr(source: MetricSource, apply_coalesce: bool = True) -> ast.Expr:
    """
    Extracts the value expression from the metric source configuration.
    For ratio metrics, pass the specific source (numerator or denominator).
    For mean metrics, pass the resolved metric source explicitly.

    Args:
        source: The metric source configuration
        apply_coalesce: If True, wrap numeric values with coalesce(..., 0) so that
                       NULL property values are treated as 0. This should be True
                       for event CTEs (metric_events, numerator_events, denominator_events)
                       so that downstream aggregations don't need to distinguish between
                       metric types.

    Note: For count distinct math types (UNIQUE_SESSION, DAU, UNIQUE_GROUP), coalesce
    is not applied since the value is an ID, not a numeric value.
    """
    base_expr = get_source_value_expr(source)

    if not apply_coalesce:
        return base_expr

    # Don't coalesce values for count distinct types (IDs) or HOGQL (user controls the expression)
    math_type = getattr(source, "math", ExperimentMetricMathType.TOTAL)
    if math_type in [
        ExperimentMetricMathType.UNIQUE_SESSION,
        ExperimentMetricMathType.DAU,
        ExperimentMetricMathType.UNIQUE_GROUP,
        ExperimentMetricMathType.HOGQL,
    ]:
        return base_expr

    # Wrap numeric values with coalesce so NULL property values become 0
    # We need toFloat to ensure type consistency - base_expr could be String (HOGQL),
    # Float64 (continuous), or UInt8 (count). Coalesce requires matching types.
    # Skip wrapping with toFloat if base_expr is already a toFloat call (e.g., continuous metrics)
    if isinstance(base_expr, ast.Call) and base_expr.name == "toFloat":
        float_expr = base_expr
    else:
        float_expr = ast.Call(name="toFloat", args=[base_expr])
    return ast.Call(name="coalesce", args=[float_expr, ast.Constant(value=0)])


def build_value_aggregation_expr(
    source: MetricSource,
    events_alias: str = "metric_events",
    column_name: str = "value",
    value_expr: ast.Expr | None = None,
) -> ast.Expr:
    """
    Returns the value aggregation expression based on math type.
    For ratio metrics, pass the specific source (numerator or denominator) and events_alias.
    For mean metrics, pass the resolved metric source explicitly with "metric_events" alias.

    Args:
        source: The metric source configuration
        events_alias: The table/CTE alias to use (e.g., "metric_events", "combined_events")
        column_name: The column name containing the value (e.g., "value", "numerator_value")

    Note: NULL handling (coalesce) is applied upstream in _build_value_expr() when building
    the event CTEs. This method does not need to handle NULLs - aggregation functions will
    naturally ignore NULLs from combined_events (ratio metrics), while NULL property values
    have already been coalesced to 0 at the source.
    """
    math_type = getattr(source, "math", ExperimentMetricMathType.TOTAL)
    column_ref = f"{events_alias}.{column_name}"

    if math_type in [
        ExperimentMetricMathType.UNIQUE_SESSION,
        ExperimentMetricMathType.DAU,
        ExperimentMetricMathType.UNIQUE_GROUP,
    ]:
        if value_expr is not None:
            # Count distinct values, filtering out null UUIDs and empty strings.
            # Conditional CUPED expressions can be Nullable, so handle NULL before
            # applying the same empty-value filtering as the base path.
            return parse_expr(
                """toFloat(count(distinct
                    multiIf(
                        isNull({value_expr}), NULL,
                        toTypeName({value_expr}) IN ('UUID', 'Nullable(UUID)') AND reinterpretAsUInt128(assumeNotNull({value_expr})) = 0, NULL,
                        toString({value_expr}) = '', NULL,
                        {value_expr}
                    )
                ))""",
                placeholders={"value_expr": value_expr},
            )

        # Count distinct values, filtering out null UUIDs and empty strings
        return parse_expr(
            f"""toFloat(count(distinct
                multiIf(
                    toTypeName({column_ref}) = 'UUID' AND reinterpretAsUInt128({column_ref}) = 0, NULL,
                    toString({column_ref}) = '', NULL,
                    {column_ref}
                )
            ))"""
        )
    elif math_type == ExperimentMetricMathType.MIN:
        # Outer coalesce ensures 0 (not NULL) when entity has no events of this type
        if value_expr is not None:
            return parse_expr("coalesce(min(toFloat({value_expr})), 0)", placeholders={"value_expr": value_expr})
        return parse_expr(f"coalesce(min(toFloat({column_ref})), 0)")
    elif math_type == ExperimentMetricMathType.MAX:
        if value_expr is not None:
            return parse_expr("coalesce(max(toFloat({value_expr})), 0)", placeholders={"value_expr": value_expr})
        return parse_expr(f"coalesce(max(toFloat({column_ref})), 0)")
    elif math_type == ExperimentMetricMathType.AVG:
        if value_expr is not None:
            return parse_expr("coalesce(avg(toFloat({value_expr})), 0)", placeholders={"value_expr": value_expr})
        return parse_expr(f"coalesce(avg(toFloat({column_ref})), 0)")
    elif math_type == ExperimentMetricMathType.HOGQL:
        math_hogql = getattr(source, "math_hogql", None)
        if math_hogql is not None:
            aggregation_function, _, params, distinct = extract_aggregation_and_inner_expr(math_hogql)
            if aggregation_function:
                inner_value_expr = value_expr or parse_expr(column_ref)
                if aggregation_needs_numeric_input(aggregation_function):
                    inner_value_expr = ast.Call(name="toFloat", args=[inner_value_expr])
                agg_call = build_aggregation_call(
                    aggregation_function, inner_value_expr, params=params, distinct=distinct
                )
                # Non-numeric aggregations (count, uniq, etc.) return UInt64, which is
                # incompatible with Float64 in ClickHouse greatest/least functions used
                # by winsorization. Wrap with toFloat to ensure consistent Float64 type.
                if not aggregation_needs_numeric_input(aggregation_function):
                    agg_call = ast.Call(name="toFloat", args=[agg_call])
                return ast.Call(name="coalesce", args=[agg_call, ast.Constant(value=0)])
        # Fallback to SUM
        if value_expr is not None:
            return parse_expr("sum(coalesce(toFloat({value_expr}), 0))", placeholders={"value_expr": value_expr})
        return parse_expr(f"sum(coalesce(toFloat({column_ref}), 0))")
    else:
        # SUM (default) - coalesce is needed here because sum(NULL) returns NULL.
        # For ratio metrics with combined_events, when there are no events of one type,
        # all values for that type are NULL (from UNION ALL structure), and we want 0 not NULL.
        if value_expr is not None:
            return parse_expr("sum(coalesce(toFloat({value_expr}), 0))", placeholders={"value_expr": value_expr})
        return parse_expr(f"sum(coalesce(toFloat({column_ref}), 0))")
