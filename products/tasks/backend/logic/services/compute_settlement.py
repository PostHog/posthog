import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, NoReturn
from uuid import UUID

from django.conf import settings
from django.db.models import Count, F, QuerySet, Sum
from django.utils import timezone

import httpx
import structlog

from posthog.dataclasses import frozen
from posthog.llm.gateway_internal_client import (
    AIGatewayNotConfigured,
    ReportedSpendResponse,
    get_usage_report_rows,
    report_spend,
)
from posthog.models.project_secret_api_key import find_project_secret_api_key

from products.tasks.backend.logic.services.compute_quota import is_billable_sandbox_session
from products.tasks.backend.logic.services.run_actor import get_actor_distinct_id, get_task_run_credential_user
from products.tasks.backend.logic.services.sandbox_pricing import (
    COMPUTE_RATE_CARDS,
    SandboxComputeCost,
    calculate_sandbox_compute_cost,
)
from products.tasks.backend.logic.services.sandbox_usage import (
    close_sandbox_session,
    get_billable_sandbox_compute_usage_by_team,
)
from products.tasks.backend.metrics import (
    ComputeSettlementOutcome,
    observe_compute_settlement,
    push_compute_settlement_sweep_gauges,
)
from products.tasks.backend.models import SandboxSession, TaskRun

logger = structlog.get_logger(__name__)

MAX_SETTLE_ATTEMPTS = 20
ATTEMPTS_EXHAUSTED_ERROR = "attempts_exhausted"
ENDED_GRACE = timedelta(minutes=10)
TTL_GRACE = timedelta(hours=1)
HOGLAND_OPEN_ALERT_AGE = timedelta(days=1)
UNSETTLED_ALERT_AGE = timedelta(hours=1)
DETAIL_MAX_BYTES = 2048
_USD_QUANTUM = Decimal("0.000001")
_RETRYABLE_STATUSES = frozenset({408, 429})
_DEPLOYMENT_STATUSES = frozenset({401, 403, 404})
_ERROR_MAX_LENGTH = 200


class SettlementOutcome(StrEnum):
    DISABLED = "disabled"
    SKIPPED = "skipped"
    SETTLED = "settled"
    DUPLICATE = "duplicate"
    SETTLED_LOCALLY = "settled_locally"
    CONFLICT = "conflict"
    RETRY = "retry"
    ATTEMPTS_EXHAUSTED = "attempts_exhausted"
    CONTRACT_ERROR = "contract_error"
    CONTRACT_ERROR_REPEAT = "contract_error_repeat"
    INSUFFICIENT_CREDITS = "insufficient_credits"


_CONTRACT_ERROR_OUTCOMES = frozenset({SettlementOutcome.CONTRACT_ERROR, SettlementOutcome.CONTRACT_ERROR_REPEAT})
_SETTLED_OUTCOMES = frozenset({SettlementOutcome.SETTLED, SettlementOutcome.DUPLICATE})
ParkReason = SandboxSession.ComputeSettleParkReason


class ComputeSettlementDeploymentError(Exception):
    pass


def _reject_settle_since(raw: str, reason: str) -> NoReturn:
    observe_compute_settlement("deployment_error")
    logger.error("compute_settlement.invalid_settle_since", value=raw, reason=reason)
    raise ComputeSettlementDeploymentError(f"GATEWAY_COMPUTE_SETTLE_SINCE {reason}")


def _settle_since() -> datetime | None:
    raw = settings.GATEWAY_COMPUTE_SETTLE_SINCE
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        _reject_settle_since(raw, "is not a valid ISO timestamp")
    value = parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    if value > timezone.now():
        _reject_settle_since(raw, "is in the future")
    return value


def reconcile_window_since(since: datetime) -> datetime:
    cutoff = _settle_since()
    return cutoff if cutoff is not None and cutoff > since else since


def _unsettled(queryset: QuerySet[SandboxSession]) -> QuerySet[SandboxSession]:
    return queryset.filter(compute_settled_at__isnull=True, compute_settle_conflict_at__isnull=True)


def _session_rows(session: SandboxSession) -> QuerySet[SandboxSession]:
    return SandboxSession.objects.for_team(session.team_id).filter(id=session.id)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _fixed6(value: Decimal) -> str:
    return str(value.quantize(_USD_QUANTUM, rounding=ROUND_HALF_EVEN))


