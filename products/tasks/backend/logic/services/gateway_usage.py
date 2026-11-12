import re
import time
import asyncio
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal
from functools import lru_cache
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Min
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen
from posthog.llm.gateway_usage import GatewayRequestCost, fetch_gateway_cost

from products.tasks.backend.facade.contracts import TaskRunCost, TaskRunSpend, TaskRunTokenUsage
from products.tasks.backend.facade.task_run_signals import task_run_cost_updated
from products.tasks.backend.logic.services.sandbox_pricing import COMPUTE_RATE_CARDS, calculate_sandbox_compute_cost
from products.tasks.backend.models import SandboxSession, TaskRun, TaskRunGatewayRequest

if TYPE_CHECKING:
    from temporalio.client import Client

logger = structlog.get_logger(__name__)
_REQUEST_ID = re.compile(r"[a-zA-Z0-9_-]{1,255}\Z")
_PROCESSING_SECONDS = 10
_DRAIN_BATCH_SIZE = 200
_SCHEDULING_LOOP: asyncio.AbstractEventLoop | None = None
_SCHEDULING_LOCK = threading.Lock()


@frozen
class _CostSources:
    token_cost_microusd: int | None
    compute_cost_usd: Decimal | None

    def as_contract(self) -> TaskRunCost:
        return TaskRunCost(
            token_cost=_cents(Decimal(self.token_cost_microusd) / 1_000_000)
            if self.token_cost_microusd is not None
            else None,
            compute_cost=_cents(self.compute_cost_usd) if self.compute_cost_usd is not None else None,
        )


def _locked_run(run_id: UUID | str, team_id: int) -> TaskRun:
    return (
        TaskRun.objects.select_for_update()
        .only("id", "team_id", "state", "environment", "task_id", "status", "created_at")
        .get(id=run_id, team_id=team_id)
    )


def gateway_usage_enabled(run: TaskRun) -> bool:
    state = run.state or {}
    return (
        run.environment == TaskRun.Environment.CLOUD
        and isinstance(state.get("unprocessed_request_ids"), list)
        and isinstance(state.get("token_cost"), dict)
    )


def _accounting_failed(run: TaskRun) -> bool:
    return bool((run.state or {}).get("token_cost_incomplete")) or (run.is_terminal and not gateway_usage_enabled(run))


def _save_accounting_state(run: TaskRun) -> None:
    # Accounting can finish after completion; it must not emit completion signals again.
    # It also leaves `updated_at` alone, because recency gauges and stale-run sweeps read it.
    previous = TaskRun.objects.select_related("task").get(id=run.id, team_id=run.team_id)
    delta = (_recorded_cost_microusd(run) or 0) - (_recorded_cost_microusd(previous) or 0)
    TaskRun.objects.filter(id=run.id, team_id=run.team_id).update(state=run.state)
    task_run_cost_updated.send(
        sender=TaskRun,
        run_id=run.id,
        team_id=run.team_id,
        cost_delta_microusd=delta,
        accounting_failed=_accounting_failed(run),
        origin_product=previous.task.origin_product,
    )


def record_gateway_routing(*, run_id: UUID | str, team_id: int, uses_gateway: bool) -> None:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        if run.environment != TaskRun.Environment.CLOUD:
            raise ValueError("Gateway cost requires a cloud run")
        state = dict(run.state or {})
        if uses_gateway:
            state.setdefault("unprocessed_request_ids", [])
            state.setdefault("token_cost", {})
        else:
            state["token_cost_incomplete"] = True
        if state == run.state:
            return
        run.state = state
        _save_accounting_state(run)


def _cost_buckets(state: dict[str, Any]) -> Iterable[dict[str, Any]]:
    models = state.get("token_cost")
    if not isinstance(models, dict):
        return
    for providers in models.values():
        if isinstance(providers, dict):
            for bucket in providers.values():
                if isinstance(bucket, dict):
                    yield bucket


def _processed_gateway_request_ids(state: dict[str, Any]) -> set[str]:
    return {
        request_id
        for bucket in _cost_buckets(state)
        for request_id in bucket.get("request_ids", [])
        if isinstance(request_id, str)
    }


