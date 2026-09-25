import re
import time
from collections.abc import Iterable
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen

from products.tasks.backend.facade.contracts import TaskRunSpend
from products.tasks.backend.logic.services.sandbox_pricing import COMPUTE_RATE_CARDS, calculate_sandbox_compute_cost
from products.tasks.backend.models import SandboxSession, TaskRun

logger = structlog.get_logger(__name__)
_REQUEST_ID = re.compile(r"[a-zA-Z0-9_-]{1,255}\Z")
_USD_AMOUNT = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,6})?\Z")
_PROCESSING_SECONDS = 10


@frozen
class GatewayRequestSpend:
    model: str
    provider: str
    spend_microusd: int


@frozen
class _SpendSources:
    token_spend_microusd: int | None
    compute_spend_usd: Decimal | None

    def as_contract(self) -> TaskRunSpend:
        return TaskRunSpend(
            token_spend=_cents(Decimal(self.token_spend_microusd) / 1_000_000)
            if self.token_spend_microusd is not None
            else None,
            compute_spend=_cents(self.compute_spend_usd) if self.compute_spend_usd is not None else None,
        )


def _locked_run(run_id: UUID | str, team_id: int) -> TaskRun:
    return TaskRun.objects.select_for_update().get(id=run_id, team_id=team_id)


def gateway_usage_enabled(run: TaskRun) -> bool:
    state = run.state or {}
    return (
        run.environment == TaskRun.Environment.CLOUD
        and isinstance(state.get("unprocessed_request_ids"), list)
        and isinstance(state.get("token_spend"), dict)
    )


def _save_accounting_state(run: TaskRun) -> None:
    # Accounting can finish after completion; it must not emit completion signals again.
    # It also leaves `updated_at` alone, because recency gauges and stale-run sweeps read it.
    TaskRun.objects.filter(id=run.id, team_id=run.team_id).update(state=run.state)


def record_gateway_routing(*, run_id: UUID | str, team_id: int, uses_gateway: bool) -> None:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        if run.environment != TaskRun.Environment.CLOUD:
            raise ValueError("Gateway spend requires a cloud run")
        state = dict(run.state or {})
        if uses_gateway:
            state.setdefault("unprocessed_request_ids", [])
            state.setdefault("token_spend", {})
        else:
            state["token_spend_incomplete"] = True
        if state == run.state:
            return
        run.state = state
        _save_accounting_state(run)


def _spend_buckets(state: dict[str, Any]) -> Iterable[dict[str, Any]]:
    models = state.get("token_spend")
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
        for bucket in _spend_buckets(state)
        for request_id in bucket.get("request_ids", [])
        if isinstance(request_id, str)
    }


def record_generation_request(*, team_id: int, run_id: UUID, request_id: str) -> bool:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        if run.environment != TaskRun.Environment.CLOUD:
            return False
        state = dict(run.state or {})
        pending = state.get("unprocessed_request_ids")
        if not isinstance(pending, list):
            pending = []
        if request_id not in pending and request_id not in _processed_gateway_request_ids(state):
            pending = [*pending, request_id]
        state["unprocessed_request_ids"] = pending
        state.setdefault("token_spend", {})
        if state == run.state:
            return True
        run.state = state
        _save_accounting_state(run)
        return True


def _pending_ids(state: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            value
            for value in state.get("unprocessed_request_ids", [])
            if isinstance(value, str) and _REQUEST_ID.fullmatch(value)
        )
    )


def process_pending_gateway_usage(*, run_id: UUID, team_id: int, limit: int = 20) -> TaskRunSpend:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        state = run.state or {}
        if not gateway_usage_enabled(run):
            return _spend_sources(run).as_contract()
        pending = _pending_ids(state)[:limit]
    deadline = time.monotonic() + _PROCESSING_SECONDS
    for request_id in pending:
        if time.monotonic() >= deadline:
            break
        request_spend = async_to_sync(_fetch_gateway_spend)(request_id)
        with transaction.atomic():
            run = _locked_run(run_id, team_id)
            state = dict(run.state or {})
            remaining = _pending_ids(state)
            if request_id not in remaining:
                continue
            remaining.remove(request_id)
            processed = _processed_gateway_request_ids(state)
            if request_id not in processed:
                if request_spend is None:
                    # A missing response must not block the rest of the queue.
                    remaining.append(request_id)
                else:
                    providers = state["token_spend"].setdefault(request_spend.model, {})
                    bucket = providers.setdefault(request_spend.provider, {})
                    bucket["spend_microusd"] = bucket.get("spend_microusd", 0) + request_spend.spend_microusd
                    bucket["request_ids"] = [*bucket.get("request_ids", []), request_id]
            state["unprocessed_request_ids"] = remaining
            run.state = state
            _save_accounting_state(run)
    return refresh_task_run_spend(run_id=run_id, team_id=team_id)


