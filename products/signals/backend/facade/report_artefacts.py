"""Report artefact content types, and the artefact reads and writes other products make on a report."""

from datetime import datetime

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ArtefactContentValidationError as ArtefactContentValidationError,
    CodeReference as CodeReference,
    CodeReview as CodeReview,
    CodeReviewCounts as CodeReviewCounts,
    Commit as Commit,
    NoteArtefact as NoteArtefact,
    TaskRunArtefact as TaskRunArtefact,
)
from products.signals.backend.enums import ReportPriority
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_generation.priority import persisted_report_priority as _persisted_report_priority


def report_exists(*, team_id: int, report_id: str) -> bool:
    return SignalReport.objects.filter(team_id=team_id, id=report_id).exists()


def append_code_review(*, team_id: int, report_id: str, content: CodeReview, attribution: ArtefactAttribution) -> None:
    SignalReportArtefact.add_log(team_id=team_id, report_id=report_id, content=content, attribution=attribution)


def persisted_report_priority(*, team_id: int, report_id: str, before: datetime) -> ReportPriority | None:
    """The priority from the report's latest `priority_judgment` written before `before`, or None."""
    return _persisted_report_priority(team_id=team_id, report_id=report_id, before=before)
