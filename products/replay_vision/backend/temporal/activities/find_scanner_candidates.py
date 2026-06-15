from pydantic import ValidationError
from temporalio import activity
from temporalio.exceptions import ApplicationError

from posthog.rbac.user_access_control import UserAccessControl

from products.replay_vision.backend.models.replay_scanner import ReplayScanner
from products.replay_vision.backend.queries.scanner_candidate_query import (
    DEFAULT_CANDIDATE_LIMIT,
    ScannerCandidateQuery,
)
from products.replay_vision.backend.temporal.decorators import track_activity
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
        last_seen_session_id=scanner.last_seen_session_id or None,
        candidate_limit=limit,
    )
    candidates = candidate_query.run()

    return FindScannerCandidatesOutput(
        candidates=[CandidateSessionPayload(session_id=c.session_id, session_end=c.session_end) for c in candidates],
        # A full batch means there may be more past the keyset; the next sweep resumes from the last candidate.
        saturated=len(candidates) == limit,
    )
