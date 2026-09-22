"""Resolve which experiments (and variants) a session recording saw.

Variants come from the flag, via complementary event signals:

- `$feature_flag_called` flag evaluations: variant evidence for every experiment — the replay
  shows exactly what the session was served, whatever the exposure criteria say — and the
  exposure moment for experiments with the default criteria shape (variant in
  `$feature_flag_response`).
- Exposure events resolved per experiment from custom exposure criteria through the shared
  `exposure_query_logic` helpers: the configured event/action defines the exposure moment
  (variant in the stamped `$feature/<key>` property).
- `$feature/<key>` properties stamped on every captured event by posthog-js. These cover the
  SDK dedupe gap: a returning user's later sessions may carry no exposure event at all.

The exposure timestamp follows each experiment's exposure criteria, but only within this
session and only within the experiment's own run window: every variant source is clipped to
[start_date, end_date], so a flag evaluation from before the experiment launched or after it
was stopped is not reported as a variant the session saw. The experiment analysis counts
exposure per person across the whole run window (and applies test-account filtering and
multiple-variant handling, which are deliberately not applied here — this surface shows the
raw session truth). Callers must present this as what the session *saw*, not what the
experiment analysis counts.
"""

import logging
import contextvars
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import partial
from typing import Optional

from django.conf import settings
from django.db.models import Q, QuerySet

import pydantic

from posthog.schema import ExperimentEventExposureConfig, ExperimentExposureCriteria

from posthog.hogql import ast
from posthog.hogql.database.database import Database
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dataclasses import frozen
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents, uuidv7_session_lower_bound
from posthog.utils import get_safe_cache, safe_cache_set

from products.cohorts.backend.models.cohort import Cohort

# The module is also imported whole: the capped-session check reads MAX_SCANNED_METRICS as a
# module attribute so it always sees the same value the scan applies (tests patch it there).
from products.experiments.backend import metric_events
from products.experiments.backend.hogql_queries.base_query_utils import analysis_window_end
from products.experiments.backend.hogql_queries.exposure_query_logic import (
    DEFAULT_EXPOSURE_EVENT,
    build_exposure_event_conditions,
    get_exposure_event_and_property,
    normalize_to_exposure_criteria,
)
from products.experiments.backend.metric_events import (
    MetricEventSource,
    MetricHit,
    SharedHogQLDatabase,
    resolve_metric_events,
    scan_sessions_for_metric_events,
)
from products.experiments.backend.models.experiment import Experiment

logger = logging.getLogger(__name__)

# Slack around the recording bounds — flag evaluation can be captured slightly outside the
# replay window (clock skew, events flushed before/after snapshots).
EVENT_WINDOW_SLACK = timedelta(hours=1)
MAX_CANDIDATE_EXPERIMENTS = 50
# The exposure query filters to real experiment flag keys and defined variant names, so its
# group-by output is bounded by team configuration, not by event payloads. The explicit limit
# is a backstop far above any real configuration — without it HogQL applies an implicit
# LIMIT 100, which would silently and nondeterministically truncate legitimate rows.
MAX_EXPOSURE_ROWS = 10_000
# Every distinct clipped run window becomes one union branch in the flag-evaluations query and
# one aggregate column per flag in the stamped-property query, and the experiment set feeding
# those scans is deliberately uncapped (the rescue path must see past the candidate cap).
# Windows only split when an experiment starts or stops inside the scan window, so real
# sessions see one or two; the cap bounds query width against many staggered experiment
# boundaries. Newest experiments keep their windows, like every other cap here.
MAX_DISTINCT_SCAN_WINDOWS = 50
# Short-lived because the context is not immutable: late-arriving events and experiment edits
# must surface within minutes. The key includes the viewer because the experiment set is
# filtered by per-user access control, so entries must never be shared across users.
# The TTL is not an access-control boundary. Entries are re-filtered against the viewer's
# current experiment access on read (see _accessible_items), and whether the viewer may open
# the recording at all is decided per request in the view, so neither kind of revocation waits
# for expiry. That keeps invalidation out of a path whose only job is to cut latency.
SESSION_CONTEXT_CACHE_TTL = 10 * 60
# Hard cap on the batch endpoint's id list. A playlist page holds 20 recordings, and every
# extra session widens the grouped scans; anything larger should arrive as separate batches.
MAX_SESSION_CONTEXT_BATCH = 20
# Each distinct recording day in a batch runs its own set of scans, so ids scattered across
# many days would fan one throttled HTTP request out into dozens of ClickHouse queries. The
# most recent days win (recordings lists sort by recency); sessions beyond the budget are
# omitted — never cached — so the single-session endpoint computes them on demand.
MAX_SESSION_CONTEXT_BATCH_DAYS = 5


@frozen
class _ScanWindow:
    """A closed timestamp range one variant source is read over."""

    start: datetime
    end: datetime


@frozen
class _RunWindow:
    """An experiment's own run window, open-ended (`end is None`) while the experiment runs.

    Variant evidence from outside this window is not something the session saw while the
    experiment ran, so every variant source is clipped to it. The experiment analysis clips the
    same way, which is why an evaluation past `end_date` shows up in the replay context but not
    in the results.
    """

    start: datetime
    end: Optional[datetime]

    def clip(self, window_start: datetime, window_end: datetime) -> Optional[_ScanWindow]:
        """This run window intersected with the given scan window, or None when they don't
        overlap at all and the source has nothing to read."""
        start = max(self.start, window_start)
        # analysis_window_end also caps the experiment analysis, so the replay boundary and the
        # analysis boundary come from one definition and cannot drift apart.
        end = analysis_window_end(self.end, window_end)
        return _ScanWindow(start=start, end=end) if start <= end else None


@frozen
class _BranchMeta:
    """One non-batchable experiment's inputs for its exposure-event union branch."""

    experiment_id: int
    resolution: "_ResolvedExposure"
    variant_keys: set[str]
    run_window: _RunWindow


@dataclass(frozen=True)
class _ResolvedExposure:
    """An experiment's exposure criteria resolved to what its exposure query needs: which
    property carries the variant, whether the experiment can share the batched default
    `$feature_flag_called` query, and the normalized criteria + flag key from which the
    per-experiment branch conditions are built — lazily, after the branch cap, since
    action-based conditions cost a Postgres lookup each."""

    flag_key: str
    variant_property: str
    criteria: Optional[ExperimentExposureCriteria]
    batchable: bool


