"""Dispatch a scout run from a workflow's "Run scout" step.

The third way a scout run starts, after the coordinator's schedule and the manual `run` endpoint.
`products/workflows/backend/presentation/views/workflow_scout_runs.py` has already proved *which* workflow is
firing; this module decides whether that fire may spend a run, and dispatches it if so.

Two deliberate properties. A trigger is additive to the schedule: it never stamps `last_run_at`, so
fires can't mark a cron slot fulfilled or starve an interval scout's patrol. And it is not a health
signal: its failures don't feed the failure-streak breaker, whose threshold is sized on the
schedule's cadence. The only content from the triggering event that reaches the run is the step's
optional note, which renders in its own fenced prompt section and makes the subject it names the
run's first job. Without a note, the run gets a short section saying a workflow started it, and
otherwise behaves as a scheduled run unless its skill says what to do on a workflow-triggered run.
Every run's prompt also names its trigger and, here, the workflow that fired.

A fire that arrives while the scout is busy (inside the workflow cooldown, or while any run of the
scout is live) is queued rather than dropped, unless the step asked to skip it. The coordinator
drains a lane's queue on its tick (`drain_pending_workflow_triggers`, and
`pending_trigger_lanes_for_scheduled_runs` for a lane whose scheduled run is due), and the run that
takes the fires renders each of them. See `workflow_trigger_queue.py` for the storage.
"""

from __future__ import annotations

import structlog
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.dataclasses import frozen
from posthog.models import Team
from posthog.temporal.common.client import sync_connect

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.run_gates import (
    ScoutRunRejection,
    ScoutRunRejectionKind,
    check_fleet_gates,
    check_run_in_flight,
    check_spend_gates,
    check_workflow_cooldown,
)
from products.signals.backend.scout_harness.team_limits import withheld_skills_for_team
from products.signals.backend.scout_harness.workflow_trigger_queue import (
    PendingTriggerLane,
    drop_pending_triggers,
    enqueue_workflow_trigger,
    pending_trigger_lanes,
)
from products.skills.backend.models.skills import LLMSkill

logger = structlog.get_logger(__name__)


class WorkflowScoutRunRejected(Exception):
    """A fire that will not become a run. Carries the shared `ScoutRunRejection` so the HTTP layer
    maps it to a status code without re-deriving why."""

    def __init__(self, rejection: ScoutRunRejection) -> None:
        super().__init__(rejection.detail)
        self.rejection = rejection


@frozen
class WorkflowScoutRunStarted:
    skill_name: str
    workflow_id: str


@frozen
class WorkflowScoutRunQueued:
    """A fire that arrived while the scout was busy, held for the coordinator's next tick."""

    skill_name: str
    pending_count: int


@frozen
class DrainSummary:
    lanes: int = 0
    dispatched: int = 0
    deferred: int = 0
    dropped: int = 0


# Bounds one tick's drain, so the coordinator activity stays inside its timeout. The oldest lanes
# drain first, and the rest wait for the next tick.
MAX_DRAIN_DISPATCHES_PER_TICK = 200


def _rejected(kind: ScoutRunRejectionKind, reason: str, detail: str) -> WorkflowScoutRunRejected:
    return WorkflowScoutRunRejected(ScoutRunRejection(kind=kind, reason=reason, detail=detail))


