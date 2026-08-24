"""Compute a bounded session-id list for one experiment's recordings tab.

A recordings query carries a single AND/OR operator across its whole filter tree, so the tab
can only ask "fired every one of these metrics". Three questions it cannot express client-side
are answered here instead — "fired any of these", "fired none of them", and "was exposed but
never completed the funnel in this session" — by computing the matching session ids server-side
and feeding them to the playlist as `RecordingsQuery.session_ids`.

Buckets are goal-free: they say what happened in the session, never whether it helped or hurt a
metric. The analysis counts per person over the whole run window, while a recording is one
session of one person, so copy built on this must stay session-scoped ("in this session") and
must never claim the analysis counted or discounted anyone.

The population is session-scoped exposure evidence: an event matching the experiment's
exposure criteria, carrying one of the flag's defined variants, inside the session. That is a
deliberate choice, kept even though the tab's own list is person-scoped
(`RecordingsQuery.experiment_exposure`): every bucket asks what happened *in the session*, and
"fired none of these metrics" only means something over sessions that demonstrably saw the
experiment, whereas over all of an exposed person's sessions it would surface their unrelated
browsing. The playlist ANDs the returned ids with its person-scoped filter, so a bucket session
whose person the analysis excludes (multiple variants, for example) drops out there rather than
widening the shown set; ids spent on such sessions are wasted slots out of the cap, which is
the price of staying session-scoped. The default exposure event goes through the same
`resolve_default_exposure_event` rollout resolution the analysis queries apply, so an
experiment whose results count `$experiment_exposure` is bucketed on it too.

Whether an event can match sessions at all is decided here, from the same `EventProperty` fact
the taxonomy `seen_together` endpoint serves the tab: an event never ingested with a
`$session_id` (backend-fired exposure, server-side metrics) can only ever match zero sessions.
For the default exposure event the population falls back to the stamped `$feature/<flag_key>`
property — the same fallback the per-variant "View recordings" links use — flagged in the
response as `used_exposure_fallback`. Custom criteria get no such stand-in: they assert that something
specific happened, which the stamped property doesn't imply, so a custom exposure event that
can't be matched is refused with a reason rather than answered over a wider population.
Metrics whose every source is such an event are excluded with a reason instead of silently
matching nothing, which for `no_metric_activity` would otherwise inflate the bucket to the whole
exposed population. Drop-off narrows that rule to the one step it reads, the funnel's last: an
experiment funnel's first step is the exposure event, which every bucket already requires
in-session, so a funnel stays matchable overall while its completion can't be seen in a
recording, and counting an unobservable completion as zero would return every exposed session.
"""

import json
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Optional

from django.utils import timezone

from posthog.schema import EventsNode

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.utils import get_safe_cache, safe_cache_set

from products.access_control.backend.property_access_control import get_restricted_properties_for_team
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    get_test_accounts_filter,
    normalize_to_exposure_criteria,
)
from products.experiments.backend.metric_events import (
    MetricEventSource,
    MetricSource,
    MetricSourceRole,
    SharedHogQLDatabase,
    build_source_condition,
    node_signature,
    resolve_metric_events,
)
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.session_exposure import SessionExposure, resolve_session_exposure

logger = logging.getLogger(__name__)

# Ceiling on returned session ids. The recordings list is fetched over GET, so the ids ride in a
# query string: ~45 encoded characters each puts 100 ids at ~4.5 KB, with headroom under the 8 KB
# request-line limits proxies commonly enforce. Doubling it would not.
MAX_SESSION_BUCKET_LIMIT = 100
# The scan reads every session in the window, not a known id list, so the window is what bounds
# it. Recency-ordered output capped at 100 means older sessions could not surface anyway, which
# makes this clamp close to free in practice — but it must be stated wherever the bucket is.
MAX_BUCKET_SCAN_DAYS = 30
# Rows fetched before filtering to sessions that actually have a recording, so the cap isn't
# spent on sessions sampled out of replay.
RECORDING_LOOKUP_FACTOR = 3
# Ceilings on how wide one scan can get. An experiment's metric count and a funnel's step count
# are user-configurable with no server-side cap, so without these a single request can compile a
# query hundreds of conditions wide over the whole window. The numbers mirror MAX_SCANNED_METRICS
# and MAX_AGGREGATE_GROUPS in the metric-events scan. Over the ceiling the request is refused
# rather than quietly computed over a subset: a bucket answered over fewer metrics than asked for
# is a different question, and for `no_metric_activity` a dropped metric inflates the result.
MAX_BUCKET_METRICS = 50
MAX_BUCKET_SOURCES = 200
# Per (team, viewer, experiment, bucket spec). Shorter than the session-context cache: that
# caches an immutable-ish fact about one recording, this caches a list that should visibly grow
# as an experiment runs. Keyed by viewer for the same reason — the metric set is read through
# the viewer's access control.
SESSION_BUCKET_CACHE_TTL = 5 * 60

