from celery import shared_task

from posthog.tasks.utils import CeleryQueue

from products.managed_warehouse.backend.facade.contracts import CPUnavailableError
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


# Retried with jittered backoff (at most about 1.5 hours in all) while hogtower does not confirm. After the last
# retry, the move_out_repeat_failed log leads to the managed_warehouse_moved_rows command.
@shared_task(
    ignore_result=True,
    queue=CeleryQueue.DEFAULT.value,
    autoretry_for=(CPUnavailableError,),
    retry_backoff=60,
    retry_backoff_max=600,
    max_retries=12,
)
def repeat_project_move_out(organization_id: str, team_ids: list[int]) -> None:
    """Ten minutes after a project move: remove the old organization's rows that a slow writer re-created."""
    if not repeat_move_out(organization_id, team_ids):
        raise CPUnavailableError("hogtower did not confirm the removal")
