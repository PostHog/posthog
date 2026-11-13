from uuid import UUID

from products.tasks.backend.facade import api as tasks_facade

from .intake import start_held_requests
from .pull_requests import record_pull_request_failure, release_publication_claim


def settle_publication(task_run_id: UUID, *, team_id: int, has_failed: bool) -> None:
    run = tasks_facade.get_task_run(task_run_id, team_id)
    if run is None:
        return
    if has_failed:
        record_pull_request_failure(run.task_id, team_id, "publish_failed")
    release_publication_claim(run.task_id, team_id, task_run_id)
    start_held_requests(team_id)
