"""Read one user's own tasks and activity log rows in one project, from in-region Postgres."""

import datetime

from django.db.models.fields.json import KeyTextTransform, KeyTransform

from posthog.models import ActivityLog

from products.signals.backend.activity_summary.render import (
    MAX_ACTIVITY_ROWS_PER_PERSON,
    MAX_TASKS_PER_PERSON,
    ActivityItem,
    TaskItem,
)
from products.tasks.backend.facade.user_task_summaries import list_user_task_summaries

# Tasks a person started: in PostHog AI, in Slack, or by hand in the web or desktop app. Scouts,
# reports and workflows start tasks under a person's name too, and those are not the person's intent.
TASK_ORIGIN_PRODUCTS = ("posthog_ai", "slack", "user_created")


def user_tasks(team_id: int, user_id: int, start: datetime.datetime, end: datetime.datetime) -> list[TaskItem]:
    """The user's own tasks in [start, end), newest `MAX_TASKS_PER_PERSON` first."""
    return [
        TaskItem(at=task.created_at, title=task.title, summary=task.summary, tags=task.tags)
        for task in list_user_task_summaries(
            team_ids=[team_id],
            user_id=user_id,
            start=start,
            end=end,
            origin_products=TASK_ORIGIN_PRODUCTS,
            limit=MAX_TASKS_PER_PERSON,
        )
    ]


def user_activity(team_id: int, user_id: int, start: datetime.datetime, end: datetime.datetime) -> list[ActivityItem]:
    """The user's own activity log rows in [start, end), newest `MAX_ACTIVITY_ROWS_PER_PERSON` first.

    System rows and rows written while someone impersonated the user are not the user's."""
    rows = (
        ActivityLog.objects.filter(team_id=team_id, user_id=user_id, created_at__gte=start, created_at__lt=end)
        .exclude(is_system=True)
        .exclude(was_impersonated=True)
        .order_by("-created_at")
        .annotate(
            name=KeyTextTransform("name", "detail"),
            intent=KeyTextTransform("intent", KeyTransform("payload", KeyTransform("trigger", "detail"))),
        )
        .values("scope", "activity", "client", "created_at", "name", "intent")[:MAX_ACTIVITY_ROWS_PER_PERSON]
    )
    return [
        ActivityItem(
            at=row["created_at"],
            scope=row["scope"],
            activity=row["activity"],
            name=row["name"],
            client=row["client"],
            intent=row["intent"],
        )
        for row in rows
    ]