RETENTION_EXCLUSION_REASON = (
    "Retention metrics measure a return visit, which happens in a later session than the one that starts it. "
    "No single recording can show both, so these metrics are left out of the filter."
)
DATA_WAREHOUSE_EXCLUSION_REASON = (
    "This metric is measured entirely in the data warehouse, which has no session events to match recordings on."
)
SERVER_SIDE_EXCLUSION_REASON = (
    "This metric's events have only ever been captured server-side, where there is no session to record, "
    "so they can never be matched to a recording."
)
CUSTOM_EXPOSURE_UNLINKABLE_REASON = (
    "This experiment's exposure event has only ever been captured server-side, where there is no session to "
    "record, so no session can match it."
)
# Drop-off reads only a funnel's last step, because an experiment funnel's first step is the
# exposure event, which every bucket already requires in-session. Its check is therefore
# narrower than the whole-metric one above: a funnel stays matchable on its other steps.
FUNNEL_SERVER_SIDE_COMPLETION_REASON = (
    "Drop-off reads this funnel's last step. It has only ever been captured server-side, "
    "where there is no session to record, so it can never be matched to a recording."
)
FUNNEL_DATA_WAREHOUSE_COMPLETION_REASON = (
    "Drop-off reads this funnel's last step. It is measured in the data warehouse, "
    "which has no session events to match recordings on."
)


class SessionBucket(StrEnum):
    """Which question the returned session set answers."""

    FIRED_ANY = "fired_any"
    NO_METRIC_ACTIVITY = "no_metric_activity"
    FUNNEL_DROPOFF = "funnel_dropoff"


class SessionBucketUnavailable(Exception):
    """The requested bucket can't be computed for this experiment — a caller error, not a
    failure. Raised instead of returning an empty session list, so an unmatchable metric never
    reads as "no sessions matched"."""


@dataclass(frozen=True)
class BucketMetric:
    metric_uuid: str
    metric_name: str


@dataclass(frozen=True)
class ExcludedBucketMetric:
    metric_uuid: str
    metric_name: str
    reason: str


@dataclass(frozen=True)
class SessionBucketScan:
    """What the scan found, and what gets cached: every recorded match, most recent first, not yet
    cut to `limit`.

    The cut waits for the viewer's per-recording access filter, which runs on read so a revocation
    lands even on a warm entry. Cutting first would let a denied recording spend a returned slot,
    and would let `truncated` carry the one bit that a recording the viewer can't see matched.
    """

    candidate_session_ids: list[str]
    # The scan filled its over-fetch batch, so more matches may exist beyond the ones it saw.
    scan_hit_cap: bool
    limit: int
    considered_metrics: list[BucketMetric]
    excluded_metrics: list[ExcludedBucketMetric]
    date_from: datetime
    date_to: datetime
    filter_test_accounts: bool
    used_exposure_fallback: bool


@dataclass(frozen=True)
class SessionBucketResult:
    """One viewer's answer: the sessions they may see, cut to the limit."""

    session_ids: list[str]
    truncated: bool
    considered_metrics: list[BucketMetric]
    excluded_metrics: list[ExcludedBucketMetric]
    date_from: datetime
    date_to: datetime
    filter_test_accounts: bool
    used_exposure_fallback: bool


def finalize_session_bucket(scan: SessionBucketScan, accessible_session_ids: list[str]) -> SessionBucketResult:
    """Cut the sessions this viewer may see to the limit, and say whether anything was left out."""
    return SessionBucketResult(
        session_ids=accessible_session_ids[: scan.limit],
        truncated=len(accessible_session_ids) > scan.limit or scan.scan_hit_cap,
        considered_metrics=scan.considered_metrics,
        excluded_metrics=scan.excluded_metrics,
        date_from=scan.date_from,
        date_to=scan.date_to,
        filter_test_accounts=scan.filter_test_accounts,
        used_exposure_fallback=scan.used_exposure_fallback,
    )


