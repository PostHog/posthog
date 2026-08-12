import datetime as dt

from pydantic import ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.schema import RecordingsQuery

from posthog.rbac.user_access_control import UserAccessControl

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.queries.scanner_candidate_query import (
    DEFAULT_CANDIDATE_LIMIT,
    SWEEP_EVENTS_LOOKBACK,
    BackfillCandidateQuery,
    CandidateSession,
    ScannerCandidateQuery,
)
from products.replay_vision.backend.temporal.constants import DEEP_SWEEP_INTERVAL
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

    deep_candidates, deep_swept_through = _deep_sweep(scanner, query, limit)

    record_sweep_outcome(
        "candidates_found" if candidates or deep_candidates else "no_candidates",
        candidates=len(candidates) + len(deep_candidates),
    )
    return FindScannerCandidatesOutput(
        candidates=[CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in candidates],
        # A full batch means there may be more past the keyset; the next sweep resumes from the last candidate.
        saturated=len(candidates) == limit,
        swept_through=candidate_query.settle_cutoff,
        deep_candidates=[
            CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in deep_candidates
        ],
        deep_swept_through=deep_swept_through,
    )


def _deep_sweep(
    scanner: ReplayScanner, query: RecordingsQuery, limit: int
) -> tuple[list[CandidateSession], dt.datetime | None]:
    """Catch-up pass behind the fast watermark with the full events lookback.

    The fast sweep's narrow events window can miss a session whose only matching event happened hours
    before it ended; this pass re-walks the already-swept range with full-width windows every
    `DEEP_SWEEP_INTERVAL`, excluding sessions the scanner already observed. Bounded above by
    `last_swept_at` so it never overlaps the fast keyset's territory.
    """
    if scanner.last_deep_swept_at is None:
        # Start the deep clock at the fast watermark; everything before this deploy was swept full-width.
        return [], scanner.last_swept_at

    now = dt.datetime.now(dt.UTC)
    if now - scanner.last_deep_swept_at < DEEP_SWEEP_INTERVAL or scanner.last_deep_swept_at >= scanner.last_swept_at:
        return [], None

    deep_query = BackfillCandidateQuery(
        team=scanner.team,
        query=query,
        window_start=scanner.last_deep_swept_at,
        window_end=scanner.last_swept_at,
        sampling_rate=scanner.sampling_rate,
        sampling_salt=str(scanner.id),
        sampling_mode=scanner.sampling_mode,
        exclude_observed_by_scanner=str(scanner.id),
        candidate_limit=limit,
    )
    deep_candidates = deep_query.run()
    # A saturated batch may have more stragglers; keep the watermark so the next eligible tick retries
    # (the observed-exclusion shrinks each retry, so this converges).
    if len(deep_candidates) == limit:
        return deep_candidates, None
    return deep_candidates, scanner.last_swept_at
