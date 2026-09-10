"""Celery entrypoints for subscription housekeeping."""

from celery import shared_task

from products.subscriptions.backend.logic.adoption_reconciliation import reconcile_proactive_artifact_adoptions_batch


@shared_task(
    name="products.subscriptions.backend.tasks.reconcile_proactive_artifact_adoptions",
    ignore_result=True,
)
def reconcile_proactive_artifact_adoptions() -> None:
    reconcile_proactive_artifact_adoptions_batch()
