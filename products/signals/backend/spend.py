from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import field
from datetime import timedelta
from decimal import Decimal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from django.conf import settings
from django.db import transaction
from django.db.models import F, Func, JSONField, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from asgiref.sync import async_to_sync

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport, SignalScoutRun, SignalSpend
from products.signals.backend.pricing import cost_to_spend
from products.signals.backend.spend_billing import apply_report_billing, scout_spend_exempt, trial_spend_exempt


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


def finalized_signal_ids(*, team_id: int, signal_ids: Sequence[str]) -> set[str]:
    if not signal_ids:
        return set()
    return {
        str(signal_id)
        for signal_id in SignalSpend.objects.for_team(team_id)
        .filter(kind=SignalSpend.Kind.AD_HOC, signal_id__in=signal_ids, finalized_at__isnull=False)
        .values_list("signal_id", flat=True)
    }


def report_triggering_signal(
    *, team_id: int, report_id: str, ch_user: ClickHouseUser = ClickHouseUser.DEFAULT
) -> str | None:
    report = SignalReport.objects.filter(team_id=team_id, id=report_id).only("triggering_signal_id", "team_id").first()
    if report is None:
        return None
    if report.triggering_signal_id is not None:
        return str(report.triggering_signal_id)

    from products.signals.backend.signal_metadata import (
        fetch_signals_for_report_sync,  # noqa: PLC0415 — keeps HogQL off Django startup
    )

    signals = fetch_signals_for_report_sync(report.team, report_id, newest=1, ch_user=ch_user)
    if not signals or finalized_signal_ids(team_id=team_id, signal_ids=[signals[0]["signal_id"]]):
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
) -> None:
    from temporalio.common import WorkflowIDReusePolicy  # noqa: PLC0415 — keeps Temporal off Django startup

    from posthog.temporal.common.client import async_connect  # noqa: PLC0415 — keeps Temporal off Django startup

    if not signal_ids:
        return
    client = await asyncio.wait_for(async_connect(), timeout=5)
    for start in range(0, len(signal_ids), 20):
        await asyncio.gather(
            *(
                client.start_workflow(
                    "update-signal-spend",
                    SignalSpendUpdate(team_id=team_id, signal_id=signal_id),
                    id=f"signal-spend-{team_id}-{signal_id}",
                    task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                    start_signal="update_metadata" if change else "refresh",
                    start_signal_args=[change] if change else [],
                    rpc_timeout=timedelta(seconds=5),
                )
                for signal_id in signal_ids[start : start + 20]
            )
        )


def _locked_ad_hoc_spend(*, team_id: int, signal_id: str) -> SignalSpend:
    spend, _ = SignalSpend.objects.for_team(team_id).get_or_create(
        team_id=team_id,
        signal_id=signal_id,
        kind=SignalSpend.Kind.AD_HOC,
        # get_or_create calls callable defaults only when it creates the row, so the trial lookup is
        # skipped for existing rows. django-stubs types defaults as plain field values.
        defaults={"billing_exempt": lambda: trial_spend_exempt(team_id)},  # type: ignore[misc]
    )
    return SignalSpend.objects.for_team(team_id).select_for_update().get(id=spend.id)


def _save_ad_hoc_spend(spend: SignalSpend, *, finalize: bool = False) -> None:
    if spend.finalized_at is not None:
        return
    spend.accounting_failed = bool(spend.llm_failed_stages)
    if finalize and not spend.accounting_failed:
        spend.finalized_at = timezone.now()
    spend.save()


def record_llm_spend(
    *,
    token_cost_microusd: int | None,
    team_id: int | None,
    stage: str,
    signal_id: str | None = None,
) -> None:
    if team_id is None or signal_id is None:
        return
    with transaction.atomic():
        spend = _locked_ad_hoc_spend(team_id=team_id, signal_id=signal_id)
        if spend.finalized_at is not None:
            raise ValueError("Cannot add generation costs to finalized spend")
        if token_cost_microusd is None:
            spend.llm_failed_stages = sorted(set(spend.llm_failed_stages) | {stage})
        else:
            spend.spend += cost_to_spend(token_cost_microusd)
        _save_ad_hoc_spend(spend)


def signal_spend_summaries(*, team_id: int, signal_ids: list[str]) -> dict[str, SignalSpendSummary]:
    ids = []
    for signal_id in dict.fromkeys(signal_ids):
        try:
            ids.append(UUID(signal_id))
        except ValueError:
            continue
    amounts: dict[str, Decimal] = {}
    failures: dict[str, set[str]] = {}
    for spend in SignalSpend.objects.for_team(team_id).filter(signal_id__in=ids):
        if spend.kind is None:
            continue
        key = str(spend.signal_id)
        amounts[key] = amounts.get(key, Decimal(0)) + spend.spend
        if spend.accounting_failed:
            failures.setdefault(key, set()).update(spend.llm_failed_stages or [spend.kind])
    return {
        key: SignalSpendSummary(total_spend=float(amount), failed_stages=sorted(failures.get(key, set())))
        for key, amount in amounts.items()
    }


