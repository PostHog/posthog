from __future__ import annotations

import json
import time
import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from functools import partial
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import F, Q, QuerySet
from django.db.models.functions import Substr
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from products.signals.backend.contracts import MonitoringUnresolvedSignalExtra
from products.signals.backend.daily_limit import daily_report_limit_gate
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import (
    SignalEmissionRecord,
    SignalReport,
    SignalReportArtefact,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
    SignalSourceConfig,
)
from products.signals.backend.quota import self_driving_quota_gate
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_lifecycle import disabled_monitoring_organizations
from products.signals.backend.spend import complete_signal_pipeline, finalized_signal_ids, signal_id_for

logger = structlog.get_logger(__name__)
MONITORING_SIGNAL_RETRY_DELAY = timedelta(minutes=5)
MONITORING_EVIDENCE_MAX_CHARS = 12_000
MONITORING_EVIDENCE_MIN_CHARS = 512
MONITORING_EVIDENCE_MAX_ROWS = 10
# Prompts become team-readable task descriptions, so query-protected snapshots stay behind the API.
MONITORING_EVIDENCE_ARTEFACT_TYPES = (
    SignalReportArtefact.ArtefactType.NOTE,
    SignalReportArtefact.ArtefactType.SIGNAL_FINDING,
    SignalReportArtefact.ArtefactType.CODE_REFERENCE,
    SignalReportArtefact.ArtefactType.COMMIT,
    SignalReportArtefact.ArtefactType.PULL_REQUEST,
    SignalReportArtefact.ArtefactType.IMPLEMENTATION_DECISION,
    SignalReportArtefact.ArtefactType.IMPLEMENTATION_REPLACEMENT,
    SignalReportArtefact.ArtefactType.IMPLEMENTATION_HANDOVER,
)


def pending_research_requests() -> Q:
    return SignalReportMonitoringAttempt.pending_research_filter()


def current_research_attempt(
    *, team_id: int, report_id: str | UUID, attempt_id: str | UUID, lock: bool = False
) -> SignalReportMonitoringAttempt | None:
    if not team_report_monitoring_enabled(team_id):
        return None
    attempts = (
        SignalReportMonitoringAttempt.objects.for_team(team_id)
        .using("default")
        .select_related("report")
        .filter(
            pending_research_requests(),
            id=attempt_id,
            report_id=report_id,
            report__team_id=team_id,
            report__status=SignalReport.Status.CLOSED,
            monitoring_started_at=F("report__monitoring_started_at"),
            research_requested_at__isnull=False,
        )
    )
    if lock:
        attempts = attempts.select_for_update(of=("report",), no_key=True)
    return attempts.first()


def monitoring_emission_records(*, team_id: int, attempt_id: str | UUID) -> QuerySet[SignalEmissionRecord]:
    return SignalEmissionRecord.objects.using("default").filter(
        team_id=team_id,
        source_product=SignalSourceProduct.SIGNALS_CHECK,
        source_type=SignalSourceType.MONITORING_UNRESOLVED,
        source_id=str(attempt_id),
    )


def _settle_terminal_monitoring_delivery(*, team_id: int, attempt_id: str) -> None:
    record = monitoring_emission_records(team_id=team_id, attempt_id=attempt_id).first()
    if record is None or not record.report_id or not record.signal_id:
        return
    with transaction.atomic():
        target = SignalReport.objects.select_for_update().filter(team_id=team_id, id=record.report_id).first()
        if target is not None:
            if (
                target.status in {SignalReport.Status.CANDIDATE, SignalReport.Status.IN_PROGRESS}
                and str(target.triggering_signal_id) == record.signal_id
            ):
                return
            if str(target.pending_triggering_signal_id) == record.signal_id:
                target.pending_triggering_signal_id = None
                target.save(update_fields=["pending_triggering_signal_id"])
        complete_signal_pipeline(team_id=team_id, signal_id=record.signal_id)


def _set_monitoring_delivery_status(attempt: SignalReportMonitoringAttempt, status: str) -> None:
    attempt.research_delivery_status = status
    attempt.save(update_fields=["research_delivery_status"])
    if status in {"cancelled", "failed", "rejected"}:
        transaction.on_commit(
            partial(_settle_terminal_monitoring_delivery, team_id=attempt.team_id, attempt_id=str(attempt.id))
        )


