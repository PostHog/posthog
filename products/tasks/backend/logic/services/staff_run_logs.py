from uuid import UUID

from posthog.models.user import User
from posthog.storage import object_storage

from products.tasks.backend.facade.contracts import TaskRunLogLink
from products.tasks.backend.models import TaskRun
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
    if object_storage.head_object(run.log_url) is None:
        return TaskRunLogLink(
            url=None,
            unavailable_reason="This run has no logs. They may not be written yet, or object storage is unreachable.",
        )
    url = object_storage.get_presigned_url(
        run.log_url,
        expiration=LOG_LINK_EXPIRATION_SECONDS,
        content_disposition=f'attachment; filename="run_{run.id}.jsonl"',
    )
    if not url:
        return TaskRunLogLink(
            url=None,
            unavailable_reason="Could not create a download link for this run's logs. Object storage is unavailable.",
        )
    return TaskRunLogLink(url=url)