def _window_end(session: SandboxSession) -> datetime:
    assert session.ended_at is not None
    return min(session.ended_at, session.ttl_expires_at)


def _resource(session: SandboxSession) -> str:
    if session.sandbox_backend == "hogland":
        return "hogland"
    return "sandbox-vm" if session.vm_runtime else "modal"


def session_compute_cost(session: SandboxSession) -> SandboxComputeCost | None:
    if not COMPUTE_RATE_CARDS or session.user_attributed_at is None or session.ended_at is None:
        return None
    start = COMPUTE_RATE_CARDS[0].effective_at
    end = max(_window_end(session), start + timedelta(seconds=1))
    return calculate_sandbox_compute_cost(
        session, start, end, calculated_at=session.ended_at, rate_cards=COMPUTE_RATE_CARDS
    )


def _ai_product(run: TaskRun) -> str:
    from products.tasks.backend.temporal.process_task.ai_gateway_token import (  # noqa: PLC0415 - the temporal package imports this module via cleanup_sandbox
        resolve_sandbox_ai_product,
    )

    state = run.state or {}
    profile = run.task.stored_profile
    return resolve_sandbox_ai_product(
        run.task.origin_product,
        state.get("ai_stage"),
        internal=run.task.internal,
        billing_product=state.get("billing_product"),
        profile_billing_product=profile.billing_product if profile else None,
    )


def build_settlement_body(session: SandboxSession, run: TaskRun, cost: SandboxComputeCost) -> dict[str, Any]:
    assert session.user_attributed_at is not None
    window_end = _window_end(session)
    detail: dict[str, Any] = {
        "rate_cards": [
            {
                "version": item.rate_card.version,
                "seconds": _fixed6(item.billable_seconds),
                "usd": _fixed6(item.total_cost_usd),
            }
            for item in cost.line_items
        ],
        "resource": _resource(session),
        "cpu_cores": session.cpu_cores,
        "memory_gb": session.memory_gb,
        "attributed_seconds": round(max((window_end - session.user_attributed_at).total_seconds(), 0.0), 3),
        "window_start": _iso(session.user_attributed_at),
        "window_end": _iso(window_end),
        "ended_reason": session.ended_reason or "",
        "sandbox_id": session.sandbox_id,
    }
    body: dict[str, Any] = {
        "reference": f"compute:{session.id}",
        "amount_usd": _fixed6(cost.total_cost_usd),
        "charge_kind": "compute",
        "product": _ai_product(run),
    }
    actor = get_task_run_credential_user(run.task, run.state)
    if actor is not None:
        body["user"] = get_actor_distinct_id(actor)
    body.update(
        {
            "obo": str(session.team_id),
            "run": str(session.task_run_id),
            "billable": is_billable_sandbox_session(session),
            "detail": detail,
            "reason": "sandbox compute",
            "strict": True,
        }
    )
    return body


def wallet_team_id() -> int:
    mint_key = settings.SANDBOX_AI_GATEWAY_MINT_KEY
    record = find_project_secret_api_key(mint_key) if mint_key else None
    if record is None:
        observe_compute_settlement("deployment_error")
        logger.error("compute_settlement.wallet_unresolved")
        raise ComputeSettlementDeploymentError("SANDBOX_AI_GATEWAY_MINT_KEY does not resolve to a wallet team")
    return record.team_id


_METRIC_LABELS: dict[SettlementOutcome, ComputeSettlementOutcome] = {
    SettlementOutcome.SKIPPED: "skipped",
    SettlementOutcome.SETTLED: "settled",
    SettlementOutcome.DUPLICATE: "duplicate",
    SettlementOutcome.SETTLED_LOCALLY: "settled_locally",
    SettlementOutcome.CONFLICT: "conflict",
    SettlementOutcome.RETRY: "retry",
    SettlementOutcome.ATTEMPTS_EXHAUSTED: "attempts_exhausted",
    SettlementOutcome.CONTRACT_ERROR: "contract_error",
    SettlementOutcome.CONTRACT_ERROR_REPEAT: "contract_error",
    SettlementOutcome.INSUFFICIENT_CREDITS: "insufficient_credits",
}


def _record(outcome: SettlementOutcome) -> SettlementOutcome:
    label = _METRIC_LABELS.get(outcome)
    if label is not None:
        observe_compute_settlement(label)
    return outcome