@dataclass(frozen=True)
class ExperimentSessionContextItem:
    experiment_id: int
    experiment_name: str
    flag_key: str
    variant: str
    variants_seen: list[str]
    multiple_variants: bool
    first_exposure_timestamp: Optional[datetime]
    experiment_start_date: Optional[datetime]
    experiment_end_date: Optional[datetime]
    # The experiment's metrics with >=1 matching event in the session, sorted by first occurrence.
    metrics_in_session: list[MetricHit]


@dataclass(frozen=True)
class _SessionWindow:
    """One session's recording bounds — the unit the batch compute fans out over."""

    session_id: str
    recording_start: datetime
    recording_end: datetime


@dataclass(frozen=True)
class _ResolvedCandidates:
    """The batch's overlapping experiments and their resolved exposure metadata, computed once
    over the union of the sessions' recording windows and shared by every day-chunk. The
    capped candidate slice is per chunk, not here — see _compute_session_experiment_contexts."""

    overlapping: QuerySet[Experiment]
    flag_key_by_id: dict[int, str]
    variant_keys_by_id: dict[int, set[str]]
    batchable_ids: set[int]
    all_variant_keys: set[str]
    branch_meta: list[_BranchMeta]
    run_window_by_id: dict[int, "_RunWindow"]


def _cache_key(team: Team, user: User, session_id: str) -> str:
    # The version segment must be bumped whenever the cached dataclasses change shape: entries are
    # pickled, so a deploy would otherwise restore instances missing the new fields. Bump it for a
    # fix that changes the computed values too, so corrected entries replace wrong ones on deploy
    # instead of after the TTL.
    return f"experiment_session_context_v3_{team.pk}_{user.pk}_{session_id}"


def _accessible_items(
    items: list[ExperimentSessionContextItem], accessible_experiment_ids: set[int]
) -> list[ExperimentSessionContextItem]:
    """Re-check cached items against the viewer's current experiment access.

    An entry was filtered against `experiments` when it was computed, so without this a viewer
    whose access to an experiment is revoked would keep seeing it until the entry expires.
    Re-checking on read makes revocation take effect immediately; a newly granted experiment
    still waits for the entry to expire, which is the safe direction to lag in.
    """
    return [item for item in items if item.experiment_id in accessible_experiment_ids]


def get_session_experiment_context(
    team: Team, session_id: str, experiments: QuerySet[Experiment], user: User
) -> Optional[list[ExperimentSessionContextItem]]:
    """Returns the experiments the session saw, or None when the recording doesn't exist for this team.

    `experiments` is the caller's base queryset — the view passes it through object-level
    access control so private experiments never surface in another user's session context.
    `user` is the viewer: exposure criteria can filter on arbitrary event/person properties,
    and the queries must enforce that user's property-level access control (as the experiment
    query runners do) — userless execution would apply only the default property rules.

    Results are cached per (team, viewer, session) for SESSION_CONTEXT_CACHE_TTL so reopening
    a recording doesn't re-run the ClickHouse scans. "Recording not found" is not cached: the
    recording may simply still be ingesting.
    """
    cache_key = _cache_key(team, user, session_id)
    cached = get_safe_cache(cache_key)
    if cached is not None:
        return _accessible_items(cached, set(experiments.values_list("id", flat=True)))

    metadata = SessionReplayEvents().get_metadata(session_id, team)
    if metadata is None:
        return None
    window = _SessionWindow(
        session_id=session_id, recording_start=metadata["start_time"], recording_end=metadata["end_time"]
    )
    # fail_open=False: unlike the best-effort batch prefetch, the player's request must surface
    # a scan failure as an error, never as a false "recording not found".
    computed, _ = _compute_session_experiment_contexts(team, [window], experiments, user, fail_open=False)
    items = computed[session_id]
    # A capped single session is still cached: with one session there is no batch union, so a
    # recompute would drop the same metrics again and caching the capped result loses nothing.
    safe_cache_set(cache_key, items, timeout=SESSION_CONTEXT_CACHE_TTL)
    return items


def get_session_experiment_contexts(
    team: Team, session_ids: list[str], experiments: QuerySet[Experiment], user: User
) -> dict[str, list[ExperimentSessionContextItem]]:
    """Batch variant of get_session_experiment_context: session_id -> items, in input order.

    Reads and writes the same per-(team, viewer, session) cache entries as the single-session
    endpoint — already-warm sessions are skipped, cold ones are computed in shared scans and
    written back so a later single-session request hits cache. Sessions whose recording
    metadata doesn't exist (yet) are omitted and never cached, mirroring the single endpoint's
    not-found rule; so are ids without a parseable uuidv7 timestamp, whose metadata lookup
    would otherwise run unbounded. The batch is best-effort: a day-chunk whose scans fail is
    logged and omitted rather than failing the whole request, and a session is returned but
    not cached when the shared scan's metric cap dropped a metric that session's own
    single-session scan would have kept — so the cache never holds less than a single-session
    request would compute. A session whose own metrics already exceed the cap is cached
    despite the truncation: a recompute would drop the same metrics again, mirroring how the
    single-session endpoint caches its own capped results.
    """
    unique_ids = list(dict.fromkeys(session_ids))
    results: dict[str, list[ExperimentSessionContextItem]] = {}
    cold_ids: list[str] = []
    # Resolved once for the whole batch, and only when something is actually served from cache.
    accessible_experiment_ids: Optional[set[int]] = None
    for session_id in unique_ids:
        cached = get_safe_cache(_cache_key(team, user, session_id))
        if cached is not None:
            if accessible_experiment_ids is None:
                accessible_experiment_ids = set(experiments.values_list("id", flat=True))
            results[session_id] = _accessible_items(cached, accessible_experiment_ids)
        else:
            cold_ids.append(session_id)

    if cold_ids:
        # Bounded below by the batch's oldest uuidv7-derived session start (with clock-skew
        # slack); ids with no usable bound are excluded from the lookup entirely so one bad id
        # can't unbound the scan. An id that defeats or lacks the bound is simply not found
        # here and never cached as absent, so the single-session endpoint — whose lookup falls
        # back to an unbounded scan — still resolves it on demand.
        bounded_ids, lower_bound = _bounded_metadata_ids(cold_ids)
        metadata_by_id = SessionReplayEvents().get_group_metadata(
            bounded_ids, team, recordings_min_timestamp=lower_bound
        )
        windows = [
            _SessionWindow(
                session_id=session_id,
                recording_start=metadata["start_time"],
                recording_end=metadata["end_time"],
            )
            for session_id, metadata in metadata_by_id.items()
            if metadata is not None
        ]
        computed, capped_session_ids = _compute_session_experiment_contexts(
            team, windows, experiments, user, fail_open=True
        )
        for session_id, items in computed.items():
            # A capped session lost a metric to the batch-wide scan cap that its own
            # single-session scan would have kept, so caching would serve less than the
            # single-session endpoint computes; it is returned best-effort and left for
            # on-demand recompute instead.
            if session_id not in capped_session_ids:
                safe_cache_set(_cache_key(team, user, session_id), items, timeout=SESSION_CONTEXT_CACHE_TTL)
        results.update(computed)

    return {session_id: results[session_id] for session_id in unique_ids if session_id in results}


