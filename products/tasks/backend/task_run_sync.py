import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime
from enum import StrEnum
from itertools import batched
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q, Value
from django.db.models.functions import Coalesce
from django.db.models.signals import post_save
from django.dispatch import receiver

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.tasks.backend.constants import STOPPED_BEFORE_TURN_CLOSED_STATE_KEY
from products.tasks.backend.facade.profiles import find_task_profile
from products.tasks.backend.metrics import observe_task_done, observe_task_status_outside_transitions
from products.tasks.backend.models import TASK_RUN_FINISH_REPORT_STATE_KEY, Task, TaskRun, TaskStatusChange

logger = structlog.get_logger(__name__)

TRANSITIONS: dict[str, frozenset[str]] = {
    Task.Status.QUEUED: frozenset({Task.Status.RUNNING, Task.Status.IDLE, Task.Status.DONE}),
    Task.Status.RUNNING: frozenset({Task.Status.IDLE, Task.Status.DONE}),
    Task.Status.IDLE: frozenset({Task.Status.QUEUED, Task.Status.DONE}),
    Task.Status.DONE: frozenset(),
}
_SEEN_WHEN_A_RUN_STARTS_BEFORE_ITS_FIRST_SYNC: dict[str, frozenset[str]] = {
    Task.Status.IDLE: frozenset({Task.Status.RUNNING}),
}

_DONE_ONLY_REASONS: frozenset[str | None] = frozenset(
    {Task.StatusReason.FINISHED, Task.StatusReason.CLOSED, Task.StatusReason.CANCELLED}
)
REASONS: dict[str, frozenset[str | None]] = {
    Task.Status.QUEUED: frozenset({None}),
    Task.Status.RUNNING: frozenset({None}),
    Task.Status.IDLE: frozenset({None, *Task.StatusReason}) - _DONE_ONLY_REASONS,
    Task.Status.DONE: _DONE_ONLY_REASONS,
}

RUN_SYNC_ACTOR = "task_run"
BACKFILL_ACTOR = "backfill"
STATUS_REPAIR_ACTOR = "status_repair"
REOPEN_ACTOR = "reopen"
SHADOW_ACTOR_PREFIX = "shadow:"
DONE_FLAG = "tasks-task-done"
DONE_MODE_CACHE_SECONDS = 60
_UNRESOLVED_DONE_MODE = "unresolved"

_DERIVED_FROM_RUN_FIELDS = frozenset({"status", "scheduled_at", "error_message"})
_LIVE_TASK_STATUSES = (Task.Status.QUEUED, Task.Status.RUNNING)
_OPEN_RUN_STATUSES = (TaskRun.Status.NOT_STARTED, TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)
_QUERY_CHUNK = 1000
MAX_REPAIRS_PER_PASS = 500


class DoneMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


@frozen
class LatestRun:
    id: UUID
    status: str
    scheduled_at: datetime | None
    error_message: str | None
    finish_report_saved: bool = False
    stopped_before_turn_closed: bool = False


@frozen
class TaskStatusValue:
    status: str
    reason: str | None = None
    detail: str | None = None


_TURN_CLOSED = TaskStatusValue(status=Task.Status.IDLE, reason=Task.StatusReason.TURN_CLOSED)


@frozen
class StoredTaskStatus:
    team_id: int
    profile: str | None
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
            .values_list(
                "task_id",
                "id",
                "status",
                "scheduled_at",
                "error_message",
                f"state__{TASK_RUN_FINISH_REPORT_STATE_KEY}",
                f"state__{STOPPED_BEFORE_TURN_CLOSED_STATE_KEY}",
            )
        )
        for task_id, run_id, status, scheduled_at, error_message, finish_report_saved, stopped_early in rows:
            runs[task_id] = LatestRun(
                id=run_id,
                status=status,
                scheduled_at=scheduled_at,
                error_message=error_message,
                finish_report_saved=finish_report_saved is True,
                stopped_before_turn_closed=stopped_early is True,
            )
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
    row = tasks.values_list("team_id", "profile", "status", "status_reason", "status_detail").first()
    if row is None:
        return None
    team_id, profile, status, reason, detail = row
    value = None if status is None else TaskStatusValue(status=status, reason=reason, detail=detail)
    return StoredTaskStatus(team_id=team_id, profile=profile, value=value)


def _latest_run(task_id: UUID | str) -> LatestRun | None:
    return latest_runs([task_id]).get(UUID(str(task_id)))


