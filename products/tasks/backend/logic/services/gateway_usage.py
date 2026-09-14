import re
import time
from collections.abc import Iterable
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import dateparse, timezone

import requests
import structlog

from posthog.dataclasses import frozen

from products.tasks.backend.facade.contracts import TaskRunSpend
from products.tasks.backend.logic.services.sandbox_pricing import COMPUTE_RATE_CARDS, calculate_sandbox_compute_cost
from products.tasks.backend.models import SandboxSession, TaskRun

logger = structlog.get_logger(__name__)
TokenStatus = Literal["unavailable", "partial", "current", "final"]
ComputeStatus = Literal["unavailable", "current", "final"]
_REQUEST_ID = re.compile(r"[a-zA-Z0-9_-]{1,255}\Z")
_USD_AMOUNT = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,6})?\Z")
_MAX_BIGINT = 2**63 - 1
_PROCESSING_SECONDS = 10


@frozen
class SpendSources:
    token_microusd: int | None
    compute_usd: Decimal | None
    token_status: TokenStatus
    compute_status: ComputeStatus

    def as_contract(self) -> TaskRunSpend:
        return TaskRunSpend(
            token_cost=_cents(Decimal(self.token_microusd) / 1_000_000) if self.token_microusd is not None else None,
            compute_cost=_cents(self.compute_usd) if self.compute_usd is not None else None,
            token_status=self.token_status,
            compute_status=self.compute_status,
            is_final=self.token_status == "final" and self.compute_status == "final",
        )


def _locked_run(run_id: UUID, team_id: int) -> TaskRun:
    return TaskRun.objects.select_for_update().get(id=run_id, team_id=team_id)


def gateway_usage_enabled(*, run_id: UUID, team_id: int) -> bool:
    return TaskRun.objects.filter(
        id=run_id, team_id=team_id, environment=TaskRun.Environment.CLOUD, state___spend_accounting__enabled=True
    ).exists()


def enable_gateway_usage(*, run_id: UUID, team_id: int) -> None:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        if run.environment != TaskRun.Environment.CLOUD:
            raise ValueError("Gateway accounting requires a cloud run")
        state = dict(run.state or {})
        accounting = dict(state.get("_spend_accounting") or {})
        accounting["enabled"] = True
        state["_spend_accounting"] = accounting
        state["gateway_usage_complete"] = False
        run.state = state
        _persist_projection(run)


def _reported_ids(state: dict[str, Any]) -> list[str]:
    return list(
        dict.fromkeys(
            value
            for value in state.get("gateway_request_ids", [])
            if isinstance(value, str) and _REQUEST_ID.fullmatch(value)
        )
    )


def process_pending_gateway_usage(*, run_id: UUID, team_id: int, limit: int = 20) -> TaskRunSpend:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        state = run.state or {}
        accounting = state.get("_spend_accounting") or {}
        if accounting.get("enabled") is not True:
            return _persist_projection(run).as_contract()
        receipts = accounting.get("receipts") or {}
        pending = [request_id for request_id in _reported_ids(state) if request_id not in receipts]
        start = int(accounting.get("lookup_cursor", 0)) % len(pending) if pending else 0
    ordered = pending[start:] + pending[:start]
    deadline = time.monotonic() + _PROCESSING_SECONDS
    attempted = 0
    for request_id in ordered[:limit]:
        if time.monotonic() >= deadline:
            break
        receipt = _fetch_gateway_usage(request_id)
        attempted += 1
        if receipt is None:
            continue
        with transaction.atomic():
            run = _locked_run(run_id, team_id)
            state = dict(run.state or {})
            accounting = dict(state.get("_spend_accounting") or {})
            receipts = dict(accounting.get("receipts") or {})
            receipts.setdefault(request_id, receipt)
            accounting["receipts"] = receipts
            state["_spend_accounting"] = accounting
            run.state = state
            _persist_projection(run)
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        state = dict(run.state or {})
        accounting = dict(state.get("_spend_accounting") or {})
        # Rotate pending reads so an unpriced request cannot block later receipts.
        accounting["lookup_cursor"] = start + attempted
        state["_spend_accounting"] = accounting
        run.state = state
        return _persist_projection(run).as_contract()


def refresh_sandbox_run_spend(*, sandbox_id: str) -> TaskRunSpend | None:
    session = SandboxSession.objects.unscoped().filter(sandbox_id=sandbox_id).only("task_run_id", "team_id").first()
    if session is None:
        return None
    return refresh_task_run_spend(run_id=session.task_run_id, team_id=session.team_id)


def refresh_task_run_spend(*, run_id: UUID, team_id: int) -> TaskRunSpend:
    with transaction.atomic():
        return _persist_projection(_locked_run(run_id, team_id)).as_contract()


def get_task_run_spend(*, run: TaskRun) -> TaskRunSpend:
    return refresh_task_run_spend(run_id=run.id, team_id=run.team_id)


