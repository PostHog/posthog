"""Read tasks any member of a team may read, with the summary and status of each task's latest run.

Signals scouts read discussion tasks on their own reports through the facade. A scout acts for no
person, so only tasks the whole team can read qualify: null-channel tasks from a team-readable
origin, and tasks in a public channel. A Slack task sits in its creator's personal channel, so it
qualifies on its thread instead: only when every thread it answers in is a public Slack channel,
because the conversation was already open to the whole workspace. A private channel, a direct
message, a group DM, and a thread nobody classified stay out. The query pulls the summary keys out of the run state in
Postgres instead of loading whole state blobs.
"""

import datetime
from collections.abc import Collection

from django.db.models import BooleanField, Case, Exists, F, OuterRef, Q, Subquery, Value, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Coalesce

from posthog.dataclasses import frozen

from products.tasks.backend.models import PRIOR_RUN_SUMMARY_STATE_KEY, TASK_RUN_SUMMARY_STATE_KEY, Task, TaskRun
from products.tasks.backend.visibility import task_visibility_q


@frozen
class TeamTaskSummary:
    task_id: str
    created_at: datetime.datetime
    # When a run of the task last changed, such as a new summary. The creation time for a task with no run.
    active_at: datetime.datetime
    created_by_id: int | None
    origin_product: str
    run_status: str | None
    # None when the latest run wrote no summary, or when its summary is not readable without a viewer.
    summary: str | None
    # True when only the creator can drive the task or write its run summary. That holds for a task
    # filed into a channel. A null-channel task from a team-controlled origin can be driven by any
    # member, so its summary may be someone else's text. A Slack task never qualifies: other people in
    # its thread can send it turns, and the thread itself reaches its agent as context. A caller that
    # returns a Slack summary anyway decides that for itself.
    creator_controls_alone: bool


def _readable_by_team_q(team_id: int) -> Q:
    """Tasks any member of the team may read, with a Slack task judged by its thread rather than its channel."""
    from products.slack_app.backend.models import (  # noqa: PLC0415 — cross-product import kept off the import path
        PUBLIC_CHANNEL_CONVERSATION_TYPES,
        SlackThreadTaskMapping,
    )

    thread_mappings = SlackThreadTaskMapping.objects.filter(task_id=OuterRef("pk"))
    in_public_thread = Exists(thread_mappings.filter(conversation_type__in=sorted(PUBLIC_CHANNEL_CONVERSATION_TYPES)))
    in_other_thread = Exists(thread_mappings.exclude(conversation_type__in=sorted(PUBLIC_CHANNEL_CONVERSATION_TYPES)))
    slack_q = Q(origin_product=Task.OriginProduct.SLACK)
    return (slack_q & in_public_thread & ~in_other_thread) | (~slack_q & task_visibility_q(None, team_id))


def list_team_task_summaries(
    *,
    team_id: int,
    task_ids: Collection[str],
    origin_products: Collection[str],
    active_after: datetime.datetime,
    limit: int,
) -> list[TeamTaskSummary]:
    """The `limit` most recently active of these tasks that every member of the team may read.

    A task counts when it was created or one of its runs changed at or after `active_after`. A
    conversation that started earlier still counts once a run writes its outcome, because writing a
    run summary also moves the run's `updated_at`.

    A run that carries `analytics_query_context` keeps its summary private, because reading it needs
    the viewer's own access to the queries behind it. A workflow task's summary is readable by its
    creator only. Both come back with a null `summary`, matching the task summaries API for a viewer
    who cannot read them.
    """
    if not task_ids or not origin_products or limit <= 0:
        return []
    last_run_change = (
        TaskRun.objects.filter(team_id=team_id, task_id=OuterRef("pk")).order_by("-updated_at").values("updated_at")[:1]
    )
    tasks = list(
        Task.objects.filter(
            team_id=team_id,
            id__in=list(task_ids),
            origin_product__in=list(origin_products),
            deleted=False,
        )
        .filter(_readable_by_team_q(team_id))
        .annotate(active_at=Coalesce(Subquery(last_run_change), F("created_at")))
        .filter(active_at__gte=active_after)
        .order_by("-active_at", "id")
        .values("id", "created_at", "active_at", "created_by_id", "origin_product", "channel_id")[:limit]
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
                active_at=task["active_at"],
                created_by_id=task["created_by_id"],
                origin_product=task["origin_product"],
                run_status=run["status"] if run is not None else None,
                summary=summary,
                creator_controls_alone=(
                    task["channel_id"] is not None
                    and task["created_by_id"] is not None
                    and task["origin_product"] != Task.OriginProduct.SLACK
                ),
            )
        )
    return summaries
