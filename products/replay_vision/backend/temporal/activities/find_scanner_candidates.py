import time
import datetime as dt

from django.utils import timezone

from pydantic import ValidationError
from rest_framework.exceptions import (
    PermissionDenied,
    ValidationError as DRFValidationError,
)
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.schema import RecordingsQuery

from posthog.dataclasses import frozen
from posthog.temporal.session_replay.rasterize_recording.activities.stuck_counter import read_stuck_session_ids

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import SETTLE_INTERVAL, ReplayScanner
from products.replay_vision.backend.queries import excluded_sessions
from products.replay_vision.backend.queries.scanner_candidate_query import (
    DEEP_SWEEP_CANDIDATE_QUERY_TYPE,
    DEFAULT_CANDIDATE_LIMIT,
    EXCLUDED_SESSIONS_QUERY_TYPE,
    SWEEP_EVENTS_LOOKBACK,
    CandidateSession,
    ScannerCandidateQuery,
    WindowedCandidateQuery,
)
from products.replay_vision.backend.temporal.constants import (
    DEEP_SWEEP_INTERVAL,
    DEEP_SWEEP_MAX_EXECUTION_SECONDS,
    DEEP_SWEEP_MAX_WINDOW,
    FIND_SCANNER_CANDIDATES_TIMEOUT,
    PRIMING_LOOKBACK,
    PRIMING_MAX_EXECUTION_SECONDS,
    PRIMING_SCAN_SESSIONS,
    SCANNER_SCHEDULE_INTERVAL,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import (
    record_candidate_page_full,
    record_deep_candidates,
    record_deep_sweep_failure,
    record_sweep_outcome,
)
from products.replay_vision.backend.temporal.read_meter_types import (
    deep_spend_bytes_per_day,
    deep_sweep_throttle_factor,
    sweep_spend_bytes_24h,
    sweep_throttle_factor,
)
from products.replay_vision.backend.temporal.sweep_types import (
    CandidateSessionPayload,
    FindScannerCandidatesInputs,
    FindScannerCandidatesOutput,
)


@frozen
class _DeepProgress:
    """How far the deep pass got; the two fields are one keyset, moved together or not at all."""

    swept_through: dt.datetime
    seen_session_id: str = ""


def _seconds_left(started_at: float) -> float:
    """What the activity has left of its own timeout, which both ClickHouse budgets are carved from."""
    return FIND_SCANNER_CANDIDATES_TIMEOUT.total_seconds() - (time.monotonic() - started_at)


@activity.defn
@track_activity()
def find_scanner_candidates_activity(inputs: FindScannerCandidatesInputs) -> FindScannerCandidatesOutput:
    # `enabled=True` short-circuits sweeps the instant a scanner is disabled.
    scanner = (
        ReplayScanner.objects.filter(pk=inputs.scanner_id, team_id=inputs.team_id, enabled=True)
        .select_related("team", "created_by")
        .first()
    )
    if scanner is None:
        return FindScannerCandidatesOutput(candidates=[], saturated=False)

    # Defence in depth against the creator losing recording access after the scanner was saved.
    if scanner.created_by is not None and not UserAccessControl(
        user=scanner.created_by, team=scanner.team
    ).check_access_level_for_resource("session_recording", required_level="viewer"):
        return FindScannerCandidatesOutput(candidates=[], saturated=False)

    try:
        query = scanner.targeted_recordings_query()
    except ValidationError as exc:
        raise ApplicationError(
            f"ReplayScanner {inputs.scanner_id} has malformed query: {exc}", non_retryable=True
        ) from exc

    if _throttled(scanner):
        record_sweep_outcome("throttled")
        # No watermark advance, so the next executed sweep covers the skipped range in one query.
        return FindScannerCandidatesOutput(candidates=[], saturated=False)

    started_at = time.monotonic()
    limit = inputs.candidate_limit if inputs.candidate_limit is not None else DEFAULT_CANDIDATE_LIMIT
    candidate_query = ScannerCandidateQuery(
        team=scanner.team,
        query=query,
        # The exposure filter's access check runs as the creator, matching the defence-in-depth check above.
        user=scanner.created_by,
        last_swept_at=scanner.last_swept_at,
        sampling_rate=scanner.sampling_rate,
        sampling_salt=str(scanner.id),
        sampling_mode=scanner.sampling_mode,
        last_seen_session_id=scanner.last_seen_session_id or None,
        candidate_limit=limit,
        events_lookback=SWEEP_EVENTS_LOOKBACK,
        # Exclusion is applied below against the fetched batch instead.
        skip_negative_blocklists=True,
        scanner_id=str(scanner.id),
    )
    try:
        batch = candidate_query.run_batch(limit)
    except (DRFValidationError, PermissionDenied):
        # The exposure filter (run as the creator) can't resolve the targeted experiment: the creator
        # lost experiment access, or the experiment can't answer for its exposed population — most
        # often a draft that hasn't launched, but also deleted, group-aggregated, or renamed-variant.
        # A draft heals itself at launch and none of the rest are the sweep's to repair, so skip the
        # tick (no watermark advance) instead of failing it on every fire.
        record_sweep_outcome("experiment_linkage_unresolved")
        return FindScannerCandidatesOutput(candidates=[], saturated=False)
    fetched = batch.matched
    if batch.saturated:
        record_candidate_page_full()

    # Deliberately not wrapped: the in-query blocklists are off, so a swallowed failure here would
    # dispatch the batch unfiltered. Returns empty when the scanner excludes nothing.
    excluded = excluded_sessions.excluded_session_ids(
        query_type=EXCLUDED_SESSIONS_QUERY_TYPE,
        team=scanner.team,
        candidate_query=candidate_query,
        candidates=fetched,
        scanner_id=str(scanner.id),
        seconds_remaining=_seconds_left(started_at),
    )
    candidates = [c for c in fetched if c.session_id not in excluded]

    # Deep candidates dispatch alongside fast ones, so the two share one in-flight budget: the deep
    # pass gets whatever headroom the fast pass left. At zero there is nothing left to dispatch, which
    # also covers the case where the fast batch used the budget on its own.
    deep_candidates: list[CandidateSession] = []
    deep_progress: _DeepProgress | None = None
    deep_limit = limit - len(candidates)
    if scanner.deep_swept_through is None:
        # Seed the deep clock at the fast watermark; everything before this deploy was swept
        # full-width. This happens whatever the headroom, because the fast watermark advances on every
        # tick: seeding only once headroom frees up would leave the range in between with no deep pass.
        deep_progress = _DeepProgress(swept_through=scanner.last_swept_at)
    elif deep_limit > 0:
        try:
            deep_candidates, deep_progress = _deep_sweep(
                scanner,
                query,
                candidate_query,
                deep_limit,
                seconds_remaining=_seconds_left(started_at),
            )
        except Exception:
            # Best-effort catch-up must never fail the tick: the fast pass has already found and
            # filtered its candidates, and losing them to a retry costs their reads again.
            activity.logger.exception("replay_vision.deep_sweep_failed", extra={"scanner_id": str(scanner.id)})
            record_deep_sweep_failure()

    # A never-swept scanner gets a one-off priming pass over the recordings that already exist, so
    # its page has observations without waiting for new sessions to land and settle. Strictly behind
    # the fast walk's range (bounded by the pre-advance watermark), so the two can't overlap.
    priming_candidates: list[CandidateSession] = []
    priming_limit = min(PRIMING_SCAN_SESSIONS, limit - len(candidates) - len(deep_candidates))
    if scanner.primed_at is None and priming_limit > 0:
        priming_candidates = _priming_pass(scanner, query, priming_limit)
        # Marked on the first tick that had headroom to try, whatever the outcome: priming is
        # one-shot, and an empty or failed pass just means the regular sweep takes it from here.
        # A tick whose batches spent the whole in-flight budget defers priming to a later tick.
        ReplayScanner.objects.filter(pk=scanner.pk, primed_at__isnull=True).update(primed_at=timezone.now())

    # Sessions that repeatedly exhausted the rasterizer's whole retry envelope (the Class B
    # compositor wedge) get quarantined for the counter's TTL window; each dispatch would otherwise
    # burn up to an hour of shared rasterizer capacity on a render that cannot finish. The watermark
    # still advances past them, so they are skipped, not retried forever.
    stuck = read_stuck_session_ids(
        inputs.team_id, [c.session_id for c in [*candidates, *deep_candidates, *priming_candidates]]
    )
    if stuck:
        activity.logger.warning("replay_vision.stuck_sessions_skipped %d", len(stuck))
        record_sweep_outcome("stuck_sessions_skipped")
        candidates = [c for c in candidates if c.session_id not in stuck]
        deep_candidates = [c for c in deep_candidates if c.session_id not in stuck]
        priming_candidates = [c for c in priming_candidates if c.session_id not in stuck]

    if deep_candidates:
        record_deep_candidates(len(deep_candidates))
    record_sweep_outcome(
        "candidates_found" if candidates or deep_candidates or priming_candidates else "no_candidates",
        candidates=len(candidates) + len(deep_candidates) + len(priming_candidates),
    )
    return FindScannerCandidatesOutput(
        candidates=[CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in candidates],
        saturated=batch.saturated,
        swept_through=candidate_query.settle_cutoff,
        keyset_end=batch.keyset_end,
        keyset_session_id=batch.keyset_session_id,
        deep_candidates=[
            CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in deep_candidates
        ],
        deep_swept_through=deep_progress.swept_through if deep_progress else None,
        deep_keyset_session_id=deep_progress.seen_session_id if deep_progress else "",
        priming_candidates=[
            CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in priming_candidates
        ],
    )


# Ceiling on the ids inlined into the deep query; past it the walk re-fetches observed sessions,
# which the post-query filter below then drops.
_DEEP_SWEEP_MAX_EXCLUSIONS = 20_000


def _throttled(scanner: ReplayScanner) -> bool:
    """True when this tick should be skipped to keep the scanner inside its 24h read budget.

    The factor stretches the effective cadence: factor N means one executed sweep per N schedule
    intervals. Distance is measured watermark-to-settle-horizon, so a saturated keyset walk (watermark
    lagging behind the horizon) is never throttled harder while it drains its backlog.
    """
    now = dt.datetime.now(dt.UTC)
    factor = sweep_throttle_factor(
        sweep_spend_bytes_24h(_buckets_or_pre_split(scanner.fast_read_bytes_by_hour, scanner), now),
        scanner.sweep_throttle_factor_override,
    )
    if factor <= 1:
        return False
    return (now - SETTLE_INTERVAL) - scanner.last_swept_at < SCANNER_SCHEDULE_INTERVAL * factor


def _priming_pass(scanner: ReplayScanner, query: RecordingsQuery, limit: int) -> list[CandidateSession]:
    """A few of the freshest already-settled recordings from before the fast walk's range.

    Ignores the scanner's sampling rate (priming exists to produce examples now) but keeps its
    sampling mode, so a surfacing-scored scanner still primes on the sessions it would surface.
    Never raises: priming is advisory and must not fail the tick that carries the real sweep.
    """
    window_start = timezone.now() - PRIMING_LOOKBACK
    if window_start >= scanner.last_swept_at:
        # The watermark already covers the whole priming window (a scanner that sat throttled or
        # unswept for over a day); there is nothing behind the fast walk to prime from.
        return []
    try:
        return WindowedCandidateQuery(
            team=scanner.team,
            query=query,
            window_start=window_start,
            window_end=scanner.last_swept_at,
            query_type="ReplayVisionPrimingCandidateQuery",
            sampling_rate=1.0,
            sampling_salt=str(scanner.id),
            sampling_mode=scanner.sampling_mode,
            candidate_limit=limit,
            max_execution_time_seconds=PRIMING_MAX_EXECUTION_SECONDS,
            scanner_id=str(scanner.id),
        ).run()
    except Exception:
        activity.logger.exception("replay_vision.priming_pass_failed")
        record_sweep_outcome("priming_failed")
        return []


def _buckets_or_pre_split(buckets: dict[str, int] | None, scanner: ReplayScanner) -> dict[str, int] | None:
    """`is None`, not truthiness: only a column the meter has never written falls back to the
    pre-split total bucket, which keeps throttled scanners throttled across the deploy."""
    return scanner.sweep_read_bytes_by_hour if buckets is None else buckets


# Kept back for the activity's own wrap-up (exclusion filtering, result serialization).
_DEEP_QUERY_RESERVE_SECONDS = 60
# Below this a deep query over a padded events window has no realistic chance of finishing.
_DEEP_QUERY_MIN_SECONDS = 60


def _deep_execution_budget(seconds_remaining: float) -> int:
    """ClickHouse budget for one deep query, or 0 when too little of the activity is left to try.

    Zero rather than a sliver, because a doomed query still costs a cadence stamp.
    """
    affordable = int(seconds_remaining) - _DEEP_QUERY_RESERVE_SECONDS
    if affordable < _DEEP_QUERY_MIN_SECONDS:
        return 0
    return min(DEEP_SWEEP_MAX_EXECUTION_SECONDS, affordable)


def _deep_sweep(
    scanner: ReplayScanner,
    query: RecordingsQuery,
    fast_query: ScannerCandidateQuery,
    limit: int,
    *,
    seconds_remaining: float,
) -> tuple[list[CandidateSession], _DeepProgress | None]:
    """Catch-up pass behind the fast watermark with the full events lookback.

    The fast sweep's narrow events window can miss a session whose only matching event happened hours
    before it ended; this pass re-walks the already-swept range with full-width windows every
    `DEEP_SWEEP_INTERVAL`, excluding sessions the scanner already observed. Bounded above by
    `last_swept_at` so it never overlaps the fast keyset's territory.
    """
    assert scanner.deep_swept_through is not None  # seeded by the caller before the first pass runs
    swept_through = scanner.deep_swept_through
    now = timezone.now()
    if swept_through >= scanner.last_swept_at:
        return [], None
    # Cadence runs off the last attempt, not the progress watermark: the watermark deliberately stays
    # put when a pass is cut short, and gating on it would let every such pass re-run on the next tick.
    last_attempt = scanner.deep_attempted_at or swept_through
    # The factor is >= 1, so the unstretched interval is a sound pre-filter that skips pricing the
    # spend buckets on the ~143 of 144 ticks where the pass is not remotely due.
    if now - last_attempt < DEEP_SWEEP_INTERVAL:
        return [], None
    factor = deep_sweep_throttle_factor(
        deep_spend_bytes_per_day(_buckets_or_pre_split(scanner.deep_read_bytes_by_hour, scanner), now)
    )
    if now - last_attempt < DEEP_SWEEP_INTERVAL * factor:
        return [], None

    # Only the fast pass's events window can cost it candidates, so with nothing matching on events
    # this pass would only re-find what the fast pass already dispatched — advance and skip the query.
    # `updated_at` is compared against the attempt stamp (both wall-clock) and is safe to read as
    # "query may have changed" because watermarks advance through queryset updates, which skip it.
    settled_since_last_edit = scanner.deep_attempted_at is not None and scanner.updated_at <= scanner.deep_attempted_at
    if settled_since_last_edit and not fast_query.matches_on_events():
        return [], _DeepProgress(swept_through=scanner.last_swept_at)
    # An edit invalidates the cursor: it points partway into a window the new filters have never walked.
    cursor_session_id = (scanner.deep_seen_session_id if settled_since_last_edit else None) or None

    window_end = min(scanner.last_swept_at, swept_through + DEEP_SWEEP_MAX_WINDOW)

    budget = _deep_execution_budget(seconds_remaining)
    if budget == 0:
        return [], None

    # Excluded on observation rows rather than the `$recording_observed` event: that event only lands
    # on the success path, so failed and ineligible sessions would keep matching forever, and it is
    # ingested, so it is not ours to trust.
    observed_session_ids = list(
        ReplayObservation.objects.filter(
            team_id=scanner.team_id,
            scanner_id=scanner.id,
            created_at__gte=swept_through,
        ).values_list("session_id", flat=True)[:_DEEP_SWEEP_MAX_EXCLUSIONS]
    )

    deep_query = WindowedCandidateQuery(
        team=scanner.team,
        query=query,
        user=scanner.created_by,
        window_start=swept_through,
        window_end=window_end,
        ascending=True,
        cursor_end_time=swept_through if cursor_session_id else None,
        cursor_session_id=cursor_session_id,
        query_type=DEEP_SWEEP_CANDIDATE_QUERY_TYPE,
        sampling_rate=scanner.sampling_rate,
        sampling_salt=str(scanner.id),
        sampling_mode=scanner.sampling_mode,
        exclude_session_ids=observed_session_ids,
        candidate_limit=limit,
        max_execution_time_seconds=budget,
        scanner_id=str(scanner.id),
    )
    # Stamped before the query, so a pass that times out still counts against the cadence. Queryset
    # update rather than save(): `updated_at` means "the scanner was edited", which the skip above reads.
    ReplayScanner.objects.filter(pk=scanner.id).update(deep_attempted_at=now)
    deep_candidates = deep_query.run()

    if len(deep_candidates) == limit:
        # Filled up, so resume from the last row rather than re-walking. Oldest-first means everything
        # below it is covered, which is what lets the watermark move at all here.
        last = deep_candidates[-1]
        progress = _DeepProgress(swept_through=last.session_end, seen_session_id=last.session_id)
    else:
        progress = _DeepProgress(swept_through=window_end)
    if deep_candidates:
        # The in-query exclusion is a bounded cost optimization; this filter is what guarantees an
        # already-observed session never burns dispatch headroom, however far past the cap the backlog is.
        already_observed = set(
            ReplayObservation.objects.filter(
                team_id=scanner.team_id,
                scanner_id=scanner.id,
                session_id__in=[c.session_id for c in deep_candidates],
            ).values_list("session_id", flat=True)
        )
        deep_candidates = [c for c in deep_candidates if c.session_id not in already_observed]
    return deep_candidates, progress
