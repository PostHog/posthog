"""Route new evidence after a fixed verdict or a rejected repository choice.

A resolved report and a report dismissed as fixed make the same factual claim: the issue is gone.
A wrong-repo dismissal leaves the issue unresolved. Both need a fresh report for later matching
signals, but only fixed verdicts supply prior-fix context to research.
"""

from datetime import datetime

from pydantic import ValidationError

from products.signals.backend.artefact_schemas import DISMISSAL_REASON_WRONG_REPO, FIXED_DISMISSAL_REASONS, Dismissal
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.typed_report_links import incoming_links


def _dismissal_at(report: SignalReport, reasons: frozenset[str]) -> datetime | None:
    latest = (
        SignalReportArtefact.objects.filter(
            report_id=report.id,
            team_id=report.team_id,
            type=SignalReportArtefact.ArtefactType.DISMISSAL,
        )
        .order_by("-created_at")
        .values_list("content", "created_at")
        .first()
    )
    if latest is None:
        return None
    content, created_at = latest
    try:
        reason = Dismissal.model_validate_json(content).reason
    except ValidationError:
        return None
    return created_at if reason in reasons else None


def fixed_dismissal_at(report: SignalReport) -> datetime | None:
    """When the report was dismissed with a claim that the issue is fixed, or None.

    Only the latest dismissal counts: dismissals stack, so an earlier "already fixed" that a
    reviewer has since overruled with a `wontfix_*` must not keep forking reports.
    """
    return _dismissal_at(report, FIXED_DISMISSAL_REASONS)


def recurrence_dismissal_at(report: SignalReport) -> datetime | None:
    return _dismissal_at(report, FIXED_DISMISSAL_REASONS | {DISMISSAL_REASON_WRONG_REPO})


def _next_recurrence_report(report: SignalReport, *, lock: bool) -> SignalReport | None:
    # Deleted successors are kept: the chain is walked *through* them to reach the live report at
    # its end, which is why this read cannot take the reader's default.
    linked_ids = [
        edge.source_id
        for edge in incoming_links(
            team_id=report.team_id,
            report_id=report.id,
            kinds=(ReportLinkKind.RECURRENCE_OF,),
            include_deleted_sources=True,
        )
    ]
    candidates = SignalReport.objects.filter(team_id=report.team_id, id__in=linked_ids).order_by("-created_at")
    if lock:
        candidates = candidates.select_for_update()
    return candidates.first()


def recurrence_report(report: SignalReport, *, lock: bool = False) -> SignalReport | None:
    """Return the next live successor, traversing deleted intermediate reports."""
    visited = {report.id}
    while successor := _next_recurrence_report(report, lock=lock):
        if successor.id in visited:
            return None
        if successor.status != SignalReport.Status.DELETED:
            return successor
        visited.add(successor.id)
        report = successor
    return None


def latest_recurrence_report(report: SignalReport, *, lock: bool = False) -> SignalReport:
    """Follow the recurrence chain to its current live report."""
    visited = {report.id}
    while successor := recurrence_report(report, lock=lock):
        if successor.id in visited:
            break
        visited.add(successor.id)
        report = successor
    return report