def get_experiment_session_bucket(
    team: Team,
    user: User,
    experiment: Experiment,
    *,
    bucket: SessionBucket,
    metric_uuids: list[str],
    variant: Optional[str],
    limit: int,
) -> SessionBucketScan:
    """Session ids of this experiment's exposed sessions matching `bucket`, most recent first.

    The caller filters the result through the viewer's per-recording access control and passes it
    to `finalize_session_bucket`, which cuts it to `limit`.

    `user` is the viewer: metric sources and exposure criteria can filter on arbitrary event
    properties, so the query must run under that user's property-level access control, as the
    experiment query runners do.

    Raises SessionBucketUnavailable when the request can't produce a meaningful set — an
    experiment that never launched, a variant the flag doesn't define, a metric that can't be
    matched to recordings at all.
    """
    # The scan is experiments' own — exposure criteria and metric definitions over the events
    # table — so it bills to experiments, following the convention of tagging the product whose
    # logic and cost a query is rather than the surface it renders on. Without this it runs
    # untagged: no cost attribution in production, and a hard error in local dev. The replay
    # recording-existence lookup that follows tags itself, as replay's own query.
    tag_queries(product=Product.EXPERIMENTS, feature=Feature.QUERY, team_id=team.pk)

    if experiment.start_date is None:
        raise SessionBucketUnavailable("This experiment hasn't launched, so it has no exposed sessions yet.")

    variant_keys = {variant_definition["key"] for variant_definition in experiment.feature_flag.variants or []}
    if not variant_keys:
        raise SessionBucketUnavailable("This experiment's feature flag defines no variants.")
    if variant is not None and variant not in variant_keys:
        raise SessionBucketUnavailable(f"'{variant}' is not a variant of this experiment.")

    window_end = experiment.end_date or timezone.now()
    window_start = max(experiment.start_date, window_end - timedelta(days=MAX_BUCKET_SCAN_DAYS))
    criteria = normalize_to_exposure_criteria(experiment.exposure_criteria)
    filter_test_accounts = bool(criteria.filterTestAccounts) if criteria else False
    limit = min(limit, MAX_SESSION_BUCKET_LIMIT)

    requested = _resolve_requested_metrics(experiment, metric_uuids)
    # The same rollout resolution the analysis queries apply, so the bucket population is counted
    # on the event the experiment's results actually read. The linkability verdict must be the
    # endpoint's own: callers other than the tab (the API, MCP tools) have no reason to know the
    # lookup exists, and an empty bucket that's really an unlinkable event would read as "no
    # sessions did this".
    #
    # Event names collected per source, not per metric: `_source_event_names` is all-or-nothing, so
    # a funnel with an action step among its named ones would contribute none of its event names and
    # the boundary check below would pass on a name the lookup never asked about.
    lookup_names: set[str] = set()
    for metric in requested:
        lookup_names |= _concrete_event_names(metric)
    exposure = resolve_session_exposure(team, experiment, event_names=frozenset(lookup_names))
    if exposure.is_unmatchable:
        raise SessionBucketUnavailable(CUSTOM_EXPOSURE_UNLINKABLE_REASON)

    considered, excluded = _partition_metrics(requested, bucket, exposure.never_linked)

    cache_key = _cache_key(
        team,
        user,
        experiment,
        bucket,
        considered,
        variant,
        window_start,
        window_end,
        limit,
        exposure.default_exposure_event,
    )
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return cached

    candidate_session_ids, scan_hit_cap = _query_bucket_sessions(
        team,
        user,
        experiment,
        bucket=bucket,
        considered=considered,
        variant_keys=[variant] if variant is not None else sorted(variant_keys),
        window_start=window_start,
        window_end=window_end,
        limit=limit,
        exposure=exposure,
    )
    result = SessionBucketScan(
        candidate_session_ids=candidate_session_ids,
        scan_hit_cap=scan_hit_cap,
        limit=limit,
        considered_metrics=[
            BucketMetric(metric_uuid=metric.metric_uuid, metric_name=metric.metric_name) for metric in considered
        ],
        excluded_metrics=excluded,
        date_from=window_start,
        date_to=window_end,
        filter_test_accounts=filter_test_accounts,
        used_exposure_fallback=exposure.used_fallback,
    )
    safe_cache_set(cache_key, result, timeout=SESSION_BUCKET_CACHE_TTL)
    return result


