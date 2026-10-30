from __future__ import annotations

import json
import time
import asyncio
from collections.abc import Mapping
from datetime import timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import CharField, Exists, F, OuterRef, Q, QuerySet, Subquery, TextField
from django.db.models.functions import Cast, Substr
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from products.signals.backend.contracts import MonitoringUnresolvedSignalExtra
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import (
    SignalEmissionRecord,
    SignalReport,
    SignalReportArtefact,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
)
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_lifecycle import disabled_monitoring_organizations
from products.signals.backend.spend import finalized_signal_ids, signal_id_for

logger = structlog.get_logger(__name__)
MONITORING_SIGNAL_RETRY_DELAY = timedelta(minutes=5)
MONITORING_EVIDENCE_MAX_CHARS = 12_000
MONITORING_EVIDENCE_MAX_ROWS = 10


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


def emit_monitoring_research(*, team_id: int, report_id: str | UUID, attempt_id: str | UUID) -> None:
    from products.signals.backend.facade.api import emit_signal  # noqa: PLC0415 -- breaks the facade import cycle

    with transaction.atomic():
        attempt = current_research_attempt(team_id=team_id, report_id=report_id, attempt_id=attempt_id, lock=True)
        if attempt is None:
            return
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
        if record.report_id:
            return
        if record.signal_id and finalized_signal_ids(team_id=team_id, signal_ids=[record.signal_id]):
            record.signal_id = signal_id_for(
                team_id=team_id,
                source_product=SignalSourceProduct.SIGNALS_CHECK,
                source_type=SignalSourceType.MONITORING_UNRESOLVED,
                idempotency_key=f"{attempt.id}:{record.signal_id}",
            )
        record.emitted_at = timezone.now()
        record.save(update_fields=["signal_id", "emitted_at"])
        payload = MonitoringUnresolvedSignalExtra(
            report_id=str(report_id),
            attempt_id=str(attempt.id),
            explanation=(attempt.aggregation_reason or "Monitoring ended without establishing resolution.")[:1000],
        )
        report = attempt.report
    team = report.team

    async def deliver() -> None:
        async with asyncio.timeout(10):
            await emit_signal(
                team=team,
                source_product=SignalSourceProduct.SIGNALS_CHECK,
                source_type=SignalSourceType.MONITORING_UNRESOLVED,
                source_id=str(attempt.id),
                signal_id=record.signal_id,
                idempotency_key=record.signal_id,
                description=(
                    f"Monitoring did not establish resolution: {(report.title or 'Untitled report')[:200]}\n"
                    f"Original report: {report.id}. Attempt: {attempt.id}.\n"
                    f"{payload.explanation[:1000]}\n"
                    "Investigate the original findings, implementation and verification evidence. "
                    "Uncertainty does not establish an implementation defect."
                ),
                weight=1.0,
                extra=payload.model_dump(mode="json"),
            )

    async_to_sync(deliver)()


def emit_due_monitoring_research(*, deadline: float, limit: int) -> None:
    if limit <= 0 or time.monotonic() >= deadline:
        return
    records = SignalEmissionRecord.objects.filter(
        team_id=OuterRef("team_id"),
        source_product=SignalSourceProduct.SIGNALS_CHECK,
        source_type=SignalSourceType.MONITORING_UNRESOLVED,
        source_id=Cast(OuterRef("id"), CharField()),
    )
    candidates = (
        SignalReportMonitoringAttempt.objects.unscoped()
        .filter(
            research_requested_at__isnull=False,
            report__status=SignalReport.Status.CLOSED,
            monitoring_started_at=F("report__monitoring_started_at"),
        )
        .filter(~Exists(records.filter(report_id__isnull=False)))
    )
    disabled = disabled_monitoring_organizations(
        candidates.values_list("report__team__organization_id", flat=True).distinct()
    )
    due = (
        candidates.exclude(report__team__organization_id__in=disabled)
        .annotate(
            last_emitted_at=Subquery(records.values("emitted_at")[:1]),
        )
        .filter(
            Q(last_emitted_at__isnull=True) | Q(last_emitted_at__lte=timezone.now() - MONITORING_SIGNAL_RETRY_DELAY)
        )
        .order_by(F("last_emitted_at").asc(nulls_first=True), "research_requested_at", "id")[:limit]
    )
    for attempt in due:
        if time.monotonic() >= deadline:
            break
        try:
            emit_monitoring_research(team_id=attempt.team_id, report_id=attempt.report_id, attempt_id=attempt.id)
        except Exception:
            logger.exception("signals.monitoring.signal_emission_failed", attempt_id=str(attempt.id))


def schedule_monitoring_research(*, team_id: int, report_id: UUID, attempt_id: UUID) -> None:
    from products.signals.backend.tasks import (
        emit_monitoring_research_request,  # noqa: PLC0415 -- breaks the task import cycle
    )

    def emit() -> None:
        emit_monitoring_research_request.delay(team_id=team_id, report_id=str(report_id), attempt_id=str(attempt_id))

    transaction.on_commit(emit, robust=True)


def monitoring_research_evidence(
    *, team_id: int, payload: MonitoringUnresolvedSignalExtra, max_chars: int = MONITORING_EVIDENCE_MAX_CHARS
) -> str:
    max_chars = max(512, max_chars)
    field_chars = min(1000, max_chars // 10)
    attempt = (
        SignalReportMonitoringAttempt.objects.for_team(team_id)
        .using("default")
        .only("id", "report_id", "aggregation_state")
        .annotate(
            title_excerpt=Substr("report__title", 1, field_chars),
            summary_excerpt=Substr("report__summary", 1, field_chars),
            reason_excerpt=Substr("aggregation_reason", 1, field_chars),
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
            .annotate(reason_excerpt=Substr("aggregation_reason", 1, field_chars))
            .values("id", "monitoring_started_at", "aggregation_state", "reason_excerpt")[:MONITORING_EVIDENCE_MAX_ROWS]
        ),
        "results": list(
            SignalReportMonitoringResult.objects.for_team(team_id)
            .using("default")
            .filter(attempt_id=attempt.id)
            .order_by("-created_at", "-id")
            .annotate(
                explanation_excerpt=Substr("explanation", 1, field_chars),
                evidence_reason_excerpt=Substr("evidence_reason", 1, field_chars),
                evidence_refs_excerpt=Substr(Cast("evidence_refs", TextField()), 1, field_chars),
            )
            .values(
                "id",
                "report_check_id",
                "outcome",
                "evidence_status",
                "explanation_excerpt",
                "evidence_reason_excerpt",
                "evidence_refs_excerpt",
                "window_start",
                "window_end",
            )[:MONITORING_EVIDENCE_MAX_ROWS]
        ),
        "artefacts": list(
            SignalReportArtefact.objects.using("default")
            .filter(team_id=team_id, report_id=attempt.report_id)
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
        "history": f"Bounded excerpts. Full findings, implementation links and assessment notes: inbox-report-artefacts-list for report_id {attempt.report_id}.",
        "original_report": {
            "id": str(attempt.report_id),
            "title": attempt.title_excerpt or "",
            "summary": attempt.summary_excerpt or "",
        },
        "requested_attempt": {
            "id": str(attempt.id),
            "outcome": attempt.aggregation_state,
            "reason_excerpt": attempt.reason_excerpt or "",
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
