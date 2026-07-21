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
from posthog.hogql.parser import parse_select
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
    event_names: tuple[str, ...]
    # True when any EventsNode source has event=None ("all events").
    matches_all_events: bool
    action_ids: tuple[int, ...]
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
                event_names=tuple(
                    node.event for node in nodes if isinstance(node, EventsNode) and node.event is not None
                ),
                matches_all_events=any(isinstance(node, EventsNode) and node.event is None for node in nodes),
                action_ids=tuple(int(node.id) for node in nodes if isinstance(node, ActionsNode)),
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

    Metrics with no hits are omitted. Duplicate metric uuids (a saved metric shared by several
    experiments) are scanned once. `user` threads through to HogQL for property-level access
    control — metric source nodes can carry property filters.
    """
    names_by_uuid: dict[str, str] = {}
    branches: list[ast.SelectQuery] = []
    for source in metric_sources:
        if not source.session_linkable or source.metric_uuid in names_by_uuid:
            continue
        conditions = [_node_condition(node, team) for node in source.nodes]
        if not conditions:
            continue
        names_by_uuid[source.metric_uuid] = source.metric_name
        branch = parse_select(
            """
            SELECT {metric_uuid} AS metric_uuid,
                   count() AS event_count,
                   min(timestamp) AS first_timestamp,
                   arraySlice(arraySort(groupArray(timestamp)), 1, {max_timestamps}) AS timestamps
            FROM events
            WHERE {metric_conditions}
              AND $session_id = {session_id}
              AND timestamp >= {window_start}
              AND timestamp <= {window_end}
            GROUP BY $session_id
            """,
            placeholders={
                "metric_uuid": ast.Constant(value=source.metric_uuid),
                "metric_conditions": ast.Or(exprs=conditions) if len(conditions) > 1 else conditions[0],
                "session_id": ast.Constant(value=session_id),
                "window_start": ast.Constant(value=window_start),
                "window_end": ast.Constant(value=window_end),
                "max_timestamps": ast.Constant(value=MAX_METRIC_EVENT_TIMESTAMPS),
            },
        )
        assert isinstance(branch, ast.SelectQuery)
        branches.append(branch)

    if not branches:
        return []

    # Each branch groups a single session, so it yields at most one row — the implicit
    # LIMIT 100 HogQL stamps on every union branch can never truncate anything here.
    query = ast.SelectSetQuery.create_from_queries(branches, "UNION ALL")
    response = execute_hogql_query(query, team=team, user=user)

    hits: list[MetricHit] = []
    for metric_uuid, event_count, first_timestamp, timestamps in response.results or []:
        if not event_count:
            continue
        hits.append(
            MetricHit(
                metric_uuid=str(metric_uuid),
                metric_name=names_by_uuid[str(metric_uuid)],
                event_count=int(event_count),
                first_timestamp=first_timestamp,
                timestamps=tuple(timestamps),
            )
        )
    hits.sort(key=lambda hit: hit.first_timestamp)
    return hits
