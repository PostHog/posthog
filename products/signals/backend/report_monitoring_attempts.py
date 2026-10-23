from __future__ import annotations

import json
import hashlib
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import (
    InvalidStatusTransition,
    SignalReport,
    SignalReportCheck,
    SignalReportMonitoringAttempt,
)
from products.signals.backend.report_check_artefacts import write_check_expired
from products.signals.backend.report_content_gates import team_report_monitoring_enabled

if TYPE_CHECKING:
    from posthog.models import User


def check_definition_version(check: SignalReportCheck) -> str:
    definition = {
        "title": check.title,
        "rationale": check.rationale,
        "kind": check.kind,
        "config": check.config,
        "soak_minutes": check.soak_minutes,
        "run_interval_minutes": check.run_interval_minutes,
    }
    return hashlib.sha256(json.dumps(definition, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def current_monitoring_attempt(report: SignalReport) -> SignalReportMonitoringAttempt | None:
    if report.monitoring_started_at is None:
        return None
    return (
        SignalReportMonitoringAttempt.objects.for_team(report.team_id)
        .filter(report_id=report.id, monitoring_started_at=report.monitoring_started_at)
        .first()
    )


def complete_implementation(
    *,
    team_id: int,
    report_id: UUID | str,
    monitoring_started_at: datetime,
    attribution: ArtefactAttribution | None = None,
    actor_user: User | None = None,
    close_pr_on_resolve: bool = False,
) -> SignalReportMonitoringAttempt | None:
    if timezone.is_naive(monitoring_started_at):
        raise ValueError("An aware implementation-complete timestamp is required.")
    if monitoring_started_at > timezone.now():
        raise ValueError("Implementation cannot complete in the future.")

    with transaction.atomic():
        # Check cancellation can write an artefact FK while entry waits for the check row.
        report = SignalReport.objects.select_for_update(no_key=True).get(team_id=team_id, id=report_id)
        report._transition_actor = attribution  # type: ignore[attr-defined]
        report._transition_actor_user = actor_user  # type: ignore[attr-defined]
        if report.status == SignalReport.Status.RESOLVED:
            return None
        enabled = team_report_monitoring_enabled(team_id)
        if report.status == SignalReport.Status.MONITORING:
            if not enabled:
                return None
            attempt = current_monitoring_attempt(report)
            if attempt is None:
                raise ValueError("The Monitoring period has no check snapshot.")
            return attempt
        if report.status not in {
            SignalReport.Status.READY,
            SignalReport.Status.PENDING_INPUT,
            SignalReport.Status.FAILED,
        }:
            raise InvalidStatusTransition(report.status, SignalReport.Status.MONITORING)
        if not enabled:
            report._close_pr_on_resolve = close_pr_on_resolve  # type: ignore[attr-defined]
            report.save(update_fields=report.transition_to(SignalReport.Status.RESOLVED))
            return None
        if (
            SignalReportMonitoringAttempt.objects.for_team(team_id)
            .filter(report_id=report.id, monitoring_started_at__gte=monitoring_started_at)
            .exists()
        ):
            raise ValueError("Implementation must complete after the report's earlier Monitoring periods.")

        checks = list(
            SignalReportCheck.objects.for_team(team_id)
            .select_for_update()
            .filter(report_id=report.id, status__in=SignalReportCheck.OPEN_STATUSES)
            .order_by("id")
        )
        now = timezone.now()
        applicable: list[SignalReportCheck] = []
        for check in checks:
            if check.expires_at <= now:
                check.status = SignalReportCheck.Status.EXPIRED
                check.save(update_fields=["status", "updated_at"])
                write_check_expired(check, now, raise_on_error=True)
            else:
                applicable.append(check)
        if not applicable:
            report._close_pr_on_resolve = close_pr_on_resolve  # type: ignore[attr-defined]
            report.save(update_fields=report.transition_to(SignalReport.Status.RESOLVED))
            return None

        attempt = SignalReportMonitoringAttempt.objects.for_team(team_id).create(
            team_id=team_id,
            report=report,
            monitoring_started_at=monitoring_started_at,
            check_versions={str(check.id): check_definition_version(check) for check in applicable},
        )
        SignalReportCheck.objects.for_team(team_id).filter(id__in=[check.id for check in applicable]).update(
            status=SignalReportCheck.Status.PENDING,
            measurement_start_at=None,
            last_run_at=None,
            last_outcome=None,
            last_outcome_reason=None,
            dispatched_at=None,
            consecutive_errors=0,
            consecutive_inconclusive=0,
            monitoring_fallback_expires_at=None,
            updated_at=now,
        )
        report.save(
            update_fields=report.transition_to(
                SignalReport.Status.MONITORING, monitoring_started_at=monitoring_started_at
            )
        )
        return attempt
