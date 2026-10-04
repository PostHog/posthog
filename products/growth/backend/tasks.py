from uuid import UUID

from celery import shared_task

from posthog.redis import get_client

from products.growth.backend.models import AccountAuditAdmission


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=70)
def finalize_account_audit(team_id: int, task_run_id: str) -> None:
    from products.growth.backend.audit_execution import (
        finish_account_audit,  # noqa: PLC0415 — keeps agent dependencies off task registration
    )

    lock = get_client().lock(f"account-audit-finish:{team_id}:{task_run_id}", timeout=90)
    if not lock.acquire(blocking=False):
        return
    try:
        finish_account_audit(team_id=team_id, task_run_id=UUID(task_run_id))
    finally:
        lock.release()


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=70)
def reconcile_account_audits() -> None:
    pending = AccountAuditAdmission.objects.unscoped().filter(finalized_at__isnull=True)
    for team_id, run_id in pending.values_list("team_id", "task_run_id").iterator(chunk_size=100):
        finalize_account_audit.delay(team_id, str(run_id))
