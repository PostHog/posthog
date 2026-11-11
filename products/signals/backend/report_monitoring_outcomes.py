from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timedelta
from uuid import UUID

from django.db import transaction
from django.db.models import Count, F, Func, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

import structlog

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import CheckResult, NoteArtefact
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
    SignalReportMonitoringResult,
)
from products.signals.backend.report_checks import MAX_CONSECUTIVE_CHECK_ERRORS
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_lifecycle import disabled_monitoring_organizations
from products.signals.backend.report_monitoring_aggregation import (
    MonitoringAggregation,
    MonitoringMemberState,
    aggregate_monitoring_members,
)
from products.signals.backend.report_monitoring_attempts import check_definition_version, current_monitoring_attempt

logger = structlog.get_logger(__name__)


def _member_results(
    check: SignalReportCheck | None,
    version: str,
    attempt: SignalReportMonitoringAttempt,
    results: list[SignalReportMonitoringResult],
    now: datetime,
) -> list[SignalReportMonitoringResult]:
    if (
        check is None
        or check.status == SignalReportCheck.Status.CANCELLED
        or check_definition_version(check) != version
        or check.soak_minutes is None
    ):
        return []
    end = attempt.monitoring_started_at + timedelta(minutes=check.soak_minutes)
    if end > now:
        return []
    return [
        result
        for result in results
        if result.definition_version == version
        and result.window_start == attempt.monitoring_started_at
        and result.window_end == end
        and end <= result.evaluated_at <= now
    ]


def _member_state(results: list[SignalReportMonitoringResult]) -> MonitoringMemberState:
    for result in results:
        if result.evidence_status == "sufficient":
            if result.outcome == "failed" and result.expectation_matches is False:
                return MonitoringMemberState.FAILED
            if result.outcome == "passed" and result.expectation_matches is True:
                return MonitoringMemberState.PASSED
    if any(result.evidence_status in {"insufficient", "unsupported"} for result in results):
        return MonitoringMemberState.INCONCLUSIVE
    if sum(result.evidence_status == "errored" for result in results) >= MAX_CONSECUTIVE_CHECK_ERRORS:
        return MonitoringMemberState.EXHAUSTED
    return MonitoringMemberState.WAITING