def _cache_key(
    team: Team,
    user: User,
    experiment: Experiment,
    bucket: SessionBucket,
    considered: list[MetricEventSource],
    variant: Optional[str],
    window_start: datetime,
    window_end: datetime,
    limit: int,
    default_exposure_event: str,
) -> str:
    # The version segment must be bumped whenever SessionBucketScan changes shape (entries are
    # pickled, so a deploy would otherwise restore instances missing the new fields) and whenever
    # a bucket's semantics change, so a warm entry can't keep answering the old question.
    spec = json.dumps(
        [
            bucket.value,
            sorted(metric.metric_uuid for metric in considered),
            variant,
            # The scan window moves with wall-clock time on a running experiment; rounding to the
            # minute keeps a burst of requests on one entry without pinning a stale window.
            window_start.replace(second=0, microsecond=0).isoformat(),
            window_end.replace(second=0, microsecond=0).isoformat(),
            # Part of the key even though the cut happens on read: the scan over-fetches a
            # multiple of the limit, so a larger one looks further than a cached smaller one did.
            limit,
            # The rollout flag can flip which event the default exposure reads mid-window, and a
            # scan computed on the other event must not be served after the flip.
            default_exposure_event,
            # Property restrictions are compiled into the SQL, so unlike recording access they
            # can't be re-filtered on read; a restriction change has to miss the cache instead.
            sorted(get_restricted_properties_for_team(user=user, team=team)),
        ]
    )
    digest = hashlib.sha256(spec.encode()).hexdigest()[:16]
    return f"experiment_session_bucket_v4_{team.pk}_{user.pk}_{experiment.pk}_{digest}"


def _resolve_requested_metrics(experiment: Experiment, metric_uuids: list[str]) -> list[MetricEventSource]:
    resolved = resolve_metric_events(experiment)
    by_uuid = {metric.metric_uuid: metric for metric in resolved}

    unknown = [metric_uuid for metric_uuid in metric_uuids if metric_uuid not in by_uuid]
    if unknown:
        raise SessionBucketUnavailable(f"Unknown metric(s) for this experiment: {', '.join(sorted(unknown))}.")

    return [by_uuid[metric_uuid] for metric_uuid in dict.fromkeys(metric_uuids)] if metric_uuids else resolved


def _partition_metrics(
    requested: list[MetricEventSource], bucket: SessionBucket, never_linked: frozenset[str]
) -> tuple[list[MetricEventSource], list[ExcludedBucketMetric]]:
    """Split the requested metrics into the ones the bucket is computed over and the ones that
    can't be matched to a recording at all, with the reason.

    Reporting the excluded ones back matters most for `no_metric_activity`: "fired nothing" is
    only meaningful next to the list of metrics it was evaluated against — a metric whose events
    never carry a session id would count as "fired nothing" in every session, inflating the
    bucket to the whole exposed population.
    """
    considered: list[MetricEventSource] = []
    excluded: list[ExcludedBucketMetric] = []
    for metric in requested:
        reason = _exclusion_reason(metric, never_linked)
        if reason is None:
            considered.append(metric)
        else:
            excluded.append(
                ExcludedBucketMetric(metric_uuid=metric.metric_uuid, metric_name=metric.metric_name, reason=reason)
            )

    if not considered:
        raise SessionBucketUnavailable(
            "None of these metrics can be matched to recordings, so no session set would be meaningful."
        )
    if len(considered) > MAX_BUCKET_METRICS:
        raise SessionBucketUnavailable(
            f"This bucket would be computed over {len(considered)} metrics, more than the {MAX_BUCKET_METRICS} "
            "one scan can cover. Ask for fewer metrics."
        )
    source_count = sum(len(metric.sources) for metric in considered)
    if source_count > MAX_BUCKET_SOURCES:
        raise SessionBucketUnavailable(
            f"These metrics count {source_count} events between them, more than the {MAX_BUCKET_SOURCES} "
            "one scan can cover. Ask for fewer metrics."
        )
    if bucket == SessionBucket.FUNNEL_DROPOFF:
        if len(considered) != 1:
            raise SessionBucketUnavailable("The drop-off bucket takes exactly one funnel metric.")
        completion_reason = _funnel_completion_reason(considered[0], never_linked)
        if completion_reason is not None:
            # Raised rather than excluded: drop-off takes one metric, so excluding it would leave
            # the generic "none of these can be matched" message and lose the reason.
            raise SessionBucketUnavailable(completion_reason)
    return considered, excluded


