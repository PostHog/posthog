import asyncio
from dataclasses import field
from datetime import timedelta
from typing import TypedDict, cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

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

    signals = fetch_signals_for_report_sync(report.team, report_id, newest=1)
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


class SpendSource(TypedDict):
    cost_microusd: int | None
    stage: str
    is_task: bool
    task_id: str | None
    accounting_failed: bool
    finished: bool
    updated_at: str


def _sources(spend: SignalSpend) -> dict[str, SpendSource]:
    return cast(dict[str, SpendSource], spend.sources)


def _save_spend(spend: SignalSpend) -> None:
    sources = _sources(spend)
    cost = sum(source["cost_microusd"] or 0 for source in sources.values())
    tasks = sum(source["is_task"] for source in sources.values())
    if (cost, tasks) != (spend.token_cost_microusd, spend.task_count):
        spend.finalized_at = None
    spend.token_cost_microusd = cost
    spend.task_count = tasks
    spend.accounting_failed = any(source["accounting_failed"] for source in sources.values())
    finished = not spend.pending_work and all(source["finished"] for source in sources.values())
    spend.finalized_at = (spend.finalized_at or timezone.now()) if finished and not spend.accounting_failed else None
    spend.save()
    if spend.scout_run_id:
        scout = SignalScoutRun.objects.for_team(spend.team_id).select_for_update().get(id=spend.scout_run_id)
        scout.total_spend = cost_to_spend(cost, task_count=tasks)
        scout.metadata = {
            **(scout.metadata or {}),
            "spend_accounting_failed_stages": sorted(
                {source["stage"] for source in sources.values() if source["accounting_failed"]}
            ),
        }
        scout.save(update_fields=["total_spend", "metadata"])


def _merge_legacy_sources(spend: SignalSpend, legacy: list[LegacySignalSpend]) -> bool:
    sources = _sources(spend)
    changed = False
    # Old workers may still settle sources after the backfill during a rolling deploy.
    # Merge absolute observations by source identity, never add their totals a second time.
    for receipt in legacy:
        key = f"task:{receipt.source_id}" if receipt.is_task else receipt.source_id
        previous = sources.get(key)
        if previous is not None and previous["updated_at"] >= receipt.updated_at.isoformat():
            continue
        changed = True
        sources[key] = SpendSource(
            cost_microusd=receipt.token_cost_microusd
            if receipt.token_cost_microusd is not None
            else (previous["cost_microusd"] if previous else None),
            stage=receipt.stage,
            is_task=receipt.is_task,
            task_id=str(receipt.task_id) if receipt.task_id else None,
            accounting_failed=receipt.accounting_failed,
            finished=previous["finished"] if previous else not receipt.is_task,
            updated_at=receipt.updated_at.isoformat(),
        )
        if receipt.task_id and receipt.task_id not in spend.task_ids:
            spend.task_ids.append(receipt.task_id)
    return changed


def _locked_spend(
    *, team_id: int, signal_id: str | None = None, scout_run_id: str | None = None, create: bool = True
) -> SignalSpend | None:
    if (signal_id is None) == (scout_run_id is None):
        raise ValueError("Spend must have exactly one owner")
    owner = {"signal_id": signal_id} if signal_id is not None else {"scout_run_id": scout_run_id}
    queryset = SignalSpend.objects.for_team(team_id)
    if create or LegacySignalSpend.objects.for_team(team_id).filter(**owner).exists():
        queryset.get_or_create(team_id=team_id, **owner, defaults={"pending_work": ["pipeline"] if signal_id else []})
    spend = queryset.select_for_update().filter(**owner).first()
    if spend is None:
        return None
    _merge_legacy_sources(spend, list(LegacySignalSpend.objects.for_team(team_id).filter(**owner)))
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
            key = request_id or f"unknown-{uuid4()}"
            previous = _sources(spend).get(key)
            if previous is None and spend.finalized_at is not None:
                spend.pending_work = sorted(set(spend.pending_work) | {"pipeline"})
            if previous is None or token_cost_microusd is not None:
                _sources(spend)[key] = SpendSource(
                    cost_microusd=token_cost_microusd,
                    stage=stage,
                    is_task=False,
                    task_id=None,
                    accounting_failed=token_cost_microusd is None,
                    finished=True,
                    updated_at=timezone.now().isoformat(),
                )
            _save_spend(spend)
        if token_cost_microusd is None:
            logger.warning("signals.spend.generation_unaccounted", stage=stage, team_id=team_id, signal_id=signal_id)
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage=stage, team_id=team_id, signal_id=signal_id)


