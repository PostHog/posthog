import asyncio
from dataclasses import field
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async

from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportTask,
    SignalScoutRun,
    SignalSpend,
)
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


def report_triggering_signal(
    *, team_id: int, report_id: str, ch_user: ClickHouseUser = ClickHouseUser.DEFAULT
) -> str | None:
    with transaction.atomic():
        report = (
            SignalReport.objects.filter(team_id=team_id, id=report_id).only("triggering_signal_id", "team_id").first()
        )
    if report is None:
        return None
    if report.triggering_signal_id is not None:
        return str(report.triggering_signal_id)

    from products.signals.backend.signal_metadata import (
        fetch_signals_for_report_sync,  # noqa: PLC0415 — keeps HogQL off Django startup
    )

    signals = fetch_signals_for_report_sync(report.team, report_id, newest=1, ch_user=ch_user)
    if not signals:
        return None
    with transaction.atomic():
        reports = SignalReport.objects.filter(team_id=team_id, id=report_id)
        reports.filter(triggering_signal_id__isnull=True).update(triggering_signal_id=signals[0]["signal_id"])
        signal_id = reports.values_list("triggering_signal_id", flat=True).get()
    return str(signal_id)


@frozen
class SignalMetadataChange:
    report_id: str | None = None
    deleted: bool = False
    clear_content: bool = False
    expected_report_id: str | None = None


@frozen
class SignalSpendUpdate:
    team_id: int
    signal_id: str
    changes: list[SignalMetadataChange] = field(default_factory=list)


@frozen
class SignalSpendPublication:
    signal: SignalSpendUpdate
    summary: SignalSpendSummary
    versions: dict[str, int]


async def submit_signal_metadata_updates(
    *,
    team_id: int,
    signal_ids: list[str],
    change: SignalMetadataChange | None = None,
    wait_for_completion: bool = False,
) -> None:
    from temporalio.common import WorkflowIDReusePolicy  # noqa: PLC0415 — keeps Temporal off Django startup

    from posthog.temporal.common.client import async_connect  # noqa: PLC0415 — keeps Temporal off Django startup

    if not signal_ids:
        return
    client = await asyncio.wait_for(async_connect(), timeout=5)
    for start in range(0, len(signal_ids), 20):
        handles = await asyncio.gather(
            *(
                client.start_workflow(
                    "update-signal-spend",
                    SignalSpendUpdate(team_id=team_id, signal_id=signal_id),
                    id=f"signal-spend-{team_id}-{signal_id}",
                    task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    start_signal="update_metadata" if change else "refresh",
                    start_signal_args=[change] if change else [],
                    execution_timeout=timedelta(minutes=15),
                    rpc_timeout=timedelta(seconds=5),
                )
                for signal_id in signal_ids[start : start + 20]
            )
        )
        if wait_for_completion:
            await asyncio.gather(*(handle.result() for handle in handles))


async def publish_signal_spend(*, team_id: int, signal_id: str) -> None:
    try:
        await submit_signal_metadata_updates(team_id=team_id, signal_ids=[signal_id], wait_for_completion=True)
    except Exception:
        logger.exception(
            "signals.spend.accounting_failed", stage="persist_metadata", team_id=team_id, signal_id=signal_id
        )


