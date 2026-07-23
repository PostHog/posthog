"""Resolve which events an experiment's metrics count, and scan a session for them.

A session recording can contain the events an experiment's metrics count. This module maps an
experiment's metrics (inline primary + secondary and saved/shared, via the shared
`metric_resolution` enumerator) to their concrete event/action sources, and scans one session
for those events. Data-warehouse sources have no session events, so metrics whose every source
is a data-warehouse node are marked non-linkable and skipped by the scan.

Consumed by the additive `metrics_in_session` fields on the single-session `session_context`
endpoint.
"""

import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

import pydantic

from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
)

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.models.team.team import Team
from posthog.models.user import User

from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.hogql_queries.base_query_utils import event_or_action_to_filter
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.temporal.metric_resolution import ExperimentMetric, build_metric, iter_metric_dicts

logger = logging.getLogger(__name__)

# Per hit we return the first N event timestamps as seek points; event_count carries the true
# total, so a busier metric shows the real count and the UI notes the seek points are capped.
MAX_METRIC_EVENT_TIMESTAMPS = 50
# Ceiling on metrics accepted per scan. An experiment's metric count is user-configurable
# with no server-side cap, so overlapping metric-heavy experiments could otherwise compile an
# arbitrarily wide query or emit an unbounded hit list; 50 mirrors MAX_CANDIDATE_EXPERIMENTS
# in session_context.
MAX_SCANNED_METRICS = 50

MetricSourceNode = EventsNode | ActionsNode


@dataclass(frozen=True)
class MetricEventSource:
    """An experiment metric resolved to the concrete event/action sources it counts."""

    metric_uuid: str
    metric_name: str
    # False when the metric has no event/action source at all (purely data-warehouse) — there
    # are no session events to scan for. A metric with one event side and one data-warehouse
    # side is still linkable on the event side.
    session_linkable: bool
    # The parsed event/action source nodes, kept for their per-node property filters.
    nodes: tuple[MetricSourceNode, ...]


@dataclass(frozen=True)
class MetricHit:
    """A metric with at least one matching event in a session."""

    metric_uuid: str
    metric_name: str
    event_count: int
    first_timestamp: datetime
    # The first MAX_METRIC_EVENT_TIMESTAMPS event timestamps, ascending — seek points for the
    # player. event_count is the true total, so this can be shorter than event_count.
    timestamps: tuple[datetime, ...]


def _metric_source_nodes(metric: ExperimentMetric) -> list[MetricSourceNode | ExperimentDataWarehouseNode]:
    if isinstance(metric, ExperimentMeanMetric):
        return [metric.source]
    if isinstance(metric, ExperimentFunnelMetric):
        return list(metric.series)
    if isinstance(metric, ExperimentRatioMetric):
        return [metric.numerator, metric.denominator]
    return [metric.start_event, metric.completion_event]


def _source_title(node: MetricSourceNode | ExperimentDataWarehouseNode) -> str | None:
    """Display name for one metric source node, mirroring the frontend `getDefaultName`."""
    if isinstance(node, EventsNode):
        return node.name or node.event
    if isinstance(node, ActionsNode):
        return node.name or f"Action {node.id}"
    if isinstance(node, ExperimentDataWarehouseNode):
        return node.table_name


def _default_metric_title(metric: ExperimentMetric) -> str:
    """A title derived from a metric's source events, mirroring the frontend
    `getDefaultMetricTitle` — so an unnamed metric reads the same in the player and the
    recordings tab (a `$pageview` mean metric shows "$pageview", not "Metric a34f9547")."""
    if isinstance(metric, ExperimentMeanMetric):
        return _source_title(metric.source) or "Untitled metric"
    if isinstance(metric, ExperimentFunnelMetric):
        return (_source_title(metric.series[0]) if metric.series else None) or "Untitled funnel"
    if isinstance(metric, ExperimentRatioMetric):
        return (
            f"{_source_title(metric.numerator) or 'Numerator'} / {_source_title(metric.denominator) or 'Denominator'}"
        )
    if isinstance(metric, ExperimentRetentionMetric):
        return f"{_source_title(metric.start_event) or 'Start event'} / {_source_title(metric.completion_event) or 'Completion event'}"


