"""Dispatch a scout run from a workflow's "Run scout" action.

The third way a scout run starts, after the coordinator's schedule and the manual `run` endpoint.
A workflow node fires this via `products/workflows/backend/api/workflow_scout_runs.py`, which has
already proved *which* workflow is calling; everything this module does is decide whether that fire
is allowed to spend a run, and dispatch it if so.

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
    maps it to a status code without re-deriving why."""

    def __init__(self, rejection: ScoutRunRejection) -> None:
        super().__init__(rejection.detail)
        self.rejection = rejection


@frozen
class WorkflowScoutRunStarted:
    skill_name: str
    workflow_id: str


def _rejected(kind: ScoutRunRejectionKind, reason: str, detail: str) -> WorkflowScoutRunRejected:
    return WorkflowScoutRunRejected(ScoutRunRejection(kind=kind, reason=reason, detail=detail))


def start_workflow_scout_run(*, team_id: int, skill_name: str) -> WorkflowScoutRunStarted:
    """Start one workflow-triggered run of `skill_name`, or raise `WorkflowScoutRunRejected`.

    `team_id` may be a child environment; scout rows live under the canonical parent project, so
    everything below resolves against that — matching how the coordinator plans and how the manual
    endpoint canonicalizes.

    Rejection kinds are chosen so the workflow step reads them correctly: `NOT_FOUND` means the
    node names a scout that cannot run (a typo, a deleted skill) and should surface as a step
    failure the author notices, while `CONFLICT` / `THROTTLED` are ordinary backpressure the step
    treats as a graceful skip.
    """
    # Scout rows, the flag's team config, and the spend gates are all keyed to the canonical
    # project, so resolve to it up front and use that team everywhere below — passing a child
    # environment's row to the gates would check the wrong quota and daily-report ledger.
    team = Team.objects.get(pk=team_id)
    if team.parent_team_id:
        team = Team.objects.get(pk=team.parent_team_id)
    canonical_team_id = team.id

    config = SignalScoutConfig.objects.for_team(canonical_team_id).filter(skill_name=skill_name).first()
    if config is None:
        raise _rejected(
            ScoutRunRejectionKind.NOT_FOUND,
            "scout_not_found",
            f"No scout named '{skill_name}' exists in this project.",
        )

    # A withheld scout is invisible across the whole config API and the runner would refuse it
    # anyway, so it is "not found" here too rather than a skip — the node names something the
    # project cannot run.
    if skill_name in withheld_skills_for_team(canonical_team_id):
        raise _rejected(
            ScoutRunRejectionKind.NOT_FOUND,
            "scout_withheld",
            f"No scout named '{skill_name}' exists in this project.",
        )

    # A config can outlive its skill. Dispatching for one would hand back a workflow id whose run
    # dies in `load_skill_for_run` before any run row exists, so the step would look successful
    # while nothing ever happens. Reject up front, mirroring the manual endpoint.
    if not LLMSkill.objects.filter(team_id=canonical_team_id, name=skill_name, is_latest=True, deleted=False).exists():
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

    for rejection in (
        check_fleet_gates(canonical_team_id),
        check_spend_gates(team),
        # Ordered before the in-flight check so a burst of fires reports the cooldown (the thing the
        # author can actually act on) rather than whichever run happens to still be running.
        check_workflow_cooldown(canonical_team_id, skill_name),
        check_run_in_flight(canonical_team_id, skill_name),
    ):
        if rejection is not None:
            raise WorkflowScoutRunRejected(rejection)

    # Deferred: keeps the Signals Temporal workflow/activity graph off this module's import path,
    # which the workflows API imports just to reach this function.
    from products.signals.backend.temporal.agentic.scout_scheduler import (
        start_workflow_signals_scout_run,  # noqa: PLC0415
    )

    try:
        workflow_id = start_workflow_signals_scout_run(sync_connect(), team_id=canonical_team_id, skill_name=skill_name)
    except WorkflowAlreadyStartedError:
        # A run was dispatched between the in-flight check and the start call — the Temporal
        # server's id-conflict policy single-flights it. Same graceful skip.
        raise _rejected(
            ScoutRunRejectionKind.CONFLICT,
            "run_in_flight",
            "A run for this scout is already in progress.",
        )

    logger.info(
        "signals_scout: workflow-triggered run dispatched",
        team_id=canonical_team_id,
        skill_name=skill_name,
        workflow_id=workflow_id,
    )
    return WorkflowScoutRunStarted(skill_name=skill_name, workflow_id=workflow_id)
