import json
import time
import random
import asyncio
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID

from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.tasks.backend.facade.profiles import find_task_profile
from products.tasks.backend.models import ENDED_BY_STALE_SWEEP_STATE_KEY, LIVE_RUN_STALE_AFTER, Task, TaskRun
from products.tasks.backend.task_done import wake_refusal, warm_done_mode

logger = structlog.get_logger(__name__)

STALE_RUN_GRACE = timedelta(minutes=15)
STARTUP_ALLOWANCE = timedelta(hours=1)
SWEEP_FLAG = "tasks-stale-run-sweep"
SWEEP_MODE_CACHE_SECONDS = 60
NO_PROFILE = "none"
SWEEP_MODE_LOOKUP_BUDGET_SECONDS = 20
MAX_SWEEPS_PER_PASS = 100
WORKFLOW_LOOKUP_TIMEOUT = timedelta(seconds=10)
_LIVE_RUN_STATUSES = (TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)
_UNRESOLVED_SWEEP_MODE = "unresolved"


class StaleRule(StrEnum):
    HEARTBEAT = "heartbeat"
    NO_WRITES_24H = "no_writes_24h"


class SweepMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


class ReopenOutcome(StrEnum):
    REOPENED = "reopened"
    MODE_UNKNOWN = "mode_unknown"
    STILL_ENFORCED = "still_enforced"
    WORKFLOW_GONE = "workflow_gone"
    MOVED_ON = "moved_on"


@frozen
class StaleRunCount:
    profile: str | None
    environment: str
    rule: StaleRule
    count: int


@frozen
class RunToSweep:
    run_id: UUID
    workflow_id: str
    profile: str
    rule: StaleRule
    quiet_since: datetime
    not_written_since: datetime


@frozen
class _LiveRun:
    run_id: UUID
    workflow_id: str
    team_id: int
    profile: str | None
    environment: str
    status: str
    rules: frozenset[StaleRule]
    quiet_since: datetime
    not_written_since: datetime


def stale_rules(
    *,
    environment: str,
    last_heartbeat_at: datetime | None,
    queued_at: datetime | None,
    created_at: datetime,
    updated_at: datetime,
    idle_timeout: timedelta,
    now: datetime,
) -> frozenset[StaleRule]:
    rules: set[StaleRule] = set()
    last_sign_of_life = max(at for at in (last_heartbeat_at, queued_at, created_at, updated_at) if at is not None)
    if now - last_sign_of_life > idle_timeout + STALE_RUN_GRACE:
        rules.add(StaleRule.HEARTBEAT)
    if environment == TaskRun.Environment.CLOUD and now - updated_at > LIVE_RUN_STALE_AFTER:
        rules.add(StaleRule.NO_WRITES_24H)
    return frozenset(rules)


def quiet_since_q(cutoff: datetime) -> Q:
    return (
        (Q(last_heartbeat_at__lt=cutoff) | Q(last_heartbeat_at__isnull=True))
        & (Q(queued_at__lt=cutoff) | Q(queued_at__isnull=True))
        & Q(created_at__lt=cutoff)
        & Q(updated_at__lt=cutoff)
    )


def sweep_mode(profile_key: str | None, team: Team) -> SweepMode:
    return flag_mode(SWEEP_FLAG, profile_key, team)


def flag_mode(flag: str, profile_key: str | None, team: Team) -> SweepMode:
    profile_key = profile_key or NO_PROFILE
    key = f"tasks:{flag}:{team.id}:{profile_key}"
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return SweepMode.OFF if cached == _UNRESOLVED_SWEEP_MODE else SweepMode(cached)
    mode = _resolve_mode(flag, profile_key, team)
    try:
        cache.set(key, _UNRESOLVED_SWEEP_MODE if mode is None else mode.value, SWEEP_MODE_CACHE_SECONDS)
    except Exception:
        logger.warning("task_flag_mode_cache_failed", flag=flag, profile=profile_key, team_id=team.id, exc_info=True)
    return mode or SweepMode.OFF


def _flag_lookup(team: Team) -> dict[str, Any]:
    organization_id = str(team.organization_id)
    return {
        "distinct_id": str(team.uuid),
        "groups": {"organization": organization_id},
        "group_properties": {"organization": {"id": organization_id}},
        "only_evaluate_locally": False,
        "send_feature_flag_events": False,
    }


def _mode_in(payload: object, profile_key: str) -> SweepMode | None:
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        return None
    try:
        return SweepMode(str(payload.get(profile_key, SweepMode.OFF)))
    except ValueError:
        return SweepMode.OFF


def _resolve_mode(flag: str, profile_key: str, team: Team) -> SweepMode | None:
    try:
        return _mode_in(posthoganalytics.get_feature_flag_payload(flag, **_flag_lookup(team)), profile_key)
    except Exception:
        logger.warning("task_flag_mode_unresolved", flag=flag, profile=profile_key, team_id=team.id, exc_info=True)
        return None


