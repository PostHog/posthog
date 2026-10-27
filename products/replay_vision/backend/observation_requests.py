"""Programmatic scan requests: one handle over a batch of on-demand scans.

A request points either a saved scanner or an inline question at named sessions, through the same
`scanning` helpers the scanner endpoints use, so quota, caps and dedup behave exactly as they do there.
Nothing here checks consent or access; the caller does, as with `scanning`.
"""

import time
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from django.core.cache import cache
from django.db import IntegrityError, OperationalError, connection, models, transaction
from django.db.models import F, Q
from django.utils import timezone

import structlog

from posthog.api.statement_timeout import is_query_canceled
from posthog.dataclasses import frozen
from posthog.kafka_client.client import ProduceResult
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.models.user import User
from posthog.slack.formatting import escape_slack_mrkdwn

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.cdp.backend.internal_events import (
    InternalEventEvent,
    flush_internal_events_producer,
    produce_internal_event,
)
from products.cdp.backend.workflow_step_resume import RESULT_BYTE_CAP, cap_value, emit_workflow_step_resume
from products.replay_vision.backend.distinct_ids import replay_vision_distinct_id
from products.replay_vision.backend.error_kinds import FailureKind, IneligibleSessionKind
from products.replay_vision.backend.models.replay_observation import TERMINAL_STATUSES, ReplayObservation
from products.replay_vision.backend.models.replay_observation_request import (
    ObservationRequestSource,
    ReplayObservationRequest,
)
from products.replay_vision.backend.models.replay_scanner import SETTLE_INTERVAL, ReplayScanner, ScannerType
from products.replay_vision.backend.queries.session_last_activity import fetch_session_last_activity
from products.replay_vision.backend.scanner_access import can_read_observation, can_read_targeted_experiment
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

# Each sweep gets its own budget, and together they leave headroom inside the completion activity's query
# budget (75% of its timeout), so a slow start sweep can't starve the completion sweep or the reverse.
START_SWEEP_BUDGET_SECONDS = 15
COMPLETION_SWEEP_BUDGET_SECONDS = 20

# Matches the `max_wait` the workflow step parks with (posthog-replay-vision.template.ts): the
# longest wait for the sessions to end plus the scan itself.
WORKFLOW_STEP_MAX_WAIT = timedelta(hours=8)

_DELIVERY_TIMEOUT_SECONDS = 10
# The completion sweep stops this long before the query budget ends, so its last page can flush and stamp.
_STAMP_HEADROOM_SECONDS = _DELIVERY_TIMEOUT_SECONDS + 5
_SWEEP_CURSOR_KEY = "replay_vision:completion_sweep_cursor"
_WRITER = "default"
_SWEEP_CURSOR_TTL_SECONDS = 60 * 60

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
class WorkflowScanCaps:
    """The most scan requests one workflow, and all of a project's workflows, may make in 24 hours."""

    per_workflow: int
    per_team: int


class WorkflowScanCapReached(Exception):
    def __init__(self, scope: Literal["workflow", "team"], cap: int) -> None:
        super().__init__(f"The {scope} reached its daily cap of {cap} scans")
        self.scope = scope
        self.cap = cap


@frozen
class InlineScanSpec:
    scanner_type: ScannerType
    scanner_config: dict[str, Any]
    model: str


