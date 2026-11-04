from django.core.cache import cache

from posthog.models import Team

from products.signals.backend.trial.models import SignalTrialReportReservation
from products.signals.backend.trial.policy import TrialPolicy
from products.tasks.backend.facade.api import has_active_task_runs

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
