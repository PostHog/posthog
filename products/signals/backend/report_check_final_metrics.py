from __future__ import annotations

import math
import time
from dataclasses import replace
from datetime import datetime
from functools import partial

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport, SignalReportCheck, SignalReportMonitoringResult
from products.signals.backend.report_check_final_candidates import DueFinalCheck, collect_due_final_checks
from products.signals.backend.report_check_metric_evaluation import evaluate_final_metric
from products.signals.backend.report_check_telemetry import capture_report_monitoring_evaluated
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_metric_refresh import MetricQueryBudgetExhausted
from products.signals.backend.report_monitoring_attempts import check_definition_version, current_monitoring_attempt
from products.signals.backend.report_monitoring_results import (
    MONITORING_RESULT_ELIGIBLE_STATUSES,
    InvalidMonitoringResult,
    MonitoringResultConflict,
    save_monitoring_result,
)

logger = structlog.get_logger(__name__)


@frozen
class FinalMetricSummary:
    passed: int = 0
    failed: int = 0
    inconclusive: int = 0
    errored: int = 0
    deferred: int = 0


def collect_due_final_metrics(now: datetime, *, limit: int, deadline: float = math.inf) -> list[DueFinalCheck]:
    return collect_due_final_checks(now, kind=SignalReportCheck.Kind.METRIC_THRESHOLD, limit=limit, deadline=deadline)


def _prepare_final_metric(due: DueFinalCheck) -> bool:
    member = due.member
    with transaction.atomic():
        report = SignalReport.objects.select_for_update(no_key=True).get(
            id=member.check.report_id, team_id=member.check.team_id
        )
        if (
            report.status != SignalReport.Status.MONITORING
            or report.monitoring_started_at != member.window_start
            or not team_report_monitoring_enabled(report.team_id)
        ):
            return False
        attempt = current_monitoring_attempt(report)
        if attempt is None or attempt.id != member.attempt_id:
            return False
        results = SignalReportMonitoringResult.objects.for_team(report.team_id).filter(
            report_id=report.id, attempt_id=attempt.id, report_check_id=member.check.id
        )
        if (
            results.filter(submission_id=due.submission_id).exists()
            or results.exclude(evidence_status="errored").exists()
        ):
            return False
        check = (
            SignalReportCheck.objects.for_team(report.team_id)
            .select_for_update()
            .get(id=member.check.id, report_id=report.id)
        )
        if check_definition_version(check) != member.definition_version:
            return False
        return check.status in MONITORING_RESULT_ELIGIBLE_STATUSES


def run_due_final_metrics(*, now: datetime, deadline: float, limit: int) -> FinalMetricSummary:
    counts = {"passed": 0, "failed": 0, "inconclusive": 0, "errored": 0, "deferred": 0}
    for due in collect_due_final_metrics(now, limit=limit, deadline=deadline):
        if time.monotonic() >= deadline:
            break
        try:
            if not _prepare_final_metric(due):
                counts["deferred"] += 1
                continue
            evaluation = evaluate_final_metric(
                due.member, submission_id=due.submission_id, evaluated_at=timezone.now(), deadline=deadline
            )
            result = save_monitoring_result(replace(evaluation, evaluated_at=timezone.now()))
            transaction.on_commit(
                partial(capture_report_monitoring_evaluated, due.member.check.report.team, due.member.check, result)
            )
            counts[result.outcome] += 1
        except (MetricQueryBudgetExhausted, InvalidMonitoringResult, MonitoringResultConflict):
            counts["deferred"] += 1
        except Exception:
            logger.exception(
                "signals.monitoring.final_metric_step_failed",
                team_id=due.member.check.team_id,
                check_id=str(due.member.check.id),
            )
    return FinalMetricSummary(**counts)