def _bounded_metadata_ids(session_ids: list[str]) -> tuple[list[str], Optional[datetime]]:
    """The session ids whose embedded uuidv7 timestamp yields a metadata-scan lower bound
    (with clock-skew slack), and the oldest of those bounds. Ids without a usable bound are
    excluded rather than queried: keeping one in would force the whole batch's metadata scan
    unbounded across the table's retained date range. The batch is best-effort, so such an
    id (rare legacy formats, or garbage) is simply omitted — the single-session endpoint,
    whose lookup falls back to an unbounded scan, still resolves it on demand."""
    bounds_by_id = {
        session_id: bound for session_id in session_ids if (bound := uuidv7_session_lower_bound(session_id)) is not None
    }
    if not bounds_by_id:
        return [], None
    return list(bounds_by_id), min(bounds_by_id.values())


def _chunk_windows_by_recording_day(windows: list[_SessionWindow]) -> list[list[_SessionWindow]]:
    """Group sessions by recording start day. Each chunk scans one contiguous timestamp range,
    so a batch mixing old and new recordings doesn't widen every scan to the full span and
    destroy the events table's date-partition pruning."""
    by_day: dict[date, list[_SessionWindow]] = {}
    for window in windows:
        by_day.setdefault(window.recording_start.date(), []).append(window)
    return [by_day[day] for day in sorted(by_day)]


def _compute_session_experiment_contexts(
    team: Team,
    windows: list[_SessionWindow],
    experiments: QuerySet[Experiment],
    user: User,
    *,
    fail_open: bool,
) -> tuple[dict[str, list[ExperimentSessionContextItem]], set[str]]:
    """Returns (session_id -> items, capped session ids). Capped sessions had a metric dropped
    by the batch-wide scan cap that their own single-session scan would have kept; their items
    are still returned, but the batch caller must not cache them, because a single-session
    recompute would return more. Sessions whose own metrics exceed the cap by themselves are
    not marked capped — a recompute would drop the same metrics — so they stay cacheable."""
    if not windows:
        return {}, set()

    union_start = min(window.recording_start for window in windows)
    union_end = max(window.recording_end for window in windows)

    # Launched experiments whose run window overlaps any of the recordings (the union of the
    # windows here; each session re-checks its own bounds when surfacing). Archived experiments
    # are kept on purpose: the session really saw their variant while they ran.
    overlapping = (
        experiments.filter(team_id=team.pk)
        .exclude(deleted=True)
        .filter(start_date__isnull=False, start_date__lte=union_end)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=union_start))
        .select_related("feature_flag")
    )
    # Every overlapping experiment's flag key (uncapped — the rescue below must be able to see
    # beyond the candidate cap), its exposure criteria, its defined variant names, and its run
    # window (so each day-chunk can pick its own candidate slice below, and every variant source
    # is clipped to the window its experiment ran over). Filtering the exposure queries to these
    # bounds their cardinality by real configuration: sessions call plenty of non-experiment
    # flags, and event payloads can carry arbitrary keys/variants.
    flag_meta = list(
        overlapping.order_by("-start_date").values_list(
            "id", "feature_flag__key", "feature_flag__filters", "exposure_criteria", "start_date", "end_date"
        )
    )
    if not flag_meta:
        return {window.session_id: [] for window in windows}, set()
    # Each experiment's exposure criteria resolve (through the shared helpers) to what counts
    # as its exposure event and which property carries the variant. Experiments with the plain
    # default shape take their exposure moment straight from the shared flag-evaluations query;
    # the rest get one union branch each. Everything is keyed by experiment id, since two
    # experiments can share a flag with different criteria.
    flag_key_by_id: dict[int, str] = {}
    variant_keys_by_id: dict[int, set[str]] = {}
    batchable_ids: set[int] = set()
    all_variant_keys: set[str] = set()
    branch_meta: list[_BranchMeta] = []
    run_window_by_id: dict[int, _RunWindow] = {}
    for experiment_id, flag_key, filters, exposure_criteria, start_date, end_date in flag_meta:
        # The overlapping queryset filters start_date__isnull=False.
        assert start_date is not None
        variant_keys = _variant_keys_from_filters(filters)
        if not variant_keys:
            continue
        run_window = _RunWindow(start=start_date, end=end_date)
        run_window_by_id[experiment_id] = run_window
        flag_key_by_id[experiment_id] = flag_key
        variant_keys_by_id[experiment_id] = variant_keys
        all_variant_keys |= variant_keys
        resolution = _resolve_exposure(flag_key, exposure_criteria)
        if resolution.batchable:
            batchable_ids.add(experiment_id)
        else:
            branch_meta.append(
                _BranchMeta(
                    experiment_id=experiment_id,
                    resolution=resolution,
                    variant_keys=variant_keys,
                    run_window=run_window,
                )
            )
    if not flag_key_by_id:
        # No overlapping experiment defines variants, so nothing could surface a variant seen.
        return {window.session_id: [] for window in windows}, set()

    chunks = _chunk_windows_by_recording_day(windows)
    if len(chunks) > MAX_SESSION_CONTEXT_BATCH_DAYS:
        # Ascending day order, so the slice keeps the most recent days' chunks. The dropped
        # sessions are omitted from the result (never cached as anything).
        dropped = [window.session_id for chunk in chunks[:-MAX_SESSION_CONTEXT_BATCH_DAYS] for window in chunk]
        logger.warning(
            "Session-context batch spans more than %s recording days; omitting sessions %s",
            MAX_SESSION_CONTEXT_BATCH_DAYS,
            dropped,
        )
        chunks = chunks[-MAX_SESSION_CONTEXT_BATCH_DAYS:]

    # The stamped-property query needs one column per flag, so each chunk's candidate set must
    # be capped; newest-first keeps a slice deterministic and biased toward the most relevant
    # experiments. Capping per chunk — against the chunk's own recording window — means a batch
    # mixing old and new recordings surfaces the same experiments N single-session requests
    # would: a global slice over the union window could displace an older chunk's experiments
    # behind newer ones, and stamped-only evidence is never rescued.
    candidate_ids_by_chunk: list[list[int]] = []
    for chunk in chunks:
        chunk_start = min(window.recording_start for window in chunk)
        chunk_end = max(window.recording_end for window in chunk)
        candidate_ids_by_chunk.append(
            [
                experiment_id
                for experiment_id, _flag_key, _filters, _criteria, start_date, end_date in flag_meta
                if start_date is not None and start_date <= chunk_end and (end_date is None or end_date >= chunk_start)
            ][:MAX_CANDIDATE_EXPERIMENTS]
        )
    all_candidate_ids = {experiment_id for chunk_ids in candidate_ids_by_chunk for experiment_id in chunk_ids}
    if not all_candidate_ids:
        return {window.session_id: [] for chunk in chunks for window in chunk}, set()
    experiments_by_id = {experiment.pk: experiment for experiment in overlapping.filter(id__in=all_candidate_ids)}

    # Every scan below goes through HogQL, and constructing the virtual database dominates this
    # endpoint's wall time on teams with a large warehouse schema — several seconds per query,
    # paid once per query, while ClickHouse itself answers in well under a second. Build the
    # database once here and share it across all the scans, including across the thread pool
    # and every day-chunk. Sound only while every scan sticks to plain table reads —
    # SharedHogQLDatabase documents the two query shapes that mutate a database at query time,
    # and test_uncached_request_shares_one_readonly_hogql_database pins that these scans don't.
    # The build modifiers travel with the database so every scan queries the schema it was
    # built for; no scan may pass its own modifiers. Postgres foreign-key lazy joins are
    # skipped — the single most expensive build step, and these queries only ever read the
    # events table.
    # Tagged here, not at the entry points: the recording-metadata lookup above is replay's own
    # query and tags itself as such, so an earlier tag would be overwritten and these scans would
    # bill to replay. The scans are experiments' own — exposure criteria and metric definitions
    # over the events table — and follow the convention of tagging the product whose logic and
    # cost they are, not the surface they render on.
    tag_queries(product=Product.EXPERIMENTS, feature=Feature.QUERY, team_id=team.pk)

    hogql_modifiers = create_default_modifiers_for_team(team)
    shared_hogql = SharedHogQLDatabase(
        database=Database.create_for(
            team=team,
            user=user,
            modifiers=hogql_modifiers,
            build_postgres_foreign_keys=False,
        ),
        modifiers=hogql_modifiers,
    )

    resolved = _ResolvedCandidates(
        overlapping=overlapping,
        flag_key_by_id=flag_key_by_id,
        variant_keys_by_id=variant_keys_by_id,
        batchable_ids=batchable_ids,
        all_variant_keys=all_variant_keys,
        branch_meta=branch_meta,
        run_window_by_id=run_window_by_id,
    )

    results: dict[str, list[ExperimentSessionContextItem]] = {}
    capped_session_ids: set[str] = set()
    for chunk, candidate_ids in zip(chunks, candidate_ids_by_chunk):
        candidates = [
            experiments_by_id[experiment_id] for experiment_id in candidate_ids if experiment_id in experiments_by_id
        ]
        if not candidates:
            # No experiment overlaps this chunk's recordings — the same empty answer a
            # single-session request would compute (and cache) without running any scan.
            results.update({window.session_id: [] for window in chunk})
            continue
        try:
            chunk_results, chunk_capped = _compute_chunk_contexts(team, user, shared_hogql, resolved, chunk, candidates)
            results.update(chunk_results)
            capped_session_ids |= chunk_capped
        except Exception:
            if not fail_open:
                raise
            # Best-effort batch: one pathological chunk must not take down the others. Its
            # sessions are omitted (and never cached), so they can still compute on demand.
            logger.exception(
                "Session-context scan failed for sessions %s; omitting them from the batch",
                [window.session_id for window in chunk],
            )
    return results, capped_session_ids


