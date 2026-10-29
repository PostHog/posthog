"""
Metric-events precomputation for one events/actions metric source.

A mean metric has one source, a ratio metric has two (numerator and denominator),
and all of them aggregate the same (entity_id, timestamp, value) rows at read time.
The build query and the precomputed read below are therefore written per source, so
a ratio side with the same source and conversion window as a mean metric produces the
same build query, hashes the same, and shares its precompute jobs.
"""

from posthog.schema import ActionsNode, EventsNode, ExperimentMetricMathType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team import Team

from products.experiments.backend.hogql_queries.base_query_utils import event_or_action_to_filter
from products.experiments.backend.hogql_queries.experiment_metric_values import build_value_expr


def build_metric_events_precompute_query(
    *,
    team: Team,
    source: EventsNode | ActionsNode,
    entity_key: str,
    date_range_query: QueryDateRange,
    conversion_window_seconds: int,
) -> tuple[str, dict[str, ast.Expr]]:
    """
    Returns the SELECT query that the lazy computation system wraps in an
    INSERT INTO experiment_metric_events_preaggregated. This is the write
    path. It scans the events table and stores one row per matching metric
    event with its per-event value in numeric_value. For numeric math the
    value is already coalesced to a non-null float by build_value_expr(),
    so storing it in the non-nullable numeric_value column is lossless.
    For ID-valued math (dau, unique_session) the read side counts distinct
    IDs from entity_id/session_id instead, and numeric_value stores the
    same constant a count metric stores, so the build query hashes the same
    as a count metric on the same source and the two share precompute jobs.

    The query uses {time_window_min} and {time_window_max} placeholders filled
    by the lazy computation system for each daily bucket. The experiment date
    bounds must stay named placeholders (the caller declares experiment_date_to
    a sentinel) rather than reusing build_metric_predicate(), which bakes the
    resolved dates into the AST. The window end of a running experiment moves,
    so baked dates would change the job hash and defeat cache reuse.
    """
    # The job hash includes the parser source position of each node, so a change to
    # this template's whitespace invalidates every cached job. Keep it byte for byte.
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

    math_type = getattr(source, "math", None) or ExperimentMetricMathType.TOTAL
    if math_type in (ExperimentMetricMathType.DAU, ExperimentMetricMathType.UNIQUE_SESSION):
        # build_value_expr() returns the ID itself for these math types, which
        # cannot go into the Float64 column. Build the count-metric expression
        # node for node so repr-based job hashing matches a count metric build.
        value_expr: ast.Expr = ast.Call(
            name="coalesce",
            args=[ast.Call(name="toFloat", args=[ast.Constant(value=1)]), ast.Constant(value=0)],
        )
    else:
        value_expr = build_value_expr(source)

    placeholders: dict[str, ast.Expr] = {
        "entity_key": parse_expr(entity_key),
        "value_expr": value_expr,
        "experiment_date_from": date_range_query.date_from_as_hogql(),
        "experiment_date_to": date_range_query.date_to_as_hogql(),
        "conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
        "metric_event_filter": event_or_action_to_filter(team, source),
    }

    return query_string, placeholders


def build_precomputed_metric_events_cte(
    *,
    cte_name: str,
    source: EventsNode | ActionsNode,
    entity_key: str,
    job_ids_placeholder: str,
) -> str:
    """
    A CTE that reads one source's metric events from the precomputed table instead
    of scanning events, with the same (entity_id, timestamp, value) columns as the
    direct-scan CTE it replaces. Uses the placeholders from
    build_precomputed_metric_events_placeholders() plus {job_ids_placeholder}.

    cte_name and job_ids_placeholder are internal identifiers, never user input, so
    interpolating them into the query string is safe.
    """
    # Filter by experiment date range: jobs can cover broader time ranges than
    # the experiment for cache reuse, so the read must filter. The upper
    # bound includes the conversion window since metric events can occur after
    # experiment end, mirroring build_metric_predicate() on the direct path.
    # GROUP BY collapses replayed rows by event identity: ReplacingMergeTree only
    # dedups at merge time and this read doesn't use FINAL, so a re-applied build
    # INSERT would otherwise double-count sums. Same defense as the exposures read;
    # the funnel read skips it because funnel evaluation tolerates duplicate events.
    entity_id_cast = "toUUID(t.entity_id)" if entity_key == "person_id" else "t.entity_id"
    # For ID-valued math the value is the ID itself: the stored entity_id
    # is the person id (dau) and session_id is the unique_session value,
    # so the downstream count(distinct) matches the direct path.
    math_type = getattr(source, "math", None) or ExperimentMetricMathType.TOTAL
    if math_type == ExperimentMetricMathType.DAU:
        value_select = entity_id_cast
    elif math_type == ExperimentMetricMathType.UNIQUE_SESSION:
        value_select = "any(t.session_id)"
    else:
        value_select = "any(t.numeric_value)"
    return f"""
        {cte_name} AS (
            SELECT
                {entity_id_cast} AS entity_id,
                t.timestamp AS timestamp,
                {value_select} AS value
            FROM experiment_metric_events_preaggregated AS t
            WHERE t.job_id IN {{{job_ids_placeholder}}}
                AND t.team_id = {{metric_events_team_id}}
                AND t.timestamp >= {{metric_events_date_from}}
                AND t.timestamp < {{metric_events_date_to}} + toIntervalSecond({{metric_events_conversion_window_seconds}})
            GROUP BY t.entity_id, t.timestamp, t.event_uuid
        )"""


def build_precomputed_metric_events_placeholders(
    *,
    team: Team,
    date_range_query: QueryDateRange,
    conversion_window_seconds: int,
) -> dict[str, ast.Expr]:
    """The placeholders every build_precomputed_metric_events_cte() CTE of one query shares."""
    return {
        "metric_events_team_id": ast.Constant(value=team.id),
        "metric_events_date_from": date_range_query.date_from_as_hogql(),
        "metric_events_date_to": date_range_query.date_to_as_hogql(),
        "metric_events_conversion_window_seconds": ast.Constant(value=conversion_window_seconds),
    }
