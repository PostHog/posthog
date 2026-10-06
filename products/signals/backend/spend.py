from collections.abc import Awaitable, Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial, wraps
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Count, Q, Sum

import structlog

from posthog.dataclasses import frozen
from posthog.llm.usage import record_gateway_usage
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend
from products.signals.backend.pricing import cost_to_spend

logger = structlog.get_logger(__name__)


@frozen
class SpendOwner:
    team_id: int
    signal_id: str


@frozen
class SignalSpendSummary:
    total_spend: float
    failed_stages: list[str]


_owner: ContextVar[SpendOwner | None] = ContextVar("signal_spend_owner", default=None)


def current_spend_signal_id(team_id: int) -> str | None:
    owner = _owner.get()
    return owner.signal_id if owner and owner.team_id == team_id else None


class SignalSpendInput(Protocol):
    @property
    def team_id(self) -> int | None: ...

    @property
    def signal_id(self) -> str | None: ...


class ReportSpendInput(Protocol):
    @property
    def team_id(self) -> int: ...

    @property
    def report_id(self) -> str: ...


def track_signal_spend[I: SignalSpendInput, R](
    fn: Callable[[I], Awaitable[R]],
) -> Callable[[I], Coroutine[None, None, R]]:
    @wraps(fn)
    async def wrapped(input: I) -> R:
        with signal_spend_scope(input.team_id, input.signal_id, stage=fn.__name__.removesuffix("_activity")):
            return await fn(input)

    return wrapped


def track_report_spend[I: ReportSpendInput, R](
    fn: Callable[[I], Awaitable[R]],
) -> Callable[[I], Coroutine[None, None, R]]:
    @wraps(fn)
    async def wrapped(input: I) -> R:
        stage = fn.__name__.removesuffix("_activity")
        try:
            signal_id = await database_sync_to_async(report_triggering_signal)(
                team_id=input.team_id, report_id=input.report_id
            )
        except Exception:
            logger.exception(
                "signals.spend.accounting_failed", stage=stage, team_id=input.team_id, report_id=input.report_id
            )
            signal_id = None
        with signal_spend_scope(input.team_id, signal_id, stage=stage):
            return await fn(input)

    return wrapped


def signal_id_for(*, team_id: int, source_product: str, source_type: str, idempotency_key: str | None = None) -> str:
    return (
        str(uuid5(NAMESPACE_URL, f"signals:{team_id}:{source_product}:{source_type}:{idempotency_key}"))
        if idempotency_key
        else str(uuid4())
    )


def record_llm_request(request_id: str | None, *, team_id: int, signal_id: str, stage: str) -> None:
    try:
        with transaction.atomic():
            SignalSpend.objects.for_team(team_id).get_or_create(
                team_id=team_id,
                source_id=request_id or f"unknown-{uuid4()}",
                is_task=False,
                defaults={
                    "signal_id": signal_id,
                    "stage": stage,
                    "needs_refresh": request_id is not None,
                    "accounting_failed": request_id is None,
                },
            )
        if request_id is None:
            logger.warning("signals.spend.generation_unaccounted", stage=stage, team_id=team_id, signal_id=signal_id)
    except Exception:
        logger.exception(
            "signals.spend.accounting_failed", stage=stage, team_id=team_id, signal_id=signal_id, request_id=request_id
        )


@contextmanager
def signal_spend_scope(team_id: int | None, signal_id: str | None, *, stage: str) -> Iterator[None]:
    if team_id is None or signal_id is None:
        yield
        return
    token = _owner.set(SpendOwner(team_id=team_id, signal_id=signal_id))
    try:
        with record_gateway_usage(partial(record_llm_request, team_id=team_id, signal_id=signal_id, stage=stage)):
            yield
    finally:
        _owner.reset(token)


def report_triggering_signal(*, team_id: int, report_id: str) -> str | None:
    with transaction.atomic():
        signal_id = (
            SignalReport.objects.filter(team_id=team_id, id=report_id)
            .values_list("triggering_signal_id", flat=True)
            .first()
        )
    return str(signal_id) if signal_id else None


def record_task_spend(
    *,
    team_id: int,
    run_id: str,
    stage: str,
    signal_id: str | None = None,
    scout_run_id: str | None = None,
    task_id: str | None = None,
) -> None:
    if signal_id is None and scout_run_id is None:
        return
    if (signal_id is None) == (scout_run_id is None):
        raise ValueError("A task's spend must have exactly one owner")
    SignalSpend.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        source_id=run_id,
        is_task=True,
        defaults={"signal_id": signal_id, "scout_run_id": scout_run_id, "task_id": task_id, "stage": stage},
    )


def signal_spend_summaries(*, team_id: int, signal_ids: list[str]) -> dict[str, SignalSpendSummary]:
    valid_ids = []
    for signal_id in signal_ids:
        try:
            valid_ids.append(UUID(signal_id))
        except ValueError:
            continue
    if not valid_ids:
        return {}
    try:
        with transaction.atomic():
            rows = (
                SignalSpend.objects.for_team(team_id)
                .filter(signal_id__in=valid_ids)
                .values("signal_id")
                .annotate(
                    cost=Sum("token_cost_microusd"),
                    tasks=Count("id", filter=Q(is_task=True)),
                    failed_stages=ArrayAgg("stage", distinct=True, filter=Q(accounting_failed=True)),
                )
            )
            return {
                str(row["signal_id"]): SignalSpendSummary(
                    total_spend=float(cost_to_spend(row["cost"] or 0, task_count=row["tasks"])),
                    failed_stages=sorted(row["failed_stages"] or []),
                )
                for row in rows
            }
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage="read_spend", team_id=team_id, signal_ids=signal_ids)
        return {}


def signal_spend_totals(*, team_id: int, signal_ids: list[str]) -> dict[str, float]:
    return {
        signal_id: summary.total_spend
        for signal_id, summary in signal_spend_summaries(team_id=team_id, signal_ids=signal_ids).items()
    }


def refresh_task_spend(*, spend_id: UUID, team_id: int) -> None:
    from products.tasks.backend.facade.billing import (
        get_task_run_token_cost_microusd,  # noqa: PLC0415 — keeps task cost services off startup
    )

    with transaction.atomic():
        spend = SignalSpend.objects.for_team(team_id).select_for_update().get(id=spend_id)
        cost = get_task_run_token_cost_microusd(team_id=team_id, run_id=UUID(spend.source_id))
        if cost is not None:
            spend.token_cost_microusd = cost
        spend.accounting_failed = cost is None
        spend.needs_refresh = cost is None
        spend.save(update_fields=["token_cost_microusd", "accounting_failed", "needs_refresh", "updated_at"])
        if cost is None:
            logger.warning(
                "signals.spend.generation_unaccounted",
                stage=spend.stage,
                team_id=team_id,
                signal_id=str(spend.signal_id) if spend.signal_id else None,
                scout_run_id=str(spend.scout_run_id) if spend.scout_run_id else None,
                request_id=spend.source_id,
            )
        if spend.scout_run_id:
            scout_run = SignalScoutRun.objects.for_team(team_id).select_for_update().get(id=spend.scout_run_id)
            scout_run.total_spend = cost_to_spend(spend.token_cost_microusd or 0, task_count=1)
            scout_run.metadata = {
                **(scout_run.metadata or {}),
                "spend_accounting_failed_stages": [spend.stage] if spend.accounting_failed else [],
            }
            scout_run.save(update_fields=["total_spend", "metadata"])
