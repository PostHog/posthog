"""
HogQL queries that the web-vitals signal detector runs against the events table.

Each function returns post-aggregation buckets at the (route, device_class) grain.
The sample-count gate is enforced inside SQL via HAVING so we don't transfer rows
we'd discard client-side.
"""

from datetime import datetime

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import apply_path_cleaning
from posthog.hogql.query import execute_hogql_query

from posthog.models.team.team import Team

from products.web_analytics.backend.temporal.web_vitals_signal.types import WebVitalsBucket

_ALLOWED_METRICS = frozenset({"LCP", "INP", "CLS", "FCP"})


def _percentile_expr(metric: str, percentile: float = 0.75) -> ast.Expr:
    if metric not in _ALLOWED_METRICS:
        raise ValueError(f"Unsupported web vitals metric: {metric}")
    # Both inputs are constrained: `metric` comes from a controlled set, `percentile`
    # is a float literal we render with two decimals. Not user-derived.
    # nosemgrep: hogql-injection-taint - controlled inputs
    return parse_expr(f"quantileExact({percentile:.2f})(toFloat(properties.$web_vitals_{metric}_value))")


def _route_expr(team: Team) -> ast.Expr:
    raw = ast.Field(chain=["events", "properties", "$pathname"])
    if team.path_cleaning_filters:
        return apply_path_cleaning(raw, team)
    return raw


def _device_class_expr() -> ast.Expr:
    return parse_expr("coalesce(properties.$device_type, 'unknown')")


def get_web_vitals_distribution(
    team: Team,
    metric: str,
    since: datetime,
    until: datetime,
    min_samples: int,
    percentile: float = 0.75,
) -> list[WebVitalsBucket]:
    """
    Run a (route, device_class) percentile query over $web_vitals events in [since, until).

    Returns one `WebVitalsBucket` per group with `sample_count >= min_samples`. Groups
    below the threshold are dropped in SQL — unstable percentiles produce noisy signals.
    """
    if metric not in _ALLOWED_METRICS:
        raise ValueError(f"Unsupported web vitals metric: {metric}")

    query = parse_select(
        """
SELECT
    {route} AS route,
    {device_class} AS device_class,
    {percentile} AS p75_value,
    count() AS sample_count
FROM events
WHERE event = '$web_vitals'
  AND timestamp >= {since}
  AND timestamp < {until}
  AND properties.$pathname IS NOT NULL
  AND {value_field} IS NOT NULL
GROUP BY route, device_class
HAVING sample_count >= {min_samples} AND p75_value > 0
ORDER BY route, device_class
""",
        placeholders={
            "route": _route_expr(team),
            "device_class": _device_class_expr(),
            "percentile": _percentile_expr(metric, percentile),
            "since": ast.Constant(value=since),
            "until": ast.Constant(value=until),
            "min_samples": ast.Constant(value=min_samples),
            "value_field": _web_vitals_value_field(metric),
        },
    )

    response = execute_hogql_query(
        query_type="web_vitals_signal_distribution",
        query=query,
        team=team,
    )
    assert response.results is not None

    buckets: list[WebVitalsBucket] = []
    for row in response.results:
        route, device_class, p75_value, sample_count = row
        if route is None or p75_value is None:
            continue
        buckets.append(
            WebVitalsBucket(
                route=str(route),
                device_class=str(device_class) if device_class is not None else "unknown",
                p75_value=float(p75_value),
                sample_count=int(sample_count),
            )
        )
    return buckets


def _web_vitals_value_field(metric: str) -> ast.Expr:
    """The properties.$web_vitals_{metric}_value field. Centralizes the metric-name
    interpolation so the column reference can't be passed an attacker-controlled value
    accidentally — `metric` is validated against `_ALLOWED_METRICS` upstream."""
    if metric not in _ALLOWED_METRICS:
        raise ValueError(f"Unsupported web vitals metric: {metric}")
    return ast.Field(chain=["events", "properties", f"$web_vitals_{metric}_value"])