@frozen
class RequestSession:
    session_id: str
    # None until the session's scan has started.
    scan_outcome: str | None
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
    workflow_caps: WorkflowScanCaps | None = None,
) -> tuple[ReplayObservationRequest, bool]:
    """Start scans for the sessions and record them as one request. Returns (request, created).

    With `wait_for_session_end` nothing starts yet: `start_waiting_requests` starts the scans once every
    session has gone quiet, because a scan of a session still recording sees only part of it and the
    (scanner, session) observation it writes can never be replaced by a later, complete one.

    A repeated idempotency key returns the first request untouched, so a caller that retries after a
    timeout never pays twice. The row is inserted before any scan starts, which makes the unique index
    the arbiter between two concurrent calls with the same key. A key is only handed back to the same
    caller: another one gets `IdempotencyKeyConflict`, never a request it may not be allowed to read.

    With `workflow_caps`, `reference` names the workflow, and a request over either cap raises
    `WorkflowScanCapReached`. A replayed key never counts against a cap.
    """
    if (scanner is None) == (inline is None):
        raise ValueError("Pass exactly one of scanner or inline.")
    if idempotency_key:
        existing = ReplayObservationRequest.objects.for_team(team.id).filter(idempotency_key=idempotency_key).first()
        if existing is not None:
            return _same_caller(existing, team, source, user, reference), False
    try:
        with transaction.atomic():
            if workflow_caps is not None:
                _lock_workflow_scans(team.id)
                # A same-key call that held the lock first has committed its row, which is visible now.
                replayed = (
                    ReplayObservationRequest.objects.for_team(team.id)
                    .using(_WRITER)
                    .filter(idempotency_key=idempotency_key)
                    .first()
                    if idempotency_key
                    else None
                )
                if replayed is not None:
                    return _same_caller(replayed, team, source, user, reference), False
                _check_workflow_caps(team.id, reference, workflow_caps)
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
        return _same_caller(existing, team, source, user, reference), False

    if wait_for_session_end:
        return request, True
    try:
        _start_scans(request, scanner=scanner, inline=inline)
    except Exception:
        # Free the key so the caller's retry starts the scans instead of reading back an empty request.
        request.delete()
        raise
    return request, True


def _lock_workflow_scans(team_id: int) -> None:
    # Serializes the count and the insert, so two concurrent runs can't both take the last scan.
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"replay-vision-workflow-scans:{team_id}"])


def _check_workflow_caps(team_id: int, hog_flow_id: str, caps: WorkflowScanCaps) -> None:
    # Counted on the writer, which the lock and the insert use: a lagging replica could miss the last scan taken.
    recent = (
        ReplayObservationRequest.objects.for_team(team_id)
        .using(_WRITER)
        .filter(source=ObservationRequestSource.WORKFLOW, created_at__gte=timezone.now() - timedelta(days=1))
    )
    if recent.filter(reference=hog_flow_id).count() >= caps.per_workflow:
        raise WorkflowScanCapReached("workflow", caps.per_workflow)
    if recent.count() >= caps.per_team:
        raise WorkflowScanCapReached("team", caps.per_team)


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


def start_waiting_requests(*, now: datetime | None = None, budget_seconds: float = START_SWEEP_BUDGET_SECONDS) -> int:
    """Start the scans of waiting requests whose sessions have all gone quiet, or have waited long enough.

    Each tick checks the waiting requests checked least recently, so one whose sessions never end moves to the
    back instead of holding up everyone behind it until its wait runs out. A request only counts as checked
    once its team's sessions were actually read, so a tick that runs out of time leaves the rest at the front.
    """
    now = now or timezone.now()
    deadline = time.monotonic() + budget_seconds
    waiting = list(
        ReplayObservationRequest.objects.unscoped()
        .filter(wait_for_session_end=True, started_at__isnull=True, completed_at__isnull=True)
        .select_related("team", "scanner", "created_by")
        .order_by(F("session_end_checked_at").asc(nulls_first=True), "created_at")[:MAX_CHECKS_PER_TICK]
    )
    started = 0
    for team_id in dict.fromkeys(r.team_id for r in waiting):
        if time.monotonic() >= deadline or started >= MAX_STARTS_PER_TICK:
            break
        team_requests = [r for r in waiting if r.team_id == team_id]
        session_ids = sorted({sid for r in team_requests for sid in r.session_ids})
        try:
            last_activity = fetch_session_last_activity(team=team_requests[0].team, session_ids=session_ids, now=now)
        except Exception:
            logger.exception("replay_vision.observation_request.last_activity_failed", team_id=team_id)
            continue
        # nosemgrep: idor-lookup-without-team -- cross-team reconciler sweep; ids come from the rows read just above
        ReplayObservationRequest.objects.unscoped().filter(id__in=[r.id for r in team_requests]).update(
            session_end_checked_at=now
        )
        for request in team_requests:
            if started >= MAX_STARTS_PER_TICK or time.monotonic() >= deadline:
                break
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
    if (overrun := time.monotonic() - deadline) > 0:
        logger.warning("replay_vision.observation_request.start_sweep_overran", overrun_seconds=round(overrun, 1))
    return started


