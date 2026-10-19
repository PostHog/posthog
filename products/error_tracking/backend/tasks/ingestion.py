from celery import shared_task

from products.error_tracking.backend.logic.ingestion_switch import reconcile_ingestion_disabled_tokens


@shared_task(
    name="products.error_tracking.backend.tasks.reconcile_error_tracking_ingestion_disabled_tokens",
    ignore_result=True,
    max_retries=0,
)
def reconcile_error_tracking_ingestion_disabled_tokens() -> None:
    reconcile_ingestion_disabled_tokens()
