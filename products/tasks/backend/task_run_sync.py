from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from itertools import batched
from typing import Any
from uuid import UUID

from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Coalesce
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog

from posthog.dataclasses import frozen

from products.tasks.backend.metrics import observe_task_status_outside_transitions
from products.tasks.backend.models import Task, TaskRun, TaskStatusChange

logger = structlog.get_logger(__name__)

TRANSITIONS: dict[str, frozenset[str]] = {
    Task.Status.QUEUED: frozenset({Task.Status.RUNNING, Task.Status.IDLE, Task.Status.DONE}),
    Task.Status.RUNNING: frozenset({Task.Status.IDLE, Task.Status.DONE}),
    Task.Status.IDLE: frozenset({Task.Status.QUEUED, Task.Status.DONE}),
    Task.Status.DONE: frozenset(),
}

RUN_SYNC_ACTOR = "task_run"
BACKFILL_ACTOR = "backfill"
STATUS_REPAIR_ACTOR = "status_repair"

_DERIVED_FROM_RUN_FIELDS = frozenset({"status", "scheduled_at", "error_message"})
_LIVE_TASK_STATUSES = (Task.Status.QUEUED, Task.Status.RUNNING)
_OPEN_RUN_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)
_QUERY_CHUNK = 1000
MAX_REPAIRS_PER_PASS = 500


@frozen
class LatestRun:
    id: UUID
    status: str
    scheduled_at: datetime | None
    error_message: str | None


@frozen
class TaskStatusValue:
    status: str
    reason: str | None = None
    detail: str | None = None


@frozen
class StoredTaskStatus:
    team_id: int
    value: TaskStatusValue | None


@frozen
class StatusMismatch:
    stored_status: str | None
    derived_status: str
    count: int


def derive_task_status(run: LatestRun | None) -> TaskStatusValue:
    if run is None:
        return TaskStatusValue(status=Task.Status.IDLE)
    match run.status:
        case TaskRun.Status.NOT_STARTED:
            return TaskStatusValue(status=Task.Status.QUEUED if run.scheduled_at is None else Task.Status.IDLE)
        case TaskRun.Status.QUEUED:
            return TaskStatusValue(status=Task.Status.QUEUED)
        case TaskRun.Status.IN_PROGRESS:
            return TaskStatusValue(status=Task.Status.RUNNING)
        case TaskRun.Status.COMPLETED:
            return TaskStatusValue(status=Task.Status.IDLE, reason=Task.StatusReason.TURN_CLOSED)
        case TaskRun.Status.FAILED:
            return TaskStatusValue(
                status=Task.Status.IDLE, reason=Task.StatusReason.UNEXPECTED_FAILURE, detail=run.error_message
            )
        case _:
            return TaskStatusValue(status=Task.Status.IDLE, reason=Task.StatusReason.USER_STOPPED)


def _chunks(task_ids: Iterable[UUID | str]) -> Iterator[tuple[UUID | str, ...]]:
    return batched(dict.fromkeys(task_ids), _QUERY_CHUNK, strict=False)


def latest_runs(task_ids: Iterable[UUID | str]) -> dict[UUID, LatestRun]:
    runs: dict[UUID, LatestRun] = {}
    for chunk in _chunks(task_ids):
        rows = (
            TaskRun.objects.filter(task_id__in=chunk)
            .order_by("task_id", "-created_at", "-id")
            .distinct("task_id")
            .values_list("task_id", "id", "status", "scheduled_at", "error_message")
        )
        for task_id, run_id, status, scheduled_at, error_message in rows:
            runs[task_id] = LatestRun(id=run_id, status=status, scheduled_at=scheduled_at, error_message=error_message)
    return runs


def pr_urls_from_runs(task_ids: Iterable[UUID | str]) -> dict[UUID, list[str]]:
    found: dict[UUID, set[str]] = {}
    for chunk in _chunks(task_ids):
        rows = (
            TaskRun.objects.filter(task_id__in=chunk, state__has_key="verified_pr_urls")
            .order_by()
            .values_list("task_id", "state__verified_pr_urls")
        )
        for task_id, verified in rows:
            if isinstance(verified, list):
                found.setdefault(task_id, set()).update(url for url in verified if isinstance(url, str))
    return {task_id: sorted(urls) for task_id, urls in found.items()}


def head_branches_from_runs(task_ids: Iterable[UUID | str]) -> dict[UUID, str]:
    branches: dict[UUID, str] = {}
    for chunk in _chunks(task_ids):
        rows = (
            TaskRun.objects.filter(task_id__in=chunk)
            .filter(Q(state__has_key="wizard_head_branch") | Q(state__has_key="self_driving_head_branch"))
            .order_by("task_id", "-created_at", "-id")
            .distinct("task_id")
            .values_list("task_id", "state__wizard_head_branch", "state__self_driving_head_branch")
        )
        for task_id, wizard_branch, self_driving_branch in rows:
            branch = wizard_branch or self_driving_branch
            if isinstance(branch, str) and branch:
                branches[task_id] = branch
    return branches


def _stored_task_status(task_id: UUID | str, *, lock: bool) -> StoredTaskStatus | None:
    tasks = Task.objects.filter(pk=task_id)
    if lock:
        tasks = tasks.select_for_update(no_key=True)
    row = tasks.values_list("team_id", "status", "status_reason", "status_detail").first()
    if row is None:
        return None
    team_id, status, reason, detail = row
    value = None if status is None else TaskStatusValue(status=status, reason=reason, detail=detail)
    return StoredTaskStatus(team_id=team_id, value=value)


def _latest_run(task_id: UUID | str) -> LatestRun | None:
    return latest_runs([task_id]).get(UUID(str(task_id)))


