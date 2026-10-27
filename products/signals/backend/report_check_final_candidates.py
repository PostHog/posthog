from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import DateTimeField, ExpressionWrapper, F, Func, QuerySet, TextField, Value
from django.db.models.functions import Cast

from products.signals.backend.models import SignalReport, SignalReportCheck
from products.signals.backend.report_monitoring_results import MONITORING_RESULT_ELIGIBLE_STATUSES


def due_final_checks(kind: SignalReportCheck.Kind, now: datetime) -> QuerySet[SignalReportCheck]:
    return (
        SignalReportCheck.all_teams.filter(
            kind=kind,
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