def _settle_locally(session: SandboxSession) -> SettlementOutcome:
    _unsettled(_session_rows(session)).update(
        compute_settled_at=timezone.now(), compute_settled_usd=Decimal(0), compute_settle_error=""
    )
    return _record(SettlementOutcome.SETTLED_LOCALLY)


def _error_text(response: ReportedSpendResponse) -> str:
    body = response.body or {}
    message = body.get("message")
    code = body.get("code")
    if isinstance(message, str) and message:
        detail = f"{code}: {message}" if isinstance(code, str) and code else message
    else:
        detail = response.text
    return f"HTTP {response.status_code}: {detail}"[:_ERROR_MAX_LENGTH]


def _mark_conflict(session: SandboxSession, error: str, reason: ParkReason) -> None:
    _unsettled(_session_rows(session)).update(
        compute_settle_conflict_at=timezone.now(), compute_settle_error=error, compute_settle_park_reason=reason
    )


def _mark_malformed(session: SandboxSession) -> SettlementOutcome:
    rows = _unsettled(_session_rows(session))
    rows.update(compute_settle_attempts=F("compute_settle_attempts") + 1)
    attempts = rows.values_list("compute_settle_attempts", flat=True).first()
    if attempts is not None and attempts >= MAX_SETTLE_ATTEMPTS:
        _mark_conflict(session, ATTEMPTS_EXHAUSTED_ERROR, ParkReason.ATTEMPTS_EXHAUSTED)
        logger.error("compute_settlement.attempts_exhausted", session_id=str(session.id), attempts=attempts)
        return _record(SettlementOutcome.ATTEMPTS_EXHAUSTED)
    return _record(SettlementOutcome.RETRY)


def _mark_contract_error(session: SandboxSession, response: ReportedSpendResponse) -> SettlementOutcome:
    error = _error_text(response)
    rows = _unsettled(_session_rows(session))
    stored = rows.values_list("compute_settle_error", flat=True).first()
    rows.update(compute_settle_error=error)
    logger.error("compute_settlement.contract_error", session_id=str(session.id), error=error)
    if stored == error:
        return _record(SettlementOutcome.CONTRACT_ERROR_REPEAT)
    return _record(SettlementOutcome.CONTRACT_ERROR)


def _mark_settled(session: SandboxSession, response: ReportedSpendResponse) -> SettlementOutcome:
    body = response.body or {}
    entry_id = body.get("entry_id")
    try:
        amount = Decimal(str(body.get("amount_usd")))
    except InvalidOperation:
        amount = None
    if not isinstance(entry_id, str) or not entry_id or amount is None or not amount.is_finite():
        logger.warning("compute_settlement.malformed_response", session_id=str(session.id))
        return _mark_malformed(session)
    _unsettled(_session_rows(session)).update(
        compute_settled_at=timezone.now(),
        compute_settled_usd=amount,
        compute_ledger_entry_id=entry_id[:64],
        compute_settle_error="",
    )
    return _record(SettlementOutcome.DUPLICATE if body.get("duplicate") is True else SettlementOutcome.SETTLED)


