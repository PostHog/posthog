from uuid import UUID

from django.core.cache import cache

from celery import shared_task

from posthog.models import Team

from products.signals.backend.trial.models import SignalTrialGrant, SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy
from products.tasks.backend.facade.api import has_active_task_runs, iter_trial_task_runs
from products.tasks.backend.facade.cancellation import cancel_task_run
from products.tasks.backend.facade.contracts import TaskRunDTO

REPORT_RESERVATION_RECOVERY_CURSOR_KEY = "signals:trial-report-recovery:cursor"


def release_abandoned_report_reservation(reservation: SignalTrialReportReservation) -> None:
    team = Team.objects.filter(id=reservation.team_id).first()
    if team is None:
        return
    with TrialPolicy(team).locked_grant(reservation.grant_id):
        reservation.refresh_from_db()
        if reservation.status == SignalTrialReportReservation.Status.RESERVED and not has_active_task_runs(
            team_id=reservation.team_id, run_ids=reservation.attempt_run_ids
        ):
            reservation.status = SignalTrialReportReservation.Status.RELEASED
            reservation.active_attempts = 0
            reservation.attempt_run_ids = []
            reservation.save(update_fields=["status", "active_attempts", "attempt_run_ids"])


def release_abandoned_report_attempts(policy: TrialPolicy, run_id: UUID) -> None:
    grant = policy.grant()
    if grant is None:
        return
    reservations = SignalTrialReportReservation.objects.for_team(policy.team_id, canonical=True).filter(
        grant=grant, status=SignalTrialReportReservation.Status.RESERVED, attempt_run_ids__contains=[run_id]
    )
    for reservation in reservations:
        release_abandoned_report_reservation(reservation)


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


def release_abandoned_report_reservations() -> None:
    # A worker can disappear inside a direct-report request. Task termination is
    # already durable, so reservations can release abandoned attempts from it.
    pending = (
        SignalTrialReportReservation.objects.unscoped()
        .filter(status=SignalTrialReportReservation.Status.RESERVED, active_attempts__gt=0, attempt_run_ids__len__gt=0)
        .order_by("id")
    )
    cursor = cache.get(REPORT_RESERVATION_RECOVERY_CURSOR_KEY)
    batch = list((pending.filter(id__gt=cursor) if cursor else pending)[:100])
    if not batch and cursor:
        batch = list(pending[:100])
    for reservation in batch:
        release_abandoned_report_reservation(reservation)
    if batch:
        # Advance past live owners and deleted teams so they cannot starve later rows.
        cache.set(REPORT_RESERVATION_RECOVERY_CURSOR_KEY, str(batch[-1].id), timeout=None)