def signal_spend_summaries(*, team_id: int, signal_ids: list[str]) -> dict[str, SignalSpendSummary]:
    summaries: dict[str, SignalSpendSummary] = {}
    valid_ids: list[str] = []
    for signal_id in dict.fromkeys(signal_ids):
        try:
            UUID(signal_id)
        except ValueError:
            continue
        valid_ids.append(signal_id)
    try:
        owners = {
            str(spend.signal_id): spend
            for spend in SignalSpend.objects.for_team(team_id).filter(signal_id__in=valid_ids)
        }
        legacy: dict[str, list[LegacySignalSpend]] = {}
        for receipt in LegacySignalSpend.objects.for_team(team_id).filter(signal_id__in=valid_ids):
            legacy.setdefault(str(receipt.signal_id), []).append(receipt)
        for signal_id in owners.keys() | legacy.keys():
            spend = owners.get(signal_id)
            if spend is None or _merge_legacy_sources(spend, legacy.get(signal_id, [])):
                with transaction.atomic():
                    spend = _locked_spend(team_id=team_id, signal_id=signal_id)
                    assert spend is not None
                    _save_spend(spend)
            summaries[signal_id] = SignalSpendSummary(
                total_spend=float(cost_to_spend(spend.token_cost_microusd, task_count=spend.task_count)),
                failed_stages=sorted({s["stage"] for s in _sources(spend).values() if s["accounting_failed"]}),
            )
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
    from products.tasks.backend.facade.billing import (
        get_task_run_token_usage,  # noqa: PLC0415 — keeps task services off startup
    )

    if signal_id is None and scout_run_id is None:
        return
    run = get_task_run(run_id, team_id=team_id)
    if run is None:
        return
    with transaction.atomic():
        spend = _locked_spend(team_id=team_id, signal_id=signal_id, scout_run_id=scout_run_id)
        assert spend is not None
        usage = get_task_run_token_usage(team_id=team_id, run_id=UUID(run_id))
        key = f"task:{run_id}"
        previous = _sources(spend).get(key)
        _sources(spend)[key] = SpendSource(
            cost_microusd=usage.cost_microusd
            if usage.cost_microusd is not None
            else (previous["cost_microusd"] if previous else None),
            stage=previous["stage"] if previous else stage,
            is_task=True,
            task_id=str(run.task_id),
            accounting_failed=not usage.complete,
            finished=previous["finished"] if previous else False,
            updated_at=timezone.now().isoformat(),
        )
        if run.task_id not in spend.task_ids:
            spend.task_ids.append(run.task_id)
        if report_id:
            spend.report_id = UUID(report_id)
        if signal_id:
            if report_id:
                spend.pending_work = [work for work in spend.pending_work if work != "pipeline"]
            if (
                spend.report_id
                and SignalReport.objects.filter(
                    team_id=team_id,
                    id=spend.report_id,
                    status__in=[SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS],
                ).exists()
            ):
                spend.pending_work = sorted(set(spend.pending_work) | {f"report:{spend.report_id}"})
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
                stage = next(source["stage"] for source in _sources(previous).values() if source["task_id"] == task_id)
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


def refresh_task_spend(*, team_id: int, run_id: str) -> str | None:
    try:
        with transaction.atomic():
            spend = _task_spend(team_id=team_id, run_id=run_id)
            if spend is None:
                return None
            previous_finalized_at = spend.finalized_at
            source = _sources(spend).get(f"task:{run_id}")
            record_task_spend(
                team_id=team_id,
                run_id=run_id,
                stage=source["stage"] if source else ("scout" if spend.scout_run_id else "implementation"),
                signal_id=str(spend.signal_id) if spend.signal_id else None,
                scout_run_id=str(spend.scout_run_id) if spend.scout_run_id else None,
            )
            spend.refresh_from_db()
            if spend.signal_id and spend.finalized_at and spend.finalized_at != previous_finalized_at:
                return str(spend.signal_id)
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage="task_cost_update", team_id=team_id, run_id=run_id)
    return None


