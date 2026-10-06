from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Count, Q, Sum

import structlog

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend
from products.signals.backend.pricing import cost_to_spend

logger = structlog.get_logger(__name__)


@frozen
class SignalSpendSummary:
    total_spend: float
    failed_stages: list[str]


def signal_id_for(*, team_id: int, source_product: str, source_type: str, idempotency_key: str | None = None) -> str:
    return (
        str(uuid5(NAMESPACE_URL, f"signals:{team_id}:{source_product}:{source_type}:{idempotency_key}"))
        if idempotency_key
        else str(uuid4())
    )


def report_triggering_signal(*, team_id: int, report_id: str) -> str | None:
    with transaction.atomic():
        signal_id = (
            SignalReport.objects.filter(team_id=team_id, id=report_id)
            .values_list("triggering_signal_id", flat=True)
            .first()
        )
    return str(signal_id) if signal_id else None


def record_llm_request(
    request_id: str | None,
    *,
    team_id: int | None,
    stage: str,
    signal_id: str | None = None,
) -> None:
    if team_id is None or signal_id is None:
        return
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
