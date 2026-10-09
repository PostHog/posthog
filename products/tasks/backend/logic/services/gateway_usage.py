import re
import time
import asyncio
from collections.abc import Collection, Iterable
from datetime import datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from functools import lru_cache
from typing import TYPE_CHECKING, Any
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.dataclasses import frozen

from products.tasks.backend.facade.contracts import (
    InferenceBilling,
    SandboxSessionUsageDTO,
    TaskRunBillingDTO,
    TaskRunCost,
)
from products.tasks.backend.logic.model_access import InvalidModelAccess, inference_billing_for_state
from products.tasks.backend.logic.services.compute_quota import (
    BillingProduct,
    compute_pricing_product,
    task_billing_product,
)
from products.tasks.backend.logic.services.sandbox_pricing import (
    SandboxComputeCost,
    calculate_sandbox_compute_cost,
    compute_pricing,
    compute_waived,
)
from products.tasks.backend.models import SandboxSession, TaskRun

if TYPE_CHECKING:
    from temporalio.client import Client

logger = structlog.get_logger(__name__)
_REQUEST_ID = re.compile(r"[a-zA-Z0-9_-]{1,255}\Z")
_USD_AMOUNT = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,6})?\Z")
_PROCESSING_SECONDS = 10


@frozen
class GatewayRequestCost:
    model: str
    provider: str
    cost_microusd: int


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
    return TaskRun.objects.select_for_update().get(id=run_id, team_id=team_id)


def gateway_usage_enabled(run: TaskRun) -> bool:
    state = run.state or {}
    return (
        run.environment == TaskRun.Environment.CLOUD
        and isinstance(state.get("unprocessed_request_ids"), list)
        and isinstance(state.get("token_cost"), dict)
    )


def _save_accounting_state(run: TaskRun) -> None:
    # Accounting can finish after completion; it must not emit completion signals again.
    # It also leaves `updated_at` alone, because recency gauges and stale-run sweeps read it.
    TaskRun.objects.filter(id=run.id, team_id=run.team_id).update(state=run.state)


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
        state.setdefault("token_cost", {})
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


def process_pending_gateway_usage(*, run_id: UUID, team_id: int, limit: int = 20) -> TaskRunCost:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        state = run.state or {}
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
        cost = _cost_sources(run).as_contract()
        state = dict(run.state or {})
        if "compute_cost" not in state or state["compute_cost"] != cost.compute_cost:
            state["compute_cost"] = cost.compute_cost
            run.state = state
            _save_accounting_state(run)
        return cost


def get_task_run_cost(*, run_id: UUID, team_id: int) -> TaskRunCost:
    return _cost_sources(TaskRun.objects.get(id=run_id, team_id=team_id)).as_contract()


def get_task_cost(*, team_id: int, task_id: UUID) -> TaskRunCost:
    runs = list(TaskRun.objects.select_related("task").filter(team_id=team_id, task_id=task_id))
    if not runs:
        return TaskRunCost(token_cost=None, compute_cost=None)
    sessions_by_run: dict[UUID, list[SandboxSession]] = {}
    for session in SandboxSession.objects.for_team(team_id).filter(task_run__in=runs):
        sessions_by_run.setdefault(session.task_run_id, []).append(session)
    sources = [_cost_sources(run, sessions=sessions_by_run.get(run.id, [])) for run in runs]
    return _CostSources(
        token_cost_microusd=None
        if any(s.token_cost_microusd is None for s in sources)
        else sum(s.token_cost_microusd or 0 for s in sources),
        compute_cost_usd=None
        if any(s.compute_cost_usd is None for s in sources)
        else sum((s.compute_cost_usd or Decimal(0) for s in sources), Decimal(0)),
    ).as_contract()


async def _fetch_gateway_cost(request_id: str) -> GatewayRequestCost | None:
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
                logger.warning("task_gateway_usage.cost_pending", status_code=response.status)
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
        return GatewayRequestCost(model=model, provider=provider, cost_microusd=int(Decimal(amount) * 1_000_000))
    except (aiohttp.ClientError, TimeoutError, ValueError, TypeError):
        logger.warning("task_gateway_usage.lookup_failed")
        return None


def _cost_sources(run: TaskRun, *, sessions: list[SandboxSession] | None = None) -> _CostSources:
    return _CostSources(
        token_cost_microusd=_token_cost_microusd(run),
        compute_cost_usd=_compute_cost_source(run, sessions=sessions),
    )


def _token_cost_microusd(run: TaskRun) -> int | None:
    if (
        gateway_usage_enabled(run)
        and not (run.state or {}).get("token_cost_incomplete")
        and not (run.state or {}).get("unprocessed_request_ids")
    ):
        return sum(bucket.get("cost_microusd", 0) for bucket in _cost_buckets(run.state or {}))
    return None


def _session_compute_cost(session: SandboxSession, product: BillingProduct, now: datetime) -> SandboxComputeCost:
    """The session's cost to date at the product's price."""
    pricing = compute_pricing(product)
    return calculate_sandbox_compute_cost(
        session,
        pricing.rate_cards[0].effective_at,
        now,
        calculated_at=now,
        rate_cards=pricing.rate_cards,
        resource_policy=pricing.resource_policy,
    )


def _compute_cost_source(run: TaskRun, *, sessions: list[SandboxSession] | None = None) -> Decimal | None:
    if run.environment != TaskRun.Environment.CLOUD:
        return None
    # An unbilled run is priced too, so a reader can show what the run would cost.
    product = compute_pricing_product(run.origin_product)
    if not compute_pricing(product).rate_cards:
        return None
    if sessions is None:
        sessions = list(SandboxSession.objects.for_team(run.team_id).filter(task_run=run))
    if not sessions:
        return None
    if compute_waived(product, run.state):
        return Decimal(0)
    now = timezone.now()
    try:
        return sum((_session_compute_cost(session, product, now).total_cost_usd for session in sessions), Decimal(0))
    except ValueError:
        return None