def record_monitoring_delivery_outcome(*, team_id: int, signal_id: str, source_id: str, status: str) -> None:
    with transaction.atomic():
        attempt = (
            SignalReportMonitoringAttempt.objects.for_team(team_id)
            .using("default")
            .select_for_update()
            .filter(pending_research_requests(), id=source_id)
            .first()
        )
        if (
            attempt is not None
            and monitoring_emission_records(team_id=team_id, attempt_id=attempt.id).filter(signal_id=signal_id).exists()
        ):
            _set_monitoring_delivery_status(attempt, status)


def acknowledge_monitoring_research(
    *, report: SignalReport, owner_signal_id: str | None, signal_ids: list[str]
) -> None:
    if not owner_signal_id or str(report.triggering_signal_id) != owner_signal_id or not signal_ids:
        return
    records = list(
        SignalEmissionRecord.objects.using("default")
        .filter(
            team_id=report.team_id,
            report_id=report.id,
            source_product=SignalSourceProduct.SIGNALS_CHECK,
            source_type=SignalSourceType.MONITORING_UNRESOLVED,
            signal_id__in=signal_ids,
        )
        .values_list("source_id", "signal_id")
    )
    SignalReportMonitoringAttempt.objects.for_team(report.team_id).filter(
        pending_research_requests(), id__in=[source_id for source_id, _ in records]
    ).update(research_delivery_status=SignalReportMonitoringAttempt.ResearchDeliveryStatus.DELIVERED)
    if report.pending_triggering_signal_id and str(report.pending_triggering_signal_id) in signal_ids:
        report.pending_triggering_signal_id = None
        report.save(update_fields=["pending_triggering_signal_id"])
    for _, included_signal_id in records:
        if included_signal_id and included_signal_id != owner_signal_id:
            complete_signal_pipeline(team_id=report.team_id, report_id=str(report.id), signal_id=included_signal_id)


def _monitoring_target_accepts_delivery(
    *, attempt: SignalReportMonitoringAttempt, record: SignalEmissionRecord
) -> bool:
    team = attempt.report.team
    team_id = attempt.team_id
    if not record.report_id:
        return True
    target = SignalReport.objects.using("default").filter(team_id=team_id, id=record.report_id).first()
    if target is not None and target.status == SignalReport.Status.FAILED:
        _set_monitoring_delivery_status(attempt, SignalReportMonitoringAttempt.ResearchDeliveryStatus.FAILED)
        return False
    if target is None or target.status in {
        SignalReport.Status.CLOSED,
        SignalReport.Status.RESOLVED,
        SignalReport.Status.DELETED,
        SignalReport.Status.SUPPRESSED,
    }:
        _set_monitoring_delivery_status(attempt, SignalReportMonitoringAttempt.ResearchDeliveryStatus.CANCELLED)
        return False
    if target.status in {
        SignalReport.Status.IN_PROGRESS,
        SignalReport.Status.PENDING_INPUT,
        SignalReport.Status.MONITORING,
    }:
        return False
    quota = self_driving_quota_gate(team)
    if (quota.limited and quota.enforced) or daily_report_limit_gate(team).limited:
        return False
    return True