def start_workflow_scout_run(
    *,
    team_id: int,
    skill_name: str,
    workflow_origin_key: str | None = None,
    run_note: str | None = None,
    trigger_workflow_id: str | None = None,
    queue_when_busy: bool = True,
) -> WorkflowScoutRunStarted | WorkflowScoutRunQueued:
    """Start one workflow-triggered run of `skill_name`, queue the fire, or raise `WorkflowScoutRunRejected`.

    `team_id` has to be the project's main environment: scout rows live under it, and there is no
    human credential here to re-authorize a child environment against it.

    `workflow_origin_key` is the calling step's dispatch key; when set, the run wakes that step at the end.

    `run_note` is the note the step rendered from its triggering event. Blank is no note.

    `trigger_workflow_id` is the workflow that fired, rendered in the run's prompt.

    `queue_when_busy` decides what a busy scout does with the fire. On, a fire inside the cooldown
    or during a live run is queued for the coordinator's next tick. Off, it is rejected as before.
    Every other rejection stays a rejection either way, so a queued fire never gets around a pause,
    a fleet gate, or a spend gate.

    Rejection kinds are chosen so the step reads them correctly. `NOT_FOUND` means the node names a
    scout that cannot run (a typo, a deleted skill) and surfaces as a step failure the author
    notices; `CONFLICT` / `THROTTLED` are ordinary backpressure the step skips on.
    """
    # `organization` is select_related for the spend gate's quota-pause capture.
    team = Team.objects.select_related("organization").get(pk=team_id)
    if team.parent_team_id:
        raise _rejected(
            ScoutRunRejectionKind.FORBIDDEN,
            "child_environment",
            "Running a scout from a workflow is only available in the project's main environment.",
        )

    _check_scout_runnable(team_id, skill_name)

    # Deferred: keeps the Signals Temporal workflow/activity graph off this module's import path,
    # which the workflows API imports just to reach this function.
    from products.signals.backend.temporal.agentic.scout_scheduler import (  # noqa: PLC0415
        start_workflow_signals_scout_run,
        workflow_triggered_run_workflow_id,
    )

    for rejection in (check_fleet_gates(team_id), check_spend_gates(team)):
        if rejection is not None:
            raise WorkflowScoutRunRejected(rejection)

    def _busy(rejection: ScoutRunRejection) -> WorkflowScoutRunQueued:
        if not queue_when_busy:
            raise WorkflowScoutRunRejected(rejection)
        queued = enqueue_workflow_trigger(
            team=team, skill_name=skill_name, note=run_note, workflow_id=trigger_workflow_id, reason=rejection.reason
        )
        return WorkflowScoutRunQueued(skill_name=skill_name, pending_count=queued.pending_count)

    # The cooldown is ordered before the in-flight check so a burst of fires reports the cooldown
    # (the thing the author can actually act on) rather than whichever run happens to still be running.
    busy = check_workflow_cooldown(team_id, skill_name) or check_run_in_flight(team_id, skill_name)
    if busy is not None:
        return _busy(busy)

    # Fires queued earlier still wait for the coordinator. This fire joins them, and the run takes
    # them all in arrival order, so an older subject is not left behind a newer one.
    pending_ids = _pending_ids(team_id, skill_name)
    if pending_ids:
        enqueue_workflow_trigger(
            team=team, skill_name=skill_name, note=run_note, workflow_id=trigger_workflow_id, reason="joined_pending"
        )
        pending_ids = _pending_ids(team_id, skill_name)

    workflow_id = workflow_triggered_run_workflow_id(team_id, skill_name)
    try:
        start_workflow_signals_scout_run(
            sync_connect(),
            team_id=team_id,
            skill_name=skill_name,
            workflow_origin_key=workflow_origin_key,
            run_note=None if pending_ids else (run_note or "").strip() or None,
            trigger_workflow_id=trigger_workflow_id,
            pending_trigger_ids=pending_ids,
        )
    except WorkflowAlreadyStartedError:
        # A run was dispatched between the in-flight check and the start call. The endpoint's
        # idempotency cache is what replays a retry whose response was lost, so a collision
        # reaching here is a genuine one. A fire that joined the queue above already waits there.
        if pending_ids:
            return WorkflowScoutRunQueued(skill_name=skill_name, pending_count=len(pending_ids))
        return _busy(
            ScoutRunRejection(
                kind=ScoutRunRejectionKind.CONFLICT,
                reason="run_in_flight",
                detail="A run for this scout is already in progress.",
            )
        )

    logger.info(
        "signals_scout: workflow-triggered run dispatched",
        team_id=team_id,
        skill_name=skill_name,
        workflow_id=workflow_id,
        has_run_note=bool((run_note or "").strip()),
    )
    return WorkflowScoutRunStarted(skill_name=skill_name, workflow_id=workflow_id)


def _pending_ids(team_id: int, skill_name: str) -> tuple[str, ...]:
    lane = next(iter(pending_trigger_lanes({(team_id, skill_name)})), None)
    return lane.trigger_ids if lane is not None else ()


def _check_scout_runnable(team_id: int, skill_name: str) -> SignalScoutConfig:
    """Raise `WorkflowScoutRunRejected` unless `skill_name` names a scout that accepts workflow triggers."""
    config = SignalScoutConfig.objects.for_team(team_id).filter(skill_name=skill_name).first()
    if config is None:
        raise _rejected(
            ScoutRunRejectionKind.NOT_FOUND,
            "scout_not_found",
            f"No scout named '{skill_name}' exists in this project.",
        )

    # A withheld scout is invisible across the whole config API, so the node names something this
    # project cannot run — "not found" rather than a skip.
    if skill_name in withheld_skills_for_team(team_id):
        raise _rejected(
            ScoutRunRejectionKind.NOT_FOUND,
            "scout_withheld",
            f"No scout named '{skill_name}' exists in this project.",
        )

    # A config can outlive its skill. Dispatching for one hands back a workflow id whose run dies
    # in `load_skill_for_run` before any run row exists, so the step would look successful while
    # nothing ever happens.
    if not LLMSkill.objects.filter(team_id=team_id, name=skill_name, is_latest=True, deleted=False).exists():
        raise _rejected(
            ScoutRunRejectionKind.NOT_FOUND,
            "skill_missing",
            f"Scout '{skill_name}' no longer has a skill to run.",
        )

    # Stricter than the manual endpoint, which lets a human run a disabled scout as a test act:
    # pausing has to stop automation, or a pause keeps spending while a workflow points at it.
    if config.status not in SignalScoutConfig.RUNNABLE_STATUSES:
        raise _rejected(
            ScoutRunRejectionKind.CONFLICT,
            "scout_not_runnable",
            f"Scout '{skill_name}' is {config.status} and does not accept workflow triggers.",
        )
    return config