def _exclusion_reason(metric: MetricEventSource, never_linked: frozenset[str]) -> Optional[str]:
    if not metric.session_linkable:
        return DATA_WAREHOUSE_EXCLUSION_REASON
    if any(
        source.role in (MetricSourceRole.RETENTION_START, MetricSourceRole.RETENTION_COMPLETION)
        for source in metric.sources
    ):
        # A retention metric's return visit is a later session by construction, so no single
        # recording can show the metric happening. Its start event alone would answer a different
        # question than the metric asks.
        return RETENTION_EXCLUSION_REASON
    source_events = _source_event_names(metric)
    if source_events is not None and source_events <= never_linked:
        return SERVER_SIDE_EXCLUSION_REASON
    return None


def _concrete_event_names(metric: MetricEventSource) -> set[str]:
    """Every named event this metric counts, skipping the sources that have no single name.

    What the linkability lookup reads. Deliberately not `_source_event_names`: that one answers a
    question about the metric as a whole and gives up entirely on an action source, which would
    leave a funnel's named boundary steps unchecked.
    """
    return {source.node.event for source in metric.sources if isinstance(source.node, EventsNode) and source.node.event}


def _source_event_names(metric: MetricEventSource) -> Optional[set[str]]:
    """The concrete event names a metric counts, or None when any source is an action or an
    all-events node. Those can match client-captured events, so their linkability can't be
    decided from event names and the metric must stay considered."""
    names: set[str] = set()
    for source in metric.sources:
        if not isinstance(source.node, EventsNode) or not source.node.event:
            return None
        names.add(source.node.event)
    return names


def _metric_condition(metric: MetricEventSource, team: Team) -> ast.Expr:
    """Match expression for "any of this metric's events" — the OR over its sources, built on the
    same matcher the analysis uses, so what counts as this metric's event can't diverge."""
    conditions = [build_source_condition(source.node, team) for source in metric.sources]
    return ast.Or(exprs=conditions) if len(conditions) > 1 else conditions[0]


def _funnel_completion_step(metric: MetricEventSource) -> MetricSource:
    """The one step drop-off is computed from: the funnel's completion. The funnel's implicit
    first step is the exposure event, which the bucket query already requires in-session."""
    steps = [source for source in metric.sources if source.role == MetricSourceRole.STEP]
    if not steps:
        raise SessionBucketUnavailable(
            "Drop-off needs a funnel metric with at least one step that can be matched to recordings."
        )
    return steps[-1]


def _funnel_completion_reason(metric: MetricEventSource, never_linked: frozenset[str]) -> Optional[str]:
    """Why drop-off can't be asked of this funnel, or None when it can.

    The whole-metric check in `_exclusion_reason` is too coarse here. It clears a funnel as long
    as one of its steps can be matched, while drop-off rests on the last one specifically. A
    funnel whose completion is a server-side charge passes there and would then count that
    completion as zero in every session, returning every exposed session as not having finished.
    """
    completion = _funnel_completion_step(metric)
    # Data-warehouse steps are dropped from `sources` while the survivors keep their real
    # position, so a gap at the end means the completion read landed on an inner step.
    if completion.index != completion.total - 1:
        return FUNNEL_DATA_WAREHOUSE_COMPLETION_REASON
    if isinstance(completion.node, EventsNode) and completion.node.event and completion.node.event in never_linked:
        return FUNNEL_SERVER_SIDE_COMPLETION_REASON
    return None


def _funnel_completion_condition(metric: MetricEventSource, team: Team) -> tuple[ast.Expr, int]:
    """The funnel's completion condition, and how many times the completion event must fire to
    count as completed.

    A funnel can list one event as several steps (the "N-th occurrence" shape), where completing
    means firing that event as many times as it appears in the series, the same positional
    reading the per-source hits use.
    """
    steps = [source for source in metric.sources if source.role == MetricSourceRole.STEP]
    completion_step = _funnel_completion_step(metric)
    completion_signature = node_signature(completion_step.node)
    completion_occurrences = sum(1 for step in steps if node_signature(step.node) == completion_signature)
    return build_source_condition(completion_step.node, team), completion_occurrences


