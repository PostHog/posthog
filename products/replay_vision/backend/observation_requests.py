"""Programmatic scan requests: one handle over a batch of on-demand scans.

A request points either a saved scanner or an inline question at named sessions, through the same
`scanning` helpers the scanner endpoints use, so quota, caps and dedup behave exactly as they do there.
Nothing here checks consent or access; the caller does, as with `scanning`.
"""

import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from django.db import IntegrityError, models, transaction
from django.db.models import F, Q
from django.utils import timezone

import structlog

from posthog.cdp.internal_events import InternalEventEvent, flush_internal_events_producer, produce_internal_event
from posthog.dataclasses import frozen
from posthog.kafka_client.client import ProduceResult
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.slack.formatting import escape_slack_mrkdwn

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.replay_vision.backend.distinct_ids import replay_vision_distinct_id
from products.replay_vision.backend.models.replay_observation import TERMINAL_STATUSES, ReplayObservation
from products.replay_vision.backend.models.replay_observation_request import (
    ObservationRequestSource,
    ReplayObservationRequest,
)
from products.replay_vision.backend.models.replay_scanner import SETTLE_INTERVAL, ReplayScanner, ScannerType
from products.replay_vision.backend.queries.session_last_activity import fetch_session_last_activity
from products.replay_vision.backend.scanner_access import can_read_targeted_experiment
from products.replay_vision.backend.scanning import run_inline_scan, scan_existing_scanner
from products.replay_vision.backend.temporal.constants import APPLY_SCANNER_EXECUTION_TIMEOUT

logger = structlog.get_logger(__name__)

COMPLETED_EVENT = "$replay_vision_request_completed"

_SWEEP_PAGE_SIZE = 500

# The longest a request waits for its sessions to end before scanning what has been recorded so far.
MAX_SESSION_END_WAIT = timedelta(hours=6)

# Each start launches up to 200 workflows, so a tick only starts a bounded number of waiting requests.
MAX_STARTS_PER_TICK = 50

# How many waiting requests one tick checks for ended sessions.
MAX_CHECKS_PER_TICK = 200

# Leaves headroom inside the reconciler activity's own start-to-close timeout.
_SWEEP_BUDGET_SECONDS = 30