def recording_viewer_access(user: User | None, team: Team) -> UserAccessControl | None:
    """The user's access in the project, when they are active, a member and can view its recordings."""
    if user is None or not user.is_active:
        return None
    if not OrganizationMembership.objects.filter(user=user, organization_id=team.organization_id).exists():
        return None
    access = UserAccessControl(user=user, team=team, organization_id=str(team.organization_id))
    if not access.has_project_access:
        return None
    if not access.check_access_level_for_resource("session_recording", required_level="viewer"):
        return None
    return access


def _creator_still_allowed(request: ReplayObservationRequest) -> bool:
    """Whether the person a waiting request runs as can still start it, hours after asking.

    Only a request made with a project secret API key has no person behind it; the key's scopes were checked
    when it was made. A person-made request whose creator is gone (the account was deleted) is refused.
    """
    if request.source == ObservationRequestSource.PROJECT_SECRET_API_KEY:
        return True
    team = request.team
    access = recording_viewer_access(request.created_by, team)
    if access is None:
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
    request: ReplayObservationRequest,
    team: Team,
    source: ObservationRequestSource,
    user: User | None,
    reference: str,
) -> ReplayObservationRequest:
    if request.source != source or request.created_by_id != (user.id if user is not None else None):
        raise IdempotencyKeyConflict()
    # One owner can have many workflows, so a workflow key is only handed back to the workflow that made it.
    if source == ObservationRequestSource.WORKFLOW and request.reference != reference:
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
                RequestSession(session_id=sid, scan_outcome=None, state=state, observation=None)
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


def complete_settled_requests(
    *,
    now: datetime | None = None,
    budget_seconds: float = COMPLETION_SWEEP_BUDGET_SECONDS,
    query_deadline: float | None = None,
) -> int:
    """Mark every open request whose sessions have all settled as completed, announcing each one first.

    The event goes out before the row is stamped, so a crash between the two sends it again on the next
    tick rather than never; a destination can therefore see a request complete twice. Open requests are
    walked oldest first in pages. A tick that runs out of time leaves a cursor, and the next tick starts
    there and wraps around, so requests whose wakes keep failing never hold back the ones behind them.

    `query_deadline` is the wall-clock time at which Postgres starts to cancel statements. The sweep stops early
    enough before it that a canceled stamp can't re-announce a page whose events already went out.
    """
    now = now or timezone.now()
    if query_deadline is not None:
        budget_seconds = min(budget_seconds, query_deadline - time.time() - _STAMP_HEADROOM_SECONDS)
    deadline = time.monotonic() + budget_seconds
    open_requests = (
        ReplayObservationRequest.objects.unscoped()
        .filter(completed_at__isnull=True)
        .select_related("team", "created_by", "scanner")
        .order_by("created_at", "id")
    )
    start = _load_sweep_cursor()
    cursor = start
    wrapped = start is None
    completed = 0
    try:
        while time.monotonic() < deadline:
            page_qs = open_requests
            if cursor is not None:
                page_qs = page_qs.filter(_after(cursor))
            if wrapped and start is not None:
                page_qs = page_qs.exclude(_after(start))
            page = list(page_qs[:_SWEEP_PAGE_SIZE])
            if not page:
                if wrapped:
                    _store_sweep_cursor(None)
                    return completed
                wrapped, cursor = True, None
                continue
            page_completed, stopped_at = _complete_page(page, now, deadline)
            completed += page_completed
            if stopped_at is not None:
                if stopped_at:
                    cursor = (page[stopped_at - 1].created_at, page[stopped_at - 1].id)
                break
            cursor = (page[-1].created_at, page[-1].id)
    except OperationalError as err:
        # The activity's query budget can run out before this sweep's own budget does. The page it cancels
        # starts the next tick, so stop here instead of failing the activity.
        if not is_query_canceled(err):
            raise
        logger.warning("replay_vision.observation_request.completion_sweep_canceled", completed=completed)
    _store_sweep_cursor(cursor)
    return completed