def record_generation_request(*, team_id: int, run_id: UUID, request_id: str) -> bool | None:
    environment = TaskRun.objects.filter(id=run_id, team_id=team_id).values_list("environment", flat=True).first()
    if environment is None:
        return None
    if environment != TaskRun.Environment.CLOUD:
        return False
    TaskRunGatewayRequest.objects.for_team(team_id, canonical=True).bulk_create(
        [TaskRunGatewayRequest(team_id=team_id, task_run_id=run_id, request_id=request_id)],
        ignore_conflicts=True,
    )
    return True


def _drain_queued_requests(run: TaskRun, state: dict[str, Any]) -> bool:
    queued = list(
        TaskRunGatewayRequest.objects.for_team(run.team_id, canonical=True)
        .filter(task_run_id=run.id)
        .order_by("created_at", "id")
        .values_list("id", "request_id")[:_DRAIN_BATCH_SIZE]
    )
    if not queued:
        return False

    before = _pending_ids(state)
    seen = set(before) | _processed_gateway_request_ids(state)
    merged = list(before)
    for _row_id, request_id in queued:
        if request_id not in seen:
            seen.add(request_id)
            merged.append(request_id)

    state["unprocessed_request_ids"] = merged
    state.setdefault("token_cost", {})
    TaskRunGatewayRequest.objects.for_team(run.team_id, canonical=True).filter(
        id__in=[row_id for row_id, _ in queued]
    ).delete()
    return merged != before


def _has_queued_requests(run: TaskRun) -> bool:
    return TaskRunGatewayRequest.objects.for_team(run.team_id, canonical=True).filter(task_run_id=run.id).exists()


def _runs_with_queued_requests(team_id: int, run_ids: Iterable[UUID]) -> set[UUID]:
    return set(
        TaskRunGatewayRequest.objects.for_team(team_id, canonical=True)
        .filter(task_run_id__in=list(run_ids))
        .values_list("task_run_id", flat=True)
        .distinct()
    )


def _pending_ids(state: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            value
            for value in state.get("unprocessed_request_ids", [])
            if isinstance(value, str) and _REQUEST_ID.fullmatch(value)
        )
    )


def process_pending_gateway_usage(*, run_id: UUID, team_id: int, limit: int = 20) -> TaskRunCost:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        state = dict(run.state or {})
        if _drain_queued_requests(run, state):
            run.state = state
            _save_accounting_state(run)
        if not gateway_usage_enabled(run):
            return _cost_sources(run).as_contract()
        pending = _pending_ids(state)[:limit]
    deadline = time.monotonic() + _PROCESSING_SECONDS
    for request_id in pending:
        if time.monotonic() >= deadline:
            break
        request_cost = async_to_sync(_fetch_gateway_cost)(request_id)
        with transaction.atomic():
            run = _locked_run(run_id, team_id)
            state = dict(run.state or {})
            remaining = _pending_ids(state)
            if request_id not in remaining:
                continue
            remaining.remove(request_id)
            processed = _processed_gateway_request_ids(state)
            if request_id not in processed:
                if request_cost is None:
                    # A missing response must not block the rest of the queue.
                    remaining.append(request_id)
                else:
                    providers = state["token_cost"].setdefault(request_cost.model, {})
                    bucket = providers.setdefault(request_cost.provider, {})
                    bucket["cost_microusd"] = bucket.get("cost_microusd", 0) + request_cost.cost_microusd
                    bucket["request_ids"] = [*bucket.get("request_ids", []), request_id]
            state["unprocessed_request_ids"] = remaining
            run.state = state
            _save_accounting_state(run)
    return refresh_task_run_cost(run_id=run_id, team_id=team_id)


def refresh_task_run_cost(*, run_id: UUID, team_id: int) -> TaskRunCost:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        state = dict(run.state or {})
        cost = _cost_sources(run).as_contract()
        if "compute_cost" not in state or state["compute_cost"] != cost.compute_cost:
            state["compute_cost"] = cost.compute_cost
            run.state = state
            _save_accounting_state(run)
        return cost


def get_task_run_cost(*, run_id: UUID, team_id: int) -> TaskRunCost:
    return _cost_sources(TaskRun.objects.get(id=run_id, team_id=team_id)).as_contract()