def _compute_chunk_contexts(
    team: Team,
    user: User,
    shared_hogql: SharedHogQLDatabase,
    resolved: _ResolvedCandidates,
    windows: list[_SessionWindow],
    candidates: list[Experiment],
) -> tuple[dict[str, list[ExperimentSessionContextItem]], set[str]]:
    session_ids = [window.session_id for window in windows]
    recording_start = min(window.recording_start for window in windows)
    recording_end = max(window.recording_end for window in windows)
    window_start = recording_start - EVENT_WINDOW_SLACK
    window_end = recording_end + EVENT_WINDOW_SLACK

    # Flag evaluations are variant evidence for every experiment — the replay shows exactly
    # what the session was served, whatever the exposure criteria say — and double as the
    # exposure moment for experiments with the default criteria shape.
    query_flag_evaluations = partial(
        _query_flag_evaluations,
        team,
        user,
        shared_hogql,
        session_ids,
        _scan_windows_by_flag_key(resolved, set(resolved.flag_key_by_id.values()), window_start, window_end),
        resolved.all_variant_keys,
    )
    # Same width backstop as the candidate cap — each branch experiment adds a union branch, so
    # (unlike the single-scan flag-evaluations query) non-batchable experiments beyond the
    # cap are deliberately not queried: they get no criteria-driven exposure moment, though
    # flag evaluations still evidence (and rescue) them like any other experiment.
    # Branch slots go to experiments that ran during this chunk's recordings, the same raw
    # bounds candidate selection uses: an experiment that ran only inside the slack margin can
    # never pass the per-session bounds re-check below, so it must not displace one whose
    # events the chunk can surface. Each kept branch still reads the slack-extended window,
    # computed here so slot allocation and the query cannot disagree.
    clipped_branches = [
        (meta, clipped)
        for meta in resolved.branch_meta
        if meta.run_window.clip(recording_start, recording_end) is not None
        and (clipped := meta.run_window.clip(window_start, window_end)) is not None
    ]
    query_exposure_branches = partial(
        _query_exposure_event_branches,
        team,
        user,
        shared_hogql,
        session_ids,
        clipped_branches[:MAX_CANDIDATE_EXPERIMENTS],
    )
    candidate_keys = {experiment.feature_flag.key for experiment in candidates}
    query_stamped = partial(
        _query_stamped_flag_properties,
        team,
        user,
        shared_hogql,
        session_ids,
        _scan_windows_by_flag_key(resolved, candidate_keys, window_start, window_end),
    )

    # The three scans are independent given the pre-rescue candidate set (only the rescue
    # follow-up below consumes another scan's output), so they run concurrently — total wait
    # is the slowest scan, not the sum. Sequential under TEST: worker threads open their own
    # DB connections, which can't see the test transaction's uncommitted data.
    if settings.TEST:
        flag_evaluations = query_flag_evaluations()
        branch_exposures = query_exposure_branches()
        stamped = query_stamped()
    else:
        with ThreadPoolExecutor(max_workers=3) as executor:
            # ThreadPoolExecutor does not inherit contextvars (query tags) by default; copy the
            # current context into each worker so tagged ClickHouse queries don't fail untagged.
            flag_evaluations_future = executor.submit(contextvars.copy_context().run, query_flag_evaluations)
            branch_exposures_future = executor.submit(contextvars.copy_context().run, query_exposure_branches)
            stamped_future = executor.submit(contextvars.copy_context().run, query_stamped)
            flag_evaluations = flag_evaluations_future.result()
            branch_exposures = branch_exposures_future.result()
            stamped = stamped_future.result()

    # Each experiment's run window intersected with this chunk's scan window: the range its
    # flag evidence was read over, and so the key assembly uses to pick that evidence back up.
    scan_window_by_id = {
        experiment_id: run_window.clip(window_start, window_end)
        for experiment_id, run_window in resolved.run_window_by_id.items()
    }

    # Per-session exposure evidence keyed by experiment id: batchable experiments read the
    # shared flag-evaluations query over their own clipped window, the rest their own union
    # branch.
    exposures: dict[str, dict[int, list[tuple[str, datetime]]]] = {}
    for session_id in session_ids:
        session_flag_evaluations = flag_evaluations.get(session_id, {})
        session_exposures: dict[int, list[tuple[str, datetime]]] = {}
        for experiment_id in resolved.batchable_ids:
            scan_window = scan_window_by_id[experiment_id]
            if scan_window is None:
                continue
            rows = session_flag_evaluations.get((resolved.flag_key_by_id[experiment_id], scan_window))
            if rows:
                session_exposures[experiment_id] = rows
        session_exposures.update(branch_exposures.get(session_id, {}))
        exposures[session_id] = session_exposures

    # The exposure queries cover every overlapping experiment's flag (not just the capped
    # candidates), so a flag with verifiable in-session evidence rescues its experiment even
    # when it fell outside the cap above. Rescued keys join the stamped-property evidence too,
    # through a follow-up query for just those keys (the main stamped scan already ran on the
    # pre-rescue candidates) — it stays bounded, since rescues are limited to real overlapping
    # experiments a session in the chunk demonstrably called.
    evidenced_keys: set[str] = set()
    for session_id in session_ids:
        evidenced_keys |= {flag_key for flag_key, _window in flag_evaluations.get(session_id, {})}
        evidenced_keys |= {resolved.flag_key_by_id[experiment_id] for experiment_id in exposures[session_id]}
    rescued_keys = evidenced_keys - candidate_keys
    if rescued_keys:
        candidates = candidates + list(resolved.overlapping.filter(feature_flag__key__in=sorted(rescued_keys)))
        rescued_stamped = _query_stamped_flag_properties(
            team,
            user,
            shared_hogql,
            session_ids,
            _scan_windows_by_flag_key(resolved, rescued_keys, window_start, window_end),
        )
        for session_id, values_by_key in rescued_stamped.items():
            stamped.setdefault(session_id, {}).update(values_by_key)

    surfaced_by_session: dict[str, list[tuple[Experiment, str, list[str], Optional[datetime]]]] = {}
    for window in windows:
        session_id = window.session_id
        session_exposures = exposures.get(session_id, {})
        session_flag_evaluations = flag_evaluations.get(session_id, {})
        session_stamped = stamped.get(session_id, {})
        surfaced: list[tuple[Experiment, str, list[str], Optional[datetime]]] = []
        for experiment in candidates:
            # Candidates overlap the union of the batch's recording windows; re-check this
            # session's own bounds so a batch surfaces exactly what N single requests would.
            if experiment.start_date is None or experiment.start_date > window.recording_end:
                continue
            if experiment.end_date is not None and experiment.end_date < window.recording_start:
                continue
            flag_key = experiment.feature_flag.key
            # Flag evidence is keyed by (flag key, this experiment's own clipped window), so
            # two experiments sharing a flag each read only what fell inside their own run.
            scan_window = scan_window_by_id.get(experiment.pk)
            # Only the flag's defined variant keys count, mirroring the `variant IN variants` filter
            # in the analysis queries: a non-enrolled user's flag evaluation captures
            # `$feature_flag_response: false`, which must not surface as a variant named "false".
            defined_variants = resolved.variant_keys_by_id.get(experiment.pk, set())
            exposure_rows = [row for row in session_exposures.get(experiment.pk, []) if row[0] in defined_variants]
            flag_rows = (
                [row for row in session_flag_evaluations.get((flag_key, scan_window), []) if row[0] in defined_variants]
                if scan_window
                else []
            )
            stamped_values = (
                [value for value in session_stamped.get((flag_key, scan_window), []) if value in defined_variants]
                if scan_window
                else []
            )
            variants_seen = sorted(
                {variant for variant, _ in exposure_rows} | {variant for variant, _ in flag_rows} | set(stamped_values)
            )
            if not variants_seen:
                continue

            first_exposure_timestamp: Optional[datetime] = None
            if exposure_rows:
                variant, first_exposure_timestamp = min(exposure_rows, key=lambda row: row[1])
            elif flag_rows:
                # The session was demonstrably served this variant, but no event matched the
                # experiment's exposure criteria — so there is no exposure moment to point at.
                variant = min(flag_rows, key=lambda row: row[1])[0]
            else:
                variant = variants_seen[0]

            surfaced.append((experiment, variant, variants_seen, first_exposure_timestamp))
        surfaced_by_session[session_id] = surfaced

    # Only the experiments that actually surfaced get their metrics scanned — one scan covers
    # the union across the chunk's sessions, shared saved metrics dedupe by uuid inside the
    # scan, and each session's experiments claim their own metrics' hits back by uuid.
    # MAX_SCANNED_METRICS caps that union in surfacing order. On experiment-heavy teams a
    # single session can surface dozens of experiments carrying well over the cap by itself,
    # so hitting the cap is the steady state there, for the batch and single request alike.
    # A session is reported as capped below only when the batch dropped a metric its own
    # single-session scan would have kept (see _single_scan_accepted_uuids) — those the batch
    # never caches, so a single request can recompute the fuller set on demand. Sessions whose
    # own metrics exceed the cap anyway stay cacheable: a recompute would drop the same
    # metrics, so withholding the cache entry would buy nothing and cost a full recompute per
    # open (which, before this distinction, made the prefetch useless on experiment-heavy
    # teams — every session shares the same over-cap experiment set, so every session was
    # marked capped and nothing was ever cached). Metric hits are enrichment on top of the
    # exposure context: an unexpected failure here (one experiment's malformed stored metric,
    # say) must degrade to "no metric hits", never take down the exposure context that already
    # resolved above.
    sources_by_experiment: dict[int, list[MetricEventSource]] = {}
    hits_by_session: dict[str, dict[str, MetricHit]] = {}
    dropped_metric_uuids: set[str] = set()
    try:
        for session_surfaced in surfaced_by_session.values():
            for experiment, *_ in session_surfaced:
                if experiment.pk not in sources_by_experiment:
                    sources_by_experiment[experiment.pk] = resolve_metric_events(experiment)
        all_sources = [source for sources in sources_by_experiment.values() for source in sources]
        if all_sources:
            scan = scan_sessions_for_metric_events(
                team,
                user,
                metric_sources=all_sources,
                session_ids=session_ids,
                window_start=window_start,
                window_end=window_end,
                shared_hogql=shared_hogql,
            )
            dropped_metric_uuids = scan.dropped_metric_uuids
            hits_by_session = {
                session_id: {hit.metric_uuid: hit for hit in hits} for session_id, hits in scan.hits_by_session.items()
            }
    except Exception:
        logger.exception("Metric-event scan failed for sessions %s; returning context without metric hits", session_ids)
        sources_by_experiment = {}
        hits_by_session = {}
        dropped_metric_uuids = set()

    capped_session_ids: set[str] = set()
    if dropped_metric_uuids:
        capped_session_ids = {
            session_id
            for session_id, session_surfaced in surfaced_by_session.items()
            if dropped_metric_uuids & _single_scan_accepted_uuids(session_surfaced, sources_by_experiment)
        }

    results: dict[str, list[ExperimentSessionContextItem]] = {}
    for session_id, session_surfaced in surfaced_by_session.items():
        session_hits = hits_by_session.get(session_id, {})
        items: list[ExperimentSessionContextItem] = []
        for experiment, variant, variants_seen, first_exposure_timestamp in session_surfaced:
            metrics_in_session = sorted(
                {
                    source.metric_uuid: session_hits[source.metric_uuid]
                    for source in sources_by_experiment.get(experiment.pk, [])
                    if source.metric_uuid in session_hits
                }.values(),
                key=lambda hit: hit.first_timestamp,
            )
            items.append(
                ExperimentSessionContextItem(
                    experiment_id=experiment.pk,
                    experiment_name=experiment.name,
                    flag_key=experiment.feature_flag.key,
                    variant=variant,
                    variants_seen=variants_seen,
                    multiple_variants=len(variants_seen) > 1,
                    first_exposure_timestamp=first_exposure_timestamp,
                    experiment_start_date=experiment.start_date,
                    experiment_end_date=experiment.end_date,
                    metrics_in_session=metrics_in_session,
                )
            )
        results[session_id] = sorted(items, key=lambda item: item.experiment_name.lower())
    return results, capped_session_ids


