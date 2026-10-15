from django.db import transaction

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import PriorityAdjustment, PriorityAssessment, priority_from_judgment
from products.signals.backend.enums import ReportPriority
from products.signals.backend.models import SignalReport, SignalReportArtefact


def update_report_priority(*, report: SignalReport, priority: ReportPriority, attribution: ArtefactAttribution) -> None:
    with transaction.atomic():
        SignalReport.objects.select_for_update().get(id=report.id, team_id=report.team_id)
        previous = (
            SignalReportArtefact.objects.filter(
                team_id=report.team_id,
                report_id=report.id,
                type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        previous_priority = priority_from_judgment(previous.content) if previous else None
        if previous_priority == priority:
            return
        SignalReportArtefact.append_status(
            team_id=report.team_id,
            report_id=str(report.id),
            attribution=attribution,
            content=PriorityAssessment(
                priority=priority,
                explanation="Priority changed in the inbox.",
                adjustment=PriorityAdjustment(
                    previous_priority=ReportPriority(previous_priority)
                    if previous_priority in [value.value for value in ReportPriority]
                    else None,
                    previous_judgment_id=previous.id if previous else None,
                ),
            ),
        )
        report.save(update_fields=["updated_at"])