def _after(cursor: tuple[datetime, Any]) -> Q:
    return Q(created_at__gt=cursor[0]) | Q(created_at=cursor[0], id__gt=cursor[1])


def _store_sweep_cursor(cursor: tuple[datetime, Any] | None) -> None:
    # Best effort: without the cache, a tick starts from the oldest open request, as before.
    try:
        if cursor is None:
            cache.delete(_SWEEP_CURSOR_KEY)
        else:
            cache.set(_SWEEP_CURSOR_KEY, (cursor[0].isoformat(), str(cursor[1])), timeout=_SWEEP_CURSOR_TTL_SECONDS)
    except Exception:
        logger.warning("replay_vision.observation_request.sweep_cursor_unavailable", exc_info=True)


def _load_sweep_cursor() -> tuple[datetime, Any] | None:
    try:
        stored = cache.get(_SWEEP_CURSOR_KEY)
    except Exception:
        logger.warning("replay_vision.observation_request.sweep_cursor_unavailable", exc_info=True)
        return None
    if not stored:
        return None
    try:
        return datetime.fromisoformat(stored[0]), UUID(stored[1])
    except (TypeError, ValueError, IndexError):
        return None


def _complete_page(page: list[ReplayObservationRequest], now: datetime, deadline: float) -> tuple[int, int | None]:
    """Complete the page's settled requests. Also returns the index of the first one left for the next tick."""
    progress = request_progress_many(page, now=now)
    sent: list[tuple[ReplayObservationRequest, ProduceResult]] = []
    access_cache: _AccessCache = {}
    stopped_at: int | None = None
    for index, request in enumerate(page):
        # A wake can block on the engine, so the rest of the page waits for the next tick.
        if time.monotonic() >= deadline:
            stopped_at = index
            break
        if not progress[request.id].settled:
            continue
        # The wake goes first, so a wake that fails leaves the request open without announcing it twice.
        if request.source == ObservationRequestSource.WORKFLOW and request.idempotency_key:
            if not _wake_workflow_step(request, progress[request.id], now, access_cache):
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
        return 0, stopped_at
    flush_internal_events_producer(_DELIVERY_TIMEOUT_SECONDS)
    delivered: list[Any] = []
    for request, result in sent:
        try:
            result.get(timeout=0)
        except Exception:
            logger.warning("replay_vision.observation_request.completion_event_undelivered", request_id=str(request.id))
            continue
        delivered.append(request.id)
    stamped = (
        # nosemgrep: idor-lookup-without-team -- cross-team reconciler sweep; ids come from the page read above
        ReplayObservationRequest.objects.unscoped()
        .filter(id__in=delivered, completed_at__isnull=True)
        .update(completed_at=now)
    )
    return stamped, stopped_at


_STEP_ANSWER_BUDGET = RESULT_BYTE_CAP - 512


# A page of completions shares one owner's access across that owner's requests.
_AccessCache = dict[tuple[int | None, int], "UserAccessControl | None"]