def aggregate_monitoring_attempt(*, team_id: int, report_id: UUID, attempt_id: UUID) -> MonitoringAggregation:
    with transaction.atomic():
        report = SignalReport.objects.select_for_update(no_key=True).filter(team_id=team_id, id=report_id).first()
        if (
            report is None
            or report.status != SignalReport.Status.MONITORING
            or not team_report_monitoring_enabled(team_id)
        ):
            return MonitoringAggregation.WAITING
        attempt = current_monitoring_attempt(report)
        if attempt is None or attempt.id != attempt_id:
            return MonitoringAggregation.WAITING
        checks = {
            str(check.id): check
            for check in SignalReportCheck.objects.for_team(team_id)
            .select_for_update()
            .filter(report_id=report.id)
            .filter(Q(id__in=attempt.check_versions) | Q(status__in=SignalReportCheck.OPEN_STATUSES))
            .order_by("id")
        }
        results = list(
            SignalReportMonitoringResult.objects.for_team(team_id)
            .filter(report_id=report.id, attempt_id=attempt.id, report_check_id__in=attempt.check_versions)
            .order_by("created_at", "id")
        )
        by_check: defaultdict[str, list[SignalReportMonitoringResult]] = defaultdict(list)
        for result in results:
            by_check[str(result.report_check_id)].append(result)
        now = timezone.now()
        member_results = {
            check_id: _member_results(checks.get(check_id), version, attempt, by_check[check_id], now)
            for check_id, version in attempt.check_versions.items()
        }
        states = {check_id: _member_state(valid) for check_id, valid in member_results.items()}
        decision = aggregate_monitoring_members(list(states.values()))
        previous = attempt.aggregation_state
        attempt.aggregation_state = decision
        attempt.aggregation_checked_at = now
        attempt.aggregation_result_ids = [str(result.id) for result in results]
        fields = ["aggregation_state", "aggregation_checked_at", "aggregation_result_ids"]
        reason = {
            MonitoringAggregation.WAITING: "Verification is waiting for the remaining follow-up checks.",
            MonitoringAggregation.PASSED: "All follow-up checks passed with sufficient evidence.",
            MonitoringAggregation.FAILED: "A follow-up check failed with sufficient evidence.",
            MonitoringAggregation.ASSESSMENT_REQUIRED: "Final verification needs a report-level assessment.",
        }[decision]
        attempt.aggregation_reason = reason
        fields.append("aggregation_reason")
        if decision == MonitoringAggregation.ASSESSMENT_REQUIRED and attempt.assessment_requested_at is None:
            attempt.assessment_requested_at = now
            fields.append("assessment_requested_at")
        if decision == MonitoringAggregation.FAILED and attempt.research_requested_at is None:
            attempt.research_requested_at = now
            fields.append("research_requested_at")
        if decision == MonitoringAggregation.PASSED and attempt.tracker_issue_close_requested_at is None:
            attempt.tracker_issue_close_requested_at = now
            fields.append("tracker_issue_close_requested_at")
        attempt.save(update_fields=fields)
        for check_id, state in states.items():
            if state not in {MonitoringMemberState.PASSED, MonitoringMemberState.FAILED}:
                continue
            check = checks[check_id]
            if check.status == state.value:
                continue
            result = next(result for result in member_results[check_id] if result.outcome == state.value)
            SignalReportCheck.objects.for_team(team_id).filter(id=check.id).update(
                status=state.value,
                last_outcome=state.value,
                last_outcome_reason=None,
                last_run_at=result.evaluated_at,
                dispatched_at=None,
                updated_at=now,
            )
            check.status = state.value
            SignalReportArtefact.add_log(
                team_id=team_id,
                report_id=str(report.id),
                content=CheckResult(
                    check_id=check_id,
                    kind=check.kind,
                    title=check.title,
                    outcome="passed" if state == MonitoringMemberState.PASSED else "failed",
                    explanation=result.explanation,
                ),
                attribution=ArtefactAttribution.system(),
            )
        if decision in {MonitoringAggregation.PASSED, MonitoringAggregation.FAILED}:
            # The authoring module imports the coordinator, which imports this module for recovery.
            from products.signals.backend.report_check_authoring import cancel_check  # noqa: PLC0415

            for check in checks.values():
                if check.status in SignalReportCheck.OPEN_STATUSES:
                    cancel_check(check, reason="monitoring_completed", attribution=ArtefactAttribution.system())
            target = (
                SignalReport.Status.RESOLVED if decision == MonitoringAggregation.PASSED else SignalReport.Status.CLOSED
            )
            report.save(update_fields=report.transition_to(target))
        if decision != MonitoringAggregation.WAITING and decision != previous:
            SignalReportArtefact.add_log(
                team_id=team_id,
                report_id=str(report.id),
                content=NoteArtefact(note=reason),
                attribution=ArtefactAttribution.system(),
            )
        return decision


def aggregate_monitoring_attempt_safely(*, team_id: int, report_id: UUID, attempt_id: UUID) -> None:
    try:
        aggregate_monitoring_attempt(team_id=team_id, report_id=report_id, attempt_id=attempt_id)
    except Exception:
        logger.exception("signals.monitoring.aggregation_failed", team_id=team_id, attempt_id=str(attempt_id))


def aggregate_due_monitoring_attempts(*, deadline: float, limit: int) -> None:
    if limit <= 0 or time.monotonic() >= deadline:
        return
    result_count = (
        SignalReportMonitoringResult.objects.unscoped()
        .filter(team_id=OuterRef("team_id"), report_id=OuterRef("report_id"), attempt_id=OuterRef("id"))
        .order_by()
        .values("attempt_id")
        .annotate(total=Count("id"))
        .values("total")
    )
    candidates = (
        SignalReportMonitoringAttempt.objects.unscoped()
        .filter(report__status=SignalReport.Status.MONITORING, monitoring_started_at=F("report__monitoring_started_at"))
        .annotate(
            _result_count=Coalesce(Subquery(result_count[:1]), Value(0)),
            _seen_count=Coalesce(
                Func(F("aggregation_result_ids"), function="jsonb_array_length", output_field=IntegerField()), Value(0)
            ),
        )
        .filter(_result_count__gt=F("_seen_count"))
    )
    disabled = disabled_monitoring_organizations(
        candidates.values_list("report__team__organization_id", flat=True).distinct()
    )
    candidates = candidates.exclude(report__team__organization_id__in=disabled).order_by(
        F("aggregation_checked_at").asc(nulls_first=True), "created_at", "id"
    )[:limit]
    for attempt in candidates:
        if time.monotonic() >= deadline:
            break
        aggregate_monitoring_attempt_safely(team_id=attempt.team_id, report_id=attempt.report_id, attempt_id=attempt.id)
