from collections.abc import Awaitable, Callable, Coroutine, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import partial, wraps
from typing import Protocol
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django.db import transaction
from django.db.models import Count, Q, Sum

from posthog.dataclasses import frozen
from posthog.llm.usage import record_gateway_usage
from posthog.sync import database_sync_to_async

from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend
from products.signals.backend.pricing import cost_to_spend


@frozen
class SpendOwner:
    team_id: int
    signal_id: str


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
        with signal_spend_scope(input.team_id, input.signal_id):
            return await fn(input)

    return wrapped


def track_report_spend[I: ReportSpendInput, R](
    fn: Callable[[I], Awaitable[R]],
) -> Callable[[I], Coroutine[None, None, R]]:
    @wraps(fn)
    async def wrapped(input: I) -> R:
        signal_id = await database_sync_to_async(report_triggering_signal)(
            team_id=input.team_id, report_id=input.report_id
        )
        with signal_spend_scope(input.team_id, signal_id):
            return await fn(input)

    return wrapped


def signal_id_for(*, team_id: int, source_product: str, source_type: str, idempotency_key: str | None = None) -> str:
    return (
        str(uuid5(NAMESPACE_URL, f"signals:{team_id}:{source_product}:{source_type}:{idempotency_key}"))
        if idempotency_key
        else str(uuid4())
    )


def record_llm_request(request_id: str | None, *, team_id: int, signal_id: str) -> None:
    SignalSpend.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        source_id=request_id or f"unknown-{uuid4()}",
        is_task=False,
        defaults={"signal_id": signal_id, "needs_refresh": request_id is not None},
    )


@contextmanager
def signal_spend_scope(team_id: int | None, signal_id: str | None) -> Iterator[None]:
    if team_id is None or signal_id is None:
        yield
        return
    token = _owner.set(SpendOwner(team_id=team_id, signal_id=signal_id))
    try:
        with record_gateway_usage(partial(record_llm_request, team_id=team_id, signal_id=signal_id)):
            yield
    finally:
        _owner.reset(token)


def report_triggering_signal(*, team_id: int, report_id: str) -> str | None:
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
        defaults={"signal_id": signal_id, "scout_run_id": scout_run_id, "task_id": task_id},
    )


def signal_spend_totals(*, team_id: int, signal_ids: list[str]) -> dict[str, float | None]:
    valid_ids = []
    for signal_id in signal_ids:
        try:
            valid_ids.append(UUID(signal_id))
        except ValueError:
            continue
    if not valid_ids:
        return {}
    rows = (
        SignalSpend.objects.for_team(team_id)
        .filter(signal_id__in=valid_ids)
        .values("signal_id")
        .annotate(
            cost=Sum("token_cost_microusd"),
            tasks=Count("id", filter=Q(is_task=True)),
            pending=Count("id", filter=Q(token_cost_microusd__isnull=True)),
        )
    )
    return {
        str(row["signal_id"]): None
        if row["pending"]
        else float(cost_to_spend(row["cost"] or 0, task_count=row["tasks"]))
        for row in rows
    }


def refresh_task_spend(*, spend_id: UUID, team_id: int) -> None:
    from products.tasks.backend.facade.billing import (
        get_task_run_token_cost_microusd,  # noqa: PLC0415 — keeps task cost services off startup
    )

    with transaction.atomic():
        spend = SignalSpend.objects.for_team(team_id).select_for_update().get(id=spend_id)
        cost = get_task_run_token_cost_microusd(team_id=team_id, run_id=UUID(spend.source_id))
        spend.token_cost_microusd = cost
        spend.needs_refresh = cost is None
        spend.save(update_fields=["token_cost_microusd", "needs_refresh", "updated_at"])
        if spend.scout_run_id:
            SignalScoutRun.objects.for_team(team_id).filter(id=spend.scout_run_id).update(
                total_spend=cost_to_spend(cost, task_count=1) if cost is not None else None,
            )
