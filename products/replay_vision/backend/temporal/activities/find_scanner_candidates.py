import datetime as dt

from django.utils import timezone

from pydantic import ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.schema import RecordingsQuery

from posthog.rbac.user_access_control import UserAccessControl

from products.replay_vision.backend.models.replay_observation import ReplayObservation
from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.queries.scanner_candidate_query import (
    DEFAULT_CANDIDATE_LIMIT,
    SWEEP_EVENTS_LOOKBACK,
    BackfillCandidateQuery,
    CandidateSession,
    ScannerCandidateQuery,
)
from products.replay_vision.backend.temporal.constants import DEEP_SWEEP_INTERVAL, DEEP_SWEEP_MAX_EXECUTION_SECONDS
from products.replay_vision.backend.temporal.decorators import track_activity
from products.replay_vision.backend.temporal.metrics import record_sweep_outcome
from products.replay_vision.backend.temporal.sweep_types import (
    CandidateSessionPayload,
    FindScannerCandidatesInputs,
    FindScannerCandidatesOutput,
)


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
    )
    candidates = candidate_query.run()
    # A full batch means there may be more past the keyset; the next sweep resumes from the last candidate.
    saturated = len(candidates) == limit

    # Deep candidates dispatch alongside fast ones, so the two share one in-flight budget: the deep
    # pass gets whatever headroom the fast pass left. At zero there is nothing left to dispatch, which
    # also covers the case where the fast batch used the budget on its own.
    deep_candidates: list[CandidateSession] = []
    deep_swept_through: dt.datetime | None = None
    deep_limit = limit - len(candidates)
    if scanner.last_deep_swept_at is None:
        # Seed the deep clock at the fast watermark; everything before this deploy was swept
        # full-width. This happens whatever the headroom, because the fast watermark advances on every
        # tick: seeding only once headroom frees up would leave the range in between with no deep pass.
        deep_swept_through = scanner.last_swept_at
    elif deep_limit > 0:
        deep_candidates, deep_swept_through = _deep_sweep(scanner, query, deep_limit)

    record_sweep_outcome(
        "candidates_found" if candidates or deep_candidates else "no_candidates",
        candidates=len(candidates) + len(deep_candidates),
    )
    return FindScannerCandidatesOutput(
        candidates=[CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in candidates],
        saturated=saturated,
        swept_through=candidate_query.settle_cutoff,
        deep_candidates=[
            CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in deep_candidates
        ],
        deep_swept_through=deep_swept_through,
    )


# Past this the exclusion list stops being complete, so holding the watermark could stall the walk.
_DEEP_SWEEP_MAX_EXCLUSIONS = 20_000


def _deep_sweep(
    scanner: ReplayScanner, query: RecordingsQuery, limit: int
) -> tuple[list[CandidateSession], dt.datetime | None]:
    """Catch-up pass behind the fast watermark with the full events lookback.

    The fast sweep's narrow events window can miss a session whose only matching event happened hours
    before it ended; this pass re-walks the already-swept range with full-width windows every
    `DEEP_SWEEP_INTERVAL`, excluding sessions the scanner already observed. Bounded above by
    `last_swept_at` so it never overlaps the fast keyset's territory.
    """
    assert scanner.last_deep_swept_at is not None  # seeded by the caller before the first pass runs
    now = timezone.now()
    if now - scanner.last_deep_swept_at < DEEP_SWEEP_INTERVAL or scanner.last_deep_swept_at >= scanner.last_swept_at:
        return [], None

    # Exclude on observation rows rather than on the `$recording_observed` event. That event only
    # lands on the success path, so failed and ineligible sessions would keep matching and the walk
    # would never move past them. It is also an ingested event, so it is not ours to trust.
    observed_session_ids = list(
        ReplayObservation.objects.filter(
            team_id=scanner.team_id,
            scanner_id=scanner.id,
            created_at__gte=scanner.last_deep_swept_at,
        ).values_list("session_id", flat=True)[:_DEEP_SWEEP_MAX_EXCLUSIONS]
    )

    deep_query = BackfillCandidateQuery(
        team=scanner.team,
        query=query,
        window_start=scanner.last_deep_swept_at,
        window_end=scanner.last_swept_at,
        sampling_rate=scanner.sampling_rate,
        sampling_salt=str(scanner.id),
        sampling_mode=scanner.sampling_mode,
        exclude_session_ids=observed_session_ids,
        candidate_limit=limit,
        max_execution_time_seconds=DEEP_SWEEP_MAX_EXECUTION_SECONDS,
    )
    deep_candidates = deep_query.run()
    if len(deep_candidates) == limit and len(observed_session_ids) < _DEEP_SWEEP_MAX_EXCLUSIONS:
        # Truncated by the dispatch headroom rather than by the window running out, so hold the
        # watermark and cover the rest next time. The walk is newest-first, so advancing here would
        # drop the oldest stragglers, which are exactly the ones this pass exists to catch. Re-running
        # is self-limiting: a truncated batch means the headroom is spent, and the next tick
        # short-circuits on the in-flight cap before it queries anything.
        return deep_candidates, None
    return deep_candidates, scanner.last_swept_at