def get_task_cost(*, team_id: int, task_id: UUID) -> TaskRunCost:
    runs = list(TaskRun.objects.filter(team_id=team_id, task_id=task_id))
    if not runs:
        return TaskRunCost(token_cost=None, compute_cost=None)
    queued = _runs_with_queued_requests(team_id, [run.id for run in runs])
    sessions_by_run: dict[UUID, list[SandboxSession]] = {}
    for session in SandboxSession.objects.for_team(team_id).filter(task_run__in=runs):
        sessions_by_run.setdefault(session.task_run_id, []).append(session)
    sources = [_cost_sources(run, sessions=sessions_by_run.get(run.id, []), queued=run.id in queued) for run in runs]
    return _CostSources(
        token_cost_microusd=None
        if any(s.token_cost_microusd is None for s in sources)
        else sum(s.token_cost_microusd or 0 for s in sources),
        compute_cost_usd=None
        if any(s.compute_cost_usd is None for s in sources)
        else sum((s.compute_cost_usd or Decimal(0) for s in sources), Decimal(0)),
    ).as_contract()


async def _fetch_gateway_cost(request_id: str) -> GatewayRequestCost | None:
    return await fetch_gateway_cost(
        request_id, base_url=settings.SANDBOX_AI_GATEWAY_URL or "", api_key=settings.SANDBOX_AI_GATEWAY_MINT_KEY or ""
    )


def get_task_run_token_cost_microusd(*, run_id: UUID, team_id: int) -> int | None:
    return _token_cost_microusd(TaskRun.objects.get(id=run_id, team_id=team_id))


def _token_usage(run: TaskRun, *, queued: bool | None = None) -> TaskRunTokenUsage:
    state = run.state or {}
    return TaskRunTokenUsage(
        cost_microusd=_recorded_cost_microusd(run),
        complete=gateway_usage_enabled(run)
        and not state.get("token_cost_incomplete", False)
        and not bool(state.get("unprocessed_request_ids"))
        and not (_has_queued_requests(run) if queued is None else queued),
    )


def _recorded_cost_microusd(run: TaskRun) -> int | None:
    state = run.state or {}
    if not isinstance(state.get("token_cost"), dict):
        return None
    return sum(bucket.get("cost_microusd", 0) for bucket in _cost_buckets(state))


def get_task_run_token_usage(*, run_id: UUID, team_id: int) -> TaskRunTokenUsage:
    return _token_usage(TaskRun.objects.get(id=run_id, team_id=team_id))


def _run_spend(
    run: TaskRun, *, queued: bool | None = None, sessions: list[SandboxSession] | None = None
) -> TaskRunSpend:
    usage = _token_usage(run, queued=queued)
    if sessions is None:
        sessions = list(SandboxSession.objects.for_team(run.team_id).filter(task_run=run))
    compute = _compute_cost_source(run, sessions=sessions, include_unattributed=True) if sessions else Decimal(0)
    compute_complete = compute is not None and (
        not run.is_terminal
        or all(session.ended_at is not None or session.ttl_expires_at <= timezone.now() for session in sessions)
    )
    if not sessions and (run.state or {}).get("sandbox_id"):
        compute_complete = False
    return TaskRunSpend(
        created_at=run.created_at,
        run_id=run.id,
        task_id=run.task_id,
        cost_microusd=usage.cost_microusd,
        complete=usage.complete and compute_complete,
        is_terminal=run.is_terminal,
        stage=(run.state or {}).get("ai_stage") or "task",
        accounting_failed=_accounting_failed(run),
        compute_cost_microusd=int(((compute or Decimal(0)) * 1_000_000).to_integral_value(rounding=ROUND_CEILING)),
        trial_grant_id=(run.state or {}).get("self_driving_funding", {}).get("grant_id") or None,
        billing_exempt=(run.state or {}).get("self_driving_funding", {}).get("funding") == "operator",
    )


@contextmanager
def locked_task_run_spend(*, team_id: int, run_id: UUID) -> Iterator[TaskRunSpend]:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        yield _run_spend(run)


def get_task_runs_spend(*, team_id: int, run_ids: Iterable[UUID]) -> list[TaskRunSpend]:
    runs = list(TaskRun.objects.filter(team_id=team_id, id__in=run_ids))
    if not runs:
        return []
    queued = _runs_with_queued_requests(team_id, [run.id for run in runs])
    sessions_by_run: dict[UUID, list[SandboxSession]] = {}
    for session in SandboxSession.objects.for_team(team_id).filter(task_run__in=runs):
        sessions_by_run.setdefault(session.task_run_id, []).append(session)
    return [_run_spend(run, queued=run.id in queued, sessions=sessions_by_run.get(run.id, [])) for run in runs]


