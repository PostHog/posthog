from pydantic import ValidationError

from products.signals.backend.artefact_schemas import PriorityAssessment
from products.signals.backend.enums import ReportPriority
from products.signals.backend.models import SignalReportArtefact


def persisted_report_priority(*, team_id: int, report_id: str) -> ReportPriority | None:
    """The priority from the report's latest ``priority_judgment`` artefact, or ``None`` without a readable one.

    Latest-wins, because re-research and the artefact API append new judgments instead of editing
    the old one. The ``-id`` tiebreak keeps the pick deterministic when two judgments share a
    ``created_at``: the routed effort tier is decided once and sticky, so an arbitrary tie-break
    could otherwise pin a report to a stale priority. Content that does not parse (a legacy non-JSON
    row, a hand-edited artefact) reads as missing, so a caller that keys a decision on the priority
    fails safe instead of crashing.
    """
    artefact = (
        SignalReportArtefact.objects.filter(
            team_id=team_id, report_id=report_id, type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if artefact is None:
        return None
    try:
        return PriorityAssessment.model_validate_json(artefact.content).priority
    except ValidationError:
        return None