def settle_sandbox_session(session: SandboxSession) -> SettlementOutcome:
    if not settings.GATEWAY_COMPUTE_DEBIT_ENABLED:
        return SettlementOutcome.DISABLED
    if (
        session.ended_at is None
        or session.compute_settled_at is not None
        or session.compute_settle_conflict_at is not None
    ):
        return _record(SettlementOutcome.SKIPPED)
    if session.user_attributed_at is None:
        return _settle_locally(session)
    cost = session_compute_cost(session)
    if cost is None or _fixed6(cost.total_cost_usd) == _fixed6(Decimal(0)):
        return _settle_locally(session)

    body = session.compute_settle_body
    rows = _unsettled(_session_rows(session))
    if body:
        rows.update(compute_settle_attempted_at=timezone.now())
    else:
        run = TaskRun.objects.select_related("task", "task__created_by").get(
            id=session.task_run_id, team_id=session.team_id
        )
        built = build_settlement_body(session, run, cost)
        rows.update(compute_settle_body=built, compute_settle_attempted_at=timezone.now())
        body = _session_rows(session).values_list("compute_settle_body", flat=True).first() or built
    try:
        response = report_spend(wallet_team_id(), body)
    except AIGatewayNotConfigured as error:
        observe_compute_settlement("deployment_error")
        logger.exception("compute_settlement.not_configured", session_id=str(session.id))
        raise ComputeSettlementDeploymentError(str(error)) from error
    except httpx.HTTPError:
        logger.warning("compute_settlement.transport_error", session_id=str(session.id), exc_info=True)
        return _record(SettlementOutcome.RETRY)

    status = response.status_code
    if status == 200:
        return _mark_settled(session, response)
    if status in _DEPLOYMENT_STATUSES:
        observe_compute_settlement("deployment_error")
        logger.error("compute_settlement.deployment_error", session_id=str(session.id), status=status)
        raise ComputeSettlementDeploymentError(f"gateway refused the compute debit with HTTP {status}")
    if status >= 500 or status in _RETRYABLE_STATUSES:
        logger.warning("compute_settlement.retryable_error", session_id=str(session.id), status=status)
        return _record(SettlementOutcome.RETRY)
    if status == 400:
        return _mark_contract_error(session, response)
    if status == 402 and (response.body or {}).get("code") == "insufficient_credits":
        error_text = _error_text(response)
        logger.error(
            "compute_settlement.insufficient_credits", session_id=str(session.id), status=status, error=error_text
        )
        _mark_conflict(session, error_text, ParkReason.HTTP_402)
        return _record(SettlementOutcome.INSUFFICIENT_CREDITS)
    if status == 409:
        logger.error("compute_settlement.conflict", session_id=str(session.id), status=status)
        _mark_conflict(session, _error_text(response), ParkReason.HTTP_409)
    else:
        logger.error("compute_settlement.unexpected_status", session_id=str(session.id), status=status)
        _mark_conflict(session, _error_text(response), ParkReason.UNEXPECTED_STATUS)
    return _record(SettlementOutcome.CONFLICT)


def settle_task_run_compute(task_run_id: UUID | str, team_id: int) -> list[SettlementOutcome]:
    if not settings.GATEWAY_COMPUTE_DEBIT_ENABLED:
        return []
    run_uuid = task_run_id if isinstance(task_run_id, UUID) else UUID(task_run_id)
    sessions = _unsettled(SandboxSession.objects.for_team(team_id).filter(task_run_id=run_uuid, ended_at__isnull=False))
    since = _settle_since()
    if since is not None:
        sessions = sessions.filter(ended_at__gte=since)
    return [settle_sandbox_session(session) for session in sessions]


def _overdue_ended(
    now: datetime, batch_size: int, processed: set[UUID], since: datetime | None
) -> list[SandboxSession]:
    overdue = _unsettled(SandboxSession.objects.unscoped()).filter(
        user_attributed_at__isnull=False, ended_at__lt=now - ENDED_GRACE
    )
    if since is not None:
        overdue = overdue.filter(ended_at__gte=since)
    return list(
        overdue.exclude(id__in=processed).order_by(F("compute_settle_attempted_at").asc(nulls_first=True), "ended_at")[
            :batch_size
        ]
    )


def _overdue_open_modal(now: datetime, batch_size: int, processed: set[UUID]) -> list[SandboxSession]:
    return list(
        _unsettled(SandboxSession.objects.unscoped())
        .filter(user_attributed_at__isnull=False, ended_at__isnull=True, ttl_expires_at__lt=now - TTL_GRACE)
        .exclude(sandbox_backend="hogland")
        .exclude(id__in=processed)
        .order_by("ttl_expires_at")[:batch_size]
    )


def _push_sweep_gauges(now: datetime, since: datetime | None) -> None:
    hogland_open_over_day = (
        SandboxSession.objects.unscoped()
        .filter(sandbox_backend="hogland", ended_at__isnull=True, created_at__lt=now - HOGLAND_OPEN_ALERT_AGE)
        .count()
    )
    unsettled_over_hour = 0
    if settings.GATEWAY_COMPUTE_DEBIT_ENABLED:
        overdue = _unsettled(SandboxSession.objects.unscoped()).filter(
            user_attributed_at__isnull=False, ended_at__lt=now - UNSETTLED_ALERT_AGE
        )
        if since is not None:
            overdue = overdue.filter(ended_at__gte=since)
        unsettled_over_hour = overdue.count()
    parked_counts = {
        row["compute_settle_park_reason"]: row["rows"]
        for row in SandboxSession.objects.unscoped()
        .filter(compute_settled_at__isnull=True, compute_settle_conflict_at__isnull=False)
        .order_by()
        .values("compute_settle_park_reason")
        .annotate(rows=Count("id"))
    }
    push_compute_settlement_sweep_gauges(
        hogland_open_over_day=hogland_open_over_day,
        unsettled_over_hour=unsettled_over_hour,
        parked_by_reason={reason: parked_counts.get(reason, 0) for reason in ParkReason.values},
    )


