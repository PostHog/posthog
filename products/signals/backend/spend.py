from __future__ import annotations

import asyncio
from dataclasses import field
from datetime import timedelta
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django.conf import settings
from django.db import transaction
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.dataclasses import frozen
from posthog.sync import database_sync_to_async

from products.signals.backend.models import (
    LegacySignalSpend,
    SignalReport,
    SignalReportTask,
    SignalScoutRun,
    SignalSpend,
)
from products.signals.backend.pricing import cost_to_spend
from products.signals.backend.spend_billing import (
    apply_report_billing,
    recognize_spend,
    scout_spend_exempt,
    usage_billing_enabled,
)

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from products.tasks.backend.facade.contracts import TaskRunDTO


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


async def publish_signal_spend(*, team_id: int, signal_id: str, wait_for_completion: bool = True) -> None:
    try:
        await submit_signal_metadata_updates(
            team_id=team_id, signal_ids=[signal_id], wait_for_completion=wait_for_completion
        )
    except Exception:
        logger.exception(
            "signals.spend.accounting_failed", stage="persist_metadata", team_id=team_id, signal_id=signal_id
        )


def _save_spend(spend: SignalSpend, *, finalize: bool = False) -> SignalSpendSummary:
    from products.tasks.backend.facade.billing import (
        get_task_runs_spend,  # noqa: PLC0415 — keeps task services off startup
    )

    owner = {"signal_id": spend.signal_id} if spend.signal_id else {"scout_run_id": spend.scout_run_id}
    legacy = list(LegacySignalSpend.objects.for_team(spend.team_id).filter(**owner))
    for receipt in legacy:
        if receipt.task_id and receipt.task_id not in spend.task_ids:
            spend.task_ids.append(receipt.task_id)
    runs = get_task_runs_spend(team_id=spend.team_id, task_ids=spend.task_ids)
    task_costs = {str(receipt.source_id): receipt.token_cost_microusd or 0 for receipt in legacy if receipt.is_task}
    failed_stages = set(spend.llm_failed_stages)
    failed_stages.update(receipt.stage for receipt in legacy if receipt.accounting_failed)
    for run in runs:
        task_costs[str(run.run_id)] = max(task_costs.get(str(run.run_id), 0), run.cost_microusd or 0)
        if not run.complete:
            failed_stages.add("scout" if spend.scout_run_id else run.stage)
    cost = spend.llm_cost_microusd + sum(receipt.token_cost_microusd or 0 for receipt in legacy if not receipt.is_task)
    cost += sum(task_costs.values())
    if (cost, len(task_costs)) != (spend.token_cost_microusd, spend.task_count):
        spend.finalized_at = None
    spend.token_cost_microusd = cost
    spend.task_count = len(task_costs)
    spend.accounting_failed = bool(failed_stages)
    if spend.accounting_failed or any(not run.is_terminal for run in runs):
        spend.finalized_at = None
    elif finalize:
        spend.finalized_at = spend.finalized_at or timezone.now()
    recognize_spend(spend, now=timezone.now())
    spend.save()
    summary = SignalSpendSummary(
        total_spend=float(cost_to_spend(cost, task_count=spend.task_count)), failed_stages=sorted(failed_stages)
    )
    if spend.scout_run_id:
        scout = SignalScoutRun.objects.for_team(spend.team_id).filter(id=spend.scout_run_id).first()
        if scout:
            scout.total_spend = cost_to_spend(cost, task_count=spend.task_count)
            scout.metadata = {**(scout.metadata or {}), "spend_accounting_failed_stages": summary.failed_stages}
            scout.save(update_fields=["total_spend", "metadata"])
    return summary


def _locked_spend(
    *,
    team_id: int,
    signal_id: str | None = None,
    scout_run_id: str | None = None,
    create: bool = True,
    report_id: str | None = None,
) -> SignalSpend | None:
    if (signal_id is None) == (scout_run_id is None):
        raise ValueError("Spend must have exactly one owner")
    owner = {"signal_id": signal_id} if signal_id is not None else {"scout_run_id": scout_run_id}
    queryset = SignalSpend.objects.for_team(team_id)
    spend = queryset.select_for_update().filter(**owner).first()
    if spend is None:
        legacy_exists = LegacySignalSpend.objects.for_team(team_id).filter(**owner).exists()
        if not create and not legacy_exists:
            return None
        report = SignalReport.objects.filter(team_id=team_id, id=report_id).first() if report_id else None
        usage_billing = not legacy_exists and (report.usage_based_billing if report else usage_billing_enabled(team_id))
        scout = SignalScoutRun.objects.for_team(team_id).filter(id=scout_run_id).first() if scout_run_id else None
        queryset.get_or_create(
            team_id=team_id,
            **owner,
            defaults={
                "usage_based_billing": usage_billing,
                "billing_exempt": scout_spend_exempt(scout) if scout else False,
            },
        )
        spend = queryset.select_for_update().get(**owner)
    return spend


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
            spend = _locked_spend(team_id=team_id, signal_id=signal_id)
            assert spend is not None
            spend.finalized_at = None
            if token_cost_microusd is None:
                spend.llm_failed_stages = sorted(set(spend.llm_failed_stages) | {stage})
            else:
                # This runs once where generation returns. Retrying generation makes another paid call.
                spend.llm_cost_microusd += token_cost_microusd
            _save_spend(spend)
        if token_cost_microusd is None:
            logger.warning(
                "signals.spend.generation_unaccounted",
                stage=stage,
                team_id=team_id,
                signal_id=signal_id,
                request_id=request_id,
            )
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage=stage, team_id=team_id, signal_id=signal_id)


