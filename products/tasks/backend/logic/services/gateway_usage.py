import re
import hashlib
from collections.abc import Iterable
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Literal
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.utils import dateparse, timezone

import requests
import structlog

from posthog.dataclasses import frozen

from products.tasks.backend.facade.contracts import TaskRunSpend
from products.tasks.backend.logic.services.sandbox_pricing import COMPUTE_RATE_CARDS, calculate_sandbox_compute_cost
from products.tasks.backend.models import (
    GatewayUsageCredential,
    GatewayUsageEpoch,
    GatewayUsageRequest,
    SandboxSession,
    TaskRun,
)

logger = structlog.get_logger(__name__)
TokenStatus = Literal["unavailable", "partial", "current", "final"]
ComputeStatus = Literal["unavailable", "current", "final"]
_REQUEST_ID = re.compile(r"[a-zA-Z0-9_-]{1,255}\Z")
_MAX_BIGINT = 2**63 - 1


class GatewayUsageError(RuntimeError):
    pass


class GatewayUsageCredentialMismatch(GatewayUsageError):
    pass


@frozen
class GatewayReceipt:
    credential_id: str
    cost_microusd: int
    model: str
    provider: str
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    settled_at: datetime


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
    try:
        return TaskRun.objects.select_for_update().get(id=run_id, team_id=team_id)
    except TaskRun.DoesNotExist as error:
        raise GatewayUsageError("Task run not found") from error


def has_gateway_credential(*, run_id: UUID, team_id: int) -> bool:
    return GatewayUsageCredential.objects.for_team(team_id).filter(task_run_id=run_id).exists()


def _require_credential(run: TaskRun) -> None:
    if run.environment != TaskRun.Environment.CLOUD or not has_gateway_credential(run_id=run.id, team_id=run.team_id):
        raise GatewayUsageCredentialMismatch("The cloud run has no gateway credential")


def register_gateway_credential(*, run_id: UUID, team_id: int, bearer: str) -> bool:
    digest = hashlib.sha256(bearer.encode()).hexdigest()
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        if run.environment != TaskRun.Environment.CLOUD:
            raise GatewayUsageError("Gateway accounting requires a cloud run")
        GatewayUsageCredential.objects.for_team(team_id).get_or_create(
            task_run=run, bearer_hash=digest, defaults={"team_id": team_id}
        )
    return True


def start_gateway_usage_epoch(*, run_id: UUID, team_id: int, epoch_id: UUID) -> TaskRunSpend:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        _require_credential(run)
        _, created = GatewayUsageEpoch.objects.for_team(team_id).get_or_create(
            task_run=run, epoch_id=epoch_id, defaults={"team_id": team_id}
        )
        if created:
            now = timezone.now()
            GatewayUsageEpoch.objects.for_team(team_id).filter(task_run=run, sealed_at__isnull=True).exclude(
                epoch_id=epoch_id
            ).update(sealed_at=now, interrupted_at=now)
        return _persist_projection(run).as_contract()


def _validate_request_id(request_id: str) -> None:
    if not _REQUEST_ID.fullmatch(request_id):
        raise GatewayUsageError("Invalid gateway request identifier")


def record_gateway_usage_request(
    *, run_id: UUID, team_id: int, epoch_id: UUID, attempt_id: UUID, request_id: str | None
) -> TaskRunSpend:
    if request_id is not None:
        _validate_request_id(request_id)
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        _require_credential(run)
        epoch = GatewayUsageEpoch.objects.for_team(team_id).filter(task_run=run, epoch_id=epoch_id).first()
        if epoch is None:
            raise GatewayUsageError("The gateway usage epoch does not exist")
        intent = GatewayUsageRequest.objects.for_team(team_id).filter(epoch=epoch, attempt_id=attempt_id).first()
        if intent is None:
            if epoch.sealed_at is not None:
                raise GatewayUsageError("The gateway usage epoch is sealed")
            intent = GatewayUsageRequest.objects.for_team(team_id).create(
                team_id=team_id, task_run=run, epoch=epoch, attempt_id=attempt_id
            )
        if request_id is not None:
            if intent.gateway_request_id not in (None, request_id):
                raise GatewayUsageError("The gateway request binding is immutable")
            if intent.gateway_request_id is None:
                intent.gateway_request_id = request_id
                intent.save(update_fields=["gateway_request_id"])
        return _persist_projection(run).as_contract()