def _confirmed_sweep_mode(profile_key: str, team: Team) -> SweepMode | None:
    try:
        result = posthoganalytics.get_feature_flag_result(SWEEP_FLAG, **_flag_lookup(team))
        if result is None:
            return None
        return (_mode_in(result.payload, profile_key) if result.enabled else None) or SweepMode.OFF
    except Exception:
        logger.warning(
            "task_flag_mode_unresolved", flag=SWEEP_FLAG, profile=profile_key, team_id=team.id, exc_info=True
        )
        return None


def _idle_timeout(profile_key: str | None, origin_product: str | None, run_timeout_seconds: object) -> timedelta:
    from products.tasks.backend.temporal.constants import resolve_inactivity_timeout

    profile = find_task_profile(profile_key)
    return resolve_inactivity_timeout(
        is_user_origin=Task.is_user_origin(origin_product),
        origin_product=origin_product,
        state={"inactivity_timeout_seconds": run_timeout_seconds},
        profile_idle_minutes=profile.idle_minutes if profile else None,
    )


def _live_runs(*, sweepable_only: bool = False) -> Iterator[_LiveRun]:
    now = timezone.now()
    live = TaskRun.objects.filter(status__in=_LIVE_RUN_STATUSES)
    if sweepable_only:
        live = live.filter(environment=TaskRun.Environment.CLOUD, status=TaskRun.Status.IN_PROGRESS)
    runs = (
        live.order_by()
        .values_list(
            "id",
            "team_id",
            "task__profile",
            "origin_product",
            "environment",
            "status",
            "state__inactivity_timeout_seconds",
            "state__workflow_id",
            "task_id",
            "agent_status",
            "last_heartbeat_at",
            "queued_at",
            "created_at",
            "updated_at",
        )
        .iterator(chunk_size=2000)
    )
    for (
        run_id,
        team_id,
        profile_key,
        origin_product,
        environment,
        status,
        run_timeout_seconds,
        persisted_workflow_id,
        task_id,
        agent_status,
        last_heartbeat_at,
        queued_at,
        created_at,
        updated_at,
    ) in runs:
        idle_timeout = _idle_timeout(profile_key, origin_product, run_timeout_seconds)
        if (
            environment == TaskRun.Environment.CLOUD
            and status == TaskRun.Status.IN_PROGRESS
            and agent_status in (None, TaskRun.AgentStatus.STARTING)
        ):
            idle_timeout = max(idle_timeout, STARTUP_ALLOWANCE)
        yield _LiveRun(
            run_id=run_id,
            workflow_id=persisted_workflow_id or TaskRun.get_workflow_id(task_id, run_id),
            team_id=team_id,
            profile=profile_key,
            environment=environment,
            status=status,
            rules=stale_rules(
                environment=environment,
                last_heartbeat_at=last_heartbeat_at,
                queued_at=queued_at,
                created_at=created_at,
                updated_at=updated_at,
                idle_timeout=idle_timeout,
                now=now,
            ),
            quiet_since=now - idle_timeout - STALE_RUN_GRACE,
            not_written_since=now - LIVE_RUN_STALE_AFTER,
        )


def collect_stale_live_runs() -> list[StaleRunCount]:
    counts: Counter[tuple[str | None, str, StaleRule]] = Counter()
    for run in _live_runs():
        for rule in run.rules:
            counts[(run.profile, run.environment, rule)] += 1
    return [
        StaleRunCount(profile=profile_key, environment=environment, rule=rule, count=count)
        for (profile_key, environment, rule), count in counts.items()
    ]


def modes_for(flag: str, pairs: set[tuple[int, str | None]]) -> dict[tuple[int, str | None], SweepMode]:
    teams = Team.objects.only("id", "uuid", "organization_id").in_bulk({team_id for team_id, _ in pairs})
    ordered = list(pairs)
    random.shuffle(ordered)
    deadline = time.monotonic() + SWEEP_MODE_LOOKUP_BUDGET_SECONDS
    modes: dict[tuple[int, str | None], SweepMode] = {}
    for position, (team_id, profile) in enumerate(ordered):
        if time.monotonic() > deadline:
            logger.warning("task_flag_mode_budget_spent", flag=flag, left_for_next_pass=len(ordered) - position)
            break
        team = teams.get(team_id)
        if team is not None:
            modes[(team_id, profile)] = flag_mode(flag, profile, team)
    return modes