def _single_scan_accepted_uuids(
    session_surfaced: list[tuple[Experiment, str, list[str], Optional[datetime]]],
    sources_by_experiment: dict[int, list[MetricEventSource]],
) -> set[str]:
    """The metric uuids a single-session request's scan would accept for this session.

    Mirrors scan_sessions_for_metric_events' acceptance rule — the first MAX_SCANNED_METRICS
    distinct session-linkable uuids, in source order — applied to only this session's surfaced
    experiments. The order matches what a single-session request produces: its scan receives
    the session's surfaced experiments in candidate (newest-first) order, which is exactly the
    order of `session_surfaced` here. A batch-dropped uuid outside this set would be dropped
    by a single-session recompute too, so it must not disqualify the session from caching."""
    accepted: set[str] = set()
    for experiment, *_ in session_surfaced:
        for source in sources_by_experiment.get(experiment.pk, []):
            if not source.session_linkable or source.metric_uuid in accepted:
                continue
            if len(accepted) >= metric_events.MAX_SCANNED_METRICS:
                return accepted
            accepted.add(source.metric_uuid)
    return accepted


def _resolve_exposure(flag_key: str, exposure_criteria: Optional[dict]) -> _ResolvedExposure:
    """Resolve an experiment's exposure criteria through the shared `exposure_query_logic`
    helpers — the single seam that keeps this surface in sync with the experiment analysis.
    Malformed stored criteria fall back to the default exposure event rather than failing the
    whole surface for one broken experiment."""
    criteria: Optional[ExperimentExposureCriteria]
    try:
        criteria = normalize_to_exposure_criteria(exposure_criteria)
    except pydantic.ValidationError:
        criteria = None
    exposure_config = criteria.exposure_config if criteria else None
    # This surface deliberately stays on the legacy default rather than resolving the
    # $experiment_exposure rollout per experiment: its shared flag-evaluations query reads
    # $feature_flag_called, and while ingestion emits both events every exposure still lands on
    # the same sessions, so the legacy event stays correct here for now.
    event, variant_property = get_exposure_event_and_property(
        flag_key, criteria, default_exposure_event=DEFAULT_EXPOSURE_EVENT
    )
    # Only experiments whose criteria resolve to the plain `$feature_flag_called` shape (no
    # extra property filters) can share the batched query. The literal is deliberate — it names
    # the batched query's shape, not the default: if DEFAULT_EXPOSURE_EVENT ever changes in
    # `exposure_query_logic`, criteria-less experiments resolve to the new event here and
    # automatically take the per-experiment branch path, which follows the criteria.
    has_property_filters = isinstance(exposure_config, ExperimentEventExposureConfig) and bool(
        exposure_config.properties
    )
    batchable = event == "$feature_flag_called" and not has_property_filters
    return _ResolvedExposure(
        flag_key=flag_key, variant_property=variant_property, criteria=criteria, batchable=batchable
    )