def resolve_metric_events(experiment: Experiment) -> list[MetricEventSource]:
    """Map every metric of an experiment (inline and saved) to its event/action sources.

    Which events a metric counts is the OR over all of its source nodes; `math_*` aggregation
    settings are irrelevant for containment. Metrics that can't be parsed (e.g. a legacy
    `metric_type` unknown to `build_metric`) are skipped, not fatal — one bad metric must
    never fail the whole surface.
    """
    sources: list[MetricEventSource] = []
    for metric_dict in iter_metric_dicts(experiment):
        try:
            metric = build_metric(metric_dict)
        except (KeyError, pydantic.ValidationError):
            logger.warning("Skipping unparseable metric %s on experiment %s", metric_dict.get("uuid"), experiment.pk)
            continue
        nodes = tuple(node for node in _metric_source_nodes(metric) if isinstance(node, EventsNode | ActionsNode))
        metric_uuid = str(metric_dict["uuid"])
        sources.append(
            MetricEventSource(
                metric_uuid=metric_uuid,
                metric_name=metric.name or _default_metric_title(metric),
                session_linkable=bool(nodes),
                nodes=nodes,
            )
        )
    return sources


def _node_condition(node: MetricSourceNode, team: Team) -> ast.Expr:
    """Match expression for one source node, built on `event_or_action_to_filter` — the same
    matcher the experiment analysis uses, so what counts as "this metric's event" cannot
    diverge between the analysis and this surface. `fixedProperties` are ANDed on top: the
    shared helper only reads `properties`, and layering the extra filter here keeps the scan
    strictly narrower than (never contradicting) the analysis. Sources this project can't
    resolve (a cohort filter whose cohort doesn't exist here, a filter HogQL can't compile)
    match nothing instead of failing the whole scan; the shared helper already maps a missing
    action to a match-nothing expression."""
    try:
        condition = event_or_action_to_filter(team, node)
        fixed = [property_to_expr(prop, team) for prop in node.fixedProperties or []]
    except (Cohort.DoesNotExist, BaseHogQLError):
        logger.warning("Unresolvable metric source filter for team %s; source matches nothing.", team.pk)
        return ast.Constant(value=False)
    if fixed:
        return ast.And(exprs=[condition, *fixed])
    return condition