def complete_signal_pipeline(*, team_id: int, signal_id: str, report_id: str | None = None) -> None:
    try:
        with transaction.atomic():
            spend = _locked_spend(team_id=team_id, signal_id=signal_id)
            assert spend is not None
            pending = set(spend.pending_work)
            pending.discard("pipeline")
            if report_id:
                spend.report_id = UUID(report_id)
                report = SignalReport.objects.filter(team_id=team_id, id=report_id).first()
                if report and UUID(signal_id) in {report.triggering_signal_id, report.pending_triggering_signal_id}:
                    if report.status in {SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS}:
                        pending.add(f"report:{report_id}")
            spend.pending_work = sorted(pending)
            _save_spend(spend)
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage="pipeline_completion", team_id=team_id)


def begin_report_spend(*, team_id: int, report_id: str, signal_id: str) -> None:
    try:
        with transaction.atomic():
            spend = _locked_spend(team_id=team_id, signal_id=signal_id)
            assert spend is not None
            spend.report_id = UUID(report_id)
            spend.pending_work = sorted((set(spend.pending_work) - {"pipeline"}) | {f"report:{report_id}"})
            _save_spend(spend)
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage="report_start", team_id=team_id)


def finish_report_spend(*, team_id: int, report_id: str) -> None:
    try:
        with transaction.atomic():
            report = SignalReport.objects.filter(team_id=team_id, id=report_id).first()
            if report and report.status in {SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS}:
                return
            for spend in (
                SignalSpend.objects.for_team(team_id)
                .select_for_update()
                .filter(Q(report_id=report_id) | Q(pending_work__contains=[f"report:{report_id}"]))
            ):
                spend.pending_work = [work for work in spend.pending_work if work != f"report:{report_id}"]
                _save_spend(spend)
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage="report_completion", team_id=team_id)


def settle_signal_task_spend(*, team_id: int, signal_id: str) -> None:
    from products.tasks.backend.facade.billing import (
        process_pending_gateway_usage,  # noqa: PLC0415 — keeps task services off startup
    )

    with transaction.atomic():
        spend = _locked_spend(team_id=team_id, signal_id=signal_id, create=False)
        run_ids = (
            [key.removeprefix("task:") for key, source in _sources(spend).items() if source["is_task"]] if spend else []
        )
    for run_id in run_ids:
        try:
            process_pending_gateway_usage(run_id=UUID(run_id), team_id=team_id, limit=1000)
            refresh_task_spend(team_id=team_id, run_id=run_id)
        except Exception:
            logger.exception("signals.spend.accounting_failed", stage="task_settlement", team_id=team_id, run_id=run_id)


def _report_spend_signal_ids(*, team_id: int, report_id: str) -> list[str]:
    from products.tasks.backend.facade.api import (  # noqa: PLC0415 — keeps task services off startup
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
    from products.tasks.backend.facade.billing import (
        process_pending_gateway_usage,  # noqa: PLC0415 — keeps task services off startup
    )

    try:
        run = get_task_run(run_id, team_id=team_id)
        if run is None or not run.is_terminal:
            return
        process_pending_gateway_usage(run_id=UUID(run_id), team_id=team_id, limit=1000)
        refresh_task_spend(team_id=team_id, run_id=run_id)
        with transaction.atomic():
            spend = _task_spend(team_id=team_id, run_id=run_id)
            if spend is not None:
                source = _sources(spend).get(f"task:{run_id}")
                if source is not None:
                    source["finished"] = True
                    _save_spend(spend)
        if spend and spend.report_id:
            async_to_sync(publish_report_spend)(team_id=team_id, report_id=str(spend.report_id))
    except Exception:
        logger.exception("signals.spend.accounting_failed", stage="task_completion", team_id=team_id, run_id=run_id)
