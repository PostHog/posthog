"""Read one user's own tasks and activity log rows in one project, from in-region Postgres."""

import datetime
from collections.abc import Iterable

from django.db.models.fields.json import KeyTextTransform, KeyTransform

from posthog.models import ActivityLog

from products.dashboards.backend.facade.api import dashboards_by_insight
from products.signals.backend.activity_summary.render import (
    MAX_ACTIVITY_ROWS_PER_PERSON,
    MAX_TASKS_PER_PERSON,
    NOISY_ACTIVITY_SCOPES,
    SANDBOX_PROMPT_TITLE_PREFIX,
    SCOUT_CLIENT_PREFIX,
    ActivityItem,
    Parent,
    ParentLookup,
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
            exclude_title_prefixes=(SANDBOX_PROMPT_TITLE_PREFIX,),
        )
    ]


def user_activity(team_id: int, user_id: int, start: datetime.datetime, end: datetime.datetime) -> list[ActivityItem]:
    """The user's own activity log rows in [start, end), newest `MAX_ACTIVITY_ROWS_PER_PERSON` first.

    System rows and rows written while someone impersonated the user are not the user's. Noisy scopes
    and scout writes go before the limit, so a bulk write cannot push the rest of the window out."""
    rows = (
        ActivityLog.objects.filter(team_id=team_id, user_id=user_id, created_at__gte=start, created_at__lt=end)
        .exclude(is_system=True)
        .exclude(was_impersonated=True)
        .exclude(scope__in=NOISY_ACTIVITY_SCOPES)
        .exclude(client__startswith=SCOUT_CLIENT_PREFIX)
        .order_by("-created_at")
        .annotate(
            name=KeyTextTransform("name", "detail"),
            intent=KeyTextTransform("intent", KeyTransform("payload", KeyTransform("trigger", "detail"))),
        )
        .values("scope", "activity", "client", "created_at", "name", "intent", "item_id")[:MAX_ACTIVITY_ROWS_PER_PERSON]
    )
    return [
        ActivityItem(
            at=row["created_at"],
            scope=row["scope"],
            activity=row["activity"],
            name=row["name"],
            client=row["client"],
            intent=row["intent"],
            item_id=row["item_id"],
        )
        for row in rows
    ]


def activity_parents(team_id: int, activity: Iterable[ActivityItem]) -> ParentLookup:
    """The dashboards that the insights in these rows sit on, in one query."""
    insight_ids = {
        int(item.item_id)
        for item in activity
        if item.scope == "Insight" and item.item_id and item.item_id.isascii() and item.item_id.isdigit()
    }
    if not insight_ids:
        return {}
    return {
        ("Insight", str(insight_id)): tuple(
            Parent(scope="Dashboard", item_id=str(dashboard.id), name=dashboard.name or "") for dashboard in dashboards
        )
        for insight_id, dashboards in dashboards_by_insight(insight_ids, team_id=team_id).items()
    }