def signal_spend_summaries(*, team_id: int, signal_ids: list[str]) -> dict[str, SignalSpendSummary]:
    summaries: dict[str, SignalSpendSummary] = {}
    for signal_id in dict.fromkeys(signal_ids):
        try:
            UUID(signal_id)
        except ValueError:
            continue
        try:
            with transaction.atomic():
                spend = _locked_spend(team_id=team_id, signal_id=signal_id, create=False)
                if spend:
                    summaries[signal_id] = _save_spend(spend)
        except Exception:
            logger.exception("signals.spend.accounting_failed", stage="read_spend", team_id=team_id)
    return summaries


def signal_spend_totals(*, team_id: int, signal_ids: list[str]) -> dict[str, float]:
    return {
        key: value.total_spend for key, value in signal_spend_summaries(team_id=team_id, signal_ids=signal_ids).items()
    }


def record_task_spend(
    *,
    team_id: int,
    run_id: str,
    stage: str,
    signal_id: str | None = None,
    scout_run_id: str | None = None,
    report_id: str | None = None,
) -> None:
    from products.tasks.backend.facade.api import get_task_run  # noqa: PLC0415 — keeps task services off startup

    if signal_id is None and scout_run_id is None:
        return
    run = get_task_run(run_id, team_id=team_id)
    if run is None:
        return
    with transaction.atomic():
        spend = _locked_spend(team_id=team_id, signal_id=signal_id, scout_run_id=scout_run_id, report_id=report_id)
        assert spend is not None
        if run.task_id not in spend.task_ids:
            spend.task_ids.append(run.task_id)
        if report_id:
            spend.report_id = UUID(report_id)
            report = SignalReport.objects.filter(team_id=team_id, id=report_id).first()
            if report:
                apply_report_billing(spend, report)
        _save_spend(spend)


def register_report_task_spend(*, team_id: int, run_id: str, task_id: str, report_id: str, stage: str | None) -> None:
    signal_id: str | None
    try:
        with transaction.atomic():
            previous = (
                SignalSpend.objects.for_team(team_id)
                .filter(task_ids__contains=[UUID(task_id)], signal_id__isnull=False)
                .first()
            )
            legacy = LegacySignalSpend.objects.for_team(team_id).filter(task_id=task_id, is_task=True).first()
            if previous is not None:
                signal_id = str(previous.signal_id)
            elif legacy is not None:
                signal_id, stage = str(legacy.signal_id), legacy.stage
            else:
                if (
                    stage not in {"research", "implementation", "repo_selection"}
                    and not SignalReportTask.objects.filter(
                        team_id=team_id, task_id=task_id, relationship="implementation"
                    ).exists()
                ):
                    return
                signal_id = report_triggering_signal(team_id=team_id, report_id=report_id)
            record_task_spend(
                team_id=team_id,
                run_id=run_id,
                report_id=report_id,
                signal_id=signal_id,
                stage=stage or "implementation",
            )
    except Exception:
        logger.exception(
            "signals.spend.accounting_failed", stage=stage or "implementation", team_id=team_id, run_id=run_id
        )


def _task_spend(*, team_id: int, run_id: str) -> SignalSpend | None:
    from products.tasks.backend.facade.api import get_task_run  # noqa: PLC0415 — keeps task services off startup

    scout = SignalScoutRun.objects.for_team(team_id).filter(task_run_id=UUID(run_id)).first()
    if scout:
        return _locked_spend(team_id=team_id, scout_run_id=str(scout.id))
    run = get_task_run(run_id, team_id=team_id)
    if run is None:
        return None
    owner = (
        SignalSpend.objects.for_team(team_id).filter(task_ids__contains=[run.task_id], signal_id__isnull=False).first()
    )
    if owner is not None:
        return _locked_spend(team_id=team_id, signal_id=str(owner.signal_id))
    legacy = LegacySignalSpend.objects.for_team(team_id).filter(source_id=run_id, is_task=True).first()
    if legacy and legacy.signal_id:
        return _locked_spend(team_id=team_id, signal_id=str(legacy.signal_id))
    return None


def complete_signal_pipeline(
    *, team_id: int, signal_id: str, report_id: str | None = None, billing_exempt: bool = False
) -> None:
    try:
        with transaction.atomic():
            spend = _locked_spend(team_id=team_id, signal_id=signal_id, report_id=report_id)
            assert spend is not None
            spend.billing_exempt = spend.billing_exempt or billing_exempt
            report = SignalReport.objects.filter(team_id=team_id, id=report_id).first() if report_id else None
            if report:
                spend.report_id = report.id
                apply_report_billing(spend, report)
            # READY can still be waiting for implementation; the report workflow owns completion.
            handed_off = (
                report
                and UUID(signal_id) in {report.triggering_signal_id, report.pending_triggering_signal_id}
                and report.status != SignalReport.Status.POTENTIAL
            )
            _save_spend(spend, finalize=not handed_off)
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage="pipeline_completion", team_id=team_id)


