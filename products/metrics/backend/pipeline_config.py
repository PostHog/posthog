"""Parse and validate a pipeline topology config from its stored JSON.

Framework-free: raises `ValueError` with a path-qualified message for every
rejection, so the model's `clean()` and the serializer surface the same
errors. `parse_pipeline_config` is the only constructor for `PipelineConfig`
callers should use — the graph invariants (unique ids, resolvable edges,
acyclicity) live here, not in the dataclasses.
"""

from __future__ import annotations

import re
import datetime as dt
from collections.abc import Mapping, Sequence
from typing import Any

from products.metrics.backend.facade.contracts import (
    MAX_PIPELINE_BREAKDOWN_TOP_N,
    MAX_PIPELINE_NODES,
    MAX_PIPELINE_STATS_PER_NODE,
    MetricFilter,
    PipelineBreakdownConfig,
    PipelineConfig,
    PipelineEdgeConfig,
    PipelineLink,
    PipelineNodeConfig,
    PipelineStatConfig,
    PipelineStatThresholds,
    PipelineThresholdBounds,
    PipelineVariableConfig,
)
from products.metrics.backend.facade.enums import AttributeScope, FilterOp, MetricAggregation, MetricType

_OFFSET_RE = re.compile(r"^-(\d+)([mhdw])$")
_OFFSET_UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}

_STAT_FORMATS = ("rate", "bytes", "pct", "count", "duration")


def parse_relative_offset(text: str) -> dt.timedelta:
    """Parse a negative relative offset like '-7d' into a timedelta length."""
    match = _OFFSET_RE.match(text or "")
    if match is None or int(match.group(1)) == 0:
        raise ValueError(f"invalid relative offset {text!r}: expected e.g. '-7d', '-24h', '-30m', '-1w'")
    return dt.timedelta(**{_OFFSET_UNITS[match.group(2)]: int(match.group(1))})


def _string(data: Mapping[str, Any], key: str, *, path: str, required: bool = True, default: str = "") -> str:
    value = data.get(key, None)
    if value is None:
        if required:
            raise ValueError(f"{path}: missing required field {key!r}")
        return default
    if not isinstance(value, str) or (required and not value):
        raise ValueError(f"{path}: field {key!r} must be a non-empty string")
    return value


def _number(value: Any, *, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path}: threshold bounds must be numbers")
    return float(value)


def _parse_filters(raw: Any, *, path: str) -> tuple[MetricFilter, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise ValueError(f"{path}: filters must be a list")
    filters = []
    for index, item in enumerate(raw):
        item_path = f"{path}.filters[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{item_path}: must be an object")
        try:
            op = FilterOp(item.get("op", "eq"))
            scope = AttributeScope(item.get("scope", "auto"))
        except ValueError as e:
            raise ValueError(f"{item_path}: {e}") from e
        filters.append(
            MetricFilter(
                key=_string(item, "key", path=item_path),
                op=op,
                value=_string(item, "value", path=item_path, required=False),
                scope=scope,
            )
        )
    return tuple(filters)


def _parse_aggregation(data: Mapping[str, Any], *, path: str) -> tuple[MetricAggregation, float | None]:
    raw = data.get("aggregation", "sum")
    try:
        aggregation = MetricAggregation(raw)
    except ValueError as e:
        raise ValueError(f"{path}: unknown aggregation {raw!r}") from e
    quantile = data.get("quantile")
    if quantile is not None:
        quantile = _number(quantile, path=path)
        if not 0.0 < quantile < 1.0:
            raise ValueError(f"{path}: quantile must be in (0, 1)")
    if aggregation.needs_quantile and quantile is None:
        raise ValueError(f"{path}: aggregation {aggregation.value!r} requires a quantile")
    return aggregation, quantile


def _parse_metric_type(data: Mapping[str, Any], *, path: str) -> MetricType | None:
    raw = data.get("metric_type")
    if raw is None:
        return None
    try:
        return MetricType(raw)
    except ValueError as e:
        raise ValueError(f"{path}: unknown metric_type {raw!r}") from e


def _parse_bounds(raw: Any, *, path: str) -> PipelineThresholdBounds:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: threshold bounds must be an object")
    lower = raw.get("lower")
    upper = raw.get("upper")
    if lower is None and upper is None:
        raise ValueError(f"{path}: threshold bounds need a lower or an upper value")
    return PipelineThresholdBounds(
        lower=_number(lower, path=path) if lower is not None else None,
        upper=_number(upper, path=path) if upper is not None else None,
    )


