from __future__ import annotations

import json
import time
import asyncio
from collections.abc import Mapping
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.db.models.functions import Substr
from django.utils import timezone

import structlog
from asgiref.sync import async_to_sync

from products.signals.backend.contracts import MonitoringUnresolvedSignalExtra
from products.signals.backend.enums import SignalSourceProduct, SignalSourceType
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
)
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_lifecycle import disabled_monitoring_organizations

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
            .filter(
                research_requested_at__isnull=False,
                research_processed_at__isnull=True,
                id=attempt_id,
                report_id=report_id,
            )
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
            attempt.research_processed_at = timezone.now()
            attempt.save(update_fields=["research_processed_at"])
            return
        team = report.team
        if not team_report_monitoring_enabled(team_id) or not team.organization.is_ai_data_processing_approved:
            return
        payload = MonitoringUnresolvedSignalExtra(report_id=str(report_id), attempt_id=str(attempt.id))

    async def deliver() -> None:
        async with asyncio.timeout(10):
            await emit_signal(
                team=team,
                source_product=SignalSourceProduct.SIGNALS_CHECK,
                source_type=SignalSourceType.MONITORING_UNRESOLVED,
                source_id=str(attempt.id),
                idempotency_key=str(attempt.id),
                sync_with_source=True,
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
    SignalReportMonitoringAttempt.objects.for_team(team_id).filter(id=attempt.id).update(
        research_processed_at=timezone.now()
    )


def emit_due_monitoring_research(*, deadline: float, limit: int) -> None:
    if limit <= 0 or time.monotonic() >= deadline:
        return
    due_before = timezone.now()
    due = list(
        SignalReportMonitoringAttempt.objects.unscoped()
        .filter(research_requested_at__isnull=False, research_processed_at__isnull=True)
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
        .exclude(report__status=SignalReport.Status.DELETED)
        .first()
    )
    if attempt is None:
        return json.dumps(
            {
                "report_id": payload.report_id,
                "attempt_id": payload.attempt_id,
                "history": "Monitoring history is unavailable.",
            }
        )
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