def begin_report_spend(*, team_id: int, report_id: str, signal_id: str) -> None:
    try:
        with transaction.atomic():
            spend = _locked_spend(team_id=team_id, signal_id=signal_id, report_id=report_id)
            assert spend is not None
            spend.report_id = UUID(report_id)
            spend.finalized_at = None
            report = SignalReport.objects.filter(team_id=team_id, id=report_id).first()
            if report:
                apply_report_billing(spend, report)
            _save_spend(spend)
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage="report_start", team_id=team_id)


def finish_report_spend(*, team_id: int, report_id: str, allow_candidate: bool = False) -> None:
    with transaction.atomic():
        report = SignalReport.objects.filter(team_id=team_id, id=report_id).first()
        if report and (
            report.status == SignalReport.Status.IN_PROGRESS
            or (report.status == SignalReport.Status.CANDIDATE and not allow_candidate)
        ):
            return
        for spend in SignalSpend.objects.for_team(team_id).select_for_update().filter(report_id=report_id):
            if report:
                apply_report_billing(spend, report)
            _save_spend(spend, finalize=True)


def _report_implementation_runs(*, team_id: int, report_id: str) -> list[TaskRunDTO]:
    from products.tasks.backend.facade.api import (  # noqa: PLC0415 — keeps task services off startup
        get_signal_report_implementation_runs,
    )

    task_ids = list(
        SignalReportTask.objects.filter(
            team_id=team_id, report_id=report_id, relationship="implementation"
        ).values_list("task_id", flat=True)
    )
    return get_signal_report_implementation_runs(team_id, report_id, task_ids)


async def complete_report_spend(*, team_id: int, report_id: str) -> None:
    from temporalio.client import WorkflowFailureError  # noqa: PLC0415 — keeps Temporal off Django startup

    from posthog.temporal.common.client import async_connect  # noqa: PLC0415 — keeps Temporal off Django startup

    from products.tasks.backend.facade.agents import (  # noqa: PLC0415 — keeps task workflows off Django startup
        wait_for_task_completion,
    )

    runs = await database_sync_to_async(_report_implementation_runs)(team_id=team_id, report_id=report_id)
    if any(not run.is_terminal for run in runs):
        # The implementation workflow will finalize after its teardown; research can return now.
        return
    if runs:
        client = await async_connect()
        for run in runs:
            if not run.workflow_id:
                return
            try:
                await wait_for_task_completion(client.get_workflow_handle(run.workflow_id))
            except WorkflowFailureError:
                # Failed work still incurs spend. Finalization below also requires settled usage.
                pass
    await database_sync_to_async(finish_report_spend)(team_id=team_id, report_id=report_id, allow_candidate=True)


def _report_spend_signal_ids(*, team_id: int, report_id: str) -> list[str]:
    report = SignalReport.objects.filter(team_id=team_id, id=report_id).first()
    if report is None or report.status == SignalReport.Status.IN_PROGRESS:
        return []
    runs = _report_implementation_runs(team_id=team_id, report_id=report_id)
    if any(not run.is_terminal for run in runs):
        return []
    owners = set(
        SignalSpend.objects.for_team(team_id)
        .filter(report_id=report_id, signal_id__isnull=False)
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
    from products.tasks.backend.facade.api import get_task_run  # noqa: PLC0415 — keeps task services off startup
    from products.tasks.backend.facade.billing import (  # noqa: PLC0415 — keeps task services off startup
        TaskTokenUsageUnavailable,
        get_task_run_token_usage,
        process_pending_gateway_usage,
    )

    run = get_task_run(run_id, team_id=team_id)
    if run is None or not run.is_terminal:
        return
    with transaction.atomic():
        spend = _task_spend(team_id=team_id, run_id=run_id)
        if spend is None:
            return
        if run.task_id not in spend.task_ids:
            spend.task_ids.append(run.task_id)
            spend.save(update_fields=["task_ids"])
    process_pending_gateway_usage(run_id=UUID(run_id), team_id=team_id, limit=1000)
    usage = get_task_run_token_usage(run_id=UUID(run_id), team_id=team_id)
    if not usage.complete:
        raise TaskTokenUsageUnavailable("Task usage is not settled yet")
    with transaction.atomic():
        spend = _task_spend(team_id=team_id, run_id=run_id)
        if spend is None:
            return
        _save_spend(spend, finalize=spend.scout_run_id is not None)
    if spend.report_id:
        # Research stays open until its parent finishes the implementation decision.
        if (run.state or {}).get("ai_stage") not in {"research", "repo_selection"}:
            finish_report_spend(team_id=team_id, report_id=str(spend.report_id))
        async_to_sync(publish_report_spend)(team_id=team_id, report_id=str(spend.report_id))