def signal_spend_totals(*, team_id: int, signal_ids: list[str]) -> dict[str, float]:
    return {
        key: value.total_spend for key, value in signal_spend_summaries(team_id=team_id, signal_ids=signal_ids).items()
    }


def _save_scout_total(spend: SignalSpend) -> None:
    if spend.scout_run_id is not None:
        SignalScoutRun.objects.for_team(spend.team_id).filter(id=spend.scout_run_id).update(
            total_spend=spend.spend,
            metadata=Func(
                Coalesce(F("metadata"), Value({}, output_field=JSONField())),
                Value("{spend_accounting_failed_stages}"),
                Value(["scout"] if spend.accounting_failed else [], output_field=JSONField()),
                function="jsonb_set",
                output_field=JSONField(),
            ),
        )


def record_task_spend(
    *,
    team_id: int,
    run_id: str,
    stage: str,
    signal_id: str | None = None,
    scout_run_id: str | None = None,
    report_id: str | None = None,
    implementation_kind: str | None = None,
) -> None:
    from products.tasks.backend.facade.billing import locked_task_run_spend  # noqa: PLC0415

    if scout_run_id:
        kind = SignalSpend.Kind.SCOUT_RUN
        signal_id, report_id = None, None
    elif stage == "implementation":
        kind = SignalSpend.Kind(implementation_kind or SignalSpend.Kind.REVIEWER_TRIGGERED_IMPLEMENTATION)
        if kind not in {
            SignalSpend.Kind.REVIEWER_TRIGGERED_IMPLEMENTATION,
            SignalSpend.Kind.SCOUT_TRIGGERED_IMPLEMENTATION,
        }:
            raise ValueError("Implementation requires an implementation spend kind")
        if report_id is None:
            raise ValueError("Implementation spend requires its report")
        signal_id = None
    elif stage in {SignalSpend.Kind.RESEARCH, SignalSpend.Kind.REPO_SELECTION}:
        kind = SignalSpend.Kind(stage)
        if signal_id is None:
            raise ValueError("Research and repository selection require their triggering signal")
    else:
        return
    report = SignalReport.objects.filter(team_id=team_id, id=report_id).first() if report_id else None
    owner_report_id = report_id if stage == "implementation" and scout_run_id is None else None
    with locked_task_run_spend(team_id=team_id, run_id=UUID(run_id)) as run:
        spend, created = SignalSpend.objects.for_team(team_id).get_or_create(
            team_id=team_id,
            task_run_id=run.run_id,
            defaults={"kind": kind, "signal_id": signal_id, "scout_run_id": scout_run_id, "report_id": owner_report_id},
        )
        spend = SignalSpend.objects.for_team(team_id).select_for_update().get(id=spend.id)
        if (str(spend.signal_id), str(spend.scout_run_id), str(spend.report_id)) != (
            str(signal_id),
            str(scout_run_id),
            str(owner_report_id),
        ):
            raise ValueError("Task run is already owned by another spend owner")
        if spend.finalized_at is not None:
            return
        if created:
            spend.created_at = run.created_at
            spend.billing_exempt = trial_spend_exempt(team_id)
            if scout_run_id:
                scout = SignalScoutRun.objects.for_team(team_id).get(id=scout_run_id)
                spend.created_at = min(spend.created_at, scout.created_at)
                spend.billing_exempt = spend.billing_exempt or scout_spend_exempt(scout)
            if report:
                apply_report_billing(spend, report)
        spend.spend = cost_to_spend(run.cost_microusd or 0, task_count=1)
        spend.accounting_failed = not run.complete
        spend.save()
        _save_scout_total(spend)


def record_task_cost_delta(*, team_id: int, run_id: UUID, cost_delta_microusd: int) -> None:
    # The sender holds the run lock and commits this delta together with gateway request deduplication.
    with transaction.atomic():
        spend = SignalSpend.objects.for_team(team_id).select_for_update().filter(task_run_id=run_id).first()
        if spend is None or spend.finalized_at is not None:
            return
        spend.spend += cost_to_spend(cost_delta_microusd)
        spend.save(update_fields=["spend", "updated_at"])
        _save_scout_total(spend)


