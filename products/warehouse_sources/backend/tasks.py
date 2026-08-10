import structlog
from celery import shared_task

logger = structlog.get_logger(__name__)


@shared_task(
    ignore_result=True,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=3600,
    max_retries=10,
)
def cleanup_disabled_external_data_schema(
    *,
    team_id: int,
    schema_id: str,
    reason: str,
    exclude_workflow_id: str | None = None,
) -> None:
    """Stop in-flight sync work after a schema stopped syncing (disabled or deleted).

    Dispatched from the ``ExternalDataSchema`` write chokepoints via
    ``transaction.on_commit``. Runs asynchronously because the teardown talks to
    Temporal and may fail tens of thousands of queue batch rows, which must not
    block the API response that flipped the flag. Retries with backoff; every
    teardown step is idempotent, so a retry only re-runs what previously failed.
    """
    # Deferred: keeps the queue/Temporal stack out of Celery task autodiscovery.
    from products.warehouse_sources.backend.sync_teardown import teardown_schema_syncs  # noqa: PLC0415

    teardown_schema_syncs(
        team_id=team_id,
        schema_id=schema_id,
        reason=reason,
        exclude_workflow_id=exclude_workflow_id,
    )
