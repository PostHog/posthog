from typing import Literal
from uuid import UUID

from django.db import transaction

import structlog

from products.tasks.backend.metrics import observe_task_wake_refused
from products.tasks.backend.models import Task, TaskStatusChange
from products.tasks.backend.pr_urls import canonical_github_pull_request_url
from products.tasks.backend.task_run_sync import SHADOW_ACTOR_PREFIX, DoneMode, done_mode, keeps_done, mark_done
from products.tasks.backend.visibility import task_control_q

logger = structlog.get_logger(__name__)

GITHUB_ACTOR = "github"

CloseTaskOutcome = Literal["closed", "not_found", "not_idle", "not_enabled"]


class TaskDoneError(ValueError):
    def __init__(self) -> None:
        super().__init__("This task is done. Start a new task to keep working on it.")


def _latest_change_is_shadow_done(task: Task) -> bool:
    latest = (
        TaskStatusChange.objects.for_team(task.team_id, canonical=True)
        .filter(task_id=task.id)
        .order_by("-created_at", "-id")
        .values_list("status", "changed_by")
        .first()
    )
    return latest is not None and latest[0] == Task.Status.DONE and latest[1].startswith(SHADOW_ACTOR_PREFIX)


def wake_refusal(task: Task, *, source: str) -> TaskDoneError | None:
    profile = task.profile or "none"
    if task.status == Task.Status.DONE:
        if not keeps_done(done_mode(task.profile, task.team_id)):
            return None
        observe_task_wake_refused(profile=profile, source=source, mode=DoneMode.ENFORCE)
        logger.info("task_wake_refused", task_id=str(task.id), profile=profile, source=source)
        return TaskDoneError()
    if task.profile and _latest_change_is_shadow_done(task):
        observe_task_wake_refused(profile=profile, source=source, mode=DoneMode.SHADOW)
        logger.info("task_wake_would_refuse", task_id=str(task.id), profile=profile, source=source)
    return None


def check_wake(task: Task, *, source: str) -> None:
    if (error := wake_refusal(task, source=source)) is not None:
        raise error


def check_wake_by_task_id(task_id: UUID | str, *, source: str) -> None:
    task = Task.objects.only("id", "team_id", "profile", "status").filter(pk=task_id).first()
    if task is not None:
        check_wake(task, source=source)


def close_task(task_id: UUID | str, team_id: int, user_id: int) -> CloseTaskOutcome:
    task = (
        Task.objects.filter(task_control_q(user_id), id=task_id, team_id=team_id, deleted=False)
        .only("id", "team_id", "profile", "status")
        .first()
    )
    if task is None:
        return "not_found"
    if done_mode(task.profile, task.team_id) != DoneMode.ENFORCE:
        return "not_enabled"
    closed = mark_done(task.id, reason=Task.StatusReason.CLOSED, actor=f"user:{user_id}", expected=Task.Status.IDLE)
    return "closed" if closed else "not_idle"


def _canonical(url: str) -> str:
    return canonical_github_pull_request_url(url) or url


def record_pull_request_outcome(
    task_id: UUID | str, pr_url: str, *, state: Literal["merged", "closed", "open"]
) -> None:
    url = _canonical(pr_url)
    with transaction.atomic():
        row = (
            Task.objects.select_for_update(no_key=True)
            .filter(pk=task_id)
            .values_list("pr_urls", "merged_pr_urls", "closed_pr_urls")
            .first()
        )
        if row is None:
            return
        pr_urls, merged_urls, closed_urls = ({_canonical(value) for value in urls} for urls in row)
        if url not in pr_urls:
            return
        merged = (merged_urls | {url}) if state == "merged" else merged_urls - {url}
        closed = (closed_urls | {url}) if state == "closed" else closed_urls - {url}
        if (merged, closed) != (merged_urls, closed_urls):
            Task.objects.filter(pk=task_id).update(merged_pr_urls=sorted(merged), closed_pr_urls=sorted(closed))
    if pr_urls <= merged | closed:
        reason = Task.StatusReason.FINISHED if merged else Task.StatusReason.CLOSED
        mark_done(task_id, reason=reason, actor=GITHUB_ACTOR)
