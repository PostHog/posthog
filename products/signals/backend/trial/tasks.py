from django.utils import timezone

import structlog
from celery import shared_task

from posthog.models import Team

from products.signals.backend.spend import complete_task_spend, refresh_task_spend
from products.signals.backend.trial.models import SignalTrialOperation
from products.signals.backend.trial.policy import TrialPolicy
from products.tasks.backend.facade.api import get_task_run
from products.tasks.backend.facade.billing import process_pending_gateway_usage
from products.tasks.backend.facade.cancellation import cancel_task_run

logger = structlog.get_logger(__name__)


def cancel_trial_operation(operation: SignalTrialOperation) -> None:
    if not operation.cancel_requested_at or operation.cancelled_at or not operation.task_run_id:
        return
    run = get_task_run(operation.task_run_id, team_id=operation.environment_id)
    if run is None:
        return
    outcome, _ = cancel_task_run(
        run.id,
        run.task_id,
        operation.environment_id,
        reason="Stopped: the project's one-time Self-driving trial allowance is exhausted.",
        source="self_driving_trial",
    )
    if outcome in {"accepted", "already_terminal"}:
        SignalTrialOperation.objects.for_team(operation.team_id, canonical=True).filter(id=operation.id).update(
            cancelled_at=timezone.now()
        )
        logger.info(
            "signals_trial_cancelled",
            grant_id=str(operation.grant_id),
            operation_id=str(operation.id),
            stage=operation.stage,
            latency_seconds=(timezone.now() - operation.cancel_requested_at).total_seconds(),
        )


@shared_task(ignore_result=True)
def cancel_trial_grant(team_id: int, grant_id: str) -> None:
    for operation in SignalTrialOperation.objects.for_team(team_id, canonical=True).filter(
        grant_id=grant_id,
        cancel_requested_at__isnull=False,
        cancelled_at__isnull=True,
        task_run_id__isnull=False,
    ):
        cancel_trial_operation(operation)


@shared_task(ignore_result=True)
def reconcile_trial_operation(team_id: int, operation_id: str) -> None:
    operation = SignalTrialOperation.objects.for_team(team_id, canonical=True).get(id=operation_id)
    if operation.grant_id is None or operation.task_run_id is None:
        return
    run = get_task_run(operation.task_run_id, team_id=operation.environment_id)
    if run is not None:
        process_pending_gateway_usage(run_id=run.id, team_id=operation.environment_id)
        refresh_task_spend(team_id=operation.environment_id, run_id=str(run.id))
        if run.is_terminal:
            if not complete_task_spend(team_id=operation.environment_id, run_id=str(run.id)):
                return
            # nosemgrep: celery-task-team-scope-audit -- Team is the scope identity; the operation supplies its environment.
            policy = TrialPolicy(Team.objects.get(id=operation.environment_id))
            with policy.locked_grant(operation.grant_id):
                SignalTrialOperation.objects.for_team(team_id, canonical=True).filter(id=operation.id).update(
                    finished_at=timezone.now()
                )
                policy.release_abandoned_report_attempts(operation)
    cancel_trial_grant(team_id, str(operation.grant_id))


@shared_task(ignore_result=True)
def reconcile_trials() -> None:
    # Only active work needs a quota backstop; late receipts use shared cost reconciliation.
    for operation in (
        SignalTrialOperation.objects.unscoped()
        .filter(
            funding=SignalTrialOperation.Funding.TRIAL,
            task_run_id__isnull=False,
            finished_at__isnull=True,
        )
        .only("id", "team_id")
        .iterator(chunk_size=500)
    ):
        reconcile_trial_operation.apply_async(args=(operation.team_id, str(operation.id)), expires=60)