def emit_monitoring_research(
    *, team_id: int, report_id: str | UUID, attempt_id: str | UUID, due_before: datetime | None = None
) -> None:
    from products.signals.backend.facade.api import emit_signal  # noqa: PLC0415 -- breaks the facade import cycle

    with transaction.atomic():
        attempt = (
            SignalReportMonitoringAttempt.objects.for_team(team_id)
            .using("default")
            .select_for_update(of=("self",))
            .select_related("report__team__organization")
            .filter(pending_research_requests(), id=attempt_id, report_id=report_id)
            .first()
        )
        if attempt is None or (
            due_before is not None
            and attempt.research_next_attempt_at is not None
            and attempt.research_next_attempt_at > due_before
        ):
            return
        attempt.research_next_attempt_at = timezone.now() + MONITORING_SIGNAL_RETRY_DELAY
        attempt.save(update_fields=["research_next_attempt_at"])
        report = attempt.report
        if report.status != SignalReport.Status.CLOSED or attempt.monitoring_started_at != report.monitoring_started_at:
            _set_monitoring_delivery_status(attempt, SignalReportMonitoringAttempt.ResearchDeliveryStatus.CANCELLED)
            return
        team = report.team
        if (
            not team_report_monitoring_enabled(team_id)
            or not team.organization.is_ai_data_processing_approved
            or not SignalSourceConfig.is_source_enabled(
                team_id, SignalSourceProduct.SIGNALS_CHECK, SignalSourceType.MONITORING_UNRESOLVED
            )
        ):
            return
        records = monitoring_emission_records(team_id=team_id, attempt_id=attempt.id)
        # Research persistence locks its target before acknowledging attempts. Waiting on grouping's receipt can form a lock cycle.
        record = records.select_for_update(skip_locked=True).first()
        if record is None and records.exists():
            return
        if record is None:
            record, _ = SignalEmissionRecord.objects.get_or_create(
                team_id=team_id,
                source_product=SignalSourceProduct.SIGNALS_CHECK,
                source_type=SignalSourceType.MONITORING_UNRESOLVED,
                source_id=str(attempt.id),
                defaults={
                    "emitted_at": timezone.now(),
                    "signal_id": signal_id_for(
                        team_id=team_id,
                        source_product=SignalSourceProduct.SIGNALS_CHECK,
                        source_type=SignalSourceType.MONITORING_UNRESOLVED,
                        idempotency_key=str(attempt.id),
                    ),
                },
            )
        if not _monitoring_target_accepts_delivery(attempt=attempt, record=record):
            return
        target_id = record.report_id
        if record.signal_id and finalized_signal_ids(team_id=team_id, signal_ids=[record.signal_id]):
            if attempt.research_delivery_status != SignalReportMonitoringAttempt.ResearchDeliveryStatus.RETRYABLE:
                _set_monitoring_delivery_status(attempt, SignalReportMonitoringAttempt.ResearchDeliveryStatus.FAILED)
                return
            record.signal_id = str(uuid4())
        attempt.research_delivery_status = SignalReportMonitoringAttempt.ResearchDeliveryStatus.PENDING
        attempt.save(update_fields=["research_delivery_status"])
        record.emitted_at = timezone.now()
        record.save(update_fields=["signal_id", "emitted_at"])
        payload = MonitoringUnresolvedSignalExtra(report_id=str(report_id), attempt_id=str(attempt.id))

    async def deliver() -> None:
        async with asyncio.timeout(10):
            await emit_signal(
                team=team,
                source_product=SignalSourceProduct.SIGNALS_CHECK,
                source_type=SignalSourceType.MONITORING_UNRESOLVED,
                source_id=str(attempt.id),
                signal_id=record.signal_id,
                idempotency_key=str(uuid4()),
                source_match_signal_id=record.signal_id if target_id else None,
                source_match_report_id=target_id,
                description=(
                    f"Monitoring did not establish resolution: {(report.title or 'Untitled report')[:200]}\n"
                    f"Original report: {report.id}. Attempt: {attempt.id}.\n"
                    "Monitoring ended without establishing resolution.\n"
                    "Investigate the original findings, implementation and verification evidence. "
                    "Read its history with inbox-report-artefacts-list. "
                    "Uncertainty does not establish an implementation defect."
                ),
                weight=1.0,
                extra=payload.model_dump(mode="json"),
            )

    async_to_sync(deliver)()


def emit_due_monitoring_research(*, deadline: float, limit: int) -> None:
    if limit <= 0 or time.monotonic() >= deadline:
        return
    due_before = timezone.now()
    due = list(
        SignalReportMonitoringAttempt.objects.unscoped()
        .filter(pending_research_requests())
        .filter(Q(research_next_attempt_at__isnull=True) | Q(research_next_attempt_at__lte=due_before))
        .order_by(F("research_next_attempt_at").asc(nulls_first=True), "research_requested_at", "id")
        .values("id", "team_id", "report_id", "report__team__organization_id")[:limit]
    )
    disabled = disabled_monitoring_organizations({row["report__team__organization_id"] for row in due})
    for row in due:
        if time.monotonic() >= deadline:
            break
        if row["report__team__organization_id"] in disabled:
            SignalReportMonitoringAttempt.objects.for_team(row["team_id"]).filter(id=row["id"]).update(
                research_next_attempt_at=timezone.now() + MONITORING_SIGNAL_RETRY_DELAY
            )
            continue
        try:
            emit_monitoring_research(
                team_id=row["team_id"], report_id=row["report_id"], attempt_id=row["id"], due_before=due_before
            )
        except Exception:
            logger.exception("signals.monitoring.signal_emission_failed", attempt_id=str(row["id"]))