def _parse_thresholds(raw: Any, *, path: str) -> PipelineStatThresholds | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: thresholds must be an object")
    warn = raw.get("warn")
    crit = raw.get("crit")
    return PipelineStatThresholds(
        warn=_parse_bounds(warn, path=f"{path}.warn") if warn is not None else None,
        crit=_parse_bounds(crit, path=f"{path}.crit") if crit is not None else None,
    )


def _parse_breakdown(raw: Any, *, path: str) -> PipelineBreakdownConfig | None:
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: breakdown must be an object")
    top_n = raw.get("top_n", 10)
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= MAX_PIPELINE_BREAKDOWN_TOP_N:
        raise ValueError(f"{path}: breakdown top_n must be an integer between 1 and {MAX_PIPELINE_BREAKDOWN_TOP_N}")
    try:
        scope = AttributeScope(raw.get("scope", "auto"))
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from e
    return PipelineBreakdownConfig(group_by_key=_string(raw, "group_by_key", path=path), top_n=top_n, scope=scope)


def _parse_stat(raw: Any, *, path: str) -> PipelineStatConfig:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: must be an object")
    aggregation, quantile = _parse_aggregation(raw, path=path)
    stat_format = raw.get("format", "count")
    if stat_format not in _STAT_FORMATS:
        raise ValueError(f"{path}: unknown format {stat_format!r}; expected one of {_STAT_FORMATS}")
    return PipelineStatConfig(
        id=_string(raw, "id", path=path),
        label=_string(raw, "label", path=path),
        format=stat_format,
        metric_name=_string(raw, "metric_name", path=path),
        aggregation=aggregation,
        filters=_parse_filters(raw.get("filters"), path=path),
        quantile=quantile,
        metric_type=_parse_metric_type(raw, path=path),
        thresholds=_parse_thresholds(raw.get("thresholds"), path=path),
        breakdown=_parse_breakdown(raw.get("breakdown"), path=path),
    )


def _parse_links(raw: Any, *, path: str) -> tuple[PipelineLink, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, Sequence) or isinstance(raw, str):
        raise ValueError(f"{path}: links must be a list")
    links = []
    for index, item in enumerate(raw):
        item_path = f"{path}.links[{index}]"
        if not isinstance(item, Mapping):
            raise ValueError(f"{item_path}: must be an object")
        links.append(
            PipelineLink(label=_string(item, "label", path=item_path), url=_string(item, "url", path=item_path))
        )
    return tuple(links)


def _parse_node(raw: Any, *, path: str) -> PipelineNodeConfig:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: must be an object")
    raw_stats = raw.get("stats")
    if not isinstance(raw_stats, Sequence) or isinstance(raw_stats, str) or not raw_stats:
        raise ValueError(f"{path}: a node needs at least one stat")
    if len(raw_stats) > MAX_PIPELINE_STATS_PER_NODE:
        raise ValueError(f"{path}: at most {MAX_PIPELINE_STATS_PER_NODE} stats are allowed per node")
    stats = tuple(_parse_stat(s, path=f"{path}.stats[{i}]") for i, s in enumerate(raw_stats))
    stat_ids = [s.id for s in stats]
    for stat_id in stat_ids:
        if stat_ids.count(stat_id) > 1:
            raise ValueError(f"{path}: duplicate stat id {stat_id!r}")
    headline = tuple(raw.get("headline_stat_ids") or ())
    for stat_id in headline:
        if stat_id not in stat_ids:
            raise ValueError(f"{path}: headline stat {stat_id!r} does not match any stat id")
    return PipelineNodeConfig(
        id=_string(raw, "id", path=path),
        name=_string(raw, "name", path=path),
        kind=_string(raw, "kind", path=path, required=False),
        stats=stats,
        headline_stat_ids=headline,
        links=_parse_links(raw.get("links"), path=path),
        note=_string(raw, "note", path=path, required=False),
    )


