from datetime import datetime

from pydantic import ValidationError

from products.signals.backend.artefact_schemas import PriorityAssessment
from products.signals.backend.enums import ReportPriority
from products.signals.backend.models import SignalReportArtefact


def persisted_report_priority(*, team_id: int, report_id: str, before: datetime) -> ReportPriority | None:
    """The priority from the report's latest ``priority_judgment`` written before ``before``, or ``None``.

    ``before`` is the trust cut-off. The implementation agent holds the artefact tool that appends
    judgments, so a caller that routes on the priority reads it as of the moment that agent's task
    was created, before the agent could vote on how hard its own PR gets reviewed.

    Latest-wins, because re-research and the artefact API append new judgments instead of editing
    the old one. The ``-id`` tiebreak keeps the pick deterministic when two judgments share a
    ``created_at``: the routed effort tier is decided once and sticky, so an arbitrary tie-break
    could otherwise pin a report to a stale priority. Content that does not parse (a legacy non-JSON
    row, a hand-edited artefact) reads as missing, so a caller that keys a decision on the priority
    fails safe instead of crashing.
    """
    artefact = (
        SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id=report_id,
            type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
            created_at__lt=before,
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
