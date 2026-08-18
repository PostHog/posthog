import time
import datetime as dt

from django.utils import timezone

from pydantic import ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.schema import RecordingsQuery

from posthog.rbac.user_access_control import UserAccessControl

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import SETTLE_INTERVAL, DeepSweepState, ReplayScanner
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
    SCANNER_SCHEDULE_INTERVAL,
)
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_sweep_outcome
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
        query = scanner.recordings_query()
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
    fetched = candidate_query.run()
    # A full batch means there may be more past the keyset; the next sweep resumes from the last row.
    # Measured before exclusion, since the keyset walks what was fetched, not what survived.
    saturated = len(fetched) == limit

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
    deep_progress: DeepSweepState | None = None
    deep_limit = limit - len(candidates)
    if scanner.deep_sweep_state is None:
        # Seed the deep clock at the fast watermark; everything before this deploy was swept
        # full-width. This happens whatever the headroom, because the fast watermark advances on every
        # tick: seeding only once headroom frees up would leave the range in between with no deep pass.
        deep_progress = DeepSweepState(swept_through=scanner.last_swept_at, seen_session_id="")
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
            activity.logger.warning("replay_vision.deep_sweep_failed", extra={"scanner_id": str(scanner.id)})
            record_sweep_outcome("deep_sweep_failed")

    record_sweep_outcome(
        "candidates_found" if candidates or deep_candidates else "no_candidates",
        candidates=len(candidates) + len(deep_candidates),
    )
    return FindScannerCandidatesOutput(
        candidates=[CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in candidates],
        saturated=saturated,
        swept_through=candidate_query.settle_cutoff,
        keyset_end=fetched[-1].session_end if fetched else None,
        keyset_session_id=fetched[-1].session_id if fetched else "",
        deep_candidates=[
            CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in deep_candidates
        ],
        deep_swept_through=deep_progress.swept_through if deep_progress else None,
        deep_keyset_session_id=deep_progress.seen_session_id if deep_progress else "",
    )


# Ceiling on the ids inlined into the deep query. Past it the exclusion is incomplete and a few
# already-observed sessions get re-dispatched, which the unique constraint then drops.
_DEEP_SWEEP_MAX_EXCLUSIONS = 20_000


def _throttled(scanner: ReplayScanner) -> bool:
    """True when this tick should be skipped to keep the scanner inside its 24h read budget.

    The factor stretches the effective cadence: factor N means one executed sweep per N schedule
    intervals. Distance is measured watermark-to-settle-horizon, so a saturated keyset walk (watermark
    lagging behind the horizon) is never throttled harder while it drains its backlog.

    Metered on this pass's own queries, so backfill and catch-up reads cannot stretch it.
    """
    now = dt.datetime.now(dt.UTC)
    factor = sweep_throttle_factor(
        # `is None`, not truthiness: an empty dict means every bucket aged out, which is real
        # information. Only a column the meter has never written falls back to the pre-split total,
        # which is what keeps throttled scanners throttled across the deploy.
        sweep_spend_bytes_24h(
            scanner.sweep_read_bytes_by_hour
            if scanner.fast_read_bytes_by_hour is None
            else scanner.fast_read_bytes_by_hour,
            now,
        ),
        scanner.sweep_throttle_factor_override,
    )
    if factor <= 1:
        return False
    return (now - SETTLE_INTERVAL) - scanner.last_swept_at < SCANNER_SCHEDULE_INTERVAL * factor


def _deep_execution_budget(factor: int, seconds_remaining: float) -> int:
    """ClickHouse budget for one deep query, or 0 when too little of the activity is left to try.

    A stretched pass scans proportionally more, so a fixed budget would time it out at exactly the
    scanners the stretch exists for. Bounded by what the activity has left, and zero rather than a
    sliver: a doomed query still costs a cadence stamp, and at a stretched factor that is a week.
    """
    affordable = int(seconds_remaining) - DEEP_SWEEP_MAX_EXECUTION_SECONDS
    if affordable < DEEP_SWEEP_MAX_EXECUTION_SECONDS:
        return 0
    return min(DEEP_SWEEP_MAX_EXECUTION_SECONDS * factor, affordable)


