from collections.abc import Sequence

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


def _latest_artefacts(team_id: int, report_ids: Sequence[str], artefact_type: str) -> dict[str, str]:
    """The newest artefact content of one type per report, by report id."""
    # Pick the newest id per report first, so Postgres reads `content` once per report, not once per row.
    latest_ids = (
        SignalReportArtefact.objects.filter(team_id=team_id, report_id__in=report_ids, type=artefact_type)
        .order_by("report_id", "-created_at")
        .distinct("report_id")
        .values("id")
    )
    rows = SignalReportArtefact.objects.filter(team_id=team_id, id__in=latest_ids).values_list("report_id", "content")
    return {str(report_id): content for report_id, content in rows}


def latest_report_priorities(team_id: int, report_ids: Sequence[str]) -> dict[str, str]:
    """Latest priority judgment per report, read the same way the inbox serializer reads it. A report
    without a judgment, or whose latest judgment has no priority, has no entry."""
    latest: dict[str, str] = {}
    for report_id, content in _latest_artefacts(
        team_id, report_ids, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
    ).items():
        priority = priority_from_judgment(content)
        if priority is not None:
            latest[report_id] = priority
    return latest