def _variant_keys_from_filters(filters: Optional[dict]) -> set[str]:
    multivariate = (filters or {}).get("multivariate") or {}
    return {variant["key"] for variant in multivariate.get("variants", []) if variant.get("key")}


def _scan_windows_by_flag_key(
    resolved: _ResolvedCandidates,
    flag_keys: set[str],
    window_start: datetime,
    window_end: datetime,
) -> dict[str, list[_ScanWindow]]:
    """The timestamp ranges each flag key's events are read over: each of its experiments' run
    windows intersected with the scan window, deduplicated. Experiments sharing one flag
    usually share one clipped window; when their run windows differ inside the scan window,
    each window gets its own entry, so no experiment reads a sibling's range. At most
    MAX_DISTINCT_SCAN_WINDOWS distinct windows are kept, newest experiments first. A key with
    no window to read is dropped, since none of its events can evidence a variant the session
    saw; that also covers candidate keys for variant-less experiments and flags renamed
    between the metadata fetch and the candidate fetch."""
    windows: dict[str, list[_ScanWindow]] = {}
    kept_windows: set[_ScanWindow] = set()
    for experiment_id, flag_key in resolved.flag_key_by_id.items():
        if flag_key not in flag_keys:
            continue
        window = resolved.run_window_by_id[experiment_id].clip(window_start, window_end)
        if window is None:
            continue
        if window not in kept_windows:
            # flag_key_by_id iterates newest experiments first, so past the cap the oldest
            # experiments' windows are the ones dropped; a dropped window means that experiment
            # contributes no batched evidence, the same degradation as the candidate cap.
            if len(kept_windows) >= MAX_DISTINCT_SCAN_WINDOWS:
                continue
            kept_windows.add(window)
        key_windows = windows.setdefault(flag_key, [])
        if window not in key_windows:
            key_windows.append(window)
    return {
        flag_key: sorted(key_windows, key=lambda window: (window.start, window.end))
        for flag_key, key_windows in windows.items()
    }