def _parse_edge(raw: Any, *, path: str, node_ids: set[str]) -> PipelineEdgeConfig:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: must be an object")
    source = _string(raw, "source", path=path)
    target = _string(raw, "target", path=path)
    for endpoint in (source, target):
        if endpoint not in node_ids:
            raise ValueError(f"{path}: edge references unknown node {endpoint!r}")
    if source == target:
        raise ValueError(f"{path}: an edge cannot connect a node to itself")
    aggregation, quantile = _parse_aggregation(raw, path=path)
    baseline_offset = raw.get("baseline_offset", "-7d")
    parse_relative_offset(baseline_offset)
    hot_multiplier = raw.get("hot_multiplier", 2.0)
    hot_multiplier = _number(hot_multiplier, path=path)
    if hot_multiplier <= 1.0:
        raise ValueError(f"{path}: hot_multiplier must be greater than 1")
    return PipelineEdgeConfig(
        source=source,
        target=target,
        metric_name=_string(raw, "metric_name", path=path),
        aggregation=aggregation,
        filters=_parse_filters(raw.get("filters"), path=path),
        quantile=quantile,
        metric_type=_parse_metric_type(raw, path=path),
        baseline_offset=baseline_offset,
        hot_multiplier=hot_multiplier,
    )


def _parse_variable(raw: Any, *, path: str) -> PipelineVariableConfig:
    if not isinstance(raw, Mapping):
        raise ValueError(f"{path}: must be an object")
    options = raw.get("options") or ()
    if not isinstance(options, Sequence) or isinstance(options, str):
        raise ValueError(f"{path}: options must be a list of strings")
    default = raw.get("default")
    if default is not None and options and default not in options:
        raise ValueError(f"{path}: default {default!r} is not one of the options")
    return PipelineVariableConfig(
        key=_string(raw, "key", path=path),
        label=_string(raw, "label", path=path),
        filter_key=_string(raw, "filter_key", path=path),
        options=tuple(str(o) for o in options),
        default=default,
    )


def _assert_acyclic(nodes: tuple[PipelineNodeConfig, ...], edges: tuple[PipelineEdgeConfig, ...]) -> None:
    # Kahn's algorithm: if a topological order cannot consume every node,
    # the leftover nodes sit on a cycle.
    remaining_in_degree = {node.id: 0 for node in nodes}
    outgoing: dict[str, list[str]] = {node.id: [] for node in nodes}
    for edge in edges:
        remaining_in_degree[edge.target] += 1
        outgoing[edge.source].append(edge.target)
    frontier = [node_id for node_id, degree in remaining_in_degree.items() if degree == 0]
    visited = 0
    while frontier:
        node_id = frontier.pop()
        visited += 1
        for downstream in outgoing[node_id]:
            remaining_in_degree[downstream] -= 1
            if remaining_in_degree[downstream] == 0:
                frontier.append(downstream)
    if visited != len(nodes):
        raise ValueError("edges: the topology contains a cycle; a pipeline must be a DAG")


def parse_pipeline_config(data: Any) -> PipelineConfig:
    """Parse a stored pipeline config JSON object into a validated
    `PipelineConfig`. Raises `ValueError` with a path-qualified message on
    the first rejection."""
    if not isinstance(data, Mapping):
        raise ValueError("config must be an object")

    raw_nodes = data.get("nodes")
    if not isinstance(raw_nodes, Sequence) or isinstance(raw_nodes, str) or not raw_nodes:
        raise ValueError("nodes: a pipeline needs at least one node")
    if len(raw_nodes) > MAX_PIPELINE_NODES:
        raise ValueError(f"nodes: at most {MAX_PIPELINE_NODES} nodes are allowed")
    nodes = tuple(_parse_node(n, path=f"nodes[{i}]") for i, n in enumerate(raw_nodes))
    node_ids = [node.id for node in nodes]
    for node_id in node_ids:
        if node_ids.count(node_id) > 1:
            raise ValueError(f"nodes: duplicate node id {node_id!r}")

    raw_edges = data.get("edges") or ()
    if not isinstance(raw_edges, Sequence) or isinstance(raw_edges, str):
        raise ValueError("edges: must be a list")
    edges = tuple(_parse_edge(e, path=f"edges[{i}]", node_ids=set(node_ids)) for i, e in enumerate(raw_edges))
    _assert_acyclic(nodes, edges)

    raw_variables = data.get("variables") or ()
    if not isinstance(raw_variables, Sequence) or isinstance(raw_variables, str):
        raise ValueError("variables: must be a list")
    variables = tuple(_parse_variable(v, path=f"variables[{i}]") for i, v in enumerate(raw_variables))
    variable_keys = [v.key for v in variables]
    for key in variable_keys:
        if variable_keys.count(key) > 1:
            raise ValueError(f"variables: duplicate variable key {key!r}")

    return PipelineConfig(nodes=nodes, edges=edges, variables=variables)
