from uuid import UUID

from celery import shared_task

from ..logic import cleanup


@shared_task(
    ignore_result=True,
    soft_time_limit=60,
    time_limit=70,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=5,
)
def delete_orphaned_fragments(after: str | None = None) -> None:
    next_cursor = cleanup.delete_orphaned_fragment_batch(UUID(after) if after else None)
    if next_cursor is not None:
        delete_orphaned_fragments.delay(str(next_cursor))