def _query_bucket_sessions(
    team: Team,
    user: User,
    experiment: Experiment,
    *,
    bucket: SessionBucket,
    considered: list[MetricEventSource],
    variant_keys: list[str],
    window_start: datetime,
    window_end: datetime,
    limit: int,
    exposure: SessionExposure,
) -> tuple[list[str], bool]:
    def exposure_condition() -> ast.Expr:
        return exposure.condition(variant_keys)

    def metric_conditions() -> list[ast.Expr]:
        return [_metric_condition(metric, team) for metric in considered]

    def any_metric_condition() -> ast.Expr:
        conditions = metric_conditions()
        return ast.Or(exprs=conditions) if len(conditions) > 1 else conditions[0]

    def count_if(condition: ast.Expr) -> ast.Expr:
        return ast.Call(name="countIf", args=[condition])

    if bucket == SessionBucket.FIRED_ANY:
        bucket_predicate: ast.Expr = ast.CompareOperation(
            op=ast.CompareOperationOp.Gt, left=count_if(any_metric_condition()), right=ast.Constant(value=0)
        )
    elif bucket == SessionBucket.NO_METRIC_ACTIVITY:
        bucket_predicate = ast.CompareOperation(
            op=ast.CompareOperationOp.Eq, left=count_if(any_metric_condition()), right=ast.Constant(value=0)
        )
    else:
        completion, completion_occurrences = _funnel_completion_condition(considered[0], team)
        # The funnel's implicit first step is the exposure event, and the HAVING below already
        # requires an in-session exposure for every bucket, so drop-off needs only the completion
        # side. Count-based on purpose: the filter promises "fired the last step's event", not
        # funnel ordering.
        bucket_predicate = ast.CompareOperation(
            op=ast.CompareOperationOp.Lt,
            left=count_if(completion),
            right=ast.Constant(value=completion_occurrences),
        )

    # The WHERE keeps the OR of every condition the query can match on, so ClickHouse still prunes
    # by event name on the events table's primary key — without it this reads the team's whole
    # window. Sessions are then classified in the HAVING over the same conditions.
    where_conditions: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.GtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value=window_start),
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.LtEq, left=ast.Field(chain=["timestamp"]), right=ast.Constant(value=window_end)
        ),
        ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq, left=ast.Field(chain=["$session_id"]), right=ast.Constant(value="")
        ),
        ast.Or(exprs=[exposure_condition(), *metric_conditions()]),
        *get_test_accounts_filter(team, experiment.exposure_criteria),
    ]

    # Over-fetched, because ids without a recording are dropped below and would otherwise eat the
    # cap on projects that sample replay.
    fetch_limit = limit * RECORDING_LOOKUP_FACTOR
    query = ast.SelectQuery(
        select=[
            ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"])),
            ast.Alias(alias="last_seen", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(exprs=where_conditions),
        group_by=[ast.Field(chain=["session_id"])],
        having=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=count_if(exposure_condition()),
                    right=ast.Constant(value=0),
                ),
                bucket_predicate,
            ]
        ),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["last_seen"]), order="DESC")],
        limit=ast.Constant(value=fetch_limit),
    )

    # One query, so there is no union to hide an implicit per-branch limit — but the limit is
    # still set explicitly, since an unset one would silently become HogQL's LIMIT 100.
    modifiers = create_default_modifiers_for_team(team)
    shared_hogql = SharedHogQLDatabase(
        # Postgres foreign-key lazy joins are the most expensive part of building the virtual
        # database and this query only reads events.
        database=Database.create_for(team=team, user=user, modifiers=modifiers, build_postgres_foreign_keys=False),
        modifiers=modifiers,
    )
    response = execute_hogql_query(
        query, team=team, user=user, context=shared_hogql.fresh_context(team, user), modifiers=shared_hogql.modifiers
    )

    candidate_ids = [str(row[0]) for row in response.results or []]
    exists_by_id = SessionReplayEvents().batch_exists(candidate_ids, team)
    # Not cut to `limit` here: the caller drops the recordings this viewer can't open first, and
    # the cut has to come after that.
    recorded_ids = [session_id for session_id in candidate_ids if exists_by_id.get(session_id)]
    return recorded_ids, len(candidate_ids) >= fetch_limit
