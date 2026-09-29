from celery import shared_task


@shared_task(ignore_result=True, soft_time_limit=60, time_limit=70)
def retry_account_audit_dispatches() -> None:
    from products.growth.backend.account_audits import (
        AccountAuditService,  # noqa: PLC0415 — keeps Temporal off task registration
    )

    AccountAuditService.retry_pending_dispatches()
