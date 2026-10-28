from __future__ import annotations

import math
import time
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid5

from django.db.models import (
    Case,
    Count,
    DateTimeField,
    Exists,
    ExpressionWrapper,
    F,
    Func,
    OuterRef,
    Q,
    Subquery,
    TextField,
    Value,
    When,
    Window,
)
from django.db.models.functions import Cast, Coalesce, RowNumber

from posthog.dataclasses import frozen

from products.signals.backend.models import SignalReport, SignalReportCheck, SignalReportMonitoringResult
from products.signals.backend.report_lifecycle import check_monitoring_disabled_organizations
from products.signals.backend.report_monitoring_attempts import check_definition_version
from products.signals.backend.report_monitoring_results import (
    LEGACY_MONITORING_TERMINAL_STATUSES,
    MONITORING_RESULT_ELIGIBLE_STATUSES,
)

FINAL_CHECK_RETRY_DELAYS = (timedelta(minutes=5), timedelta(minutes=15))
MAX_FINAL_CHECKS_PER_TEAM = 10


@frozen
class FinalCheck:
    check: SignalReportCheck
    attempt_id: UUID
    definition_version: str
    window_start: datetime
    window_end: datetime


@frozen
class DueFinalCheck:
    member: FinalCheck
    submission_id: UUID


def collect_due_final_checks(
    now: datetime, *, kind: str, limit: int, deadline: float = math.inf
) -> list[DueFinalCheck]:
    if limit <= 0:
        return []
    candidates = (
        SignalReportCheck.all_teams.filter(
            kind=kind,
            soak_minutes__isnull=False,
            report__status=SignalReport.Status.MONITORING,
            report__monitoring_attempts__team_id=F("team_id"),
            report__monitoring_attempts__monitoring_started_at=F("report__monitoring_started_at"),
        )
        .filter(
            Q(status__in=MONITORING_RESULT_ELIGIBLE_STATUSES)
            | Q(
                kind=SignalReportCheck.Kind.AGENT,
                status__in=LEGACY_MONITORING_TERMINAL_STATUSES,
                legacy_monitoring_attempt_id=F("report__monitoring_attempts__id"),
            )
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
    if kind == SignalReportCheck.Kind.AGENT:
        # Scout history and memory belong to the parent project, so child evidence must wait.
        candidates = candidates.filter(report__team__parent_team_id__isnull=True).filter(
            Q(monitoring_dispatch_after__isnull=True) | Q(monitoring_dispatch_after__lte=now)
        )
    results = SignalReportMonitoringResult.objects.unscoped().filter(
        team_id=OuterRef("team_id"), attempt_id=OuterRef("_attempt_id"), report_check_id=OuterRef("id")
    )
    errors = results.filter(evidence_status="errored")
    disabled = check_monitoring_disabled_organizations(candidates)
    candidates = (
        candidates.exclude(report__team__organization_id__in=disabled)
        .annotate(
            _candidate_at=(
                Coalesce("monitoring_dispatch_after", "_window_end")
                if kind == SignalReportCheck.Kind.AGENT
                else F("_window_end")
            ),
            _settled=Exists(results.exclude(evidence_status="errored")),
            _error_count=Coalesce(
                Subquery(errors.order_by().values("report_check_id").annotate(total=Count("id")).values("total")[:1]),
                Value(0),
            ),
            _last_error_at=Subquery(errors.order_by("-created_at", "-id").values("evaluated_at")[:1]),
        )
        .filter(_settled=False, _error_count__lte=len(FINAL_CHECK_RETRY_DELAYS))
        .annotate(
            _retry_at=Case(
                *[
                    When(_error_count=index + 1, then=F("_last_error_at") + Value(delay))
                    for index, delay in enumerate(FINAL_CHECK_RETRY_DELAYS)
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
                order_by=[F("_candidate_at").asc(), F("id").asc()],
            )
        )
        .select_related("report", "report__team")
        .order_by("_team_rank", "_candidate_at", "id")
    )
    due: list[DueFinalCheck] = []
    per_team: dict[int, int] = {}
    for check in candidates.iterator(chunk_size=limit * MAX_FINAL_CHECKS_PER_TEAM):
        if time.monotonic() >= deadline:
            break
        if per_team.get(check.team_id, 0) >= MAX_FINAL_CHECKS_PER_TEAM:
            continue
        version = cast(str, check._member_version)
        if check_definition_version(check) != version:
            continue
        attempt_id = cast(UUID, check._attempt_id)
        start = check.report.monitoring_started_at
        assert start is not None
        due.append(
            DueFinalCheck(
                member=FinalCheck(
                    check=check,
                    attempt_id=attempt_id,
                    definition_version=version,
                    window_start=start,
                    window_end=cast(datetime, check._window_end),
                ),
                # Competing ticks share an ID so only one result consumes this logical retry.
                submission_id=uuid5(
                    attempt_id,
                    f"{'metric' if kind == SignalReportCheck.Kind.METRIC_THRESHOLD else 'agent'}:{check.id}:{version}:{check._error_count}",
                ),
            )
        )
        per_team[check.team_id] = per_team.get(check.team_id, 0) + 1
        if len(due) >= limit:
            break
    return due
