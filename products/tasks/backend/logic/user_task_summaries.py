"""Read the tasks people started themselves, with the summary and tags of each task's latest run.

The activity summary pipeline in products/signals reads these through the facade. It needs the
title, origin, and the run's own `task_summary` and `task_tags`, and nothing else from the run's
state, so the query pulls those keys out in Postgres instead of loading whole state blobs.
"""

import datetime
from collections.abc import Collection, Mapping
from typing import Any

from django.db.models.fields.json import KeyTextTransform, KeyTransform

from posthog.dataclasses import frozen

from products.tasks.backend.models import (
    PRIOR_RUN_SUMMARY_STATE_KEY,
    PRIOR_RUN_TAGS_STATE_KEY,
    TASK_RUN_SUMMARY_STATE_KEY,
    TASK_RUN_TAGS_STATE_KEY,
    Task,
    TaskRun,
)


@frozen
class UserTaskSummary:
    task_id: str
    team_id: int
    user_id: int
    created_at: datetime.datetime
    title: str
    origin_product: str
    summary: str | None
    tags: tuple[str, ...]


@frozen
class UserTaskTime:
    team_id: int
    user_id: int
    created_at: datetime.datetime


def _tags(value: object) -> tuple[str, ...]:
    return tuple(tag for tag in value if isinstance(tag, str)) if isinstance(value, list) else ()


def list_user_task_summaries(
    *,
    team_ids: Collection[int],
    user_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
    origin_products: Collection[str],
    limit: int,
    exclude_title_prefixes: Collection[str] = (),
) -> list[UserTaskSummary]:
    """The newest `limit` non-deleted tasks one user created in these teams, in [start, end).

    Tasks whose title starts with one of `exclude_title_prefixes` do not count towards the limit.

    One user per call, so a single busy person cannot take another person's share of a batch.
    """
    if not team_ids or not origin_products or limit <= 0:
        return []
    queryset = Task.objects.filter(
        team_id__in=list(team_ids),
        created_by_id=user_id,
        origin_product__in=list(origin_products),
        created_at__gte=start,
        created_at__lt=end,
        deleted=False,
    )
    for prefix in exclude_title_prefixes:
        queryset = queryset.exclude(title__startswith=prefix)
    tasks = list(
        queryset.order_by("-created_at").values("id", "team_id", "created_at", "title", "origin_product")[:limit]
    )
    if not tasks:
        return []
    latest_runs = {
        row["task_id"]: row
        for row in TaskRun.objects.filter(team_id__in=list(team_ids), task_id__in=[task["id"] for task in tasks])
        .order_by("task_id", "-created_at")
        .distinct("task_id")
        .annotate(
            summary=KeyTextTransform(TASK_RUN_SUMMARY_STATE_KEY, "state"),
            prior_summary=KeyTextTransform(PRIOR_RUN_SUMMARY_STATE_KEY, "state"),
            run_tags=KeyTransform(TASK_RUN_TAGS_STATE_KEY, "state"),
            prior_tags=KeyTransform(PRIOR_RUN_TAGS_STATE_KEY, "state"),
        )
        .values("task_id", "summary", "prior_summary", "run_tags", "prior_tags")
    }
    summaries: list[UserTaskSummary] = []
    for task in tasks:
        run: Mapping[str, Any] = latest_runs.get(task["id"], {})
        summary = (run.get("summary") or run.get("prior_summary") or "").strip() or None
        # An explicit tag list on the run wins, even an empty one, as in `task_tags_from_state`.
        tags = run.get("run_tags") if isinstance(run.get("run_tags"), list) else run.get("prior_tags")
        summaries.append(
            UserTaskSummary(
                task_id=str(task["id"]),
                team_id=task["team_id"],
                user_id=user_id,
                created_at=task["created_at"],
                title=task["title"],
                origin_product=task["origin_product"],
                summary=summary,
                tags=_tags(tags),
            )
        )
    return summaries


def list_user_task_times(
    *,
    team_ids: Collection[int],
    start: datetime.datetime,
    end: datetime.datetime,
    origin_products: Collection[str],
    exclude_title_prefixes: Collection[str] = (),
) -> list[UserTaskTime]:
    """The creator and creation time of every non-deleted task in these teams, in [start, end).

    One query for all users, so a caller can count new tasks per person without a query per person.
    Tasks with no creator, and tasks whose title starts with one of `exclude_title_prefixes`, are left out.
    """
    if not team_ids or not origin_products:
        return []
    queryset = Task.objects.filter(
        team_id__in=list(team_ids),
        created_by_id__isnull=False,
        origin_product__in=list(origin_products),
        created_at__gte=start,
        created_at__lt=end,
        deleted=False,
    )
    for prefix in exclude_title_prefixes:
        queryset = queryset.exclude(title__startswith=prefix)
    rows = queryset.values_list("team_id", "created_by_id", "created_at")
    return [
        UserTaskTime(team_id=team_id, user_id=user_id, created_at=created_at) for team_id, user_id, created_at in rows
    ]
