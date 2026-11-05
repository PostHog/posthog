from celery import shared_task

from posthog.tasks.utils import CeleryQueue

from products.managed_warehouse.backend.facade.contracts import CPUnavailableError
from products.managed_warehouse.backend.internal_loading import load_internal_team
from products.managed_warehouse.backend.project_moves import repeat_move_out, restore_rows


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


# Jittered backoff, at most about 1.5 hours in all, on any error (a restore's locked re-read can time out).
# After the last retry, the move_out_repeat_failed or move_undo_skipped log leads to the design's runbook.
_MOVE_RETRIES: dict = {"autoretry_for": (Exception,), "retry_backoff": 60, "retry_backoff_max": 600, "max_retries": 12}


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value, **_MOVE_RETRIES)
def repeat_project_move_out(organization_id: str, team_ids: list[int]) -> None:
    """Ten minutes after a project move: remove the old organization's rows that a slow writer re-created."""
    if not repeat_move_out(organization_id, team_ids):
        raise CPUnavailableError("hogtower did not confirm the removal")


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value, **_MOVE_RETRIES)
def restore_project_move_out(project_id: int, organization_id: str, rows: list[dict]) -> None:
    """Put back the rows a failed project move could not restore, while the org still owns their teams."""
    if restore_rows(project_id, organization_id, rows):
        raise CPUnavailableError("hogtower did not confirm the restore")