def _request_intent(run: TaskRun, epoch_id: UUID, attempt_id: UUID, request_id: str) -> GatewayUsageRequest:
    intent = (
        GatewayUsageRequest.objects.for_team(run.team_id)
        .filter(task_run=run, epoch__epoch_id=epoch_id, attempt_id=attempt_id, gateway_request_id=request_id)
        .first()
    )
    if intent is None:
        raise GatewayUsageError("The gateway receipt has no matching request intent")
    return intent


def settle_gateway_usage_request(
    *, run_id: UUID, team_id: int, epoch_id: UUID, attempt_id: UUID, request_id: str
) -> tuple[bool, TaskRunSpend]:
    _validate_request_id(request_id)
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        _require_credential(run)
        intent = _request_intent(run, epoch_id, attempt_id, request_id)
        if intent.settled_at is not None:
            return True, _persist_projection(run).as_contract()
        canonical = (
            GatewayUsageRequest.objects.for_team(team_id)
            .filter(task_run=run, gateway_request_id=request_id, settled_at__isnull=False)
            .first()
        )
        if canonical is not None:
            _copy_receipt(intent, canonical)
            return True, _persist_projection(run).as_contract()

    receipt = _fetch_gateway_usage(request_id)
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        intent = _request_intent(run, epoch_id, attempt_id, request_id)
        if intent.settled_at is not None:
            return True, _persist_projection(run).as_contract()
        if receipt is None:
            return False, _persist_projection(run).as_contract()
        if (
            not GatewayUsageCredential.objects.for_team(team_id)
            .filter(task_run=run, bearer_hash=receipt.credential_id)
            .exists()
        ):
            raise GatewayUsageCredentialMismatch("The gateway receipt belongs to a different task run")
        canonical = (
            GatewayUsageRequest.objects.for_team(team_id)
            .filter(task_run=run, gateway_request_id=request_id, settled_at__isnull=False)
            .first()
        )
        if canonical is not None:
            if any(getattr(canonical, key) != getattr(receipt, key) for key in _RECEIPT_FIELDS):
                raise GatewayUsageError("Conflicting receipts for the gateway request")
            _copy_receipt(intent, canonical)
        else:
            _copy_receipt(intent, receipt)
        return True, _persist_projection(run).as_contract()


_RECEIPT_FIELDS = (
    "cost_microusd",
    "model",
    "provider",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "settled_at",
)


def _copy_receipt(intent: GatewayUsageRequest, source: GatewayReceipt | GatewayUsageRequest) -> None:
    for key in _RECEIPT_FIELDS:
        setattr(intent, key, getattr(source, key))
    intent.save(update_fields=list(_RECEIPT_FIELDS))


def finish_gateway_usage_epoch(*, run_id: UUID, team_id: int, epoch_id: UUID) -> TaskRunSpend:
    with transaction.atomic():
        run = _locked_run(run_id, team_id)
        _require_credential(run)
        epoch = GatewayUsageEpoch.objects.for_team(team_id).filter(task_run=run, epoch_id=epoch_id).first()
        if epoch is None:
            raise GatewayUsageError("The gateway usage epoch does not exist")
        epoch.sealed_at = epoch.sealed_at or timezone.now()
        epoch.interrupted_at = None
        epoch.save(update_fields=["sealed_at", "interrupted_at"])
        return _persist_projection(run).as_contract()


