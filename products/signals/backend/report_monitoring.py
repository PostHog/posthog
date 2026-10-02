from django.db import transaction
from django.db.models import Q

from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import SignalReport, SignalReportCheck
from products.signals.backend.typed_report_links import incoming_links


def resolve_verified_monitoring_report(*, team_id: int, report_id: str) -> bool:
    with transaction.atomic():
        report = (
            SignalReport.objects.select_for_update()
            .filter(team_id=team_id, id=report_id, status=SignalReport.Status.MONITORING)
            .first()
        )
        if report is None or report.monitoring_started_at is None:
            return False
        child_ids = [
            edge.source_id
            for edge in incoming_links(team_id=team_id, report_id=report_id, kinds=(ReportLinkKind.PART_OF,))
        ]
        child_statuses = list(
            SignalReport.objects.using("default")
            .filter(team_id=team_id, id__in=child_ids)
            .exclude(status=SignalReport.Status.DELETED)
            .values_list("status", flat=True)
        )
        if any(
            status not in {SignalReport.Status.RESOLVED, SignalReport.Status.SUPPRESSED} for status in child_statuses
        ):
            return False
        checks = list(
            SignalReportCheck.objects.for_team(team_id)
            .using("default")
            .filter(report_id=report_id)
            # A pending check has no measurement start until it is armed, but it still owes runs to this period.
            .filter(
                Q(status=SignalReportCheck.Status.PENDING) | Q(measurement_start_at__gte=report.monitoring_started_at)
            )
            .exclude(status=SignalReportCheck.Status.CANCELLED)
            .values_list("status", "runs_remaining")
        )
        if not checks and SignalReport.Status.RESOLVED not in child_statuses:
            return False
        if any(status != SignalReportCheck.Status.PASSED or remaining != 0 for status, remaining in checks):
            return False
        report.save(update_fields=report.transition_to(SignalReport.Status.RESOLVED))
        return True
