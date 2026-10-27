from __future__ import annotations

import math
import time
from dataclasses import replace
from datetime import datetime, timedelta
from functools import partial
from typing import cast
from uuid import UUID, uuid5

from django.db import transaction
from django.db.models import (
    Case,
    Count,
    DateTimeField,
    Exists,
    ExpressionWrapper,
    F,
    Func,
    OuterRef,
    Subquery,
    TextField,
    Value,
    When,
    Window,
)
from django.db.models.functions import Cast, Coalesce, RowNumber
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport, SignalReportCheck, SignalReportMonitoringResult
from products.signals.backend.report_check_metric_evaluation import FinalMetricCheck, evaluate_final_metric
from products.signals.backend.report_check_telemetry import capture_report_monitoring_evaluated
from products.signals.backend.report_content_gates import team_report_monitoring_enabled
from products.signals.backend.report_lifecycle import check_monitoring_disabled_organizations
from products.signals.backend.report_metric_refresh import MetricQueryBudgetExhausted
from products.signals.backend.report_monitoring_attempts import check_definition_version, current_monitoring_attempt
from products.signals.backend.report_monitoring_results import (
    MONITORING_RESULT_ELIGIBLE_STATUSES,
    InvalidMonitoringResult,
    MonitoringResultConflict,
    save_monitoring_result,
)

logger = structlog.get_logger(__name__)
FINAL_METRIC_RETRY_DELAYS = (timedelta(minutes=5), timedelta(minutes=15))
MAX_FINAL_METRICS_PER_TEAM = 10


@frozen
class DueFinalMetric:
    member: FinalMetricCheck
    submission_id: UUID


@frozen
class FinalMetricSummary:
    passed: int = 0
    failed: int = 0
    inconclusive: int = 0
    errored: int = 0
    deferred: int = 0


def collect_due_final_metrics(now: datetime, *, limit: int, deadline: float = math.inf) -> list[DueFinalMetric]:
    if limit <= 0:
        return []
    candidates = (
        SignalReportCheck.all_teams.filter(
            kind=SignalReportCheck.Kind.METRIC_THRESHOLD,
            status__in=MONITORING_RESULT_ELIGIBLE_STATUSES,
            soak_minutes__isnull=False,
            report__status=SignalReport.Status.MONITORING,
            report__monitoring_attempts__team_id=F("team_id"),
            report__monitoring_attempts__monitoring_started_at=F("report__monitoring_started_at"),
        )
        .annotate(
            _attempt_id=F("report__monitoring_attempts__id"),
            _member_version=Func(
                F("report__monitoring_attempts__check_versions"),
                Cast(F("id"), output_field=TextField()),
                function="jsonb_extract_path_text",
                output_field=TextField(),
            ),
            _window_end=ExpressionWrapper(
                F("report__monitoring_started_at") + F("soak_minutes") * Value(timedelta(minutes=1)),
                output_field=DateTimeField(),
            ),
        )
        .filter(_member_version__isnull=False, _window_end__lte=now)
    )
    results = SignalReportMonitoringResult.objects.unscoped().filter(
        team_id=OuterRef("team_id"), attempt_id=OuterRef("_attempt_id"), report_check_id=OuterRef("id")
    )
    errors = results.filter(evidence_status="errored")
    disabled = check_monitoring_disabled_organizations(candidates)
    candidates = (
        candidates.exclude(report__team__organization_id__in=disabled)
        .annotate(
            _settled=Exists(results.exclude(evidence_status="errored")),
            _error_count=Coalesce(
                Subquery(errors.order_by().values("report_check_id").annotate(total=Count("id")).values("total")[:1]),
                Value(0),
            ),
            _last_error_at=Subquery(errors.order_by("-created_at", "-id").values("evaluated_at")[:1]),
        )
        .filter(_settled=False, _error_count__lte=len(FINAL_METRIC_RETRY_DELAYS))
        .annotate(
            _retry_at=Case(
                *[
                    When(_error_count=index + 1, then=F("_last_error_at") + Value(delay))
                    for index, delay in enumerate(FINAL_METRIC_RETRY_DELAYS)
                ],
                default=Value(now),
                output_field=DateTimeField(),
            )
        )
        .filter(_retry_at__lte=now)
        .annotate(
            _team_rank=Window(
                expression=RowNumber(),
                partition_by=[F("team_id")],
                order_by=[F("_window_end").asc(), F("id").asc()],
            )
        )
        .select_related("report", "report__team")
        .order_by("_team_rank", "_window_end", "id")
    )
    due: list[DueFinalMetric] = []
    per_team: dict[int, int] = {}
    for check in candidates.iterator(chunk_size=limit * MAX_FINAL_METRICS_PER_TEAM):
        if time.monotonic() >= deadline:
            break
        if per_team.get(check.team_id, 0) >= MAX_FINAL_METRICS_PER_TEAM:
            continue
        version = cast(str, check._member_version)
        if check_definition_version(check) != version:
            continue
        attempt_id = cast(UUID, check._attempt_id)
        start = check.report.monitoring_started_at
        assert start is not None
        due.append(
            DueFinalMetric(
                member=FinalMetricCheck(
                    check=check,
                    attempt_id=attempt_id,
                    definition_version=version,
                    window_start=start,
                    window_end=cast(datetime, check._window_end),
                ),
                # Competing ticks share an ID so only one result consumes this logical retry.
                submission_id=uuid5(attempt_id, f"metric:{check.id}:{version}:{check._error_count}"),
            )
        )
        per_team[check.team_id] = per_team.get(check.team_id, 0) + 1
        if len(due) >= limit:
            break
    return due


def _prepare_final_metric(due: DueFinalMetric) -> bool:
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