def scan_session_for_metric_events(
    team: Team,
    user: User,
    *,
    metric_sources: list[MetricEventSource],
    session_id: str,
    window_start: datetime,
    window_end: datetime,
) -> list[MetricHit]:
    """The metrics with >=1 matching event in the session, sorted by first occurrence.

    One scan computes every metric via conditional aggregation (countIf/minIf/groupArrayIf):
    a per-metric UNION ALL re-reads the session's event range once per metric, which dominated
    the endpoint's ClickHouse time in production once a session overlapped dozens of
    metric-carrying experiments. Keeping the OR of every metric condition in WHERE preserves
    the event-name primary-key pruning the per-metric branches had.

    Metrics with no hits are omitted. Duplicate metric uuids (a saved metric shared by several
    experiments) and metrics with identical source nodes (several experiments measuring the
    same event) are aggregated once, and at most MAX_SCANNED_METRICS metrics are accepted per
    call (the overflow is logged, not an error). The cap counts metrics, not distinct sources:
    source dedupe only narrows the query, it must not let a metric-heavy experiment emit an
    unbounded hit list by piling metrics onto one source. `user` threads through to HogQL for
    property-level access control — metric source nodes can carry property filters.
    """
    names_by_uuid: dict[str, str] = {}
    # Metric uuids grouped by identical source nodes: identical sources compile to identical
    # row conditions, so they share one aggregate set instead of re-counting the same events.
    uuids_by_source: dict[tuple[str, ...], list[str]] = {}
    conditions_by_source: dict[tuple[str, ...], ast.Expr] = {}
    skipped_over_cap = 0
    for source in metric_sources:
        if not source.session_linkable or source.metric_uuid in names_by_uuid:
            continue
        if len(names_by_uuid) >= MAX_SCANNED_METRICS:
            skipped_over_cap += 1
            continue
        source_key = tuple(sorted(node.model_dump_json(exclude_none=True) for node in source.nodes))
        if source_key in uuids_by_source:
            names_by_uuid[source.metric_uuid] = source.metric_name
            uuids_by_source[source_key].append(source.metric_uuid)
            continue
        conditions = [_node_condition(node, team) for node in source.nodes]
        if not conditions:
            continue
        names_by_uuid[source.metric_uuid] = source.metric_name
        uuids_by_source[source_key] = [source.metric_uuid]
        conditions_by_source[source_key] = ast.Or(exprs=conditions) if len(conditions) > 1 else conditions[0]

    if skipped_over_cap:
        logger.warning(
            "Metric scan for session %s capped at %s metrics; %s metrics not scanned",
            session_id,
            MAX_SCANNED_METRICS,
            skipped_over_cap,
        )

    if not uuids_by_source:
        return []

    # Condition asts are deep-copied per use site (three aggregates + the WHERE): the HogQL
    # resolver annotates nodes in place, so sharing one instance across positions is unsafe.
    source_keys = list(uuids_by_source)
    select: list[ast.Expr] = []
    for index, source_key in enumerate(source_keys):
        condition = conditions_by_source[source_key]
        select.append(ast.Alias(alias=f"count_{index}", expr=ast.Call(name="countIf", args=[deepcopy(condition)])))
        select.append(
            ast.Alias(
                alias=f"first_{index}",
                expr=ast.Call(name="minIf", args=[ast.Field(chain=["timestamp"]), deepcopy(condition)]),
            )
        )
        select.append(
            ast.Alias(
                alias=f"timestamps_{index}",
                expr=ast.Call(
                    name="arraySlice",
                    args=[
                        ast.Call(
                            name="arraySort",
                            args=[
                                ast.Call(
                                    name="groupArrayIf",
                                    args=[ast.Field(chain=["timestamp"]), deepcopy(condition)],
                                )
                            ],
                        ),
                        ast.Constant(value=1),
                        ast.Constant(value=MAX_METRIC_EVENT_TIMESTAMPS),
                    ],
                ),
            )
        )

    any_metric_condition = [deepcopy(conditions_by_source[source_key]) for source_key in source_keys]
    query = ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["$session_id"]),
                    right=ast.Constant(value=session_id),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=window_start),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=window_end),
                ),
                ast.Or(exprs=any_metric_condition) if len(any_metric_condition) > 1 else any_metric_condition[0],
            ]
        ),
    )
    response = execute_hogql_query(query, team=team, user=user)

    # Aggregation without GROUP BY always yields exactly one row; a metric with no matching
    # events shows count 0 there (and an epoch minIf), so the count guards the timestamps.
    row = response.results[0] if response.results else None
    if row is None:
        return []
    hits: list[MetricHit] = []
    for index, source_key in enumerate(source_keys):
        event_count, first_timestamp, timestamps = row[index * 3], row[index * 3 + 1], row[index * 3 + 2]
        if not event_count:
            continue
        for metric_uuid in uuids_by_source[source_key]:
            hits.append(
                MetricHit(
                    metric_uuid=metric_uuid,
                    metric_name=names_by_uuid[metric_uuid],
                    event_count=int(event_count),
                    first_timestamp=first_timestamp,
                    timestamps=tuple(timestamps),
                )
            )
    hits.sort(key=lambda hit: hit.first_timestamp)
    return hits
