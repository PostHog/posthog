"""Programmatic scan requests: one handle over a batch of on-demand scans.

A request points either a saved scanner or an inline question at named sessions, through the same
`scanning` helpers the scanner endpoints use, so quota, caps and dedup behave exactly as they do there.
Nothing here checks consent or access; the caller does, as with `scanning`.
"""

from datetime import datetime
from typing import Any

from django.db import IntegrityError, models, transaction
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User

from products.replay_vision.backend.models.replay_observation import TERMINAL_STATUSES, ReplayObservation
from products.replay_vision.backend.models.replay_observation_request import (
    ObservationRequestSource,
    ReplayObservationRequest,
)
from products.replay_vision.backend.models.replay_scanner import ReplayScanner, ScannerType
from products.replay_vision.backend.scanning import run_inline_scan, scan_existing_scanner
from products.replay_vision.backend.temporal.constants import APPLY_SCANNER_EXECUTION_TIMEOUT

# Start outcomes that put a workflow behind the session, so an observation row is expected for it.
_OBSERVED_OUTCOMES = frozenset({"started", "already_running", "already_scanned"})


class RequestSessionState(models.TextChoices):
    # Started, but its observation row isn't written yet.
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"
    INELIGIBLE = "ineligible", "Ineligible"
    # Never started because a limit was reached; see the session's `scan_outcome` for which one.
    SKIPPED = "skipped", "Skipped"
    # Started, but no observation appeared before the workflow's own timeout ran out.
    LOST = "lost", "Lost"


_UNSETTLED_STATES = frozenset({RequestSessionState.PENDING, RequestSessionState.RUNNING})


@frozen
class InlineScanSpec:
    scanner_type: ScannerType
    scanner_config: dict[str, Any]
    model: str


@frozen
class RequestSession:
    session_id: str
    scan_outcome: str
    state: RequestSessionState
    observation: ReplayObservation | None


@frozen
class RequestProgress:
    sessions: list[RequestSession]

    @property
    def settled(self) -> bool:
        return all(s.state not in _UNSETTLED_STATES for s in self.sessions)


def create_observation_request(
    *,
    team: Team,
    user: User | None,
    source: ObservationRequestSource,
    session_ids: list[str],
    scanner: ReplayScanner | None,
    inline: InlineScanSpec | None,
    idempotency_key: str | None,
    reference: str,
) -> tuple[ReplayObservationRequest, bool]:
    """Start scans for the sessions and record them as one request. Returns (request, created).

    A repeated idempotency key returns the first request untouched, so a caller that retries after a
    timeout never pays twice. The row is inserted before any scan starts, which makes the unique index
    the arbiter between two concurrent calls with the same key.
    """
    if (scanner is None) == (inline is None):
        raise ValueError("Pass exactly one of scanner or inline.")
    if idempotency_key:
        existing = ReplayObservationRequest.objects.for_team(team.id).filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing, False
    try:
        with transaction.atomic():
            request = ReplayObservationRequest.objects.for_team(team.id).create(
                team=team,
                scanner=scanner,
                session_ids=session_ids,
                start_outcomes=[],
                idempotency_key=idempotency_key or None,
                reference=reference,
                source=source,
                created_by=user,
            )
    except IntegrityError:
        if not idempotency_key:
            raise
        return ReplayObservationRequest.objects.for_team(team.id).get(idempotency_key=idempotency_key), False

    try:
        if scanner is not None:
            _, results = scan_existing_scanner(scanner=scanner, session_ids=session_ids, user=user)
        else:
            assert inline is not None
            scan = run_inline_scan(
                team=team,
                user=user,
                session_ids=session_ids,
                scanner_type=inline.scanner_type,
                scanner_config=inline.scanner_config,
                model=inline.model,
            )
            scanner, results = scan.scanner, scan.results
    except Exception:
        # Free the key so the caller's retry starts the scans instead of reading back an empty request.
        request.delete()
        raise

    request.scanner = scanner
    request.start_outcomes = results
    if not any(r["scan_outcome"] in _OBSERVED_OUTCOMES for r in results):
        request.completed_at = timezone.now()
    request.save(update_fields=["scanner", "start_outcomes", "completed_at"])
    return request, True


def request_progress(request: ReplayObservationRequest, *, now: datetime | None = None) -> RequestProgress:
    """Where each of the request's sessions stands, read from the observations it started."""
    observations: dict[str, ReplayObservation] = {}
    if request.scanner_id is not None:
        observations = {
            o.session_id: o
            for o in ReplayObservation.objects.filter(
                team_id=request.team_id, scanner_id=request.scanner_id, session_id__in=request.session_ids
            )
        }
    # A workflow that dies before it writes its row leaves nothing to read, so past the workflow's own
    # timeout the session can't still be on its way.
    expired = (now or timezone.now()) - request.created_at > APPLY_SCANNER_EXECUTION_TIMEOUT
    sessions = [
        _session(outcome, observations.get(outcome["session_id"]), expired) for outcome in request.start_outcomes
    ]
    return RequestProgress(sessions=sessions)


def _session(outcome: dict[str, str], observation: ReplayObservation | None, expired: bool) -> RequestSession:
    scan_outcome = outcome["scan_outcome"]
    if scan_outcome not in _OBSERVED_OUTCOMES:
        state = RequestSessionState.FAILED if scan_outcome == "failed" else RequestSessionState.SKIPPED
    elif observation is None:
        state = RequestSessionState.LOST if expired else RequestSessionState.PENDING
    elif observation.status in TERMINAL_STATUSES:
        state = RequestSessionState(observation.status)
    else:
        state = RequestSessionState.RUNNING
    return RequestSession(
        session_id=outcome["session_id"], scan_outcome=scan_outcome, state=state, observation=observation
    )