def record_llm_spend(
    request_id: str | None,
    *,
    token_cost_microusd: int | None,
    team_id: int | None,
    stage: str,
    signal_id: str | None = None,
) -> None:
    if team_id is None or signal_id is None:
        return
    try:
        with transaction.atomic():
            spend, created = SignalSpend.objects.for_team(team_id).get_or_create(
                team_id=team_id,
                source_id=request_id or f"unknown-{uuid4()}",
                is_task=False,
                defaults={
                    "signal_id": signal_id,
                    "stage": stage,
                    "token_cost_microusd": token_cost_microusd,
                    "accounting_failed": token_cost_microusd is None,
                },
            )
            if not created and token_cost_microusd is not None:
                SignalSpend.objects.for_team(team_id).filter(id=spend.id).update(
                    token_cost_microusd=token_cost_microusd,
                    accounting_failed=False,
                    updated_at=timezone.now(),
                )
        if token_cost_microusd is None:
            logger.warning("signals.spend.generation_unaccounted", stage=stage, team_id=team_id, signal_id=signal_id)
    except Exception:
        logger.exception(
            "signals.spend.accounting_failed", stage=stage, team_id=team_id, signal_id=signal_id, request_id=request_id
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
    try:
        from products.tasks.backend.facade.billing import (
            get_task_run_token_usage,  # noqa: PLC0415 — keeps task cost services off startup
        )

        with transaction.atomic():
            spend = SignalSpend.objects.for_team(team_id).select_for_update().get(id=spend_id)
            usage = get_task_run_token_usage(team_id=team_id, run_id=UUID(spend.source_id))
            if usage.cost_microusd is not None:
                spend.token_cost_microusd = usage.cost_microusd
            spend.accounting_failed = not usage.complete
            spend.save(update_fields=["token_cost_microusd", "accounting_failed", "updated_at"])
            if not usage.complete:
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
    except Exception:
        logger.exception(
            "signals.spend.accounting_failed", stage="task_cost_update", team_id=team_id, spend_id=str(spend_id)
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
    spend, _ = SignalSpend.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        source_id=run_id,
        is_task=True,
        defaults={"signal_id": signal_id, "scout_run_id": scout_run_id, "task_id": task_id, "stage": stage},
    )
    refresh_task_spend(spend_id=spend.id, team_id=team_id)


def _settle_task_spend(spend: SignalSpend) -> None:
    from products.tasks.backend.facade.billing import (  # noqa: PLC0415 — keeps task services off startup
        process_pending_gateway_usage,
    )

    try:
        process_pending_gateway_usage(run_id=UUID(spend.source_id), team_id=spend.team_id, limit=1000)
        refresh_task_spend(spend_id=spend.id, team_id=spend.team_id)
    except Exception:
        with transaction.atomic():
            SignalSpend.objects.for_team(spend.team_id).filter(id=spend.id).update(accounting_failed=True)
        logger.exception(
            "signals.spend.accounting_failed", stage=spend.stage, team_id=spend.team_id, source_id=spend.source_id
        )


def settle_signal_task_spend(*, team_id: int, signal_id: str) -> None:
    for spend in SignalSpend.objects.for_team(team_id).filter(signal_id=signal_id, is_task=True):
        _settle_task_spend(spend)


def _report_spend_signal_ids(*, team_id: int, report_id: str) -> list[str]:
    from products.tasks.backend.facade.api import (  # noqa: PLC0415 — keeps the task facade off startup
        TaskRunStatus,
        get_signal_report_implementation_runs,
    )

    report = SignalReport.objects.filter(team_id=team_id, id=report_id).first()
    if report is None or report.status == SignalReport.Status.IN_PROGRESS:
        return []
    task_ids = list(
        SignalReportTask.objects.filter(
            team_id=team_id, report_id=report_id, relationship="implementation"
        ).values_list("task_id", flat=True)
    )
    runs = get_signal_report_implementation_runs(team_id, report_id, task_ids)
    if any(run.status not in {TaskRunStatus.COMPLETED, TaskRunStatus.FAILED, TaskRunStatus.CANCELLED} for run in runs):
        return []
    task_ids.extend(
        SignalReportArtefact.objects.filter(team_id=team_id, report_id=report_id, task_id__isnull=False).values_list(
            "task_id", flat=True
        )
    )
    owners = set(
        SignalSpend.objects.for_team(team_id)
        .filter(task_id__in=task_ids, signal_id__isnull=False)
        .values_list("signal_id", flat=True)
    )
    if report.triggering_signal_id:
        owners.add(report.triggering_signal_id)
    return sorted(str(owner) for owner in owners)


async def publish_report_spend(*, team_id: int, report_id: str) -> None:
    try:
        signal_ids = await database_sync_to_async(_report_spend_signal_ids)(team_id=team_id, report_id=report_id)
        for signal_id in signal_ids:
            await publish_signal_spend(team_id=team_id, signal_id=signal_id)
    except Exception:
        logger.exception(
            "signals.spend.accounting_failed", stage="report_completion", team_id=team_id, report_id=report_id
        )


def complete_task_spend(*, team_id: int, run_id: str) -> None:
    try:
        spend = SignalSpend.objects.for_team(team_id).filter(source_id=run_id, is_task=True).first()
        if spend is None:
            return
        if spend.scout_run_id:
            _settle_task_spend(spend)
        else:
            refresh_task_spend(spend_id=spend.id, team_id=team_id)
        if spend.stage == "implementation" and spend.task_id:
            report_ids = SignalReportTask.objects.filter(
                team_id=team_id, task_id=spend.task_id, relationship="implementation"
            ).values_list("report_id", flat=True)
            for report_id in report_ids:
                async_to_sync(publish_report_spend)(team_id=team_id, report_id=str(report_id))
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage="task_completion", team_id=team_id, run_id=run_id)