def _deep_sweep(
    scanner: ReplayScanner,
    query: RecordingsQuery,
    fast_query: ScannerCandidateQuery,
    limit: int,
    *,
    seconds_remaining: float,
) -> tuple[list[CandidateSession], DeepSweepState | None]:
    """Catch-up pass behind the fast watermark with the full events lookback.

    The fast sweep's narrow events window can miss a session whose only matching event happened hours
    before it ended; this pass re-walks the already-swept range with full-width windows every
    `DEEP_SWEEP_INTERVAL`, excluding sessions the scanner already observed. Bounded above by
    `last_swept_at` so it never overlaps the fast keyset's territory.
    """
    deep = scanner.deep_sweep
    if deep.swept_through is None:
        # Stored but unreadable. Skipping loses one cycle; seeding would jump the watermark to the
        # fast one and abandon everything behind it.
        activity.logger.warning("replay_vision.deep_sweep_state_unreadable", extra={"scanner_id": str(scanner.id)})
        record_sweep_outcome("deep_sweep_state_unreadable")
        return [], None
    swept_through = deep.swept_through
    now = timezone.now()
    if swept_through >= scanner.last_swept_at:
        return [], None
    # Stretching widens the next window, so the saving is sublinear: the fixed events padding gets
    # amortized over more window rather than paid per pass.
    factor = deep_sweep_throttle_factor(deep_spend_bytes_per_day(scanner.deep_read_bytes_by_hour, now))
    interval = DEEP_SWEEP_INTERVAL * factor
    # Cadence runs off the last attempt, not the progress watermark. The watermark deliberately stays
    # put when a pass is cut short, and gating on it would make every such pass clear the gate again
    # on the next tick with headroom, which is the throttle this whole pass is supposed to obey.
    last_attempt = deep.attempted_at or swept_through
    if now - last_attempt < interval:
        return [], None

    # Only the fast pass's events window can cost it candidates, so with nothing matching on events
    # this pass would re-find what the fast pass already dispatched. Advancing rather than parking the
    # watermark keeps the window this pass would open bounded if the query later gains an event filter.
    # The range behind the watermark has to have been swept under the current query though: an edit
    # that drops the last event filter leaves stragglers back there that only this pass ever revisits.
    # `updated_at` is safe to read as "query may have changed" because watermarks advance through
    # queryset updates, which do not touch it.
    # Both wall-clock: when the scanner was last edited against when this pass last ran. Comparing an
    # edit time against `swept_through` instead compares it to a position in swept time, which for a
    # lagging scanner is always in the past, so the cursor would be dropped on every pass.
    settled_since_last_edit = deep.attempted_at is not None and scanner.updated_at <= deep.attempted_at
    resume_from_cursor = settled_since_last_edit and bool(deep.seen_session_id)
    if settled_since_last_edit and not fast_query.matches_on_events():
        return [], DeepSweepState(swept_through=scanner.last_swept_at, seen_session_id="")

    window_end = min(scanner.last_swept_at, swept_through + DEEP_SWEEP_MAX_WINDOW)

    budget = _deep_execution_budget(factor, seconds_remaining)
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
        window_start=swept_through,
        window_end=window_end,
        ascending=True,
        # Dropped when the scanner was edited since the last pass: a cursor from the old filters
        # points partway into a window the new ones have never walked.
        cursor_end_time=swept_through if resume_from_cursor else None,
        cursor_session_id=deep.seen_session_id if resume_from_cursor else None,
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
    ReplayScanner.objects.filter(pk=scanner.id).update(
        deep_sweep_state=DeepSweepState.patch(attempted_at=now.isoformat())
    )
    deep_candidates = deep_query.run()

    if len(deep_candidates) == limit:
        # Filled up, so resume from the last row rather than re-walking. Oldest-first means everything
        # below it is covered, which is what lets the watermark move at all here.
        last = deep_candidates[-1]
        return deep_candidates, DeepSweepState(swept_through=last.session_end, seen_session_id=last.session_id)
    return deep_candidates, DeepSweepState(swept_through=window_end, seen_session_id="")