def _token_cost_microusd(run: TaskRun, *, queued: bool | None = None) -> int | None:
    usage = _token_usage(run, queued=queued)
    return usage.cost_microusd if usage.complete else None


def _cost_sources(
    run: TaskRun, *, sessions: list[SandboxSession] | None = None, queued: bool | None = None
) -> _CostSources:
    return _CostSources(
        token_cost_microusd=_token_cost_microusd(run, queued=queued),
        compute_cost_usd=_compute_cost_source(run, sessions=sessions),
    )


def _compute_cost_source(
    run: TaskRun, *, sessions: list[SandboxSession] | None = None, include_unattributed: bool = False
) -> Decimal | None:
    if run.environment != TaskRun.Environment.CLOUD or not COMPUTE_RATE_CARDS:
        return None
    if sessions is None:
        sessions = list(SandboxSession.objects.for_team(run.team_id).filter(task_run=run))
    if not sessions:
        return None
    now = timezone.now()
    try:
        return sum(
            (_session_compute_cost(session, now, include_unattributed=include_unattributed) for session in sessions),
            Decimal(0),
        )
    except ValueError:
        return None


def _session_compute_cost(session: SandboxSession, now: datetime, *, include_unattributed: bool = False) -> Decimal:
    if not include_unattributed and session.compute_settled_at is not None and session.compute_settled_usd is not None:
        return session.compute_settled_usd
    return calculate_sandbox_compute_cost(
        session,
        COMPUTE_RATE_CARDS[0].effective_at,
        now,
        calculated_at=now,
        rate_cards=COMPUTE_RATE_CARDS,
        include_unattributed=include_unattributed,
    ).total_cost_usd


def _cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_EVEN))


@lru_cache(maxsize=1)
def _gateway_usage_client(loop: asyncio.AbstractEventLoop) -> asyncio.Task["Client"]:
    from posthog.temporal.common.client import async_connect  # noqa: PLC0415 - keeps Temporal off Django's startup path

    # ASGI requests share a loop; a client must not cross into a different loop.
    return loop.create_task(asyncio.wait_for(async_connect(), timeout=5))


async def _schedule_gateway_usage(*, run_id: UUID, team_id: int) -> None:
    from temporalio.common import WorkflowIDReusePolicy  # noqa: PLC0415 - keeps Temporal off Django's startup path

    from products.tasks.backend.temporal.gateway_usage import (  # noqa: PLC0415 — avoids loading workflows during Django startup
        GatewayUsageInput,
    )

    try:
        client = await asyncio.shield(_gateway_usage_client(asyncio.get_running_loop()))
    except Exception:
        _gateway_usage_client.cache_clear()
        raise
    await client.start_workflow(
        "task-run-gateway-usage",
        GatewayUsageInput(run_id=str(run_id), team_id=team_id),
        id=f"task-run-gateway-usage-{team_id}-{run_id}",
        task_queue=settings.TASKS_TASK_QUEUE,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
        start_signal="requests_available",
        rpc_timeout=timedelta(seconds=5),
    )


def schedule_gateway_usage(*, run_id: UUID, team_id: int) -> None:
    with _SCHEDULING_LOCK:
        _scheduling_loop().run_until_complete(_schedule_gateway_usage(run_id=run_id, team_id=team_id))


def _scheduling_loop() -> asyncio.AbstractEventLoop:
    # asgiref builds a fresh loop per sync call, so the client cache below would miss on every callback.
    global _SCHEDULING_LOOP
    if _SCHEDULING_LOOP is None or _SCHEDULING_LOOP.is_closed():
        _SCHEDULING_LOOP = asyncio.new_event_loop()
    return _SCHEDULING_LOOP


def sweep_queued_gateway_requests(*, older_than_seconds: int = 600, limit: int = 50) -> int:
    cutoff = timezone.now() - timedelta(seconds=older_than_seconds)
    stale = list(
        TaskRunGatewayRequest.objects.unscoped()
        .values("team_id", "task_run_id")
        .annotate(oldest=Min("created_at"))
        .filter(oldest__lt=cutoff)
        .order_by("oldest")
        .values_list("team_id", "task_run_id")[:limit]
    )
    scheduled = 0
    for team_id, run_id in stale:
        try:
            schedule_gateway_usage(run_id=run_id, team_id=team_id)
        except Exception:
            logger.exception("task_gateway_usage.sweep_schedule_failed", run_id=str(run_id), team_id=team_id)
            continue
        scheduled += 1
    return scheduled
