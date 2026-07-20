"""Resolve which events an experiment's metrics count, and scan sessions for them.

A session recording can contain the events an experiment's metrics count. This module maps an
experiment's metrics (inline primary + secondary and saved/shared, via the shared
`metric_resolution` enumerator) to their concrete event/action sources, and scans a bounded set
of sessions for those events. Data-warehouse sources have no session events, so metrics whose
every source is a data-warehouse node are marked non-linkable and skipped by the scan.

Consumed by two API surfaces: the per-experiment `session_metric_hits` batch action and the
additive `metrics_in_session` fields on the single-session `session_context` endpoint.
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
)

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_select
from posthog.hogql.property import action_to_expr, property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.models.team.team import Team
from posthog.models.user import User

from products.actions.backend.models.action import Action
from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.temporal.metric_resolution import ExperimentMetric, build_metric, iter_metric_dicts

logger = logging.getLogger(__name__)

# The scan groups by session id, so its output is bounded by the caller's session batch, not by
# event payloads. The explicit limit is a backstop far above any real batch — without it HogQL
# applies an implicit LIMIT 100 per union branch, which would silently truncate legitimate rows.
MAX_METRIC_HIT_ROWS = 10_000

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


def _metric_source_nodes(metric: ExperimentMetric) -> list[MetricSourceNode | ExperimentDataWarehouseNode]:
    if isinstance(metric, ExperimentMeanMetric):
        return [metric.source]
    if isinstance(metric, ExperimentFunnelMetric):
        return list(metric.series)
    if isinstance(metric, ExperimentRatioMetric):
        return [metric.numerator, metric.denominator]
    return [metric.start_event, metric.completion_event]


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
                metric_name=metric.name or f"Metric {metric_uuid[:8]}",
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
    """Match expression for one source node: the event/action match ANDed with the node's own
    property filters. Sources this project can't resolve (a missing action, a cohort filter
    whose cohort doesn't exist here, a filter HogQL can't compile) match nothing instead of
    failing the whole scan — mirroring `_build_action_filter` in `exposure_query_logic`."""
    exprs: list[ast.Expr] = []
    if isinstance(node, ActionsNode):
        try:
            action = Action.objects.get(pk=int(node.id), team=team)
        except Action.DoesNotExist:
            logger.warning("Action %s not found for team %s; metric source matches nothing.", node.id, team.pk)
            return ast.Constant(value=False)
        exprs.append(action_to_expr(action))
    elif node.event is not None:
        exprs.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value=node.event),
            )
        )
    try:
        for prop in [*(node.properties or []), *(node.fixedProperties or [])]:
            exprs.append(property_to_expr(prop, team))
    except (Cohort.DoesNotExist, BaseHogQLError):
        return ast.Constant(value=False)
    if not exprs:
        # An EventsNode with event=None and no filters counts all events.
        return ast.Constant(value=True)
    return ast.And(exprs=exprs) if len(exprs) > 1 else exprs[0]


def scan_sessions_for_metric_events(
    team: Team,
    user: User,
    *,
    metric_sources: list[MetricEventSource],
    session_ids: list[str],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, list[MetricHit]]:
    """session_id -> metrics with >=1 matching event in that session, sorted by first occurrence.

    Metrics with no hits are omitted from each session's list; sessions with no hits at all are
    absent from the map. Duplicate metric uuids (a saved metric shared by several experiments)
    are scanned once. `user` threads through to HogQL for property-level access control —
    metric source nodes can carry property filters.
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
                   $session_id AS session_id,
                   count() AS event_count,
                   min(timestamp) AS first_timestamp
            FROM events
            WHERE {metric_conditions}
              AND $session_id IN {session_ids}
              AND timestamp >= {window_start}
              AND timestamp <= {window_end}
            GROUP BY session_id
            """,
            placeholders={
                "metric_uuid": ast.Constant(value=source.metric_uuid),
                "metric_conditions": ast.Or(exprs=conditions) if len(conditions) > 1 else conditions[0],
                "session_ids": ast.Constant(value=session_ids),
                "window_start": ast.Constant(value=window_start),
                "window_end": ast.Constant(value=window_end),
            },
        )
        assert isinstance(branch, ast.SelectQuery)
        # The backstop must sit on each branch: HogQL stamps an implicit LIMIT 100 on every
        # union branch whose limit is unset, so a set-level limit alone would not prevent
        # per-branch truncation. Real branches stay far below this — each groups by the
        # caller's bounded session batch.
        branch.limit = ast.Constant(value=MAX_METRIC_HIT_ROWS)
        branches.append(branch)

    if not branches:
        return {}

    query = ast.SelectSetQuery.create_from_queries(branches, "UNION ALL")
    # No set-level LIMIT here: the printer emits it directly after the last branch's own
    # LIMIT, which ClickHouse rejects as a syntax error. The per-branch limits above are
    # the backstop.
    response = execute_hogql_query(query, team=team, user=user)

    hits: dict[str, list[MetricHit]] = {}
    for metric_uuid, session_id, event_count, first_timestamp in response.results or []:
        if not event_count:
            continue
        hits.setdefault(str(session_id), []).append(
            MetricHit(
                metric_uuid=str(metric_uuid),
                metric_name=names_by_uuid[str(metric_uuid)],
                event_count=int(event_count),
                first_timestamp=first_timestamp,
            )
        )
    for session_hits in hits.values():
        session_hits.sort(key=lambda hit: hit.first_timestamp)
    return hits
