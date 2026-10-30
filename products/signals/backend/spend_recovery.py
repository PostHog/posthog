import time
from bisect import bisect_right
from typing import TYPE_CHECKING

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from redis.exceptions import LockNotOwnedError

from posthog import redis
from posthog.celery_queues import CeleryQueue
from posthog.llm.gateway_client import resolve_ai_gateway_config
from posthog.llm.gateway_usage import fetch_gateway_cost

from products.signals.backend.models import SignalSpend
from products.signals.backend.spend import (
    complete_task_spend,
    record_llm_spend,
    refresh_task_spend,
    submit_signal_metadata_updates,
)
from products.signals.backend.trial.tasks import release_abandoned_report_reservations
from products.tasks.backend.facade.api import get_task_report_id, get_task_run
from products.tasks.backend.facade.billing import process_pending_gateway_usage

if TYPE_CHECKING:
    from celery import Task

logger = structlog.get_logger(__name__)
RECOVERY_BUDGET_SECONDS = 30
RECOVERY_SOURCE_LIMIT = 20
RECOVERY_JOB_EXPIRY_SECONDS = 10 * 60
RECOVERY_LOCK_SECONDS = 60


def _recover_spend(*, team_id: int, spend_id: str) -> None:
    spend = SignalSpend.objects.for_team(team_id).filter(id=spend_id).first()
    if spend is None:
        return
    if not spend.accounting_failed:
        if spend.signal_id:
            async_to_sync(submit_signal_metadata_updates)(team_id=team_id, signal_ids=[str(spend.signal_id)])
        return
    SignalSpend.objects.for_team(team_id).filter(id=spend.id).update(updated_at=timezone.now())
    if spend.task_run_id:
        run = get_task_run(spend.task_run_id, team_id=team_id, include_child_environments=True)
        if run is None:
            return
        if run.is_terminal:
            report_id = get_task_report_id(task_id=run.task_id, team_id=run.team_id)
            complete_task_spend(
                team_id=run.team_id, run_id=str(spend.task_run_id), report_id=str(report_id) if report_id else None
            )
        else:
            process_pending_gateway_usage(team_id=run.team_id, run_id=spend.task_run_id)
            refresh_task_spend(team_id=run.team_id, run_id=str(spend.task_run_id), strict=True)
        return
    gateway = resolve_ai_gateway_config()
    if gateway is None:
        return
    deadline = time.monotonic() + RECOVERY_BUDGET_SECONDS
    key = f"signals:spend-recovery:{team_id}:{spend_id}:cursor"
    sources = sorted(spend.pending_requests)
    cursor = cache.get(key)
    start = bisect_right(sources, cursor) if isinstance(cursor, str) else 0
    recovered = False
    for source_id in (sources[start:] + sources[:start])[:RECOVERY_SOURCE_LIMIT]:
        if time.monotonic() >= deadline:
            break
        cache.set(key, source_id, timeout=24 * 60 * 60)
        source = spend.pending_requests[source_id]
        request_id = source.get("request_id")
        if not request_id:
            continue
        try:
            cost = async_to_sync(fetch_gateway_cost)(
                request_id,
                base_url=gateway.url,
                api_key=gateway.api_key,
                timeout_seconds=deadline - time.monotonic(),
            )
            if cost is not None:
                record_llm_spend(
                    request_id,
                    team_id=team_id,
                    signal_id=str(spend.signal_id),
                    source_id=source_id,
                    stage=source["stage"],
                    token_cost_microusd=cost.cost_microusd,
                )
                recovered = True
        except SoftTimeLimitExceeded:
            raise
        except Exception:
            logger.exception("signals.spend.recovery_failed", team_id=team_id, spend_id=spend_id)
    if recovered:
        async_to_sync(submit_signal_metadata_updates)(team_id=team_id, signal_ids=[str(spend.signal_id)])


@shared_task(
    bind=True,
    ignore_result=True,
    soft_time_limit=40,
    time_limit=45,
    queue=CeleryQueue.LONG_RUNNING.value,
    max_retries=None,
    acks_late=True,
    reject_on_worker_lost=True,
)
def recover_spend(self: "Task", team_id: int, spend_id: str) -> None:
    lock = redis.get_client().lock(
        f"signals:spend-recovery:{team_id}:{spend_id}", timeout=RECOVERY_LOCK_SECONDS, blocking=False
    )
    acquired = lock.acquire()
    try:
        if not acquired:
            raise RuntimeError("Spend recovery is already running")
        _recover_spend(team_id=team_id, spend_id=spend_id)
    except Exception as error:
        # The sweep retries incomplete costs, but stops selecting rows once they settle.
        if SignalSpend.objects.for_team(team_id).filter(id=spend_id, accounting_failed=False).exists():
            raise self.retry(exc=error, countdown=300, expires=None)
        raise
    finally:
        if acquired:
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
        .filter(Q(task_run_id__isnull=False) | ~Q(pending_requests={}))
        .order_by("updated_at", "id")
        .only("id", "team_id")[:100]
    ):
        recover_spend.apply_async(args=(spend.team_id, str(spend.id)), expires=RECOVERY_JOB_EXPIRY_SECONDS)