def _query_flag_evaluations(
    team: Team,
    user: User,
    shared_hogql: SharedHogQLDatabase,
    session_ids: list[str],
    flag_key_windows: dict[str, list[_ScanWindow]],
    variants: set[str],
) -> dict[str, dict[tuple[str, _ScanWindow], list[tuple[str, datetime]]]]:
    """The sessions' `$feature_flag_called` events for the given experiment flag keys and
    defined variant names, as session_id -> (flag_key, scan window) -> [(variant, first_seen)].
    Each key is read only over its experiments' own scan windows, so an evaluation from outside
    an experiment's run window never reaches that experiment. Serves two roles: variant
    evidence for every experiment (the replay shows what the session was served, whatever the
    exposure criteria say), and the exposure moment for experiments whose criteria resolve to
    the plain default shape (`$feature_flag_called` with no extra property filters).

    Shape-bound to `$feature_flag_called` on purpose — the `$feature_flag` batching key and
    the `$feature_flag_response` variant property come with that event, so all three are
    hardcoded together. If DEFAULT_EXPOSURE_EVENT changes in `exposure_query_logic`, this
    query needs no rewrite: flag evaluations stay `$feature_flag_called` events, and
    `_resolve_exposure` stops classifying criteria-less experiments as batchable, so their
    exposure moments move to the branch path."""
    if not flag_key_windows:
        return {}
    # One union branch per distinct clipped window, scanning the flag keys read over that
    # window. Windows must aggregate apart, because min(timestamp) per (session, flag, variant)
    # collapses evidence across a branch's whole range: one shared row for two experiments'
    # windows would carry the earlier experiment's timestamp into the later one, and dropping
    # or re-clipping rows afterwards would erase a variant the session really saw. While every
    # experiment runs there is exactly one distinct window, so the query is one branch: a
    # single IN plus one timestamp range, directly prunable.
    keys_by_window: dict[_ScanWindow, list[str]] = {}
    for flag_key in sorted(flag_key_windows):
        for window in flag_key_windows[flag_key]:
            keys_by_window.setdefault(window, []).append(flag_key)
    ordered_windows = sorted(keys_by_window, key=lambda window: (window.start, window.end))
    branches: list[ast.SelectQuery] = []
    for window_index, window in enumerate(ordered_windows):
        branch = parse_select(
            """
            SELECT {window_index} AS window_index,
                   $session_id AS session_id,
                   properties.$feature_flag AS flag_key,
                   toString(properties.$feature_flag_response) AS variant,
                   min(timestamp) AS first_seen
            FROM events
            WHERE event = '$feature_flag_called'
              AND $session_id IN {session_ids}
              AND properties.$feature_flag IN {flag_keys}
              AND toString(properties.$feature_flag_response) IN {variants}
              AND timestamp >= {window_start}
              AND timestamp <= {window_end}
            GROUP BY session_id, flag_key, variant
            """,
            placeholders={
                "window_index": ast.Constant(value=window_index),
                "session_ids": ast.Constant(value=session_ids),
                "flag_keys": ast.Constant(value=keys_by_window[window]),
                "variants": ast.Constant(value=sorted(variants)),
                "window_start": ast.Constant(value=window.start),
                "window_end": ast.Constant(value=window.end),
            },
        )
        assert isinstance(branch, ast.SelectQuery)
        # The backstop must sit on each branch: HogQL stamps an implicit LIMIT 100 on every
        # union branch whose limit is unset, which would silently and nondeterministically
        # truncate legitimate rows.
        branch.limit = ast.Constant(value=MAX_EXPOSURE_ROWS)
        branches.append(branch)

    query = ast.SelectSetQuery.create_from_queries(branches, "UNION ALL")
    response = execute_hogql_query(
        query, team=team, user=user, context=shared_hogql.fresh_context(team, user), modifiers=shared_hogql.modifiers
    )

    exposures: dict[str, dict[tuple[str, _ScanWindow], list[tuple[str, datetime]]]] = {}
    for window_index, session_id, flag_key, variant, first_seen in response.results or []:
        if not flag_key or not variant:
            continue
        window = ordered_windows[int(window_index)]
        exposures.setdefault(str(session_id), {}).setdefault((str(flag_key), window), []).append(
            (str(variant), first_seen)
        )
    return exposures