def monitoring_research_evidence(
    *, team_id: int, payload: MonitoringUnresolvedSignalExtra, max_chars: int = MONITORING_EVIDENCE_MAX_CHARS
) -> str:
    max_chars = max(MONITORING_EVIDENCE_MIN_CHARS, max_chars)
    field_chars = min(1000, max_chars // 10)
    attempt = (
        SignalReportMonitoringAttempt.objects.for_team(team_id)
        .using("default")
        .only("id", "report_id", "aggregation_state")
        .annotate(
            title_excerpt=Substr("report__title", 1, field_chars),
            summary_excerpt=Substr("report__summary", 1, field_chars),
        )
        .filter(
            id=payload.attempt_id,
            report_id=payload.report_id,
            report__team_id=team_id,
            research_requested_at__isnull=False,
        )
        .first()
    )
    if attempt is None:
        raise ValueError("Monitoring research request is no longer current")
    sections: dict[str, list[Mapping[str, object]]] = {
        "attempts": list(
            SignalReportMonitoringAttempt.objects.for_team(team_id)
            .using("default")
            .filter(report_id=attempt.report_id)
            .order_by("-monitoring_started_at", "-id")
            .values("id", "monitoring_started_at", "aggregation_state")[:MONITORING_EVIDENCE_MAX_ROWS]
        ),
        "results": list(
            SignalReportMonitoringResult.objects.for_team(team_id)
            .using("default")
            .filter(attempt_id=attempt.id)
            .order_by("-created_at", "-id")
            .values(
                "id",
                "report_check_id",
                "outcome",
                "evidence_status",
                "window_start",
                "window_end",
            )[:MONITORING_EVIDENCE_MAX_ROWS]
        ),
        "artefacts": list(
            SignalReportArtefact.objects.using("default")
            .filter(team_id=team_id, report_id=attempt.report_id, type__in=MONITORING_EVIDENCE_ARTEFACT_TYPES)
            .order_by("-created_at", "-id")
            .annotate(content_excerpt=Substr("content", 1, field_chars))
            .values("id", "type", "content_excerpt", "actor_kind", "task_id", "created_at")[
                :MONITORING_EVIDENCE_MAX_ROWS
            ]
        ),
        "implementations": list(
            SignalReportArtefact.objects.using("default")
            .filter(
                team_id=team_id,
                report_id=attempt.report_id,
                type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
                pull_request__team_id=team_id,
            )
            .order_by("-created_at", "-id")
            .values("id", url=F("pull_request__url"), state=F("pull_request__state"))[:MONITORING_EVIDENCE_MAX_ROWS]
        ),
    }
    evidence: dict[str, object] = {
        "history": f"Bounded public excerpts. Fetch full history and query-protected measurements through inbox-report-artefacts-list for report_id {attempt.report_id}; its access checks apply.",
        "original_report": {
            "id": str(attempt.report_id),
            "title": attempt.title_excerpt or "",
            "summary": attempt.summary_excerpt or "",
        },
        "requested_attempt": {
            "id": str(attempt.id),
            "outcome": attempt.aggregation_state,
        },
        **sections,
    }
    encoded = json.dumps(evidence, default=str)
    while len(encoded) > max_chars and any(sections.values()):
        largest = max(sections.values(), key=lambda rows: len(json.dumps(rows, default=str)))
        largest.pop()
        encoded = json.dumps(evidence, default=str)
    if len(encoded) > max_chars:
        return json.dumps(
            {"report_id": payload.report_id, "attempt_id": payload.attempt_id, "history": evidence["history"]}
        )
    return encoded
