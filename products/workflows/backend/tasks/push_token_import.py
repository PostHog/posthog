from uuid import UUID

from celery import Task, shared_task
from structlog import get_logger

from posthog.scoping_audit import skip_team_scope_audit
from posthog.tasks.utils import CeleryQueue

from products.workflows.backend.services.push_token_import import (
    EXPIRY_MARGIN,
    STALL_CHECK_EVERY,
    check_stalled_push_token_import,
    expire_unknown_person_devices,
    fail_push_token_import,
    run_push_token_import_batches,
)

logger = get_logger(__name__)

MAX_RETRIES = 3
MAINTENANCE_RETRIES = 8


@shared_task(bind=True, ignore_result=True, queue=CeleryQueue.DEFAULT.value, max_retries=MAX_RETRIES)
@skip_team_scope_audit
def run_push_token_import(self: Task, *, team_id: int, import_id: str) -> None:
    try:
        more = run_push_token_import_batches(team_id, UUID(import_id))
    except Exception as error:
        logger.warning("push_token_import_batch_failed", team_id=team_id, import_id=import_id, error=str(error))
        if self.request.retries < MAX_RETRIES:
            raise self.retry(countdown=30 * (self.request.retries + 1))
        fail_push_token_import(
            team_id,
            UUID(import_id),
            "PostHog couldn't save the devices, so the import stopped. Upload the file again to import the rest. "
            "Devices already imported are not stored twice.",
        )
        return
    if more:
        run_push_token_import.delay(team_id=team_id, import_id=import_id)


# A check that dies does not schedule the next one, so an error has to retry it rather than end the chain.
@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=30,
    max_retries=MAINTENANCE_RETRIES,
)
@skip_team_scope_audit
def check_push_token_import_stalled(*, team_id: int, import_id: str) -> None:
    if check_stalled_push_token_import(team_id, UUID(import_id)):
        check_push_token_import_stalled.apply_async(
            kwargs={"team_id": team_id, "import_id": import_id}, countdown=int(STALL_CHECK_EVERY.total_seconds())
        )


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=30,
    max_retries=MAINTENANCE_RETRIES,
)
@skip_team_scope_audit
def expire_push_token_import_devices(*, team_id: int, import_id: str) -> None:
    if expire_unknown_person_devices(team_id, UUID(import_id)):
        expire_push_token_import_devices.apply_async(
            kwargs={"team_id": team_id, "import_id": import_id}, countdown=int(EXPIRY_MARGIN.total_seconds())
        )
