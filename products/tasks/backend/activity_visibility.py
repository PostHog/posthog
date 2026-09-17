"""Task activity-log visibility, mirroring Task API visibility.

A task filed into a personal channel belongs to its owner alone, so the activity feed
must apply the same rule. Otherwise a `Task`-scoped row exposes the id and share
details of a task every other route hides from that reader.

Both helpers return the ids to hide rather than the ids to show. A project holds far
more tasks than a project holds canvases, and nearly all of them are visible, so the
hidden set is the small one to carry into the query.
"""

from uuid import UUID

from posthog.models.user import User

from products.tasks.backend.models import Task
from products.tasks.backend.visibility import task_visibility_q


def hidden_task_ids(team_id: int, user: User | None) -> set[str]:
    """Ids of this team's tasks that the ordinary Task API hides from the user.

    Soft-deleted tasks are included, so an owner still reads their deleted task's history.
    """
    user_id = getattr(user, "id", None)
    hidden = Task.objects.filter(team_id=team_id).exclude(task_visibility_q(user_id))
    return {str(task_id) for task_id in hidden.values_list("id", flat=True)}


def hidden_task_ids_for_org(organization_id: str | UUID, user: User | None) -> set[str]:
    """Ids of tasks hidden from the user across an org. Cross-team by design."""
    user_id = getattr(user, "id", None)
    hidden = Task.objects.filter(team__organization_id=organization_id).exclude(task_visibility_q(user_id))
    return {str(task_id) for task_id in hidden.values_list("id", flat=True)}