def register_report_task_spend(
    *,
    team_id: int,
    run_id: str,
    report_id: str,
    stage: str | None,
    signal_id: str | None = None,
    implementation_kind: str | None = None,
) -> None:
    if stage not in {"research", "implementation", "repo_selection"}:
        return
    if SignalSpend.objects.for_team(team_id).filter(task_run_id=run_id).exists():
        return
    if stage != "implementation" and signal_id is None:
        signal_id = report_triggering_signal(team_id=team_id, report_id=report_id)
    record_task_spend(
        team_id=team_id,
        run_id=run_id,
        report_id=report_id,
        signal_id=signal_id,
        stage=stage,
        implementation_kind=implementation_kind,
    )


def complete_signal_pipeline(
    *, team_id: int, signal_id: str, report_id: str | None = None, billing_exempt: bool = False
) -> None:
    with transaction.atomic():
        spend = _locked_ad_hoc_spend(team_id=team_id, signal_id=signal_id)
        if spend.finalized_at is not None:
            return
        spend.billing_exempt = spend.billing_exempt or billing_exempt
        report = SignalReport.objects.filter(team_id=team_id, id=report_id).first() if report_id else None
        if report:
            apply_report_billing(spend, report)
        # The summary can still make one-shot calls after grouping hands off this signal.
        handed_off = (
            report
            and UUID(signal_id) in {report.triggering_signal_id, report.pending_triggering_signal_id}
            and report.status != SignalReport.Status.POTENTIAL
        )
        _save_ad_hoc_spend(spend, finalize=not handed_off)


def begin_report_spend(*, team_id: int, report_id: str, signal_id: str, billing_exempt: bool = False) -> None:
    with transaction.atomic():
        spend = _locked_ad_hoc_spend(team_id=team_id, signal_id=signal_id)
        if spend.finalized_at is not None:
            return
        spend.billing_exempt = spend.billing_exempt or billing_exempt
        report = SignalReport.objects.get(team_id=team_id, id=report_id)
        apply_report_billing(spend, report)
        _save_ad_hoc_spend(spend)


def finish_report_spend(*, team_id: int, report_id: str, signal_id: str) -> None:
    with transaction.atomic():
        report = SignalReport.objects.select_for_update().filter(team_id=team_id, id=report_id).first()
        spend = _locked_ad_hoc_spend(team_id=team_id, signal_id=signal_id)
        if spend.finalized_at is None:
            if report:
                apply_report_billing(spend, report)
            _save_ad_hoc_spend(spend, finalize=True)
        if (
            report
            and report.triggering_signal_id == UUID(signal_id)
            and report.pending_triggering_signal_id not in {None, report.triggering_signal_id}
        ):
            pending = _locked_ad_hoc_spend(team_id=team_id, signal_id=str(report.pending_triggering_signal_id))
            if pending.finalized_at is None:
                apply_report_billing(pending, report)
                _save_ad_hoc_spend(pending, finalize=True)
            report.pending_triggering_signal_id = None
            report.save(update_fields=["pending_triggering_signal_id"])
        if report and report.status == SignalReport.Status.CANDIDATE and report.triggering_signal_id == UUID(signal_id):
            report.triggering_signal_id = None
            report.save(update_fields=["triggering_signal_id"])


def complete_task_spend(*, team_id: int, run_id: str, report_id: str | None = None) -> None:
    from products.tasks.backend.facade.billing import (  # noqa: PLC0415
        TaskTokenUsageUnavailable,
        locked_task_run_spend,
        process_pending_gateway_usage,
    )

    spend = SignalSpend.objects.for_team(team_id).filter(task_run_id=UUID(str(run_id))).first()
    if spend is None:
        return
    if spend.finalized_at is None:
        with locked_task_run_spend(team_id=team_id, run_id=UUID(run_id)) as run:
            if not run.is_terminal:
                return
        process_pending_gateway_usage(run_id=UUID(run_id), team_id=team_id, limit=1000)
        with locked_task_run_spend(team_id=team_id, run_id=UUID(run_id)) as run:
            spend = SignalSpend.objects.for_team(team_id).select_for_update().get(id=spend.id)
            if spend.finalized_at is None:
                billing_report_id = spend.report_id or report_id
                if billing_report_id is not None:
                    report = (
                        SignalReport.objects.filter(team_id=team_id, id=billing_report_id)
                        .only("billing_exempt_reason")
                        .first()
                    )
                    if report:
                        apply_report_billing(spend, report)
                spend.spend = cost_to_spend(run.cost_microusd or 0, task_count=1)
                spend.accounting_failed = not run.complete
                if run.is_terminal and run.complete:
                    spend.finalized_at = timezone.now()
                spend.save()
                _save_scout_total(spend)
        if spend.accounting_failed:
            raise TaskTokenUsageUnavailable("Task usage is not settled yet")
    if spend.signal_id:
        async_to_sync(submit_signal_metadata_updates)(team_id=team_id, signal_ids=[str(spend.signal_id)])