def pending_trigger_lanes_for_scheduled_runs(
    lanes: set[tuple[int, str]],
) -> dict[tuple[int, str], PendingTriggerLane]:
    """The pending fires the coordinator may hand to the scheduled runs it is about to dispatch.

    A lane is left out while its spend gates refuse or one of its runs is live. Its scheduled run
    would skip or collide, and the fires would wait anyway, so they stay for a later run.
    """
    pending = {(lane.team_id, lane.skill_name): lane for lane in pending_trigger_lanes(lanes)}
    if not pending:
        return {}
    teams = Team.objects.select_related("organization").in_bulk({team_id for team_id, _ in pending})
    eligible: dict[tuple[int, str], PendingTriggerLane] = {}
    for (team_id, skill_name), lane in pending.items():
        team = teams.get(team_id)
        if team is None:
            continue
        if check_spend_gates(team, capture_analytics=False) is not None:
            continue
        if check_run_in_flight(team_id, skill_name) is not None:
            continue
        eligible[(team_id, skill_name)] = lane
    return eligible


def drain_pending_workflow_triggers(excluded_lanes: set[tuple[int, str]]) -> DrainSummary:
    """Dispatch one workflow-triggered run per lane whose queued fires can run now.

    `excluded_lanes` are the lanes the coordinator dispatches on schedule this tick. Their fires
    ride on that run, or wait for the next tick when it could not take them.

    Each lane passes the same checks a live fire does: the scout must still exist and accept
    workflow triggers, the fleet and spend gates must allow a run, the cooldown must have passed,
    and no run may be live. A lane that fails a check keeps its fires, except a scout that no longer
    exists, whose fires can never run and are dropped.
    """
    from products.signals.backend.temporal.agentic.scout_scheduler import (  # noqa: PLC0415 — see start_workflow_scout_run
        start_workflow_signals_scout_run,
    )

    lanes = [lane for lane in pending_trigger_lanes() if (lane.team_id, lane.skill_name) not in excluded_lanes][
        :MAX_DRAIN_DISPATCHES_PER_TICK
    ]
    dispatched = deferred = dropped = 0
    client = None
    for lane in lanes:
        try:
            reason = _drain_blocker(lane)
            if reason is None:
                client = client or sync_connect()
                start_workflow_signals_scout_run(
                    client,
                    team_id=lane.team_id,
                    skill_name=lane.skill_name,
                    pending_trigger_ids=lane.trigger_ids,
                )
        except _LaneGone as gone:
            dropped += drop_pending_triggers(lane.team_id, lane.skill_name, reason=gone.reason)
            continue
        except WorkflowAlreadyStartedError:
            reason = "run_in_flight"
        except Exception:
            logger.exception(
                "signals_scout: failed to drain pending workflow triggers",
                team_id=lane.team_id,
                skill_name=lane.skill_name,
            )
            reason = "dispatch_failed"
        if reason is None:
            dispatched += 1
            logger.info(
                "signals_scout: dispatched a run for pending workflow triggers",
                team_id=lane.team_id,
                skill_name=lane.skill_name,
                pending_count=len(lane.trigger_ids),
            )
        else:
            deferred += 1
            logger.info(
                "signals_scout: pending workflow triggers wait for a later tick",
                team_id=lane.team_id,
                skill_name=lane.skill_name,
                reason=reason,
            )
    return DrainSummary(lanes=len(lanes), dispatched=dispatched, deferred=deferred, dropped=dropped)


class _LaneGone(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _drain_blocker(lane: PendingTriggerLane) -> str | None:
    """Why the lane's fires cannot run now, or None when they can. Raises `_LaneGone` for a scout
    whose fires can never run."""
    team = Team.objects.select_related("organization").filter(pk=lane.team_id).first()
    if team is None:
        raise _LaneGone("team_deleted")
    try:
        _check_scout_runnable(lane.team_id, lane.skill_name)
    except WorkflowScoutRunRejected as error:
        if error.rejection.kind == ScoutRunRejectionKind.NOT_FOUND:
            raise _LaneGone(error.rejection.reason)
        return error.rejection.reason
    for rejection in (
        check_fleet_gates(lane.team_id),
        check_spend_gates(team, capture_analytics=False),
        check_workflow_cooldown(lane.team_id, lane.skill_name),
        check_run_in_flight(lane.team_id, lane.skill_name),
    ):
        if rejection is not None:
            return rejection.reason
    return None
