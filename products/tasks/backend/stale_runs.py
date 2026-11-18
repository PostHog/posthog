from collections import Counter
from datetime import datetime, timedelta
from enum import StrEnum

from django.utils import timezone

from posthog.dataclasses import frozen

from products.tasks.backend.facade.profiles import find_task_profile
from products.tasks.backend.models import LIVE_RUN_STALE_AFTER, Task, TaskRun

STALE_RUN_GRACE = timedelta(minutes=15)
_LIVE_RUN_STATUSES = (TaskRun.Status.QUEUED, TaskRun.Status.IN_PROGRESS)


class StaleRule(StrEnum):
    HEARTBEAT = "heartbeat"
    NO_WRITES_24H = "no_writes_24h"


@frozen
class StaleRunCount:
    profile: str | None
    environment: str
    rule: StaleRule
    count: int


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


def _idle_timeout(profile_key: str | None, origin_product: str | None, run_timeout_seconds: object) -> timedelta:
    from products.tasks.backend.temporal.constants import resolve_inactivity_timeout

    profile = find_task_profile(profile_key)
    return resolve_inactivity_timeout(
        is_user_origin=Task.is_user_origin(origin_product),
        origin_product=origin_product,
        state={"inactivity_timeout_seconds": run_timeout_seconds},
        profile_idle_minutes=profile.idle_minutes if profile else None,
    )


def collect_stale_live_runs(*, limit: int = 10_000) -> list[StaleRunCount]:
    now = timezone.now()
    counts: Counter[tuple[str | None, str, StaleRule]] = Counter()
    runs = (
        TaskRun.objects.filter(status__in=_LIVE_RUN_STATUSES)
        .order_by()
        .values_list(
            "task__profile",
            "origin_product",
            "environment",
            "state__inactivity_timeout_seconds",
            "last_heartbeat_at",
            "queued_at",
            "created_at",
            "updated_at",
        )[:limit]
    )
    for (
        profile_key,
        origin_product,
        environment,
        run_timeout_seconds,
        last_heartbeat_at,
        queued_at,
        created_at,
        updated_at,
    ) in runs:
        rules = stale_rules(
            environment=environment,
            last_heartbeat_at=last_heartbeat_at,
            queued_at=queued_at,
            created_at=created_at,
            updated_at=updated_at,
            idle_timeout=_idle_timeout(profile_key, origin_product, run_timeout_seconds),
            now=now,
        )
        for rule in rules:
            counts[(profile_key, environment, rule)] += 1
    return [
        StaleRunCount(profile=profile_key, environment=environment, rule=rule, count=count)
        for (profile_key, environment, rule), count in counts.items()
    ]
