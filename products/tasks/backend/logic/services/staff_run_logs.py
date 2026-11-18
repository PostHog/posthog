from uuid import UUID

from posthog.models.user import User

from products.tasks.backend.facade.contracts import TaskRunLogLink
from products.tasks.backend.models import TaskRun
from products.tasks.backend.storage import run_log_download_url, run_log_exists
from products.tasks.backend.visibility import task_run_visibility_q

LOG_LINK_EXPIRATION_SECONDS = 300


def staff_task_run_log_link(run_id: UUID, user: User) -> TaskRunLogLink | None:
    """Returns None when the run does not exist or the staff member may not see it.

    Staff see the runs of their own organizations only, with the same visibility rules as the app, so a run in
    someone else's private channel stays private.
    """
    run = (
        TaskRun._default_manager.filter(task__team__organization_id__in=user.organizations.values("id"))
        .filter(task_run_visibility_q(user.id))
        .filter(id=run_id)
        .first()
    )
    if run is None:
        return None
    if not run_log_exists(run.log):
        return TaskRunLogLink(
            url=None,
            unavailable_reason="This run has no logs. They may not be written yet, or object storage is unreachable.",
        )
    url = run_log_download_url(
        run.log,
        expiration_seconds=LOG_LINK_EXPIRATION_SECONDS,
        content_disposition=f'attachment; filename="run_{run.id}.jsonl"',
    )
    if not url:
        return TaskRunLogLink(
            url=None,
            unavailable_reason="Could not create a download link for this run's logs. Object storage is unavailable.",
        )
    return TaskRunLogLink(url=url)