def _run_inference_billing(run: TaskRun) -> InferenceBilling:
    try:
        return inference_billing_for_state(run.state or {})
    except InvalidModelAccess:
        return "posthog"


def _task_inference_billing(runs: list[TaskRun]) -> InferenceBilling:
    return _run_inference_billing(max(runs, key=lambda run: run.created_at))


_NO_RUNS_BILLING = TaskRunBillingDTO(
    compute_cost_cents=None,
    inference_cost_cents=None,
    vcpu_seconds=Decimal(0),
    gib_seconds=Decimal(0),
    billable=False,
    inference_billing="posthog",
    rate_card_version=None,
    waived=False,
    settled=True,
    sessions=(),
)


def get_task_run_billing(*, team_id: int, task_id: UUID) -> TaskRunBillingDTO:
    return get_tasks_billing(team_id=team_id, task_ids=[task_id])[task_id]


def get_tasks_billing(
    *, team_id: int, task_ids: Collection[UUID], origin_product: str | None = None
) -> dict[UUID, TaskRunBillingDTO]:
    """The charges of each task in ``task_ids``, read with the same number of queries for any number of tasks.

    Every requested id is a key of the result. A task with no run in this team, or of another
    origin when ``origin_product`` is set, has no charge.
    """
    billing = dict.fromkeys(task_ids, _NO_RUNS_BILLING)
    if not billing:
        return billing
    runs = TaskRun.objects.select_related("task__loop").filter(team_id=team_id, task_id__in=list(billing))
    if origin_product is not None:
        runs = runs.filter(task__team_id=team_id, task__origin_product=origin_product)
    runs_by_task: dict[UUID, list[TaskRun]] = {}
    task_of_run: dict[UUID, UUID] = {}
    for run in runs:
        runs_by_task.setdefault(run.task_id, []).append(run)
        task_of_run[run.id] = run.task_id
    if not runs_by_task:
        return billing
    sessions_by_task: dict[UUID, list[SandboxSession]] = {}
    sessions = SandboxSession.objects.for_team(team_id).filter(task_run_id__in=list(task_of_run))
    for session in sessions.order_by("created_at", "id"):
        sessions_by_task.setdefault(task_of_run[session.task_run_id], []).append(session)
    now = timezone.now()
    for task_id, task_runs in runs_by_task.items():
        billing[task_id] = _task_billing(task_runs, sessions_by_task.get(task_id, []), now)
    return billing


def _task_billing(runs: list[TaskRun], sessions: list[SandboxSession], now: datetime) -> TaskRunBillingDTO:
    task = runs[0].task
    product = compute_pricing_product(task.origin_product)
    pricing = compute_pricing(product)
    billable = task_billing_product(task) is not None
    rate_card_version = pricing.rate_cards[-1].version if pricing.rate_cards else None
    inference_billing = _task_inference_billing(runs)

    session_rows: list[SandboxSessionUsageDTO] = []
    compute_usd: Decimal | None = Decimal(0) if sessions and pricing.rate_cards else None
    vcpu_seconds = Decimal(0)
    gib_seconds = Decimal(0)
    waived_run_ids = {run.id for run in runs if compute_waived(product, run.state)}
    for session in sessions:
        cost: SandboxComputeCost | None = None
        waived = session.task_run_id in waived_run_ids
        if pricing.rate_cards:
            try:
                cost = _session_compute_cost(session, product, now)
            except ValueError:
                compute_usd = None
        if cost is not None and not waived:
            vcpu_seconds += cost.cpu_core_seconds
            gib_seconds += cost.memory_gib_seconds
            if compute_usd is not None:
                compute_usd += cost.total_cost_usd
        session_rows.append(
            SandboxSessionUsageDTO(
                cpu_cores=session.cpu_cores,
                memory_gb=session.memory_gb,
                started_at=session.user_attributed_at or session.created_at,
                ended_at=session.ended_at,
                seconds=int(cost.billable_seconds) if cost is not None else 0,
                cost_cents=_cents(cost.total_cost_usd) if cost is not None and not waived else 0,
                waived=waived,
            )
        )

    posthog_runs = [run for run in runs if _run_inference_billing(run) == "posthog"]
    token_costs = [_token_cost_microusd(run) for run in posthog_runs]
    inference_cost_cents: int | None = None
    if posthog_runs and all(cost is not None for cost in token_costs):
        inference_cost_cents = _cents(Decimal(sum(cost or 0 for cost in token_costs)) / 1_000_000)

    # The calculator ends an unstamped session at its TTL, so such a session is closed after it.
    sessions_closed = all(session.ended_at is not None or session.ttl_expires_at <= now for session in sessions)
    gateway_usage_pending = any(_pending_ids(run.state or {}) for run in posthog_runs)
    return TaskRunBillingDTO(
        compute_cost_cents=_cents(compute_usd) if compute_usd is not None else None,
        inference_cost_cents=inference_cost_cents,
        vcpu_seconds=vcpu_seconds,
        gib_seconds=gib_seconds,
        billable=billable,
        inference_billing=inference_billing,
        rate_card_version=rate_card_version,
        waived=any(row.waived for row in session_rows),
        settled=all(run.is_terminal for run in runs) and sessions_closed and not gateway_usage_pending,
        sessions=tuple(session_rows),
    )


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
    async_to_sync(_schedule_gateway_usage)(run_id=run_id, team_id=team_id)
