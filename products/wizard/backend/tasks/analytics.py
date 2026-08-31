from celery import shared_task

from posthog.celery_queues import CeleryQueue
from posthog.models import User
from posthog.ph_client import ph_scoped_capture

from products.wizard.backend.observability.config import WIZARD_ANALYTICS_TASK


@shared_task(ignore_result=True, name=WIZARD_ANALYTICS_TASK, queue=CeleryQueue.DEFAULT.value)
def capture_wizard_run_event(
    team_id: int,
    created_by_id: int | None,
    run_id: str,
    event: str,
    event_uuid: str,
    properties: dict[str, str | int | float | bool | None] | None = None,
) -> None:
    distinct_id = str(run_id)
    if created_by_id is not None:
        user_distinct_id = User.objects.filter(id=created_by_id).values_list("distinct_id", flat=True).first()
        if user_distinct_id is not None:
            distinct_id = user_distinct_id
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=distinct_id,
            event=event,
            properties={**(properties or {}), "team_id": team_id, "wizard_run_id": str(run_id)},
            uuid=event_uuid,
        )