_DELIVERY_TIMEOUT_SECONDS = 10

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
    wait_for_session_end: bool = False,
) -> tuple[ReplayObservationRequest, bool]:
    """Start scans for the sessions and record them as one request. Returns (request, created).

    With `wait_for_session_end` nothing starts yet: `start_waiting_requests` starts the scans once every
    session has gone quiet, because a scan of a session still recording sees only part of it and the
    (scanner, session) observation it writes can never be replaced by a later, complete one.

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
                wait_for_session_end=wait_for_session_end,
                inline_config=_inline_config(inline),
            )
    except IntegrityError:
        if not idempotency_key:
            raise
        existing = ReplayObservationRequest.objects.for_team(team.id).get(idempotency_key=idempotency_key)
        return _same_caller(existing, team, source, user), False

    if wait_for_session_end:
        return request, True
    try:
        _start_scans(request, scanner=scanner, inline=inline)
    except Exception:
        # Free the key so the caller's retry starts the scans instead of reading back an empty request.
        request.delete()
        raise
    return request, True


def _inline_config(inline: InlineScanSpec | None) -> dict[str, Any] | None:
    if inline is None:
        return None
    return {
        "scanner_type": ScannerType(inline.scanner_type).value,
        "scanner_config": inline.scanner_config,
        "model": inline.model,
    }


def _start_scans(
    request: ReplayObservationRequest, *, scanner: ReplayScanner | None, inline: InlineScanSpec | None
) -> None:
    team, user = request.team, request.created_by
    if scanner is not None:
        _, results = scan_existing_scanner(scanner=scanner, session_ids=request.session_ids, user=user)
    else:
        assert inline is not None
        scan = run_inline_scan(
            team=team,
            user=user,
            session_ids=request.session_ids,
            scanner_type=inline.scanner_type,
            scanner_config=inline.scanner_config,
            model=inline.model,
        )
        scanner, results = scan.scanner, scan.results
    request.scanner = scanner
    request.start_outcomes = results
    request.started_at = timezone.now()
    request.save(update_fields=["scanner", "start_outcomes", "started_at"])


def start_waiting_requests(*, now: datetime | None = None) -> int:
    """Start the scans of waiting requests whose sessions have all gone quiet, or have waited long enough.

    Each tick checks the waiting requests checked least recently, so one whose sessions never end moves to the
    back instead of holding up everyone behind it until its wait runs out.
    """
    now = now or timezone.now()
    waiting = list(
        ReplayObservationRequest.objects.unscoped()
        .filter(wait_for_session_end=True, started_at__isnull=True, completed_at__isnull=True)
        .select_related("team", "scanner", "created_by")
        .order_by(F("session_end_checked_at").asc(nulls_first=True), "created_at")[:MAX_CHECKS_PER_TICK]
    )
    # nosemgrep: idor-lookup-without-team -- cross-team reconciler sweep; ids come from the rows read just above
    ReplayObservationRequest.objects.unscoped().filter(id__in=[r.id for r in waiting]).update(
        session_end_checked_at=now
    )
    started = 0
    for team_id in {r.team_id for r in waiting}:
        team_requests = [r for r in waiting if r.team_id == team_id]
        session_ids = sorted({sid for r in team_requests for sid in r.session_ids})
        try:
            last_activity = fetch_session_last_activity(team=team_requests[0].team, session_ids=session_ids, now=now)
        except Exception:
            logger.exception("replay_vision.observation_request.last_activity_failed", team_id=team_id)
            continue
        for request in team_requests:
            if started >= MAX_STARTS_PER_TICK:
                return started
            if not _sessions_ended(request, last_activity, now):
                continue
            if not _creator_still_allowed(request):
                _refuse_start(request)
                continue
            try:
                _start_scans(request, scanner=request.scanner, inline=_inline_spec(request))
            except Exception:
                logger.exception("replay_vision.observation_request.deferred_start_failed", request_id=str(request.id))
                continue
            started += 1
    return started


def _creator_still_allowed(request: ReplayObservationRequest) -> bool:
    """Whether the person a waiting request runs as can still start it, hours after asking.

    Only a request made with a project secret API key has no person behind it; the key's scopes were checked
    when it was made. A person-made request whose creator is gone (the account was deleted) is refused.
    """
    if request.source == ObservationRequestSource.PROJECT_SECRET_API_KEY:
        return True
    user = request.created_by
    if user is None or not user.is_active:
        return False
    team = request.team
    if not OrganizationMembership.objects.filter(user=user, organization_id=team.organization_id).exists():
        return False
    access = UserAccessControl(user=user, team=team, organization_id=str(team.organization_id))
    if not access.has_project_access:
        return False
    if not access.check_access_level_for_resource("session_recording", required_level="viewer"):
        return False
    if request.scanner is not None:
        return access.check_access_level_for_object(request.scanner, "editor") is True and can_read_targeted_experiment(
            access, team.id, request.scanner
        )
    return access.check_access_level_for_resource("replay_scanner", required_level="editor")


def _refuse_start(request: ReplayObservationRequest) -> None:
    request.start_outcomes = [{"session_id": sid, "scan_outcome": "failed"} for sid in request.session_ids]
    request.started_at = timezone.now()
    request.save(update_fields=["start_outcomes", "started_at"])
    logger.info("replay_vision.observation_request.creator_lost_access", request_id=str(request.id))


def _sessions_ended(request: ReplayObservationRequest, last_activity: dict[str, datetime], now: datetime) -> bool:
    if now - request.created_at >= MAX_SESSION_END_WAIT:
        return True
    quiet_since = now - SETTLE_INTERVAL
    # A session missing from the recordings may still be ingesting, so it holds the request back too.
    return all(sid in last_activity and last_activity[sid] <= quiet_since for sid in request.session_ids)


def _inline_spec(request: ReplayObservationRequest) -> InlineScanSpec | None:
    config = request.inline_config
    if request.scanner_id is not None or not config:
        return None
    return InlineScanSpec(
        scanner_type=ScannerType(config["scanner_type"]),
        scanner_config=config["scanner_config"],
        model=config["model"],
    )


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
        # Still waiting for its sessions to end, still starting, or the process starting it died.
        grace = MAX_SESSION_END_WAIT + _STARTUP_GRACE if request.wait_for_session_end else _STARTUP_GRACE
        state = RequestSessionState.PENDING if age < grace else RequestSessionState.FAILED
        return RequestProgress(
            sessions=[
                RequestSession(session_id=sid, scan_outcome="failed", state=state, observation=None)
                for sid in request.session_ids
            ]
        )
    # A scan that outlives its workflow's timeout is dead even if its row still says running, and the
    # orphan reaper only catches up later.
    expired = now - (request.started_at or request.created_at) > APPLY_SCANNER_EXECUTION_TIMEOUT
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


def complete_settled_requests(*, now: datetime | None = None) -> int:
    """Mark every open request whose sessions have all settled as completed, announcing each one first.

    The event goes out before the row is stamped, so a crash between the two sends it again on the next
    tick rather than never; a destination can therefore see a request complete twice. Open requests are
    walked oldest first in pages, so a request whose event keeps failing never hides the ones behind it.
    """
    now = now or timezone.now()
    deadline = time.monotonic() + _SWEEP_BUDGET_SECONDS
    open_requests = ReplayObservationRequest.objects.unscoped().filter(completed_at__isnull=True)
    completed = 0
    cursor: tuple[datetime, Any] | None = None
    while time.monotonic() < deadline:
        page_qs = open_requests.order_by("created_at", "id")
        if cursor is not None:
            page_qs = page_qs.filter(Q(created_at__gt=cursor[0]) | Q(created_at=cursor[0], id__gt=cursor[1]))
        page = list(page_qs[:_SWEEP_PAGE_SIZE])
        if not page:
            break
        cursor = (page[-1].created_at, page[-1].id)
        completed += _complete_page(page, now)
    return completed


def _complete_page(page: list[ReplayObservationRequest], now: datetime) -> int:
    progress = request_progress_many(page, now=now)
    sent: list[tuple[ReplayObservationRequest, ProduceResult]] = []
    for request in page:
        if not progress[request.id].settled:
            continue
        try:
            sent.append(
                (
                    request,
                    produce_internal_event(
                        team_id=request.team_id, event=_completed_event(request, progress[request.id], now)
                    ),
                )
            )
        except Exception:
            logger.exception("replay_vision.observation_request.completion_event_failed", request_id=str(request.id))
    if not sent:
        return 0
    flush_internal_events_producer(_DELIVERY_TIMEOUT_SECONDS)
    delivered: list[Any] = []
    for request, result in sent:
        try:
            result.get(timeout=0)
        except Exception:
            logger.warning("replay_vision.observation_request.completion_event_undelivered", request_id=str(request.id))
            continue
        delivered.append(request.id)
    return (
        # nosemgrep: idor-lookup-without-team -- cross-team reconciler sweep; ids come from the page read above
        ReplayObservationRequest.objects.unscoped()
        .filter(id__in=delivered, completed_at__isnull=True)
        .update(completed_at=now)
    )


def _completed_event(request: ReplayObservationRequest, progress: RequestProgress, now: datetime) -> InternalEventEvent:
    # Counts only: anyone who can add a destination receives this, so session ids and answers stay
    # behind the recording access that `GET /vision/requests/{id}/` enforces.
    states = [s.state for s in progress.sessions]
    return InternalEventEvent(
        event=COMPLETED_EVENT,
        distinct_id=replay_vision_distinct_id(request.team_id),
        uuid=str(uuid5(NAMESPACE_URL, f"vision-request-completed:{request.id}")),
        timestamp=now.isoformat(),
        properties={
            "request_id": str(request.id),
            "reference": request.reference,
            # The caller writes `reference`, so Slack gets it escaped and can't be made to ping a channel.
            "label_mrkdwn": escape_slack_mrkdwn(request.reference or str(request.id)),
            "scanner_id": str(request.scanner_id) if request.scanner_id else None,
            "session_count": len(progress.sessions),
            **{
                f"{state.value}_count": states.count(state)
                for state in RequestSessionState
                if state not in _UNSETTLED_STATES
            },
        },
    )