def _legacy_columns(task_id: UUID | str) -> dict[str, Any]:
    key = UUID(str(task_id))
    columns: dict[str, Any] = {"pr_urls": pr_urls_from_runs([key]).get(key, [])}
    if branch := head_branches_from_runs([key]).get(key):
        columns["head_branch"] = Coalesce("head_branch", Value(branch))
    return columns


def sync_task_status(task_id: UUID | str, *, changed_by: str = RUN_SYNC_ACTOR) -> bool:
    stored = _stored_task_status(task_id, lock=False)
    if stored is None or stored.value == derive_task_status(_latest_run(task_id)):
        return False
    with transaction.atomic():
        stored = _stored_task_status(task_id, lock=True)
        if stored is None:
            return False
        run = _latest_run(task_id)
        derived = derive_task_status(run)
        previous = stored.value
        if previous == derived:
            return False
        if previous is not None and derived.status not in {previous.status, *TRANSITIONS[previous.status]}:
            observe_task_status_outside_transitions(from_status=previous.status, to_status=derived.status)
        Task.objects.filter(pk=task_id).update(
            status=derived.status,
            status_reason=derived.reason,
            status_detail=derived.detail,
            status_changed_by=changed_by,
            **(_legacy_columns(task_id) if previous is None else {}),
        )
        TaskStatusChange.objects.for_team(stored.team_id, canonical=True).create(
            team_id=stored.team_id,
            task_id=task_id,
            run_id=run.id if run else None,
            status=derived.status,
            reason=derived.reason,
            detail=derived.detail,
            changed_by=changed_by,
        )
    return True


def sync_task_pr_urls(task_id: UUID | str) -> bool:
    with transaction.atomic():
        stored = (
            Task.objects.select_for_update(no_key=True).filter(pk=task_id).values_list("pr_urls", flat=True).first()
        )
        if stored is None:
            return False
        derived = pr_urls_from_runs([task_id]).get(UUID(str(task_id)), [])
        if list(stored) == derived:
            return False
        Task.objects.filter(pk=task_id).update(pr_urls=derived)
    return True


def _each_on_commit(task_ids: Iterable[UUID | str], sync: Callable[[UUID | str], bool]) -> None:
    pending = list(dict.fromkeys(task_ids))
    if not pending:
        return

    def run_syncs() -> None:
        for task_id in pending:
            sync(task_id)

    transaction.on_commit(run_syncs, robust=True)


def sync_task_statuses_on_commit(task_ids: Iterable[UUID | str]) -> None:
    _each_on_commit(task_ids, sync_task_status)


def sync_task_pr_urls_on_commit(task_id: UUID | str) -> None:
    _each_on_commit([task_id], sync_task_pr_urls)


@receiver(post_save, sender=TaskRun, dispatch_uid="sync_task_status_on_run")
def sync_task_status_on_run(
    sender: type[TaskRun], instance: TaskRun, created: bool, update_fields: frozenset[str] | None = None, **kwargs: Any
) -> None:
    if not created and update_fields is not None and not (_DERIVED_FROM_RUN_FIELDS & set(update_fields)):
        return
    sync_task_statuses_on_commit([instance.task_id])


def _scan_candidates(limit: int) -> tuple[dict[UUID, str | None], dict[UUID, LatestRun]]:
    live_task_ids = list(
        Task.objects.filter(status__in=_LIVE_TASK_STATUSES).order_by().values_list("id", flat=True)[:limit]
    )
    open_run_task_ids = list(
        TaskRun.objects.filter(status__in=_OPEN_RUN_STATUSES)
        .exclude(status=TaskRun.Status.NOT_STARTED, scheduled_at__isnull=False)
        .order_by()
        .values_list("task_id", flat=True)
        .distinct()[:limit]
    )
    if len(live_task_ids) == limit or len(open_run_task_ids) == limit:
        logger.warning("task_status_shadow_scan_truncated", limit=limit)
    candidates = {*live_task_ids, *open_run_task_ids}
    stored: dict[UUID, str | None] = {}
    for chunk in _chunks(candidates):
        stored.update(Task.objects.filter(id__in=chunk).values_list("id", "status"))
    return stored, latest_runs(stored)


def collect_status_mismatches(*, limit: int = 10_000) -> list[StatusMismatch]:
    stored, runs = _scan_candidates(limit)
    counts = Counter(
        (status, derived)
        for task_id, status in stored.items()
        if status != (derived := derive_task_status(runs.get(task_id)).status)
    )
    return [
        StatusMismatch(stored_status=status, derived_status=derived, count=count)
        for (status, derived), count in sorted(counts.items(), key=lambda item: (item[0][0] or "", item[0][1]))
    ]


def repair_status_mismatches(
    *, scan_limit: int = 10_000, max_repairs: int = MAX_REPAIRS_PER_PASS
) -> list[StatusMismatch]:
    stored, runs = _scan_candidates(scan_limit)
    mismatched = [
        (task_id, status, derived)
        for task_id, status in stored.items()
        if status != (derived := derive_task_status(runs.get(task_id)).status)
    ]
    counts: Counter[tuple[str | None, str]] = Counter()
    for task_id, status, derived in mismatched[:max_repairs]:
        try:
            repaired = sync_task_status(task_id, changed_by=STATUS_REPAIR_ACTOR)
        except Exception:
            logger.exception("task_status_repair_failed", task_id=str(task_id))
            continue
        if repaired:
            counts[(status, derived)] += 1
    return [
        StatusMismatch(stored_status=status, derived_status=derived, count=count)
        for (status, derived), count in sorted(counts.items(), key=lambda item: (item[0][0] or "", item[0][1]))
    ]