def refresh_task_run_spend(*, run_id: UUID, team_id: int) -> TaskRunSpend:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        spend = _spend_sources(run).as_contract()
        state = dict(run.state or {})
        if "compute_spend" not in state or state["compute_spend"] != spend.compute_spend:
            state["compute_spend"] = spend.compute_spend
            run.state = state
            _save_accounting_state(run)
        return spend


def get_task_run_spend(*, run_id: UUID, team_id: int) -> TaskRunSpend:
    return _spend_sources(TaskRun.objects.get(id=run_id, team_id=team_id)).as_contract()


def get_task_spend(*, team_id: int, task_id: UUID) -> TaskRunSpend:
    runs = list(TaskRun.objects.filter(team_id=team_id, task_id=task_id))
    if not runs:
        return TaskRunSpend(token_spend=None, compute_spend=None)
    sessions_by_run: dict[UUID, list[SandboxSession]] = {}
    for session in SandboxSession.objects.for_team(team_id).filter(task_run__in=runs):
        sessions_by_run.setdefault(session.task_run_id, []).append(session)
    sources = [_spend_sources(run, sessions=sessions_by_run.get(run.id, [])) for run in runs]
    return _SpendSources(
        token_spend_microusd=None
        if any(s.token_spend_microusd is None for s in sources)
        else sum(s.token_spend_microusd or 0 for s in sources),
        compute_spend_usd=None
        if any(s.compute_spend_usd is None for s in sources)
        else sum((s.compute_spend_usd or Decimal(0) for s in sources), Decimal(0)),
    ).as_contract()


async def _fetch_gateway_spend(request_id: str) -> GatewayRequestSpend | None:
    import aiohttp  # noqa: PLC0415 - keeps aiohttp off Django's startup path

    base_url = (settings.SANDBOX_AI_GATEWAY_URL or "").rstrip("/").removesuffix("/v1")
    mint_key = settings.SANDBOX_AI_GATEWAY_MINT_KEY
    if not base_url or not mint_key:
        return None
    try:
        async with (
            aiohttp.ClientSession(trust_env=True) as session,
            session.get(
                f"{base_url}/v1/usage/{request_id}",
                headers={"Authorization": f"Bearer {mint_key}"},
                timeout=aiohttp.ClientTimeout(total=15, connect=2, sock_read=3),
                allow_redirects=False,
            ) as response,
        ):
            if response.status != 200:
                logger.warning("task_gateway_usage.spend_pending", status_code=response.status)
                return None
            body = await response.json()
        if not isinstance(body, dict) or body.get("request_id") != request_id:
            return None
        amount = body.get("cost_usd")
        model, provider = body.get("model") or "unknown", body.get("provider") or "unknown"
        if (
            not isinstance(amount, str)
            or not _USD_AMOUNT.fullmatch(amount)
            or not isinstance(model, str)
            or len(model) > 255
            or not isinstance(provider, str)
            or len(provider) > 255
        ):
            return None
        return GatewayRequestSpend(model=model, provider=provider, spend_microusd=int(Decimal(amount) * 1_000_000))
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
        logger.warning("task_gateway_usage.lookup_failed")
        return None


def _spend_sources(run: TaskRun, *, sessions: list[SandboxSession] | None = None) -> _SpendSources:
    return _SpendSources(
        token_spend_microusd=sum(bucket.get("spend_microusd", 0) for bucket in _spend_buckets(run.state or {}))
        if gateway_usage_enabled(run) and not (run.state or {}).get("token_spend_incomplete")
        else None,
        compute_spend_usd=_compute_spend_source(run, sessions=sessions),
    )


def _compute_spend_source(run: TaskRun, *, sessions: list[SandboxSession] | None = None) -> Decimal | None:
    if run.environment != TaskRun.Environment.CLOUD or not COMPUTE_RATE_CARDS:
        return None
    if sessions is None:
        sessions = list(SandboxSession.objects.for_team(run.team_id).filter(task_run=run))
    if not sessions:
        return None
    now = timezone.now()
    try:
        return sum(
            (
                calculate_sandbox_compute_cost(
                    session, COMPUTE_RATE_CARDS[0].effective_at, now, calculated_at=now, rate_cards=COMPUTE_RATE_CARDS
                ).total_cost_usd
                for session in sessions
            ),
            Decimal(0),
        )
    except ValueError:
        return None


def _cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_EVEN))


async def _schedule_gateway_usage(*, run_id: UUID, team_id: int) -> None:
    from temporalio.common import WorkflowIDReusePolicy  # noqa: PLC0415 - keeps Temporal off Django's startup path

    from posthog.temporal.common.client import async_connect  # noqa: PLC0415 - keeps Temporal off Django's startup path

    from products.tasks.backend.temporal.gateway_usage import (  # noqa: PLC0415 — avoids loading workflows during Django startup
        GatewayUsageInput,
    )

    client = await async_connect()
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
    async_to_sync(_schedule_gateway_usage)(run_id=run_id, team_id=team_id)
