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
from enum import StrEnum
from typing import Optional

import pydantic

from posthog.schema import (
    ActionsNode,
    EventsNode,
    ExperimentDataWarehouseNode,
    ExperimentFunnelMetric,
    ExperimentMeanMetric,
    ExperimentRatioMetric,
    ExperimentRetentionMetric,
    HogQLQueryModifiers,
)

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.models.team.team import Team
from posthog.models.user import User

from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.hogql_queries.base_query_utils import (
    conversion_window_to_seconds,
    event_or_action_to_filter,
)
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
# Ceiling on aggregate groups (each costs three conditional aggregates in the scan). Only the
# per-source breakdown is capped here — every accepted metric's own totals group is registered
# unconditionally (bounded by MAX_SCANNED_METRICS), so a metric over the ceiling loses its
# per-source split but never its total. Funnel step counts are user-configurable, so without
# this a fleet of long funnels could compile a query thousands of aggregates wide.
MAX_AGGREGATE_GROUPS = 200
# The largest retention_window_start (in seconds) that could still resolve inside one session. A
# window that opens a full day or more after the start event measures a return visit that lands
# in a later session; matching the completion event within this recording would then just be the
# start behavior repeating, not the return the metric counts.
MAX_SAME_SESSION_RETENTION_START_SECONDS = 24 * 60 * 60

MetricSourceNode = EventsNode | ActionsNode


class MetricSourceRole(StrEnum):
    """What one source node means to its metric, so a hit can say which side of the metric fired."""

    SOURCE = "source"
    STEP = "step"
    NUMERATOR = "numerator"
    DENOMINATOR = "denominator"
    RETENTION_START = "retention_start"
    RETENTION_COMPLETION = "retention_completion"


@dataclass(frozen=True)
class MetricSource:
    """One event/action source of a metric, with its position in the metric's definition."""

    role: MetricSourceRole
    name: str
    # Position among *all* the metric's sources, data-warehouse ones included, so a funnel step
    # keeps its real step number even when an earlier step has no session events.
    index: int
    total: int
    node: MetricSourceNode


@dataclass(frozen=True)
class SharedHogQLDatabase:
    """A HogQL virtual database built once per request and shared across that request's
    scans, bundled with the modifiers it was built with.

    Sharing the database is sound only while every scan treats it as read-only — the
    session-context scans run against it concurrently from a thread pool. HogQL mutates a
    database at query time in exactly two cases: `system.information_schema` queries register
    hidden external tables on it (`_rows_select` in
    posthog/hogql/database/schema/information_schema.py), and direct-connection queries make
    the executor rebuild it. Scans sharing one must therefore stick to plain table reads;
    everything here reads only `events`. The modifiers travel with the database because the
    schema depends on them (person-on-events mode changes the events table's person fields):
    every query against the shared database must execute with these modifiers, never its own.
    """

    database: Database
    modifiers: HogQLQueryModifiers

    def fresh_context(self, team: Team, user: User) -> HogQLContext:
        """A per-query context carrying the shared database, so `execute_hogql_query` reuses
        it instead of building its own. Contexts accumulate per-query state during printing
        and must never be shared between queries — the database can be."""
        return HogQLContext(team_id=team.pk, user=user, database=self.database)


@dataclass(frozen=True)
class MetricEventSource:
    """An experiment metric resolved to the concrete event/action sources it counts."""

    metric_uuid: str
    metric_name: str
    # False when the metric has no event/action source at all (purely data-warehouse) — there
    # are no session events to scan for. A metric with one event side and one data-warehouse
    # side is still linkable on the event side.
    session_linkable: bool
    # The parsed event/action sources, kept for their per-node property filters.
    sources: tuple[MetricSource, ...]


@dataclass(frozen=True)
class MetricSourceHit:
    """One source of a metric with at least one matching event in a session."""

    role: MetricSourceRole
    name: str
    index: int
    total: int
    event_count: int
    first_timestamp: datetime
    timestamps: tuple[datetime, ...]


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
    # Which of the metric's sources fired, so a hit reads as "step 2 of 3" or "the start event of
    # a retention metric" rather than an unqualified "this metric happened". Sources with no
    # matching event are omitted, as is the whole breakdown when the metric is over the
    # aggregate-group ceiling.
    sources: tuple[MetricSourceHit, ...]


def _retention_measures_completion_in_session(metric: ExperimentRetentionMetric) -> bool:
    """Whether a retention metric's completion event can count within one session.

    Only when the window opens less than a day after the start event. A window starting a day or
    more later measures a return visit that lands in a later session, so matching the completion
    event here would report every session containing the start event as a return. That is the
    common shape (a retention metric usually reuses one event on both sides), and exactly the case
    where the false positive is invisible.
    """
    return (
        conversion_window_to_seconds(metric.retention_window_start, metric.retention_window_unit)
        < MAX_SAME_SESSION_RETENTION_START_SECONDS
    )