def retry_pending_gateway_usage(*, run_id: UUID, team_id: int, limit: int = 20) -> TaskRunSpend:
    pending = list(
        GatewayUsageRequest.objects.for_team(team_id)
        .filter(task_run_id=run_id, settled_at__isnull=True, gateway_request_id__isnull=False)
        .order_by("created_at")
        .values_list("epoch__epoch_id", "attempt_id", "gateway_request_id")[:limit]
    )
    for epoch_id, attempt_id, request_id in pending:
        if request_id is None:
            continue
        try:
            settled, _ = settle_gateway_usage_request(
                run_id=run_id, team_id=team_id, epoch_id=epoch_id, attempt_id=attempt_id, request_id=request_id
            )
        except GatewayUsageError:
            logger.warning("task_gateway_usage.receipt_rejected", run_id=str(run_id))
            continue
        if not settled:
            break
    return refresh_task_run_spend(run_id=run_id, team_id=team_id)


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
    token_status = _aggregate_token_status(p.token_status for p in projections)
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
        token_status=token_status,
        compute_status=compute_status,
    ).as_contract()


def _aggregate_token_status(statuses: Iterable[TokenStatus]) -> TokenStatus:
    values = set(statuses)
    for status in ("unavailable", "partial", "current", "final"):
        if status in values:
            return status
    return "unavailable"


def _fetch_gateway_usage(request_id: str) -> GatewayReceipt | None:
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
        if not isinstance(body, dict):
            return None
        credential_id = body.get("credential_id")
        cost = _nonnegative_int(body.get("cost_microusd"))
        settled_at = dateparse.parse_datetime(body.get("settled_at", ""))
        model, provider = body.get("model") or "", body.get("provider") or ""
        if (
            not isinstance(credential_id, str)
            or not re.fullmatch(r"[a-f0-9]{64}", credential_id)
            or cost is None
            or settled_at is None
            or timezone.is_naive(settled_at)
            or body.get("request_id") != request_id
            or not isinstance(model, str)
            or len(model) > 255
            or not isinstance(provider, str)
            or len(provider) > 255
        ):
            return None
        return GatewayReceipt(
            credential_id=credential_id,
            cost_microusd=cost,
            model=model,
            provider=provider,
            input_tokens=_nonnegative_int(body.get("input_tokens")),
            output_tokens=_nonnegative_int(body.get("output_tokens")),
            cache_read_tokens=_nonnegative_int(body.get("cache_read_tokens")),
            cache_write_tokens=_nonnegative_int(body.get("cache_write_tokens")),
            settled_at=settled_at,
        )
    except (requests.RequestException, ValueError, TypeError):
        logger.warning("task_gateway_usage.lookup_failed")
        return None


def _nonnegative_int(value: object) -> int | None:
    return value if type(value) is int and 0 <= value <= _MAX_BIGINT else None


def _persist_projection(run: TaskRun) -> SpendSources:
    epochs = list(GatewayUsageEpoch.objects.for_team(run.team_id).filter(task_run=run))
    requests = list(GatewayUsageRequest.objects.for_team(run.team_id).filter(task_run=run))
    canonical = {
        r.gateway_request_id: r for r in requests if r.gateway_request_id is not None and r.settled_at is not None
    }
    pending = any(r.settled_at is None for r in requests)
    has_open_epoch = any(e.sealed_at is None for e in epochs)
    interrupted = any(e.interrupted_at is not None for e in epochs)
    token_status: TokenStatus = "unavailable"
    token_source = None
    if epochs and run.environment == TaskRun.Environment.CLOUD:
        partial = pending or interrupted or (run.is_terminal and has_open_epoch)
        token_status = "partial" if partial else "final" if run.is_terminal else "current"
        if canonical or not pending:
            token_source = sum(r.cost_microusd or 0 for r in canonical.values())

    state = dict(run.state or {})
    accounting = dict(state.get("_spend_accounting") or {})
    snapshots = dict(accounting.get("compute_sessions") or {})
    compute_source, compute_status = _compute_source(run, snapshots, has_open_epoch)
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


def _compute_source(
    run: TaskRun, snapshots: dict[str, str], has_open_epoch: bool
) -> tuple[Decimal | None, ComputeStatus]:
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
    final = run.is_terminal and not has_open_epoch and all(s.ended_at is not None for s in sessions)
    return total, "final" if final else "current"


def _cents(value: Decimal) -> int:
    return int((value * 100).to_integral_value(rounding=ROUND_HALF_EVEN))
