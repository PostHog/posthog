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
    """Returns 0 when the metric has no conversion window."""
    if metric.conversion_window and metric.conversion_window_unit:
        return conversion_window_to_seconds(
            metric.conversion_window,
            metric.conversion_window_unit,
        )
    return 0


def build_conversion_window_predicate(conversion_window_seconds: int) -> ast.Expr:
    return build_conversion_window_predicate_for_events("metric_events", conversion_window_seconds)


def build_session_conversion_window_predicate(conversion_window_seconds: int) -> ast.Expr:
    if conversion_window_seconds > 0:
        return parse_expr(
            """
            metric_events_by_session.first_event_timestamp
                < exposures.first_exposure_time + toIntervalSecond({conversion_window_seconds})
            """,
            placeholders={
                "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
            },
        )
    else:
        # Without a conversion window there is no upper bound. The join already
        # requires first_event_timestamp >= first_exposure_time.
        return ast.Constant(value=True)


def build_conversion_window_predicate_for_events(events_alias: str, conversion_window_seconds: int) -> ast.Expr:
    if conversion_window_seconds > 0:
        return parse_expr(
            f"""
            {events_alias}.timestamp >= exposures.first_exposure_time
            AND {events_alias}.timestamp
                < exposures.first_exposure_time + toIntervalSecond({{conversion_window_seconds}})
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
    For ratio metrics, pass the specific source (numerator or denominator) and table_alias.
    For mean metrics, pass the resolved metric source explicitly with the "events" alias.
    """
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
    For ratio metrics, pass the specific source (numerator or denominator).
    For mean metrics, pass the resolved metric source explicitly.

    apply_coalesce wraps numeric values in coalesce(..., 0), so a NULL property
    value counts as 0. Event CTEs (metric_events, numerator_events,
    denominator_events) need it, so that downstream aggregations do not have to
    distinguish between metric types.
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

    # coalesce() needs matching argument types, and base_expr can be Float64
    # (continuous) or UInt8 (count), so cast it to Float before the coalesce.
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
    For ratio metrics, pass the specific source (numerator or denominator) and events_alias.
    For mean metrics, pass the resolved metric source explicitly with the "metric_events" alias.
    value_expr, when set, replaces the {events_alias}.{column_name} column.

    build_value_expr() already coalesces NULL property values to 0 in the event CTEs.
    The aggregated rows can still hold NULL: the LEFT JOIN from exposures gives NULL
    for an entity without events, and a CUPED value_expr is NULL outside its window.
    Each branch below returns 0, not NULL, for an entity with only NULL values.
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

        # The precomputed read casts entity_id with accurateCastOrNull, which
        # yields Nullable(UUID), so both UUID spellings must hit the zero-UUID
        # filter or the direct and precomputed paths diverge for personless
        # (zero-UUID) entities.
        return parse_expr(
            f"""toFloat(count(distinct
                multiIf(
                    isNull({column_ref}), NULL,
                    toTypeName({column_ref}) IN ('UUID', 'Nullable(UUID)') AND reinterpretAsUInt128(assumeNotNull({column_ref})) = 0, NULL,
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
        # A math_hogql without a known aggregation function falls back to sum.
        if value_expr is not None:
            return parse_expr("sum(coalesce(toFloat({value_expr}), 0))", placeholders={"value_expr": value_expr})
        return parse_expr(f"sum(coalesce(toFloat({column_ref}), 0))")
    else:
        # SUM (default). sum() over only NULL values returns NULL, so coalesce each value.
        if value_expr is not None:
            return parse_expr("sum(coalesce(toFloat({value_expr}), 0))", placeholders={"value_expr": value_expr})
        return parse_expr(f"sum(coalesce(toFloat({column_ref}), 0))")