def _park_repeated_contract_errors(
    results: list[tuple[SandboxSession, SettlementOutcome]],
) -> list[SettlementOutcome]:
    contract_ids = [session.id for session, outcome in results if outcome in _CONTRACT_ERROR_OUTCOMES]
    if not contract_ids:
        return [outcome for _, outcome in results]
    errors: dict[UUID, str] = dict(
        SandboxSession.objects.unscoped().filter(id__in=contract_ids).values_list("id", "compute_settle_error")
    )
    if not any(outcome in _SETTLED_OUTCOMES for _, outcome in results):
        shared = Counter(errors[session_id] for session_id in contract_ids if errors.get(session_id)).most_common(1)
        if shared and shared[0][1] >= 2:
            error, count = shared[0]
            observe_compute_settlement("deployment_error")
            raise ComputeSettlementDeploymentError(
                f"gateway rejected {count} compute debits with the same error: {error}"
            )
    final: list[SettlementOutcome] = []
    for session, outcome in results:
        if outcome == SettlementOutcome.CONTRACT_ERROR_REPEAT:
            _mark_conflict(session, errors.get(session.id, ""), ParkReason.HTTP_400)
            outcome = _record(SettlementOutcome.CONFLICT)
        final.append(outcome)
    return final


def settle_overdue_sandbox_compute(
    now: datetime, batch_size: int = 50, time_budget: timedelta = timedelta(minutes=15)
) -> list[SettlementOutcome]:
    since: datetime | None = None
    try:
        if not settings.GATEWAY_COMPUTE_DEBIT_ENABLED:
            return []
        deadline = time.monotonic() + time_budget.total_seconds()
        results: list[tuple[SandboxSession, SettlementOutcome]] = []
        processed: set[UUID] = set()
        try:
            since = _settle_since()
            while True:
                batch = _overdue_ended(now, batch_size, processed, since)
                for session in batch:
                    processed.add(session.id)
                    results.append((session, _settle_safely(session)))
                if len(batch) < batch_size or time.monotonic() >= deadline:
                    break
            while True:
                batch = _overdue_open_modal(now, batch_size, processed)
                for session in batch:
                    processed.add(session.id)
                    close_sandbox_session(session.sandbox_id, reason=SandboxSession.EndedReason.TTL_SWEEP)
                    closed = SandboxSession.objects.unscoped().filter(id=session.id).first()
                    if closed is not None and closed.ended_at is not None:
                        results.append((closed, _settle_safely(closed)))
                if len(batch) < batch_size or time.monotonic() >= deadline:
                    break
            return _park_repeated_contract_errors(results)
        except ComputeSettlementDeploymentError as error:
            logger.exception("compute_settlement.sweep_stopped", error=str(error))
        return [outcome for _, outcome in results]
    finally:
        _push_sweep_gauges(now, since)


def _settle_safely(session: SandboxSession) -> SettlementOutcome:
    try:
        return settle_sandbox_session(session)
    except ComputeSettlementDeploymentError:
        raise
    except Exception:
        logger.exception("compute_settlement.settle_failed", session_id=str(session.id))
        return SettlementOutcome.SKIPPED


def unpark_sandbox_compute(reason: str, since: datetime, until: datetime) -> int:
    reset: dict[str, Any] = {
        "compute_settle_conflict_at": None,
        "compute_settle_park_reason": "",
        "compute_settle_error": "",
        "compute_settle_attempts": 0,
        "compute_settle_attempted_at": None,
    }
    if reason == ParkReason.HTTP_400:
        reset["compute_settle_body"] = {}
    return (
        SandboxSession.objects.unscoped()
        .filter(
            compute_settled_at__isnull=True,
            compute_settle_conflict_at__gte=since,
            compute_settle_conflict_at__lte=until,
            compute_settle_park_reason=reason,
        )
        .update(**reset)
    )