def step_result(
    request: ReplayObservationRequest, progress: RequestProgress, access_cache: _AccessCache | None = None
) -> dict[str, Any]:
    """The answer for the step's one session, sized to fit the step result whichever way it returns.

    Unlike the internal event, this stays inside the project's own workflow, so it carries the answer. The
    owner's access is checked again here, because hours can pass between the start and the answer.
    """
    team = request.team
    session = progress.sessions[0] if progress.sessions else None
    cache_key = (request.created_by_id, team.id)
    if access_cache is not None and cache_key in access_cache:
        access = access_cache[cache_key]
    else:
        access = recording_viewer_access(request.created_by, team)
        if access_cache is not None:
            access_cache[cache_key] = access
    if access is None or session is None:
        return _step_answer("failed", None, ["The workflow's owner can no longer view session recordings."])
    scanner = request.scanner
    if scanner is not None:
        can_read_scanner = bool(
            access.check_access_level_for_object(scanner, "viewer")
        ) and can_read_targeted_experiment(access, team.id, scanner)
    else:
        can_read_scanner = access.check_access_level_for_resource("replay_scanner", required_level="viewer")
    if not can_read_scanner:
        return _step_answer("failed", None, ["The workflow's owner can no longer read this scanner's answers."])
    observation = session.observation
    if observation is not None and not can_read_observation(access, team.id, observation):
        return _step_answer("failed", None, ["The workflow's owner can't read this scanner's answers."])
    output = (
        _step_output((observation.scanner_result or {}).get("model_output"))
        if observation is not None and session.state == RequestSessionState.SUCCEEDED
        else None
    )
    return _step_answer(session.state.value, output, _unanswered_reason(session))


_SKIPPED_REASONS: dict[str, str] = {
    "skipped_quota": "Your organization's Replay Vision credits for this period are used up, so the session wasn't scanned.",
    "skipped_scanner_limit": "This scanner reached its own credit limit for this period, so the session wasn't scanned.",
    "skipped_limit": "Too many Replay Vision scans were already running, so the session wasn't scanned.",
}

# Worded as the scanner UI words them.
_INELIGIBLE_REASONS: dict[str, str] = {
    IneligibleSessionKind.NO_RECORDING: "No recording was found for this session.",
    IneligibleSessionKind.NO_SNAPSHOTS: "This recording has no screen data to play back, so there was no video to watch.",
    IneligibleSessionKind.TOO_SHORT: "The session was too short to analyze.",
    IneligibleSessionKind.TOO_INACTIVE: "The session had too little active interaction to analyze.",
    IneligibleSessionKind.TOO_LONG: "The session was too long to analyze.",
    IneligibleSessionKind.TOO_LARGE: "This recording is too large to render as a video, so there was nothing to watch.",
    IneligibleSessionKind.NO_EVENTS: "The session had no events to analyze.",
}

# These kinds store a measured value worth passing on ("Only 3.2s long; min is 5s"); the others store raw error text.
_INELIGIBLE_KINDS_WITH_DETAIL = frozenset(
    {IneligibleSessionKind.TOO_SHORT, IneligibleSessionKind.TOO_INACTIVE, IneligibleSessionKind.TOO_LONG}
)

_FAILURE_REASONS: dict[str, str] = {
    FailureKind.PROVIDER_TRANSIENT: "The AI provider stayed unreachable across every automatic retry.",
    FailureKind.PROVIDER_REJECTED: "The AI provider wouldn't analyze this recording's video.",
    FailureKind.RASTERIZATION_FAILED: "PostHog could not turn this recording into a video.",
    FailureKind.VALIDATION_FAILED: "The AI could not answer in the requested format.",
    FailureKind.INFRA_TRANSIENT: "A PostHog service was slow or unavailable while preparing this recording.",
    FailureKind.INTERNAL_ERROR: "Something inside PostHog stopped this scan.",
    FailureKind.ORPHANED: "The scan was interrupted before it finished.",
    FailureKind.PII_DETECTED: "The AI's answer included personal data the scan didn't ask for, so it wasn't kept.",
}