def _query_exposure_event_branches(
    team: Team,
    user: User,
    shared_hogql: SharedHogQLDatabase,
    session_ids: list[str],
    clipped_branches: list[tuple[_BranchMeta, _ScanWindow]],
) -> dict[str, dict[int, list[tuple[str, datetime]]]]:
    """The sessions' exposure events for experiments whose criteria don't fit the batched
    default query (a custom event, an action, or the default event narrowed by property
    filters), as session_id -> experiment_id -> [(variant, first_seen)].

    One union branch per experiment: the event/action and property filters come from the
    experiment's exposure criteria via `build_exposure_event_conditions`, and the variant from
    the property `get_exposure_event_and_property` dictates — the stamped `$feature/<key>`
    property for custom events and actions (they carry no `$feature_flag_response`),
    `$feature_flag_response` for the default event. Each branch reads only its clipped window
    (the experiment's run window intersected with the scan window), which the caller computes
    when it allocates branch slots.
    """
    branches: list[ast.SelectQuery] = []
    for meta, branch_window in clipped_branches:
        # Built here, after the branch cap, so classification stays DB-free for experiments
        # the slice discards (action-based conditions cost a Postgres lookup each).
        try:
            # The same deliberate legacy-event choice as `_resolve_exposure` above.
            conditions = build_exposure_event_conditions(
                meta.resolution.criteria, team, meta.resolution.flag_key, default_exposure_event=DEFAULT_EXPOSURE_EVENT
            )
        except (Cohort.DoesNotExist, BaseHogQLError):
            # Criteria this project can't resolve — a cohort filter whose cohort doesn't exist
            # here (e.g. a duplicated experiment carrying the source project's cohort id), or a
            # property filter HogQL can't compile — must not fail the whole surface. Match
            # nothing instead, like `_build_action_filter` does for missing actions: the
            # experiment still surfaces through stamped properties and flag evaluations, and no
            # exposure moment is fabricated from criteria the analysis can't honor either.
            conditions = [ast.Constant(value=False)]
        branch = parse_select(
            """
            SELECT {experiment_id} AS experiment_id,
                   $session_id AS session_id,
                   toString({variant_field}) AS variant,
                   min(timestamp) AS first_seen
            FROM events
            WHERE {exposure_conditions}
              AND $session_id IN {session_ids}
              AND toString({variant_field}) IN {variants}
              AND timestamp >= {window_start}
              AND timestamp <= {window_end}
            GROUP BY session_id, variant
            """,
            placeholders={
                "experiment_id": ast.Constant(value=meta.experiment_id),
                "variant_field": ast.Field(chain=["properties", meta.resolution.variant_property]),
                "exposure_conditions": ast.And(exprs=conditions) if conditions else ast.Constant(value=True),
                "session_ids": ast.Constant(value=session_ids),
                "variants": ast.Constant(value=sorted(meta.variant_keys)),
                "window_start": ast.Constant(value=branch_window.start),
                "window_end": ast.Constant(value=branch_window.end),
            },
        )
        assert isinstance(branch, ast.SelectQuery)
        # The backstop must sit on each branch: HogQL stamps an implicit LIMIT 100 on every
        # union branch whose limit is unset (`_apply_limit` walks the branches), so a set-level
        # limit alone would not prevent per-branch truncation. Real branches stay far below
        # this — each groups by one flag's defined variants.
        branch.limit = ast.Constant(value=MAX_EXPOSURE_ROWS)
        branches.append(branch)

    if not branches:
        return {}

    query = ast.SelectSetQuery.create_from_queries(branches, "UNION ALL")
    # No set-level LIMIT here: the printer emits it directly after the last branch's own
    # LIMIT, which ClickHouse rejects as a syntax error. The per-branch limits above are
    # the backstop; total output is already bounded by each flag's defined variants.
    response = execute_hogql_query(
        query, team=team, user=user, context=shared_hogql.fresh_context(team, user), modifiers=shared_hogql.modifiers
    )

    exposures: dict[str, dict[int, list[tuple[str, datetime]]]] = {}
    for experiment_id, session_id, variant, first_seen in response.results or []:
        if not variant:
            continue
        exposures.setdefault(str(session_id), {}).setdefault(int(experiment_id), []).append((str(variant), first_seen))
    return exposures


def _query_stamped_flag_properties(
    team: Team,
    user: User,
    shared_hogql: SharedHogQLDatabase,
    session_ids: list[str],
    flag_key_windows: dict[str, list[_ScanWindow]],
) -> dict[str, dict[tuple[str, _ScanWindow], list[str]]]:
    """Distinct stamped `$feature/<key>` property values per session, as
    session_id -> (flag_key, scan window) -> values. Sessions with no in-window events yield
    no entry.

    Each (key, window) pair aggregates only the events inside that window. The clip has to
    happen in the aggregate: the values come back without timestamps, so a value stamped
    outside a window could not be dropped afterwards, and experiments sharing one flag with
    different run windows need their values kept apart. The top-level bounds cover the union
    of the windows, so rows no aggregate can accept stay unread."""
    if not flag_key_windows:
        return {}
    key_window_pairs = [
        (flag_key, window) for flag_key in sorted(flag_key_windows) for window in flag_key_windows[flag_key]
    ]
    # Built as ast nodes, not string interpolation — flag keys can contain arbitrary characters.
    select: list[ast.Expr] = [
        ast.Alias(alias="session_id", expr=ast.Field(chain=["$session_id"])),
        *[
            ast.Alias(
                alias=f"v{index}",
                expr=ast.Call(
                    name="groupUniqArrayIf",
                    args=[
                        ast.Call(name="toString", args=[ast.Field(chain=["properties", f"$feature/{flag_key}"])]),
                        parse_expr(
                            "timestamp >= {window_start} AND timestamp <= {window_end}",
                            placeholders={
                                "window_start": ast.Constant(value=window.start),
                                "window_end": ast.Constant(value=window.end),
                            },
                        ),
                    ],
                ),
            )
            for index, (flag_key, window) in enumerate(key_window_pairs)
        ],
    ]
    query = ast.SelectQuery(
        select=select,
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        group_by=[ast.Field(chain=["session_id"])],
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.In,
                    left=ast.Field(chain=["$session_id"]),
                    right=ast.Constant(value=session_ids),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=min(window.start for _flag_key, window in key_window_pairs)),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=ast.Constant(value=max(window.end for _flag_key, window in key_window_pairs)),
                ),
            ]
        ),
    )
    response = execute_hogql_query(
        query, team=team, user=user, context=shared_hogql.fresh_context(team, user), modifiers=shared_hogql.modifiers
    )

    return {
        str(row[0]): {pair: [value for value in row[1 + index] if value] for index, pair in enumerate(key_window_pairs)}
        for row in response.results or []
    }