@frozen
class TeamComputeDelta:
    team_id: str
    local_usd: Decimal
    gateway_usd: Decimal
    local_rows: int

    @property
    def delta_usd(self) -> Decimal:
        return self.local_usd - self.gateway_usd


@frozen
class ComputeReconciliation:
    writer_parity: tuple[TeamComputeDelta, ...]
    pricing_parity: tuple[TeamComputeDelta, ...]
    billing_parity: tuple[TeamComputeDelta, ...]


def _report_column(rows: list[dict[str, Any]], column: str) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        keys = row.get("keys")
        obo = str((keys if isinstance(keys, dict) else row).get("obo") or "")
        try:
            value = Decimal(str(row.get(column) or "0"))
        except InvalidOperation:
            value = Decimal(0)
        totals[obo] = totals.get(obo, Decimal(0)) + value
    return totals


def _deltas(
    local: dict[str, Decimal], counts: dict[str, int], gateway: dict[str, Decimal]
) -> tuple[TeamComputeDelta, ...]:
    return tuple(
        TeamComputeDelta(
            team_id=team_id,
            local_usd=local.get(team_id, Decimal(0)),
            gateway_usd=gateway.get(team_id, Decimal(0)),
            local_rows=counts.get(team_id, 0),
        )
        for team_id in sorted(set(local) | set(gateway))
    )


def reconcile_compute_settlement(since: datetime, until: datetime, wallet_team: int) -> ComputeReconciliation:
    rows = get_usage_report_rows(
        {
            "team_id": str(wallet_team),
            "group_by": "obo,charge_kind",
            "charge_kind": "compute",
            "from": since.isoformat(),
            "to": until.isoformat(),
            "limit": "1000",
        }
    )
    gateway_compute = _report_column(rows, "compute_usd")

    settled_usd: dict[str, Decimal] = {}
    settled_rows: dict[str, int] = {}
    for row in (
        SandboxSession.objects.unscoped()
        .filter(compute_settled_at__gte=since, compute_settled_at__lt=until)
        .exclude(compute_ledger_entry_id="")
        .order_by()
        .values("team_id")
        .annotate(total=Sum("compute_settled_usd"), rows=Count("id"))
    ):
        key = str(row["team_id"])
        settled_usd[key] = row["total"] or Decimal(0)
        settled_rows[key] = row["rows"]

    priced_usd: dict[str, Decimal] = {}
    priced_rows: dict[str, int] = {}
    for session in (
        SandboxSession.objects.unscoped()
        .filter(user_attributed_at__isnull=False, ended_at__gte=since, ended_at__lt=until)
        .iterator()
    ):
        cost = session_compute_cost(session)
        key = str(session.team_id)
        priced_usd[key] = priced_usd.get(key, Decimal(0)) + (cost.total_cost_usd if cost else Decimal(0))
        priced_rows[key] = priced_rows.get(key, 0) + 1

    billing = get_billable_sandbox_compute_usage_by_team(since, until)
    billed_usd = {str(team_id): Decimal(credits) / 100 for team_id, credits in billing.credits}

    prorated_usd: dict[str, Decimal] = {}
    prorated_rows: dict[str, int] = {}
    calculated_at = timezone.now()
    for session in (
        SandboxSession.objects.unscoped()
        .filter(compute_settled_usd__isnull=False, user_attributed_at__lt=until, ended_at__gt=since)
        .exclude(compute_ledger_entry_id="")
        .iterator()
    ):
        if not is_billable_sandbox_session(session):
            continue
        lifetime = session_compute_cost(session)
        if lifetime is None or lifetime.total_cost_usd == 0:
            continue
        clipped = calculate_sandbox_compute_cost(
            session, since, until, calculated_at=calculated_at, rate_cards=COMPUTE_RATE_CARDS
        ).total_cost_usd
        assert session.compute_settled_usd is not None
        key = str(session.team_id)
        prorated_usd[key] = (
            prorated_usd.get(key, Decimal(0)) + session.compute_settled_usd * clipped / lifetime.total_cost_usd
        )
        prorated_rows[key] = prorated_rows.get(key, 0) + 1

    return ComputeReconciliation(
        writer_parity=_deltas(settled_usd, settled_rows, gateway_compute),
        pricing_parity=_deltas(priced_usd, priced_rows, gateway_compute),
        billing_parity=_deltas(billed_usd, prorated_rows, prorated_usd),
    )