def _legacy_columns(task_id: UUID | str) -> dict[str, Any]:
    key = UUID(str(task_id))
    columns: dict[str, Any] = {"pr_urls": pr_urls_from_runs([key]).get(key, [])}
    if branch := head_branches_from_runs([key]).get(key):
        columns["head_branch"] = Coalesce("head_branch", Value(branch))
    return columns


def done_mode(profile_key: str | None, team_id: int) -> DoneMode | None:
    if not profile_key:
        return DoneMode.OFF
    key = f"tasks:done_mode:{team_id}:{profile_key}"
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return None if cached == _UNRESOLVED_DONE_MODE else DoneMode(cached)
    mode = _resolve_done_mode(profile_key, team_id)
    try:
        cache.set(key, _UNRESOLVED_DONE_MODE if mode is None else mode.value, DONE_MODE_CACHE_SECONDS)
    except Exception:
        logger.warning("task_done_mode_cache_failed", profile=profile_key, team_id=team_id, exc_info=True)
    return mode


def _resolve_done_mode(profile_key: str, team_id: int) -> DoneMode | None:
    try:
        team = Team.objects.only("uuid", "organization_id").get(pk=team_id)
        organization_id = str(team.organization_id)
        payload = posthoganalytics.get_feature_flag_payload(
            DONE_FLAG,
            distinct_id=str(team.uuid),
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
    except Exception:
        logger.warning("task_done_mode_unresolved", profile=profile_key, team_id=team_id, exc_info=True)
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return DoneMode(str(payload.get(profile_key, DoneMode.OFF)))
    except ValueError:
        return DoneMode.OFF


def keeps_done(mode: DoneMode | None) -> bool:
    return mode != DoneMode.OFF


def latest_change_is_shadow_done(team_id: int, task_id: UUID | str) -> bool:
    latest = (
        TaskStatusChange.objects.for_team(team_id, canonical=True)
        .filter(task_id=task_id)
        .order_by("-created_at", "-id")
        .values_list("status", "changed_by")
        .first()
    )
    return latest is not None and latest[0] == Task.Status.DONE and latest[1].startswith(SHADOW_ACTOR_PREFIX)


def _record_change(
    team_id: int, task_id: UUID | str, value: TaskStatusValue, *, run_id: UUID | None, changed_by: str
) -> None:
    TaskStatusChange.objects.for_team(team_id, canonical=True).create(
        team_id=team_id,
        task_id=task_id,
        run_id=run_id,
        status=value.status,
        reason=value.reason,
        detail=value.detail,
        changed_by=changed_by,
    )


def _write_status(
    stored: StoredTaskStatus,
    task_id: UUID | str,
    value: TaskStatusValue,
    *,
    run_id: UUID | None,
    changed_by: str,
    extra_columns: dict[str, Any] | None = None,
) -> None:
    Task.objects.filter(pk=task_id).update(
        status=value.status,
        status_reason=value.reason,
        status_detail=value.detail,
        status_changed_by=changed_by,
        **(extra_columns or {}),
    )
    _record_change(stored.team_id, task_id, value, run_id=run_id, changed_by=changed_by)


def transition(
    task_id: UUID | str,
    to: str,
    *,
    reason: str | None,
    actor: str,
    detail: str | None = None,
    expected: str | None = None,
    run_id: UUID | None = None,
    only_if: Q | None = None,
) -> bool:
    if reason not in REASONS[to]:
        raise ValueError(f"{reason} is not a reason for {to}")
    with transaction.atomic():
        stored = _stored_task_status(task_id, lock=True)
        if stored is None or stored.value is None or to not in TRANSITIONS[stored.value.status]:
            return False
        if expected is not None and stored.value.status != expected:
            return False
        if only_if is not None and not Task.objects.filter(only_if, pk=task_id).exists():
            return False
        if run_id is not None and (latest := _latest_run(task_id)) is not None and latest.id != run_id:
            return False
        _write_status(
            stored, task_id, TaskStatusValue(status=to, reason=reason, detail=detail), run_id=run_id, changed_by=actor
        )
    return True


def mark_done(
    task_id: UUID | str,
    *,
    reason: str,
    actor: str,
    run_id: UUID | None = None,
    expected: str | None = None,
    only_if: Q | None = None,
) -> bool:
    stored = _stored_task_status(task_id, lock=False)
    if stored is None or stored.value is None:
        return False
    mode = done_mode(stored.profile, stored.team_id)
    if mode is None or mode == DoneMode.OFF:
        return False
    profile = stored.profile or "none"
    if mode == DoneMode.SHADOW:
        current = stored.value.status
        if Task.Status.DONE not in TRANSITIONS[current] or (expected is not None and current != expected):
            return False
        if only_if is not None and not Task.objects.filter(only_if, pk=task_id).exists():
            return False
        if latest_change_is_shadow_done(stored.team_id, task_id):
            return False
        _record_change(
            stored.team_id,
            task_id,
            TaskStatusValue(status=Task.Status.DONE, reason=reason),
            run_id=run_id,
            changed_by=f"{SHADOW_ACTOR_PREFIX}{actor}",
        )
        observe_task_done(profile=profile, reason=reason, mode=mode)
        logger.info("task_would_mark_done", task_id=str(task_id), profile=stored.profile, reason=reason, actor=actor)
        return False
    moved = transition(
        task_id, Task.Status.DONE, reason=reason, actor=actor, run_id=run_id, expected=expected, only_if=only_if
    )
    if moved:
        observe_task_done(profile=profile, reason=reason, mode=mode)
    return moved


def _done_on_turn_close(profile_key: str | None, run: LatestRun) -> bool:
    profile = find_task_profile(profile_key)
    if profile is None:
        return False
    if profile.finish_tool and run.finish_report_saved:
        return True
    return profile.done_on_turn_close and not run.stopped_before_turn_closed


def _keeps_stored_done(stored: StoredTaskStatus) -> bool:
    return (
        stored.value is not None
        and stored.value.status == Task.Status.DONE
        and keeps_done(done_mode(stored.profile, stored.team_id))
    )


def reopen_done_task(task_id: UUID | str) -> bool:
    with transaction.atomic():
        stored = _stored_task_status(task_id, lock=True)
        if stored is None or stored.value is None or stored.value.status != Task.Status.DONE:
            return False
        run = _latest_run(task_id)
        _write_status(stored, task_id, derive_task_status(run), run_id=run.id if run else None, changed_by=REOPEN_ACTOR)
    return True


def sync_task_status(task_id: UUID | str, *, changed_by: str = RUN_SYNC_ACTOR) -> bool:
    stored = _stored_task_status(task_id, lock=False)
    if stored is None or stored.value == derive_task_status(_latest_run(task_id)):
        return False
    if _keeps_stored_done(stored):
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
        if _keeps_stored_done(stored):
            return False
        if previous is not None and derived.status not in {
            previous.status,
            *TRANSITIONS[previous.status],
            *_SEEN_WHEN_A_RUN_STARTS_BEFORE_ITS_FIRST_SYNC.get(previous.status, ()),
        }:
            observe_task_status_outside_transitions(from_status=previous.status, to_status=derived.status)
        _write_status(
            stored,
            task_id,
            derived,
            run_id=run.id if run else None,
            changed_by=changed_by,
            extra_columns=_legacy_columns(task_id) if previous is None else None,
        )
    if run is not None and derived == _TURN_CLOSED and _done_on_turn_close(stored.profile, run):
        mark_done(
            task_id, reason=Task.StatusReason.FINISHED, actor=changed_by, run_id=run.id, expected=Task.Status.IDLE
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


@frozen
class _TaskStatusMismatch:
    task_id: UUID
    stored_status: str | None
    derived_status: str


def _mismatches(limit: int) -> list[_TaskStatusMismatch]:
    stored, runs = _scan_candidates(limit)
    return [
        _TaskStatusMismatch(task_id=task_id, stored_status=status, derived_status=derived)
        for task_id, status in stored.items()
        if status != Task.Status.DONE and status != (derived := derive_task_status(runs.get(task_id)).status)
    ]


def collect_status_mismatches(*, limit: int = 10_000) -> list[StatusMismatch]:
    counts = Counter((mismatch.stored_status, mismatch.derived_status) for mismatch in _mismatches(limit))
    return [
        StatusMismatch(stored_status=status, derived_status=derived, count=count)
        for (status, derived), count in sorted(counts.items(), key=lambda item: (item[0][0] or "", item[0][1]))
    ]


def repair_status_mismatches(
    *, scan_limit: int = 10_000, max_repairs: int = MAX_REPAIRS_PER_PASS
) -> list[StatusMismatch]:
    counts: Counter[tuple[str | None, str]] = Counter()
    for mismatch in _mismatches(scan_limit)[:max_repairs]:
        try:
            repaired = sync_task_status(mismatch.task_id, changed_by=STATUS_REPAIR_ACTOR)
        except Exception:
            logger.exception("task_status_repair_failed", task_id=str(mismatch.task_id))
            continue
        if repaired:
            counts[(mismatch.stored_status, mismatch.derived_status)] += 1
    return [
        StatusMismatch(stored_status=status, derived_status=derived, count=count)
        for (status, derived), count in sorted(counts.items(), key=lambda item: (item[0][0] or "", item[0][1]))
    ]
