"""Read tasks any member of a team may read, with the summary and status of each task's latest run.

Signals scouts read discussion tasks on their own reports through the facade. A scout acts for no
person, so only tasks the whole team can read qualify: null-channel tasks from a team-readable
origin, and tasks in a public channel. The query pulls the summary keys out of the run state in
Postgres instead of loading whole state blobs.
"""

import datetime
from collections.abc import Collection

from django.db.models import BooleanField, Case, Value, When
from django.db.models.fields.json import KeyTextTransform

from posthog.dataclasses import frozen

from products.tasks.backend.models import PRIOR_RUN_SUMMARY_STATE_KEY, TASK_RUN_SUMMARY_STATE_KEY, Task, TaskRun
from products.tasks.backend.visibility import task_visibility_q


@frozen
class TeamTaskSummary:
    task_id: str
    created_at: datetime.datetime
    created_by_id: int | None
    run_status: str | None
    # None when the latest run wrote no summary, or when its summary is not readable without a viewer.
    summary: str | None
    # True when only the creator can drive the task or write its run summary. That holds for a task
    # filed into a channel. A null-channel task from a team-controlled origin can be driven by any
    # member, so its summary may be someone else's text.
    creator_controls_alone: bool


def list_team_task_summaries(
    *,
    team_id: int,
    task_ids: Collection[str],
    origin_products: Collection[str],
    created_after: datetime.datetime,
    limit: int,
) -> list[TeamTaskSummary]:
    """The newest `limit` of these tasks that every member of the team may read, created after `created_after`.

    A run that carries `analytics_query_context` keeps its summary private, because reading it needs
    the viewer's own access to the queries behind it. A workflow task's summary is readable by its
    creator only. Both come back with a null `summary`, matching the task summaries API for a viewer
    who cannot read them.
    """
    if not task_ids or not origin_products or limit <= 0:
        return []
    tasks = list(
        Task.objects.filter(
            team_id=team_id,
            id__in=list(task_ids),
            origin_product__in=list(origin_products),
            created_at__gte=created_after,
            deleted=False,
        )
        .filter(task_visibility_q(None, team_id))
        .order_by("-created_at", "id")
        .values("id", "created_at", "created_by_id", "origin_product", "channel_id")[:limit]
    )
    if not tasks:
        return []
    latest_runs = {
        row["task_id"]: row
        for row in TaskRun.objects.filter(team_id=team_id, task_id__in=[task["id"] for task in tasks])
        .order_by("task_id", "-created_at", "-id")
        .distinct("task_id")
        .annotate(
            summary=KeyTextTransform(TASK_RUN_SUMMARY_STATE_KEY, "state"),
            prior_summary=KeyTextTransform(PRIOR_RUN_SUMMARY_STATE_KEY, "state"),
            has_analytics_context=Case(
                When(state__has_key="analytics_query_context", then=Value(True)),
                default=Value(False),
                output_field=BooleanField(),
            ),
        )
        .values("task_id", "status", "summary", "prior_summary", "has_analytics_context")
    }
    summaries: list[TeamTaskSummary] = []
    for task in tasks:
        run = latest_runs.get(task["id"])
        summary: str | None = None
        if (
            run is not None
            and not run["has_analytics_context"]
            and task["origin_product"] != Task.OriginProduct.WORKFLOW
        ):
            summary = (run["summary"] or run["prior_summary"] or "").strip() or None
        summaries.append(
            TeamTaskSummary(
                task_id=str(task["id"]),
                created_at=task["created_at"],
                created_by_id=task["created_by_id"],
                run_status=run["status"] if run is not None else None,
                summary=summary,
                creator_controls_alone=task["channel_id"] is not None and task["created_by_id"] is not None,
            )
        )
    return summaries