def runs_to_sweep() -> list[RunToSweep]:
    stale = [run for run in _live_runs(sweepable_only=True) if run.rules]
    if not stale:
        return []
    modes = modes_for(SWEEP_FLAG, {(run.team_id, run.profile) for run in stale})
    to_sweep = [
        RunToSweep(
            run_id=run.run_id,
            workflow_id=run.workflow_id,
            profile=run.profile or NO_PROFILE,
            rule=StaleRule.NO_WRITES_24H if StaleRule.NO_WRITES_24H in run.rules else StaleRule.HEARTBEAT,
            quiet_since=run.quiet_since,
            not_written_since=run.not_written_since,
        )
        for run in stale
        if modes.get((run.team_id, run.profile)) == SweepMode.ENFORCE
    ]
    if len(to_sweep) > MAX_SWEEPS_PER_PASS:
        logger.warning("task_stale_sweep_pass_capped", left_for_next_pass=len(to_sweep) - MAX_SWEEPS_PER_PASS)
    return to_sweep[:MAX_SWEEPS_PER_PASS]


def _is_still_the_run_to_reopen(task: Task, run: TaskRun) -> bool:
    return (
        run.matches_task_ownership(task)
        and wake_refusal(task, source="sweep_undo") is None
        and not TaskRun.objects.filter(task_id=task.id, team_id=task.team_id, created_at__gt=run.created_at).exists()
        and not task.live_cloud_run_ids(exclude_run_id=run.id)
    )


def reopen_swept_run(run_id: UUID, task_id: UUID, team_id: int, *, dry_run: bool = False) -> bool:
    unlocked_task = Task.objects.filter(pk=task_id, team_id=team_id).only("id", "team_id", "profile", "status").first()
    if unlocked_task is not None:
        warm_done_mode(unlocked_task)
    with transaction.atomic():
        task = Task.objects.select_for_update().filter(pk=task_id, team_id=team_id, deleted=False).first()
        if task is None:
            return False
        run = (
            TaskRun.objects.select_for_update()
            .filter(
                id=run_id,
                team_id=team_id,
                status=TaskRun.Status.FAILED,
                state__has_key=ENDED_BY_STALE_SWEEP_STATE_KEY,
            )
            .first()
        )
        if run is None or not _is_still_the_run_to_reopen(task, run):
            return False
        if dry_run:
            return True
        run.status = TaskRun.Status.IN_PROGRESS
        run.error_message = None
        run.completed_at = None
        run.state.pop(ENDED_BY_STALE_SWEEP_STATE_KEY)
        run.save(update_fields=["status", "error_message", "completed_at", "state", "updated_at"])
    return True


def reopen_swept_runs(
    *, profile: str, hours: int, team_id: int | None, check_workflows: bool, dry_run: bool
) -> Iterator[ReopenOutcome]:
    swept = TaskRun.objects.filter(
        status=TaskRun.Status.FAILED,
        environment=TaskRun.Environment.CLOUD,
        state__has_key=ENDED_BY_STALE_SWEEP_STATE_KEY,
        completed_at__gte=timezone.now() - timedelta(hours=hours),
        task__profile=None if profile == NO_PROFILE else profile,
    )
    if team_id is not None:
        swept = swept.filter(team_id=team_id)
    runs = list(swept.order_by("id").values_list("id", "team_id", "task_id", "state__workflow_id"))
    teams = Team.objects.only("id", "uuid", "organization_id").in_bulk({run_team_id for _, run_team_id, _, _ in runs})
    modes: dict[int, SweepMode | None] = {}
    workflows = WorkflowLiveness()
    for run_id, run_team_id, task_id, persisted_workflow_id in runs:
        workflow_id = persisted_workflow_id or TaskRun.get_workflow_id(task_id, run_id)
        if run_team_id not in modes:
            modes[run_team_id] = _confirmed_sweep_mode(profile, teams[run_team_id])
        mode = modes[run_team_id]
        if mode is None:
            yield ReopenOutcome.MODE_UNKNOWN
        elif mode == SweepMode.ENFORCE:
            yield ReopenOutcome.STILL_ENFORCED
        elif check_workflows and not workflows.is_running(workflow_id):
            yield ReopenOutcome.WORKFLOW_GONE
        elif reopen_swept_run(run_id, task_id, run_team_id, dry_run=dry_run):
            yield ReopenOutcome.REOPENED
        else:
            yield ReopenOutcome.MOVED_ON


class WorkflowLiveness:
    def __init__(self) -> None:
        self._client: Any = None
        self._unknown = False

    def is_running(self, workflow_id: str) -> bool:
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.service import RPCError, RPCStatusCode

        from posthog.temporal.common.client import sync_connect

        if self._unknown:
            return True
        try:
            if self._client is None:
                self._client = sync_connect()
            handle = self._client.get_workflow_handle(workflow_id)
            description = asyncio.run(handle.describe(rpc_timeout=WORKFLOW_LOOKUP_TIMEOUT))
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                return False
            self._unknown = True
            raise
        except Exception:
            self._unknown = True
            raise
        return description.status == WorkflowExecutionStatus.RUNNING
