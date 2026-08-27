"""Evaluate a pipeline topology's health for one refresh tick.

Pure orchestration over an injected `run_query` callable (the facade's
`run_metric_query` bound to a team in production, a fake in tests), so the
verdict logic needs no database to exercise.

Query shape per tick:
- each node's stats are packed into requests of up to `MAX_CLAUSES_PER_QUERY`
  clauses (clause name = stat id), one bucket grid per node
- each stat with a breakdown adds one grouped request for its table rows
- each edge runs two single-clause requests: the current window and the same
  window shifted back by its `baseline_offset`
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping

from products.metrics.backend.facade.contracts import (
    MAX_CLAUSES_PER_QUERY,
    MetricFilter,
    MetricGroupBy,
    MetricPoint,
    MetricQueryClause,
    MetricQueryRequest,
    MetricSeries,
    PipelineAlert,
    PipelineBreakdownRow,
    PipelineConfig,
    PipelineEdgeConfig,
    PipelineEdgeResult,
    PipelineEvaluation,
    PipelineNodeConfig,
    PipelineNodeResult,
    PipelineStatConfig,
    PipelineStatResult,
    PipelineStatThresholds,
    PipelineThresholdBounds,
)
from products.metrics.backend.facade.enums import FilterOp, HealthState
from products.metrics.backend.pipeline_config import parse_relative_offset

RunQuery = Callable[[MetricQueryRequest], list[MetricSeries]]

# Clause name for edge throughput requests; edges run one clause per request
# so the name never collides.
_EDGE_CLAUSE = "edge"


def _resolve_variable_filters(
    config: PipelineConfig, variable_values: Mapping[str, str] | None
) -> tuple[MetricFilter, ...]:
    values = dict(variable_values or {})
    filters: list[MetricFilter] = []
    for variable in config.variables:
        value = values.pop(variable.key, variable.default)
        if value is None:
            continue
        if variable.options and value not in variable.options:
            raise ValueError(f"variable {variable.key!r}: {value!r} is not one of the configured options")
        filters.append(MetricFilter(key=variable.filter_key, op=FilterOp.EQ, value=value))
    if values:
        unknown = ", ".join(sorted(values))
        raise ValueError(f"unknown variable keys: {unknown}")
    return tuple(filters)


def _stat_clause(
    stat: PipelineStatConfig, extra_filters: tuple[MetricFilter, ...], group_by: tuple[MetricGroupBy, ...] = ()
) -> MetricQueryClause:
    return MetricQueryClause(
        name=stat.id,
        metric_name=stat.metric_name,
        aggregation=stat.aggregation,
        filters=stat.filters + extra_filters,
        group_by=group_by,
        quantile=stat.quantile,
        metric_type=stat.metric_type,
    )


def _last_reported_value(series: MetricSeries | None) -> float | None:
    if series is None:
        return None
    for point in reversed(series.points):
        if point.value is not None:
            return point.value
    return None


def _mean_value(series: MetricSeries | None) -> float | None:
    if series is None:
        return None
    values = [p.value for p in series.points if p.value is not None]
    if not values:
        return None
    return sum(values) / len(values)


def _bounds_breached(bounds: PipelineThresholdBounds | None, value: float) -> bool:
    if bounds is None:
        return False
    if bounds.lower is not None and value < bounds.lower:
        return True
    return bounds.upper is not None and value > bounds.upper


def _stat_state(thresholds: PipelineStatThresholds | None, value: float | None) -> HealthState:
    if value is None:
        return HealthState.NO_DATA
    if thresholds is None:
        return HealthState.HEALTHY
    if _bounds_breached(thresholds.crit, value):
        return HealthState.CRITICAL
    if _bounds_breached(thresholds.warn, value):
        return HealthState.DEGRADED
    return HealthState.HEALTHY


def _chunk(items: list[MetricQueryClause], size: int) -> list[list[MetricQueryClause]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _breakdown_rows(
    stat: PipelineStatConfig, series_list: list[MetricSeries]
) -> tuple[tuple[PipelineBreakdownRow, ...], PipelineBreakdownRow | None]:
    assert stat.breakdown is not None
    rows = []
    for series in series_list:
        value = _last_reported_value(series)
        if value is None:
            continue
        rows.append(PipelineBreakdownRow(label=series.labels.get(stat.breakdown.group_by_key, ""), value=value))
    rows.sort(key=lambda row: (-row.value, row.label))
    top, rest = rows[: stat.breakdown.top_n], rows[stat.breakdown.top_n :]
    others = None
    if rest:
        others = PipelineBreakdownRow(label=f"others ({len(rest)})", value=sum(row.value for row in rest))
    return tuple(top), others


def _evaluate_node(
    node: PipelineNodeConfig,
    *,
    run_query: RunQuery,
    date_from: dt.datetime,
    date_to: dt.datetime,
    extra_filters: tuple[MetricFilter, ...],
) -> PipelineNodeResult:
    plain_clauses = [_stat_clause(stat, extra_filters) for stat in node.stats]
    series_by_stat: dict[str, MetricSeries] = {}
    for chunk in _chunk(plain_clauses, MAX_CLAUSES_PER_QUERY):
        request = MetricQueryRequest(clauses=tuple(chunk), date_from=date_from, date_to=date_to)
        for series in run_query(request):
            # Ungrouped clauses return exactly one series each; keep the first
            # per stat defensively if a runner ever returns more.
            if series.clause is not None:
                series_by_stat.setdefault(series.clause, series)

    breakdown_by_stat: dict[str, tuple[tuple[PipelineBreakdownRow, ...], PipelineBreakdownRow | None]] = {}
    for stat in node.stats:
        if stat.breakdown is None:
            continue
        group_by = (MetricGroupBy(key=stat.breakdown.group_by_key, scope=stat.breakdown.scope),)
        request = MetricQueryRequest(
            clauses=(_stat_clause(stat, extra_filters, group_by=group_by),), date_from=date_from, date_to=date_to
        )
        breakdown_by_stat[stat.id] = _breakdown_rows(stat, run_query(request))

    stat_results = []
    for stat in node.stats:
        value = _last_reported_value(series_by_stat.get(stat.id))
        rows, others = breakdown_by_stat.get(stat.id, ((), None))
        stat_results.append(
            PipelineStatResult(
                id=stat.id,
                label=stat.label,
                format=stat.format,
                value=value,
                state=_stat_state(stat.thresholds, value),
                breakdown_rows=rows,
                breakdown_others=others,
            )
        )

    return PipelineNodeResult(
        id=node.id,
        state=HealthState.worst([stat.state for stat in stat_results]),
        stats=tuple(stat_results),
    )


def _evaluate_edge(
    edge: PipelineEdgeConfig,
    *,
    run_query: RunQuery,
    date_from: dt.datetime,
    date_to: dt.datetime,
    extra_filters: tuple[MetricFilter, ...],
) -> PipelineEdgeResult:
    clause = MetricQueryClause(
        name=_EDGE_CLAUSE,
        metric_name=edge.metric_name,
        aggregation=edge.aggregation,
        filters=edge.filters + extra_filters,
        quantile=edge.quantile,
        metric_type=edge.metric_type,
    )
    offset = parse_relative_offset(edge.baseline_offset)
    current_series = run_query(MetricQueryRequest(clauses=(clause,), date_from=date_from, date_to=date_to))
    baseline_series = run_query(
        MetricQueryRequest(clauses=(clause,), date_from=date_from - offset, date_to=date_to - offset)
    )

    current = _mean_value(current_series[0] if current_series else None)
    baseline = _mean_value(baseline_series[0] if baseline_series else None)
    multiplier = None
    if current is not None and baseline is not None and baseline > 0:
        multiplier = current / baseline
    points: tuple[MetricPoint, ...] = current_series[0].points if current_series else ()
    return PipelineEdgeResult(
        source=edge.source,
        target=edge.target,
        current_value=current,
        baseline_value=baseline,
        multiplier=multiplier,
        hot=multiplier is not None and multiplier >= edge.hot_multiplier,
        points=points,
    )


def _derive_alerts(config: PipelineConfig, nodes: tuple[PipelineNodeResult, ...]) -> tuple[PipelineAlert, ...]:
    node_names = {node.id: node.name for node in config.nodes}
    alerts = []
    for node in nodes:
        for stat in node.stats:
            if stat.state not in (HealthState.DEGRADED, HealthState.CRITICAL):
                continue
            severity = "critical" if stat.state == HealthState.CRITICAL else "warning"
            alerts.append(
                PipelineAlert(
                    severity=severity,
                    node_id=node.id,
                    stat_id=stat.id,
                    message=f"{node_names[node.id]}: {stat.label} at {stat.value:g} breached the {severity} threshold",
                )
            )
    # Critical entries lead the strip; stable order within a severity.
    alerts.sort(key=lambda alert: 0 if alert.severity == "critical" else 1)
    return tuple(alerts)


def evaluate_pipeline(
    *,
    config: PipelineConfig,
    run_query: RunQuery,
    date_from: dt.datetime,
    date_to: dt.datetime,
    variable_values: Mapping[str, str] | None = None,
) -> PipelineEvaluation:
    """Evaluate every node stat and edge of `config` over one window and
    derive the alert strip. Raises `ValueError` for unknown variable keys or
    values outside a variable's configured options."""
    extra_filters = _resolve_variable_filters(config, variable_values)
    nodes = tuple(
        _evaluate_node(node, run_query=run_query, date_from=date_from, date_to=date_to, extra_filters=extra_filters)
        for node in config.nodes
    )
    edges = tuple(
        _evaluate_edge(edge, run_query=run_query, date_from=date_from, date_to=date_to, extra_filters=extra_filters)
        for edge in config.edges
    )
    return PipelineEvaluation(
        nodes=nodes,
        edges=edges,
        alerts=_derive_alerts(config, nodes),
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
    )
