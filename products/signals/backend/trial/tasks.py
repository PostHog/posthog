from celery import shared_task

from posthog.models import Team

from products.signals.backend.trial.models import SignalTrialGrant
from products.signals.backend.trial.policy import TrialPolicy
from products.tasks.backend.facade.api import iter_trial_task_runs
from products.tasks.backend.facade.cancellation import cancel_task_run
from products.tasks.backend.facade.contracts import TaskRunDTO


def cancel_trial_run(run: TaskRunDTO) -> bool:
    if run.is_terminal:
        return run.status == "cancelled"
    funding = run.state["self_driving_funding"]
    if funding.get("stage") == "research" and run.state.get("sandbox_provisioning_started") is True:
        return False
    outcome, _ = cancel_task_run(
        run.id,
        run.task_id,
        run.team_id,
        reason="Stopped: the project's one-time Self-driving trial allowance is exhausted.",
        source="self_driving_trial",
    )
    return outcome in {"accepted", "already_terminal"}


@shared_task(ignore_result=True)
def cancel_trial_grant(team_id: int, grant_id: str) -> None:
    # nosemgrep: celery-task-team-scope-audit -- Team is the tenant root, selected explicitly by the task's team_id.
    if not TrialPolicy(Team.objects.get(id=team_id)).enabled():
        return
    if (
        not SignalTrialGrant.objects.for_team(team_id, canonical=True)
        .filter(id=grant_id, exhaustion_reason="cost_limit")
        .exists()
    ):
        return
    for run in iter_trial_task_runs(team_id=team_id, grant_id=grant_id):
        cancel_trial_run(run)
