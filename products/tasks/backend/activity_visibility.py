"""Task activity-log visibility, mirroring Task API visibility.

A task filed into a personal channel belongs to its owner alone, so the activity feed
must apply the same rule. Otherwise a `Task`-scoped row exposes the id and share
details of a task every other route hides from that reader.

Both helpers return the ids to hide rather than the ids to show, as a subquery rather
than a materialized set. A reader's hidden set holds every colleague's personal-space
task and grows with the organization's whole task history, so carrying it into the
statement would grow the query with it until the bind-parameter ceiling stopped the
endpoint outright.
"""

from uuid import UUID

from django.db.models import CharField, QuerySet
from django.db.models.functions import Cast

from posthog.models.user import User

from products.tasks.backend.models import Task
from products.tasks.backend.visibility import task_read_visibility_q

# `ActivityLog.item_id` is a string column holding the id of whatever object the row is
# about, so a task id has to be compared as text.
_ITEM_ID = "item_id_text"


def _hidden(tasks: QuerySet[Task], user: User | None) -> QuerySet[Task, dict[str, str]]:
    user_id = getattr(user, "id", None)
    return (
        tasks.exclude(task_read_visibility_q(user_id)).annotate(**{_ITEM_ID: Cast("id", CharField())}).values(_ITEM_ID)
    )


def hidden_task_ids(team_id: int, user: User | None) -> QuerySet[Task, dict[str, str]]:
    """Text ids of this team's tasks that the ordinary Task API hides from the user.

    Soft-deleted tasks are included, so an owner still reads their deleted task's history.
    """
    return _hidden(Task.objects.filter(team_id=team_id), user)


def hidden_task_ids_for_org(organization_id: str | UUID, user: User | None) -> QuerySet[Task, dict[str, str]]:
    """Text ids of tasks hidden from the user across an org. Cross-team by design."""
    return _hidden(Task.objects.filter(team__organization_id=organization_id), user)
