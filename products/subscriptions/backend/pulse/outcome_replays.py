"""Task-bound access to one claimed outcome measurement replay."""

from uuid import UUID

from posthog.temporal.oauth import PULSE_ANALYSIS_SCOPES

from products.subscriptions.backend.models import OutcomePlan, PulseRun
from products.tasks.backend.facade import api as tasks_api

from .contracts import OutcomeReplayInstructionDTO
from .measurements import MeasurementValidationError, build_outcome_replay_instruction


class PulseOutcomeReplayNotFound(ValueError):
    pass


def has_exact_pulse_analysis_scopes(scope: str) -> bool:
    return frozenset(scope.split()) == frozenset(PULSE_ANALYSIS_SCOPES)


def get_outcome_replay_instruction(
    *, team_id: int, task_id: UUID, actor_id: int, plan_id: UUID
) -> OutcomeReplayInstructionDTO:
    """Return only the current sandbox's server-derived measurement call."""
    plan = OutcomePlan.objects.for_team(team_id).filter(id=plan_id).first()
    if plan is None or plan.claimed_by_run_id is None:
        raise PulseOutcomeReplayNotFound("Outcome replay instruction not found.")

    run = PulseRun.objects.for_team(team_id).filter(id=plan.claimed_by_run_id).first()
    if (
        run is None
        or run.task_id != task_id
        or run.status != PulseRun.Status.ANALYZING
        or run.analysis_task_run_id is None
        or plan.readout_status != OutcomePlan.ReadoutStatus.MEASURING
        or plan.claimed_by_run_id != run.id
        or not tasks_api.is_active_staged_analysis_task_binding(
            team_id=team_id,
            task_id=task_id,
            task_run_id=run.analysis_task_run_id,
            caller_id=run.id,
            actor_id=actor_id,
        )
    ):
        raise PulseOutcomeReplayNotFound("Outcome replay instruction not found.")
    try:
        return build_outcome_replay_instruction(plan=plan)
    except MeasurementValidationError as error:
        raise PulseOutcomeReplayNotFound("Outcome replay instruction not found.") from error