def _metric_sources(
    metric: ExperimentMetric,
) -> list[tuple[MetricSourceRole, MetricSourceNode | ExperimentDataWarehouseNode]]:
    if isinstance(metric, ExperimentMeanMetric):
        return [(MetricSourceRole.SOURCE, metric.source)]
    if isinstance(metric, ExperimentFunnelMetric):
        return [(MetricSourceRole.STEP, step) for step in metric.series]
    if isinstance(metric, ExperimentRatioMetric):
        return [
            (MetricSourceRole.NUMERATOR, metric.numerator),
            (MetricSourceRole.DENOMINATOR, metric.denominator),
        ]
    sources: list[tuple[MetricSourceRole, MetricSourceNode | ExperimentDataWarehouseNode]] = [
        (MetricSourceRole.RETENTION_START, metric.start_event)
    ]
    if _retention_measures_completion_in_session(metric):
        sources.append((MetricSourceRole.RETENTION_COMPLETION, metric.completion_event))
    return sources


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
    metric_sources: list[MetricEventSource] = []
    for metric_dict in iter_metric_dicts(experiment):
        try:
            metric = build_metric(metric_dict)
        except (KeyError, pydantic.ValidationError):
            logger.warning("Skipping unparseable metric %s on experiment %s", metric_dict.get("uuid"), experiment.pk)
            continue
        all_sources = _metric_sources(metric)
        sources = tuple(
            MetricSource(
                role=role,
                # `_source_title` returns None only for an all-events node (no name, no event).
                name=_source_title(node) or "All events",
                index=index,
                total=len(all_sources),
                node=node,
            )
            for index, (role, node) in enumerate(all_sources)
            if isinstance(node, EventsNode | ActionsNode)
        )
        metric_uuid = str(metric_dict["uuid"])
        metric_sources.append(
            MetricEventSource(
                metric_uuid=metric_uuid,
                metric_name=metric.name or _default_metric_title(metric),
                session_linkable=bool(sources),
                sources=sources,
            )
        )
    return metric_sources


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
    shared_hogql: SharedHogQLDatabase | None = None,
) -> list[MetricHit]:
    """The metrics with >=1 matching event in the session, sorted by first occurrence.

    One scan computes every metric via conditional aggregation (countIf/minIf/groupArrayIf):
    a per-metric UNION ALL re-reads the session's event range once per metric, which dominated
    the endpoint's ClickHouse time in production once a session overlapped dozens of
    metric-carrying experiments. Keeping the OR of every metric condition in WHERE preserves
    the event-name primary-key pruning the per-metric branches had.

    Each metric is aggregated twice over: once across all its sources (its own totals, an OR so
    an event matching two sources still counts once) and once per source (the breakdown that
    says *which* side of the metric fired). Groups are keyed by their source nodes, so a metric
    with a single source needs one group, and metrics sharing a source share its aggregates.

    Metrics with no hits are omitted. Duplicate metric uuids (a saved metric shared by several
    experiments) and metrics with identical source nodes (several experiments measuring the
    same event) are aggregated once, and at most MAX_SCANNED_METRICS metrics are accepted per
    call (the overflow is logged, not an error). The cap counts metrics, not distinct sources:
    source dedupe only narrows the query, it must not let a metric-heavy experiment emit an
    unbounded hit list by piling metrics onto one source. `user` threads through to HogQL for
    property-level access control — metric source nodes can carry property filters.

    `shared_hogql` optionally carries a prebuilt virtual database (session_context builds
    one shared across all its scans) — constructing it dominates query wall time on teams with
    a large warehouse schema, so callers that already hold one should pass it in, along with
    the modifiers it was built with.
    """
    accepted: list[MetricEventSource] = []
    seen_uuids: set[str] = set()
    # One row condition per distinct source node, so two metrics measuring the same event compile
    # (and count) it once.
    conditions_by_node: dict[str, ast.Expr] = {}
    # Aggregate groups, keyed by the sorted distinct source nodes they cover: one per metric (all
    # its sources) plus one per individual source. A single-source metric's two keys coincide.
    group_indexes: dict[tuple[str, ...], int] = {}
    skipped_over_cap = 0
    skipped_breakdown_sources = 0

    def node_key(source: MetricSource) -> str:
        return source.node.model_dump_json(exclude_none=True)

    def metric_group_key(metric_source: MetricEventSource) -> tuple[str, ...]:
        # Distinct nodes only, so a ratio measuring the same event on both sides is one aggregate.
        return tuple(sorted({node_key(source) for source in metric_source.sources}))

    def register_group(key: tuple[str, ...], *, capped: bool) -> bool:
        """Give the group an aggregate slot. Returns False only when a capped group was dropped
        at the aggregate ceiling."""
        if key in group_indexes:
            return True
        if capped and len(group_indexes) >= MAX_AGGREGATE_GROUPS:
            return False
        group_indexes[key] = len(group_indexes)
        return True

    for metric_source in metric_sources:
        if not metric_source.session_linkable or metric_source.metric_uuid in seen_uuids:
            continue
        if len(seen_uuids) >= MAX_SCANNED_METRICS:
            skipped_over_cap += 1
            continue
        seen_uuids.add(metric_source.metric_uuid)
        accepted.append(metric_source)
        for source in metric_source.sources:
            conditions_by_node.setdefault(node_key(source), _node_condition(source.node, team))

    # Every metric's own totals group is registered first and uncapped — it is bounded by
    # MAX_SCANNED_METRICS, so it never competes for the ceiling. Only the per-source breakdown is
    # capped, so a metric over the ceiling loses its per-source split but never its totals.
    for metric_source in accepted:
        register_group(metric_group_key(metric_source), capped=False)
    for metric_source in accepted:
        for source in metric_source.sources:
            if not register_group((node_key(source),), capped=True):
                skipped_breakdown_sources += 1

    if skipped_over_cap:
        logger.warning(
            "Metric scan for session %s capped at %s metrics; %s metrics not scanned",
            session_id,
            MAX_SCANNED_METRICS,
            skipped_over_cap,
        )
    if skipped_breakdown_sources:
        logger.warning(
            "Metric scan for session %s capped at %s aggregate groups; per-source breakdown dropped for %s source(s)",
            session_id,
            MAX_AGGREGATE_GROUPS,
            skipped_breakdown_sources,
        )

    if not group_indexes:
        return []

    # Condition asts are deep-copied per use site (three aggregates + the WHERE): the HogQL
    # resolver annotates nodes in place, so sharing one instance across positions is unsafe.
    def group_condition(key: tuple[str, ...]) -> ast.Expr:
        conditions = [deepcopy(conditions_by_node[node]) for node in key]
        return ast.Or(exprs=conditions) if len(conditions) > 1 else conditions[0]

    select: list[ast.Expr] = []
    for key, index in group_indexes.items():
        select.append(ast.Alias(alias=f"count_{index}", expr=ast.Call(name="countIf", args=[group_condition(key)])))
        select.append(
            ast.Alias(
                alias=f"first_{index}",
                expr=ast.Call(name="minIf", args=[ast.Field(chain=["timestamp"]), group_condition(key)]),
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
                                    args=[ast.Field(chain=["timestamp"]), group_condition(key)],
                                )
                            ],
                        ),
                        ast.Constant(value=1),
                        ast.Constant(value=MAX_METRIC_EVENT_TIMESTAMPS),
                    ],
                ),
            )
        )

    any_metric_condition = [deepcopy(condition) for condition in conditions_by_node.values()]
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
    # execute_hogql_query treats a passed context as fully caller-owned, so only build one when
    # there is a shared database to carry; otherwise let the executor construct its default.
    extra_kwargs: dict[str, HogQLContext | HogQLQueryModifiers] = {}
    if shared_hogql is not None:
        extra_kwargs["context"] = shared_hogql.fresh_context(team, user)
        extra_kwargs["modifiers"] = shared_hogql.modifiers
    response = execute_hogql_query(query, team=team, user=user, **extra_kwargs)

    # Aggregation without GROUP BY always yields exactly one row; a metric with no matching
    # events shows count 0 there (and an epoch minIf), so the count guards the timestamps.
    row = response.results[0] if response.results else None
    if row is None:
        return []

    def read_group(key: tuple[str, ...]) -> Optional[tuple[int, datetime, tuple[datetime, ...]]]:
        index = group_indexes.get(key)
        if index is None:
            return None
        event_count = row[index * 3]
        if not event_count:
            return None
        return int(event_count), row[index * 3 + 1], tuple(row[index * 3 + 2])

    hits: list[MetricHit] = []
    for metric_source in accepted:
        totals = read_group(metric_group_key(metric_source))
        if totals is None:
            continue
        event_count, first_timestamp, timestamps = totals
        source_hits: list[MetricSourceHit] = []
        for source in metric_source.sources:
            source_totals = read_group((node_key(source),))
            if source_totals is None:
                continue
            source_hits.append(
                MetricSourceHit(
                    role=source.role,
                    name=source.name,
                    index=source.index,
                    total=source.total,
                    event_count=source_totals[0],
                    first_timestamp=source_totals[1],
                    timestamps=source_totals[2],
                )
            )
        hits.append(
            MetricHit(
                metric_uuid=metric_source.metric_uuid,
                metric_name=metric_source.metric_name,
                event_count=event_count,
                first_timestamp=first_timestamp,
                timestamps=timestamps,
                sources=tuple(source_hits),
            )
        )
    hits.sort(key=lambda hit: hit.first_timestamp)
    return hits
