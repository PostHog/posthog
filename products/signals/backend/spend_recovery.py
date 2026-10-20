import time
from bisect import bisect_right
from uuid import UUID

from django.core.cache import cache
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from redis.exceptions import LockNotOwnedError

from posthog import redis
from posthog.llm.gateway_client import resolve_ai_gateway_config
from posthog.llm.gateway_usage import fetch_gateway_cost

from products.signals.backend.models import SignalSpend
from products.signals.backend.spend import SpendSource, complete_task_spend, record_llm_spend, refresh_task_spend
from products.signals.backend.trial.tasks import release_abandoned_report_reservations
from products.tasks.backend.facade.api import get_task_run
from products.tasks.backend.facade.billing import process_pending_gateway_usage

logger = structlog.get_logger(__name__)

RECOVERY_BUDGET_SECONDS = 30
RECOVERY_SOURCE_LIMIT = 20
RECOVERY_JOB_EXPIRY_SECONDS = 10 * 60
RECOVERY_CURSOR_TTL_SECONDS = 24 * 60 * 60
RECOVERY_LOCK_SECONDS = 60


def _recover_source(*, spend: SignalSpend, source_id: str, source: SpendSource, deadline: float) -> None:
    if source["is_task"]:
        run_id = source_id.removeprefix("task:")
        environment_id = source.get("environment_id", spend.team_id)
        run = get_task_run(run_id, team_id=environment_id)
        if run is not None and run.is_terminal:
            complete_task_spend(team_id=environment_id, run_id=run_id, deadline=deadline)
        else:
            process_pending_gateway_usage(run_id=UUID(run_id), team_id=environment_id, deadline=deadline)
            refresh_task_spend(team_id=environment_id, run_id=run_id, strict=True)
    elif source.get("actual_cost_incomplete", source["accounting_failed"]):
        gateway = resolve_ai_gateway_config()
        if gateway and (request_id := source.get("request_id")):
            cost = async_to_sync(fetch_gateway_cost)(
                request_id,
                base_url=gateway.url,
                api_key=gateway.api_key,
                timeout_seconds=deadline - time.monotonic(),
            )
            if cost is not None:
                record_llm_spend(
                    request_id,
                    token_cost_microusd=cost.cost_microusd,
                    team_id=spend.team_id,
                    signal_id=str(spend.signal_id),
                    stage=source["stage"],
                    source_id=source_id,
                )


def _recover_spend(*, team_id: int, spend_id: str, cursor_key: str) -> None:
    deadline = time.monotonic() + RECOVERY_BUDGET_SECONDS
    spend = SignalSpend.objects.for_team(team_id).filter(id=spend_id, accounting_failed=True).first()
    if spend is None:
        return
    SignalSpend.objects.for_team(team_id).filter(id=spend_id).update(updated_at=timezone.now())
    sources = sorted(
        source_id
        for source_id, source in spend.trial_sources.items()
        if source["is_task"] or source.get("actual_cost_incomplete", source["accounting_failed"])
    )
    cursor = cache.get(cursor_key)
    start = bisect_right(sources, cursor) if isinstance(cursor, str) else 0
    for source_id in (sources[start:] + sources[:start])[:RECOVERY_SOURCE_LIMIT]:
        if time.monotonic() >= deadline:
            break
        # Save progress before I/O so a killed worker cannot pin the next pass to this source.
        cache.set(cursor_key, source_id, timeout=RECOVERY_CURSOR_TTL_SECONDS)
        try:
            _recover_source(spend=spend, source_id=source_id, source=spend.trial_sources[source_id], deadline=deadline)
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            logger.exception("signals.spend.recovery_failed", team_id=team_id, spend_id=spend_id)


# The hard limit must stay below the lock expiry so a new owner cannot overlap a live worker.
@shared_task(ignore_result=True, soft_time_limit=40, time_limit=45)
def recover_spend(team_id: int, spend_id: str) -> None:
    key = f"signals:spend-recovery:{team_id}:{UUID(spend_id)}"
    lock = redis.get_client().lock(key, timeout=RECOVERY_LOCK_SECONDS, blocking=False)
    if not lock.acquire():
        return
    try:
        _recover_spend(team_id=team_id, spend_id=spend_id, cursor_key=f"{key}:cursor")
    finally:
        try:
            lock.release()
        except LockNotOwnedError:
            logger.warning("signals.spend.recovery_lock_expired", team_id=team_id, spend_id=spend_id)


@shared_task(ignore_result=True)
def recover_incomplete_spend() -> None:
    release_abandoned_report_reservations()
    for spend in (
        SignalSpend.objects.unscoped()
        .filter(accounting_failed=True)
        .exclude(trial_sources={})
        .order_by("updated_at")
        .only("id", "team_id")[:100]
    ):
        recover_spend.apply_async(args=(spend.team_id, str(spend.id)), expires=RECOVERY_JOB_EXPIRY_SECONDS)
