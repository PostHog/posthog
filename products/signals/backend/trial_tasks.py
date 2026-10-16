from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models.functions import Coalesce
from django.utils import timezone

import structlog
from celery import shared_task

from posthog.models import Organization, Team

from products.signals.backend.trial_billing import TrialBilling
from products.signals.backend.trial_gateway import fetch_trial_gateway_cost
from products.signals.backend.trial_models import SignalTrialGrant, SignalTrialOperation, SignalTrialOrganization
from products.signals.backend.trial_policy import TrialPolicy
from products.tasks.backend.facade.api import get_task_run
from products.tasks.backend.facade.billing import get_task_run_actual_cost
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
def reconcile_trial_operation(team_id: int, operation_id: str) -> None:
    operation = SignalTrialOperation.objects.for_team(team_id, canonical=True).get(id=operation_id)
    if operation.grant_id is None:
        return
    team = Team.objects.filter(id=operation.environment_id).first()
    if team is None:
        # The ledger outlives the project; reconstruct only its immutable tenant identity.
        team = Team(id=operation.team_id, organization_id=operation.organization_id)
    policy = TrialPolicy(team)
    gateway_cost = fetch_trial_gateway_cost(environment_id=operation.environment_id, operation_id=operation.id)
    compute_cost: int | None = 0
    compute_complete = True
    terminal = operation.finished_at is not None
    if operation.task_run_id is not None:
        run = get_task_run(operation.task_run_id, team_id=operation.environment_id)
        if run is not None:
            cost = get_task_run_actual_cost(run_id=operation.task_run_id, team_id=operation.environment_id)
            compute_cost, compute_complete = cost.compute_cost_microusd, cost.compute_complete
            terminal = run.is_terminal
        else:
            compute_cost, compute_complete = None, False
    policy.reconcile(
        operation_id=operation.id,
        source_id=f"operation:{operation.id}",
        is_task=operation.task_run_id is not None,
        token_cost_microusd=gateway_cost.token_cost_microusd if gateway_cost else None,
        compute_cost_microusd=compute_cost,
        complete=bool(terminal and gateway_cost and gateway_cost.complete and compute_complete),
    )
    if terminal:
        policy.finish(operation.id)
    for pending in SignalTrialOperation.objects.for_team(team_id, canonical=True).filter(
        grant_id=operation.grant_id, cancel_requested_at__isnull=False, cancelled_at__isnull=True
    ):
        cancel_trial_operation(pending)
    operation.refresh_from_db(fields=["accounting_complete"])
    now = timezone.now()
    SignalTrialOperation.objects.for_team(team_id, canonical=True).filter(id=operation.id).update(
        last_reconciled_at=now,
        next_reconcile_at=now + (timedelta(days=1) if operation.accounting_complete else timedelta(minutes=1)),
    )


@shared_task(ignore_result=True)
def reconcile_trials() -> None:
    pending = SignalTrialOrganization.objects.filter(grants_claimed__gt=0, billing_migrated_at__isnull=True)[:100]
    for allocation in pending:
        retry_pending_trial_billing.delay(str(allocation.organization_id))
    # Cross-project recovery: failed callbacks and cancelled runs remain in the durable queue.
    now = timezone.now()
    with transaction.atomic():
        operations = list(
            SignalTrialOperation.objects.unscoped()
            .filter(funding=SignalTrialOperation.Funding.TRIAL)
            .alias(due_at=Coalesce("next_reconcile_at", "admitted_at"))
            .filter(due_at__lte=now)
            .order_by("due_at", "admitted_at")
            .select_for_update(skip_locked=True)
            .only("id", "team_id")[:500]
        )
        SignalTrialOperation.objects.unscoped().filter(id__in=[operation.id for operation in operations]).update(
            next_reconcile_at=now + timedelta(minutes=5)
        )
    for operation in operations:
        reconcile_trial_operation.apply_async(args=(operation.team_id, str(operation.id)), expires=300)


def notify_trial_cost_updated(*, run_id: UUID, team_id: int, **kwargs: object) -> None:
    team = Team.objects.filter(id=team_id).first()
    if team is None:
        return
    canonical_id = team.parent_team_id or team.id
    operation = SignalTrialOperation.objects.for_team(canonical_id, canonical=True).filter(task_run_id=run_id).first()
    if operation and operation.grant_id:
        transaction.on_commit(lambda: reconcile_trial_operation.delay(canonical_id, str(operation.id)), robust=True)


@shared_task(ignore_result=True)
def retry_pending_trial_billing(organization_id: str) -> None:
    organization = Organization.objects.filter(id=organization_id).first()
    grant = (
        SignalTrialGrant.objects.unscoped().filter(organization_id=UUID(organization_id)).order_by("claimed_at").first()
    )
    if organization is None or grant is None:
        return
    try:
        status = TrialBilling(organization).status(grant_id=grant.id)
    except Exception:
        logger.warning("signals_trial_billing_retry_pending", organization_id=organization_id, exc_info=True)
        return
    if status.migrated:
        SignalTrialOrganization.objects.filter(
            organization_id=organization_id, billing_migrated_at__isnull=True
        ).update(billing_migrated_at=timezone.now())
