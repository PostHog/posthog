"""Recurrence of an issue a report already claimed was fixed.

A resolved report and a report dismissed as fixed make the same factual claim: the issue is gone.
A later matching signal is direct evidence that the claim was wrong, so both must surface the
recurrence instead of absorbing it. The grouping stage reads this module to tell the two kinds of
dismissal apart, and the `backfill_fixed_dismissal_forks` command reads it to find the parents whose
recurrences were absorbed before the rule existed.
"""

from datetime import datetime

from pydantic import ValidationError

from products.signals.backend.artefact_schemas import FIXED_DISMISSAL_REASONS, Dismissal, ReportLink
from products.signals.backend.enums import ReportLinkKind
from products.signals.backend.models import SignalReport, SignalReportArtefact


def fixed_dismissal_at(report: SignalReport) -> datetime | None:
    """When the report was dismissed with a claim that the issue is fixed, or None.

    Only the latest dismissal counts: dismissals stack, so an earlier "already fixed" that a
    reviewer has since overruled with a `wontfix_*` must not keep forking reports.
    """
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
    return created_at if reason in FIXED_DISMISSAL_REASONS else None


def recurrence_report(report: SignalReport, *, lock: bool = False) -> SignalReport | None:
    """Return the latest explicit recurrence successor, including dismissed successors."""
    linked_ids = []
    for report_id, content in SignalReportArtefact.objects.filter(
        team_id=report.team_id,
        type=SignalReportArtefact.ArtefactType.REPORT_LINK,
        content__contains=str(report.id),
    ).values_list("report_id", "content"):
        try:
            link = ReportLink.model_validate_json(content)
        except ValidationError:
            continue
        if link.kind == ReportLinkKind.RECURRENCE_OF and link.report_id == str(report.id):
            linked_ids.append(report_id)
    candidates = (
        SignalReport.objects.filter(team_id=report.team_id, id__in=linked_ids)
        .exclude(status=SignalReport.Status.DELETED)
        .order_by("-created_at")
    )
    if lock:
        candidates = candidates.select_for_update()
    return candidates.first()
