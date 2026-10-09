"""Programmatic scan requests: one handle over a batch of on-demand scans.

A request points either a saved scanner or an inline question at named sessions, through the same
`scanning` helpers the scanner endpoints use, so quota, caps and dedup behave exactly as they do there.
Nothing here checks consent or access; the caller does, as with `scanning`.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from django.db import IntegrityError, models, transaction
from django.db.models import Q
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
    # Started, but never settled before the scan workflow's own timeout ran out.
    LOST = "lost", "Lost"


_UNSETTLED_STATES = frozenset({RequestSessionState.PENDING, RequestSessionState.RUNNING})

# Starting up to 200 scans takes seconds, so a request whose outcomes are still unwritten after this
# lost the process that was starting them.
_STARTUP_GRACE = timedelta(minutes=10)


class IdempotencyKeyConflict(Exception):
    """The key already names a request someone else made, so it can't be handed back to this caller."""


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
    the arbiter between two concurrent calls with the same key. A key is only handed back to the same
    caller: another one gets `IdempotencyKeyConflict`, never a request it may not be allowed to read.
    """
    if (scanner is None) == (inline is None):
        raise ValueError("Pass exactly one of scanner or inline.")
    if idempotency_key:
        existing = ReplayObservationRequest.objects.for_team(team.id).filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return _same_caller(existing, team, source, user), False
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
        existing = ReplayObservationRequest.objects.for_team(team.id).get(idempotency_key=idempotency_key)
        return _same_caller(existing, team, source, user), False

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


def _same_caller(
    request: ReplayObservationRequest, team: Team, source: ObservationRequestSource, user: User | None
) -> ReplayObservationRequest:
    if request.source != source or request.created_by_id != (user.id if user is not None else None):
        raise IdempotencyKeyConflict()
    # Requests are stored under the project's canonical team, but scanners and observations stay per environment,
    # so a key from another environment of the same project must not read this environment's results.
    if request.scanner is not None and request.scanner.team_id != team.id:
        raise IdempotencyKeyConflict()
    return request


def request_progress(request: ReplayObservationRequest, *, now: datetime | None = None) -> RequestProgress:
    """Where each of the request's sessions stands, read from the observations it started."""
    return request_progress_many([request], now=now)[request.id]


def request_progress_many(
    requests: Sequence[ReplayObservationRequest], *, now: datetime | None = None
) -> dict[Any, RequestProgress]:
    """`request_progress` for many requests, keyed by request id, with one observation query in total."""
    now = now or timezone.now()
    wanted = Q()
    for request in requests:
        if request.scanner_id is not None and request.start_outcomes:
            wanted |= Q(team_id=request.team_id, scanner_id=request.scanner_id, session_id__in=request.session_ids)
    observations: dict[tuple[Any, str], ReplayObservation] = {}
    if wanted:
        observations = {(o.scanner_id, o.session_id): o for o in ReplayObservation.objects.filter(wanted)}
    return {request.id: _progress(request, observations, now) for request in requests}


def _progress(
    request: ReplayObservationRequest, observations: dict[tuple[Any, str], ReplayObservation], now: datetime
) -> RequestProgress:
    age = now - request.created_at
    if not request.start_outcomes:
        # Still starting, or the process starting it died; either way nothing has run to read back.
        state = RequestSessionState.PENDING if age < _STARTUP_GRACE else RequestSessionState.FAILED
        return RequestProgress(
            sessions=[
                RequestSession(session_id=sid, scan_outcome="failed", state=state, observation=None)
                for sid in request.session_ids
            ]
        )
    # A scan that outlives its workflow's timeout is dead even if its row still says running, and the
    # orphan reaper only catches up later.
    expired = age > APPLY_SCANNER_EXECUTION_TIMEOUT
    return RequestProgress(
        sessions=[
            _session(outcome, observations.get((request.scanner_id, outcome["session_id"])), expired)
            for outcome in request.start_outcomes
        ]
    )


def _session(outcome: dict[str, str], observation: ReplayObservation | None, expired: bool) -> RequestSession:
    scan_outcome = outcome["scan_outcome"]
    if scan_outcome not in _OBSERVED_OUTCOMES:
        state = RequestSessionState.FAILED if scan_outcome == "failed" else RequestSessionState.SKIPPED
    elif observation is not None and observation.status in TERMINAL_STATUSES:
        state = RequestSessionState(observation.status)
    elif expired:
        state = RequestSessionState.LOST
    elif observation is None:
        state = RequestSessionState.PENDING
    else:
        state = RequestSessionState.RUNNING
    return RequestSession(
        session_id=outcome["session_id"], scan_outcome=scan_outcome, state=state, observation=observation
    )