def _unanswered_reason(session: RequestSession) -> list[str]:
    """Why the step got no answer, so a workflow can tell a used-up limit from a session that can't be scanned."""
    state = session.state
    if state == RequestSessionState.SUCCEEDED:
        return []
    if state == RequestSessionState.SKIPPED:
        return [_SKIPPED_REASONS.get(session.scan_outcome or "", "The session wasn't scanned.")]
    if state == RequestSessionState.LOST:
        return ["The scan ran out of time before it finished."]
    # `error_reason` is `kind:message`.
    kind, _, detail = (session.observation.error_reason if session.observation is not None else "").partition(":")
    if state == RequestSessionState.INELIGIBLE:
        reason = _INELIGIBLE_REASONS.get(kind, "Replay Vision can't scan this session.")
        detail = detail.strip()
        return [f"{reason} {detail}." if detail and kind in _INELIGIBLE_KINDS_WITH_DETAIL else reason]
    if state == RequestSessionState.FAILED:
        # No observation means the scan never started: it failed to launch, or the process starting it died.
        if session.observation is None:
            return ["The scan failed to start."]
        return [_FAILURE_REASONS.get(kind, "The scan failed.")]
    return []


# The answer a workflow step gets, per scanner type. Internal fields (citation segments, idle periods,
# notability) would push a long session's answer over the step result budget and cut the chapters.
# Short fields come first: the size cap fills fields in order, so a long summary can't crowd them out.
_STEP_OUTPUT_FIELDS: dict[str, tuple[str, ...]] = {
    ScannerType.MONITOR: ("confidence", "verdict", "reasoning"),
    ScannerType.CLASSIFIER: ("confidence", "tags", "reasoning"),
    ScannerType.SCORER: ("confidence", "score", "reasoning"),
    ScannerType.SUMMARIZER: ("confidence", "title", "summary", "chapters"),
}


def _step_output(model_output: Any) -> Any:
    scanner_type = model_output.get("scanner_type") if isinstance(model_output, dict) else None
    fields = _STEP_OUTPUT_FIELDS.get(scanner_type) if isinstance(scanner_type, str) else None
    if fields is None:
        return model_output
    return {key: model_output[key] for key in fields if key in model_output}


def _step_answer(state: str, output: Any, warnings: list[str]) -> dict[str, Any]:
    capped = cap_value(output, _STEP_ANSWER_BUDGET) if output is not None else None
    if capped != output:
        cut = [key for key in output if (capped or {}).get(key) != output[key]] if isinstance(output, dict) else []
        warnings = [*warnings, "The answer was cut to fit the step result" + (f": {', '.join(cut)}" if cut else ".")]
    return {"state": state, "output": capped, "warnings": warnings}


def _state_counts(progress: RequestProgress) -> dict[str, int]:
    states = [s.state for s in progress.sessions]
    return {
        "session_count": len(states),
        **{
            f"{state.value}_count": states.count(state)
            for state in RequestSessionState
            if state not in _UNSETTLED_STATES
        },
    }


def _wake_workflow_step(
    request: ReplayObservationRequest, progress: RequestProgress, now: datetime, access_cache: _AccessCache
) -> bool:
    """Wake the workflow step waiting on this request. False leaves the request open for the next tick."""
    try:
        emit_workflow_step_resume(
            team_id=request.team_id,
            origin_key=request.idempotency_key or "",
            status="completed",
            result=step_result(request, progress, access_cache),
            raise_on_error=True,
            # A step the worker still holds gets the wake on the next tick, not after seconds of sleeping here.
            retry_delays=(),
        )
    except Exception:
        logger.exception("replay_vision.observation_request.step_resume_failed", request_id=str(request.id))
        # Past the step's own wait nobody is parked to take the wake, so the request stops retrying.
        return now - request.created_at > WORKFLOW_STEP_MAX_WAIT
    return True


def _completed_event(request: ReplayObservationRequest, progress: RequestProgress, now: datetime) -> InternalEventEvent:
    # Counts only: anyone who can add a destination receives this, so session ids and answers stay
    # behind the recording access that `GET /vision/requests/{id}/` enforces.
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
            **_state_counts(progress),
        },
    )