def get_task_spend(*, team_id: int, task_id: UUID) -> TaskRunSpend:
    run_ids = list(TaskRun.objects.filter(team_id=team_id, task_id=task_id).order_by("id").values_list("id", flat=True))
    if not run_ids:
        return TaskRunSpend.unavailable()
    projections = []
    for run_id in run_ids:
        with transaction.atomic():
            projections.append(_persist_projection(_locked_run(run_id, team_id)))
    compute_status: ComputeStatus = (
        "unavailable"
        if any(p.compute_status == "unavailable" for p in projections)
        else "final"
        if all(p.compute_status == "final" for p in projections)
        else "current"
    )
    return SpendSources(
        token_microusd=None
        if any(p.token_microusd is None for p in projections)
        else sum(p.token_microusd or 0 for p in projections),
        compute_usd=None
        if any(p.compute_usd is None for p in projections)
        else sum((p.compute_usd or Decimal(0) for p in projections), Decimal(0)),
        token_status=_aggregate_token_status(p.token_status for p in projections),
        compute_status=compute_status,
    ).as_contract()


def _aggregate_token_status(statuses: Iterable[TokenStatus]) -> TokenStatus:
    values = set(statuses)
    for status in ("unavailable", "partial", "current", "final"):
        if status in values:
            return status
    return "unavailable"


def _fetch_gateway_usage(request_id: str) -> dict[str, Any] | None:
    base_url = (settings.SANDBOX_AI_GATEWAY_URL or "").rstrip("/").removesuffix("/v1")
    mint_key = settings.SANDBOX_AI_GATEWAY_MINT_KEY
    if not base_url or not mint_key:
        return None
    try:
        response = requests.get(
            f"{base_url}/v1/usage/{request_id}",
            headers={"Authorization": f"Bearer {mint_key}"},
            timeout=(2, 3),
            allow_redirects=False,
        )
        if response.status_code != 200:
            logger.warning("task_gateway_usage.receipt_pending", status_code=response.status_code)
            return None
        body = response.json()
        if not isinstance(body, dict) or body.get("request_id") != request_id:
            return None
        amount = body.get("cost_usd")
        settled_at = dateparse.parse_datetime(body.get("settled_at", ""))
        model, provider = body.get("model") or "", body.get("provider") or ""
        if (
            not isinstance(amount, str)
            or not _USD_AMOUNT.fullmatch(amount)
            or settled_at is None
            or timezone.is_naive(settled_at)
            or not isinstance(model, str)
            or len(model) > 255
            or not isinstance(provider, str)
            or len(provider) > 255
        ):
            return None
        return {
            "cost_microusd": int(Decimal(amount) * 1_000_000),
            "model": model,
            "provider": provider,
            "input_tokens": _nonnegative_int(body.get("input_tokens")),
            "output_tokens": _nonnegative_int(body.get("output_tokens")),
            "settled_at": settled_at.isoformat(),
        }
    except (requests.RequestException, ValueError, TypeError):
        logger.warning("task_gateway_usage.lookup_failed")
        return None


def _nonnegative_int(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= _MAX_BIGINT else None


def _persist_projection(run: TaskRun) -> SpendSources:
    state = dict(run.state or {})
    accounting = dict(state.get("_spend_accounting") or {})
    receipts = accounting.get("receipts") or {}
    ids = _reported_ids(state)
    known = [receipts[request_id] for request_id in ids if request_id in receipts]
    pending = len(known) < len(ids)
    complete = state.get("gateway_usage_complete") is True
    token_status: TokenStatus = "unavailable"
    token_source = None
    if accounting.get("enabled") is True and run.environment == TaskRun.Environment.CLOUD:
        partial = pending or (run.is_terminal and not complete)
        token_status = "partial" if partial else "final" if run.is_terminal else "current"
        if known or not partial:
            token_source = sum(receipt["cost_microusd"] for receipt in known)
    snapshots = dict(accounting.get("compute_sessions") or {})
    compute_source, compute_status = _compute_source(run, snapshots)
    accounting["compute_sessions"] = snapshots
    projection = SpendSources(
        token_microusd=token_source,
        compute_usd=compute_source,
        token_status=token_status,
        compute_status=compute_status,
    )
    state["_spend_accounting"] = accounting
    state["spend"] = projection.as_contract().to_state()
    run.state = state
    run.save(update_fields=["state", "updated_at"])
    return projection


def _compute_source(run: TaskRun, snapshots: dict[str, str]) -> tuple[Decimal | None, ComputeStatus]:
    if run.environment != TaskRun.Environment.CLOUD or not COMPUTE_RATE_CARDS:
        return None, "unavailable"
    sessions = list(SandboxSession.objects.for_team(run.team_id).filter(task_run=run))
    if not sessions:
        return None, "unavailable"
    now = timezone.now()
    total = Decimal(0)
    for session in sessions:
        key = str(session.id)
        if session.ended_at is not None and key in snapshots:
            cost = Decimal(snapshots[key])
        else:
            try:
                cost = calculate_sandbox_compute_cost(
                    session, COMPUTE_RATE_CARDS[0].effective_at, now, calculated_at=now, rate_cards=COMPUTE_RATE_CARDS
                ).total_cost_usd
            except ValueError:
                return None, "unavailable"
            if session.ended_at is not None:
                snapshots[key] = str(cost)
        total += cost
    return total, "final" if run.is_terminal and all(s.ended_at is not None for s in sessions) else "current"


def _cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_EVEN))
