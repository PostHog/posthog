"""Dispatch a scout run from a workflow's "Create AI task" step with a scout selected.

The third way a scout run starts, after the coordinator's schedule and the manual `run` endpoint.
The step fires this via `products/workflows/backend/api/workflow_tasks.py`, which has already
proved *which* workflow is calling; everything this module does is decide whether that fire is
allowed to spend a run, and dispatch it if so.

Two properties define the semantics, and both are deliberate:

- **A trigger is additive to the schedule, never a substitute for it.** A workflow-triggered run
  never stamps `last_run_at`. For a cron scout, stamping would silently mark the next wall-clock
  slot fulfilled; for an interval scout, frequent fires would starve the scheduled patrol with
  nothing to show for it. Not stamping costs at most one occasionally-redundant scheduled run.
- **A trigger is not a health signal.** Workflow failures don't feed the failure-streak breaker
  (whose threshold is sized on the schedule's cadence), and the workflow only ever sees the 202 —
  so the scout's health stays covered by its schedule, which is why a schedule-less scout is out
  of scope here.

The run itself is a pure kick: no content from the triggering event reaches it, so the prompt is
identical to a scheduled run's.
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
from products.skills.backend.models.skills import LLMSkill

logger = structlog.get_logger(__name__)


class WorkflowScoutRunRejected(Exception):
    """A fire that will not become a run. Carries the shared `ScoutRunRejection` so the HTTP layer
    maps it to a status code without re-deriving why.

    `in_flight_workflow_id` is set on a `run_in_flight` rejection: the id a workflow-triggered run
    of this scout carries (stable per team and skill), so the HTTP layer can recognise its own
    earlier attempt as the run it collided with."""

    def __init__(self, rejection: ScoutRunRejection, *, in_flight_workflow_id: str | None = None) -> None:
        super().__init__(rejection.detail)
        self.rejection = rejection
        self.in_flight_workflow_id = in_flight_workflow_id


@frozen
class WorkflowScoutRunStarted:
    skill_name: str
    workflow_id: str


def _rejected(kind: ScoutRunRejectionKind, reason: str, detail: str) -> WorkflowScoutRunRejected:
    return WorkflowScoutRunRejected(ScoutRunRejection(kind=kind, reason=reason, detail=detail))


def start_workflow_scout_run(*, team_id: int, skill_name: str) -> WorkflowScoutRunStarted:
    """Start one workflow-triggered run of `skill_name`, or raise `WorkflowScoutRunRejected`.

    `team_id` has to be the project's main environment. Scout rows live under it, and unlike the
    manual endpoint there is no human credential here to re-authorize against it, so a child
    environment's workflow is refused rather than resolved upwards.

    Rejection kinds are chosen so the workflow step reads them correctly: `NOT_FOUND` means the
    node names a scout that cannot run (a typo, a deleted skill) and should surface as a step
    failure the author notices, while `CONFLICT` / `THROTTLED` are ordinary backpressure the step
    treats as a graceful skip.
    """
    team = Team.objects.get(pk=team_id)
    if team.parent_team_id:
        raise _rejected(
            ScoutRunRejectionKind.FORBIDDEN,
            "child_environment",
            "Running a scout from a workflow is only available in the project's main environment.",
        )

    config = SignalScoutConfig.objects.for_team(team_id).filter(skill_name=skill_name).first()
    if config is None:
        raise _rejected(
            ScoutRunRejectionKind.NOT_FOUND,
            "scout_not_found",
            f"No scout named '{skill_name}' exists in this project.",
        )

    # A withheld scout is invisible across the whole config API and the runner would refuse it
    # anyway, so it is "not found" here too rather than a skip — the node names something the
    # project cannot run.
    if skill_name in withheld_skills_for_team(team_id):
        raise _rejected(
            ScoutRunRejectionKind.NOT_FOUND,
            "scout_withheld",
            f"No scout named '{skill_name}' exists in this project.",
        )

    # A config can outlive its skill. Dispatching for one would hand back a workflow id whose run
    # dies in `load_skill_for_run` before any run row exists, so the step would look successful
    # while nothing ever happens. Reject up front, mirroring the manual endpoint.
    if not LLMSkill.objects.filter(team_id=team_id, name=skill_name, is_latest=True, deleted=False).exists():
        raise _rejected(
            ScoutRunRejectionKind.NOT_FOUND,
            "skill_missing",
            f"Scout '{skill_name}' no longer has a skill to run.",
        )

    # Deliberately stricter than the manual endpoint, which lets a human run a disabled scout as a
    # test act: pausing a scout has to stop automation against it, or a pause would silently keep
    # spending as long as some workflow still points at it.
    if config.status not in SignalScoutConfig.RUNNABLE_STATUSES:
        raise _rejected(
            ScoutRunRejectionKind.CONFLICT,
            "scout_not_runnable",
            f"Scout '{skill_name}' is {config.status} and does not accept workflow triggers.",
        )

    # Deferred: keeps the Signals Temporal workflow/activity graph off this module's import path,
    # which the workflows API imports just to reach this function.
    from products.signals.backend.temporal.agentic.scout_scheduler import (  # noqa: PLC0415
        start_workflow_signals_scout_run,
        workflow_triggered_run_workflow_id,
    )

    workflow_id = workflow_triggered_run_workflow_id(team_id, skill_name)

    for rejection in (
        check_fleet_gates(team_id),
        check_spend_gates(team),
        # Ordered before the in-flight check so a burst of fires reports the cooldown (the thing the
        # author can actually act on) rather than whichever run happens to still be running.
        check_workflow_cooldown(team_id, skill_name),
        check_run_in_flight(team_id, skill_name),
    ):
        if rejection is not None:
            in_flight = workflow_id if rejection.reason == "run_in_flight" else None
            raise WorkflowScoutRunRejected(rejection, in_flight_workflow_id=in_flight)

    try:
        start_workflow_signals_scout_run(sync_connect(), team_id=team_id, skill_name=skill_name)
    except WorkflowAlreadyStartedError:
        # A run was dispatched between the in-flight check and the start call — the Temporal
        # server's id-conflict policy single-flights it. Same graceful skip.
        raise WorkflowScoutRunRejected(
            ScoutRunRejection(
                kind=ScoutRunRejectionKind.CONFLICT,
                reason="run_in_flight",
                detail="A run for this scout is already in progress.",
            ),
            in_flight_workflow_id=workflow_id,
        )

    logger.info(
        "signals_scout: workflow-triggered run dispatched",
        team_id=team_id,
        skill_name=skill_name,
        workflow_id=workflow_id,
    )
    return WorkflowScoutRunStarted(skill_name=skill_name, workflow_id=workflow_id)
