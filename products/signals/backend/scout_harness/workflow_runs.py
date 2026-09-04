"""Dispatch a scout run from a workflow's "Run scout" step.

The third way a scout run starts, after the coordinator's schedule and the manual `run` endpoint.
`products/workflows/backend/api/workflow_scout_runs.py` has already proved *which* workflow is
firing; this module decides whether that fire may spend a run, and dispatches it if so.

Two deliberate properties. A trigger is additive to the schedule: it never stamps `last_run_at`, so
fires can't mark a cron slot fulfilled or starve an interval scout's patrol. And it is not a health
signal: its failures don't feed the failure-streak breaker, whose threshold is sized on the
schedule's cadence. The run is a pure kick — no content from the triggering event reaches it, so
the prompt is identical to a scheduled run's.
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

    `team_id` has to be the project's main environment: scout rows live under it, and there is no
    human credential here to re-authorize a child environment against it.

    Rejection kinds are chosen so the step reads them correctly. `NOT_FOUND` means the node names a
    scout that cannot run (a typo, a deleted skill) and surfaces as a step failure the author
    notices; `CONFLICT` / `THROTTLED` are ordinary backpressure the step skips on.
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

    # Deferred: keeps the Signals Temporal workflow/activity graph off this module's import path,
    # which the workflows API imports just to reach this function.
    from products.signals.backend.temporal.agentic.scout_scheduler import (  # noqa: PLC0415
        start_workflow_signals_scout_run,
        workflow_triggered_run_workflow_id,
    )

    for rejection in (
        check_fleet_gates(team_id),
        check_spend_gates(team),
        # Ordered before the in-flight check so a burst of fires reports the cooldown (the thing the
        # author can actually act on) rather than whichever run happens to still be running.
        check_workflow_cooldown(team_id, skill_name),
        check_run_in_flight(team_id, skill_name),
    ):
        if rejection is not None:
            raise WorkflowScoutRunRejected(rejection)

    workflow_id = workflow_triggered_run_workflow_id(team_id, skill_name)
    try:
        start_workflow_signals_scout_run(sync_connect(), team_id=team_id, skill_name=skill_name)
    except WorkflowAlreadyStartedError:
        # A run was dispatched between the in-flight check and the start call. The endpoint's
        # idempotency cache is what replays a retry whose response was lost, so a collision
        # reaching here is a genuine one and skips.
        raise _rejected(ScoutRunRejectionKind.CONFLICT, "run_in_flight", "A run for this scout is already in progress.")

    logger.info(
        "signals_scout: workflow-triggered run dispatched",
        team_id=team_id,
        skill_name=skill_name,
        workflow_id=workflow_id,
    )
    return WorkflowScoutRunStarted(skill_name=skill_name, workflow_id=workflow_id)
