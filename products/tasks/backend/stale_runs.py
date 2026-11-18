import json
from collections import Counter
from collections.abc import Iterator
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.models.team.team import Team

from products.tasks.backend.facade.profiles import find_task_profile
from products.tasks.backend.models import LIVE_RUN_STALE_AFTER, Task, TaskRun

logger = structlog.get_logger(__name__)

STALE_RUN_GRACE = timedelta(minutes=15)
SWEEP_FLAG = "tasks-stale-run-sweep"
SWEEP_MODE_CACHE_SECONDS = 60
_LIVE_RUN_STATUSES = (TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)
_UNRESOLVED_SWEEP_MODE = "unresolved"


class StaleRule(StrEnum):
    HEARTBEAT = "heartbeat"
    NO_WRITES_24H = "no_writes_24h"


class SweepMode(StrEnum):
    OFF = "off"
    SHADOW = "shadow"
    ENFORCE = "enforce"


@frozen
class StaleRunCount:
    profile: str | None
    environment: str
    rule: StaleRule
    count: int


@frozen
class RunToSweep:
    run_id: UUID
    profile: str
    quiet_since: datetime


@frozen
class _LiveRun:
    run_id: UUID
    team_id: int
    profile: str | None
    environment: str
    status: str
    awaits_first_message: bool
    rules: frozenset[StaleRule]
    quiet_since: datetime


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
    last_sign_of_life = max(at for at in (last_heartbeat_at, queued_at, created_at) if at is not None)
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
    )


def sweep_mode(profile_key: str | None, team_id: int) -> SweepMode:
    if not profile_key:
        return SweepMode.OFF
    key = f"tasks:stale_sweep_mode:{team_id}:{profile_key}"
    try:
        cached = cache.get(key)
    except Exception:
        cached = None
    if cached is not None:
        return SweepMode.OFF if cached == _UNRESOLVED_SWEEP_MODE else SweepMode(cached)
    mode = _resolve_sweep_mode(profile_key, team_id)
    try:
        cache.set(key, _UNRESOLVED_SWEEP_MODE if mode is None else mode.value, SWEEP_MODE_CACHE_SECONDS)
    except Exception:
        logger.warning("task_stale_sweep_mode_cache_failed", profile=profile_key, team_id=team_id, exc_info=True)
    return mode or SweepMode.OFF


def _resolve_sweep_mode(profile_key: str, team_id: int) -> SweepMode | None:
    try:
        team = Team.objects.only("uuid", "organization_id").get(pk=team_id)
        organization_id = str(team.organization_id)
        payload = posthoganalytics.get_feature_flag_payload(
            SWEEP_FLAG,
            distinct_id=str(team.uuid),
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
        if isinstance(payload, str):
            payload = json.loads(payload)
    except Exception:
        logger.warning("task_stale_sweep_mode_unresolved", profile=profile_key, team_id=team_id, exc_info=True)
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return SweepMode(str(payload.get(profile_key, SweepMode.OFF)))
    except ValueError:
        return SweepMode.OFF


def _idle_timeout(profile_key: str | None, origin_product: str | None, run_timeout_seconds: object) -> timedelta:
    from products.tasks.backend.temporal.constants import resolve_inactivity_timeout

    profile = find_task_profile(profile_key)
    return resolve_inactivity_timeout(
        is_user_origin=Task.is_user_origin(origin_product),
        origin_product=origin_product,
        state={"inactivity_timeout_seconds": run_timeout_seconds},
        profile_idle_minutes=profile.idle_minutes if profile else None,
    )


def _live_runs() -> Iterator[_LiveRun]:
    now = timezone.now()
    runs = (
        TaskRun.objects.filter(status__in=_LIVE_RUN_STATUSES)
        .order_by()
        .values_list(
            "id",
            "team_id",
            "task__profile",
            "origin_product",
            "environment",
            "status",
            "state__inactivity_timeout_seconds",
            "state__await_user_message",
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
        awaits_first_message,
        last_heartbeat_at,
        queued_at,
        created_at,
        updated_at,
    ) in runs:
        idle_timeout = _idle_timeout(profile_key, origin_product, run_timeout_seconds)
        yield _LiveRun(
            run_id=run_id,
            team_id=team_id,
            profile=profile_key,
            environment=environment,
            status=status,
            awaits_first_message=bool(awaits_first_message),
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


def runs_to_sweep() -> list[RunToSweep]:
    return [
        RunToSweep(run_id=run.run_id, profile=run.profile, quiet_since=run.quiet_since)
        for run in _live_runs()
        if run.profile is not None
        and StaleRule.HEARTBEAT in run.rules
        and run.environment == TaskRun.Environment.CLOUD
        and run.status == TaskRun.Status.IN_PROGRESS
        and not run.awaits_first_message
        and sweep_mode(run.profile, run.team_id) == SweepMode.ENFORCE
    ]
