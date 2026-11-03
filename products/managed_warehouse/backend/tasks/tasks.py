from celery import shared_task

from posthog.tasks.utils import CeleryQueue

from products.managed_warehouse.backend.internal_loading import load_internal_team
from products.managed_warehouse.backend.project_moves import repeat_move_out


@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=300,
    max_retries=72,
)
def load_internal_warehouse(organization_id: str, team_id: int, generation: int) -> None:
    load_internal_team(organization_id, team_id, generation)


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def repeat_project_move_out(organization_id: str, team_ids: list[int]) -> None:
    """Ten minutes after a project move: remove the old organization's rows that a slow writer re-created."""
    repeat_move_out(organization_id, team_ids)
